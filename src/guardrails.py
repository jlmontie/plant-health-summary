"""
Input Guardrails Module.

Provides safety checks for user input before LLM processing:
- Prompt injection detection
- Topic boundary enforcement  
- PII redaction (Presidio locally, Cloud DLP in production)

All checks are designed to fail open with logging, so a guardrail
failure doesn't break the application.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from google import genai

from src.config import CONFIG

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
GUARDRAILS_SYSTEM_PATH = PROMPTS_DIR / "guardrails_system.txt"
GUARDRAILS_TEMPLATE_PATH = PROMPTS_DIR / "guardrails_template.txt"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class GuardrailResult:
    """Result of running input through guardrails."""
    allowed: bool
    original_input: str
    processed_input: str  # After PII redaction
    classification: str   # on_topic, off_topic, prompt_injection, harmful
    reason: str
    pii_detected: bool
    pii_types: list[str]  # e.g., ["EMAIL_ADDRESS", "PHONE_NUMBER"]
    
    @property
    def blocked(self) -> bool:
        return not self.allowed


# =============================================================================
# Prompt Loading
# =============================================================================

def load_guardrails_prompts() -> tuple[str, str]:
    """Load guardrails prompts from separate files."""
    system_prompt = GUARDRAILS_SYSTEM_PATH.read_text().strip()
    template = GUARDRAILS_TEMPLATE_PATH.read_text().strip()
    return system_prompt, template


# =============================================================================
# Input Classifier (LLM-based)
# =============================================================================

class InputClassifier:
    """
    LLM-based classifier for prompt injection and topic boundary detection.
    
    Uses a fast model (Gemini Flash) to classify input before it reaches
    the main assessment service.
    """
    
    def __init__(self):
        self.system_prompt, self.template = load_guardrails_prompts()
        self._client = None
    
    @property
    def client(self):
        """Lazy-load the Gemini client."""
        if self._client is None:
            if CONFIG.use_vertex_ai:
                self._client = genai.Client(
                    vertexai=True,
                    project=CONFIG.gcp_project_id,
                    location=CONFIG.gcp_location,
                )
            else:
                if not CONFIG.gemini_api_key:
                    raise ValueError("GEMINI_API_KEY not set")
                self._client = genai.Client(api_key=CONFIG.gemini_api_key)
        return self._client
    
    def classify(self, user_input: str) -> dict:
        """
        Classify user input for safety and relevance.
        
        Returns:
            dict with keys: allow (bool), classification (str), reason (str)
        """
        prompt = self.template.replace("{{user_input}}", user_input)
        
        try:
            result = self.client.models.generate_content(
                model=CONFIG.model_name,
                contents=[self.system_prompt, prompt],
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=200,
                    response_mime_type="application/json",
                )
            )
            
            # Handle empty or missing response
            if not result.text or not result.text.strip():
                logger.warning("Classifier returned empty response. Allowing input.")
                return {
                    "allow": True,
                    "classification": "error",
                    "reason": "Classifier returned empty response",
                }
            
            # Try to parse JSON, with fallback for malformed responses
            try:
                classification = json.loads(result.text)
            except json.JSONDecodeError:
                # Try to extract JSON from response if wrapped in other text
                text = result.text
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    classification = json.loads(text[start:end])
                else:
                    logger.warning(f"Classifier returned non-JSON: {text[:100]}. Allowing input.")
                    return {
                        "allow": True,
                        "classification": "error", 
                        "reason": "Could not parse classifier response",
                    }
            
            return {
                "allow": classification.get("allow", True),
                "classification": classification.get("classification", "unknown"),
                "reason": classification.get("reason", ""),
            }
            
        except Exception as e:
            logger.warning(f"Input classifier error: {e}. Allowing input.")
            return {
                "allow": True,
                "classification": "error",
                "reason": f"Classifier error: {str(e)}",
            }


# =============================================================================
# PII Redactor Interface
# =============================================================================

class PIIRedactor(Protocol):
    """Protocol for PII redaction implementations."""
    def redact(self, text: str) -> tuple[str, list[str]]: ...


# =============================================================================
# Presidio PII Redactor (Local Development)
# =============================================================================

class PresidioPIIRedactor:
    """
    PII detection and redaction using Microsoft Presidio.
    
    Used for local development. Memory-intensive (~700MB for spaCy model).
    """
    
    ENTITIES = [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON",
        "CREDIT_CARD",
        "US_SSN",
        "US_BANK_NUMBER",
        "IP_ADDRESS",
        "LOCATION",
    ]
    
    def __init__(self):
        self._analyzer = None
        self._anonymizer = None
    
    @property
    def analyzer(self):
        """Lazy-load the Presidio analyzer."""
        if self._analyzer is None:
            from presidio_analyzer import AnalyzerEngine
            self._analyzer = AnalyzerEngine()
        return self._analyzer
    
    @property
    def anonymizer(self):
        """Lazy-load the Presidio anonymizer."""
        if self._anonymizer is None:
            from presidio_anonymizer import AnonymizerEngine
            self._anonymizer = AnonymizerEngine()
        return self._anonymizer
    
    def redact(self, text: str) -> tuple[str, list[str]]:
        if not text or not text.strip():
            return text, []
        
        try:
            from presidio_anonymizer.entities import OperatorConfig
            
            results = self.analyzer.analyze(
                text=text,
                entities=self.ENTITIES,
                language="en",
            )
            
            if not results:
                return text, []
            
            pii_types = list(set(r.entity_type for r in results))
            
            anonymized = self.anonymizer.anonymize(
                text=text,
                analyzer_results=results,
                operators={
                    "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
                    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[EMAIL_REDACTED]"}),
                    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[PHONE_REDACTED]"}),
                    "PERSON": OperatorConfig("replace", {"new_value": "[NAME_REDACTED]"}),
                }
            )
            
            logger.info(f"PII redacted (Presidio): {pii_types}")
            return anonymized.text, pii_types
            
        except Exception as e:
            logger.warning(f"Presidio PII redaction error: {e}. Returning original text.")
            return text, []


# =============================================================================
# Cloud DLP PII Redactor (Production)
# =============================================================================

class CloudDLPRedactor:
    """
    PII detection and redaction using Google Cloud DLP API.
    
    Used in production (Cloud Run). No local memory overhead - API call.
    Requires: roles/dlp.user IAM role on service account.
    """
    
    # Map DLP info types to redaction labels
    INFO_TYPES = [
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "PERSON_NAME",
        "CREDIT_CARD_NUMBER",
        "US_SOCIAL_SECURITY_NUMBER",
        "US_BANK_ROUTING_MICR",
        "IP_ADDRESS",
        "STREET_ADDRESS",
    ]
    
    def __init__(self):
        self._client = None
    
    @property
    def client(self):
        """Lazy-load the DLP client."""
        if self._client is None:
            from google.cloud import dlp_v2
            self._client = dlp_v2.DlpServiceClient()
        return self._client
    
    def redact(self, text: str) -> tuple[str, list[str]]:
        if not text or not text.strip():
            return text, []
        
        try:
            from google.cloud import dlp_v2
            
            # Build the inspect config
            inspect_config = dlp_v2.InspectConfig(
                info_types=[dlp_v2.InfoType(name=t) for t in self.INFO_TYPES],
                min_likelihood=dlp_v2.Likelihood.LIKELIHOOD_UNSPECIFIED,
            )
            
            # Build the deidentify config (replace with type label)
            deidentify_config = dlp_v2.DeidentifyConfig(
                info_type_transformations=dlp_v2.InfoTypeTransformations(
                    transformations=[
                        dlp_v2.InfoTypeTransformations.InfoTypeTransformation(
                            primitive_transformation=dlp_v2.PrimitiveTransformation(
                                replace_with_info_type_config=dlp_v2.ReplaceWithInfoTypeConfig()
                            )
                        )
                    ]
                )
            )
            
            # Build the request
            item = dlp_v2.ContentItem(value=text)
            parent = f"projects/{CONFIG.gcp_project_id}/locations/{CONFIG.gcp_location}"
            
            response = self.client.deidentify_content(
                request={
                    "parent": parent,
                    "inspect_config": inspect_config,
                    "deidentify_config": deidentify_config,
                    "item": item,
                }
            )
            
            # Extract found info types from the overview
            pii_types = []
            if response.overview and response.overview.transformation_summaries:
                for summary in response.overview.transformation_summaries:
                    if summary.info_type:
                        pii_types.append(summary.info_type.name)
            
            redacted_text = response.item.value
            
            # Convert DLP format [INFO_TYPE] to our format [TYPE_REDACTED]
            for info_type in self.INFO_TYPES:
                redacted_text = redacted_text.replace(
                    f"[{info_type}]",
                    f"[{info_type.replace('_', ' ').title().replace(' ', '_')}_REDACTED]"
                )
            
            if pii_types:
                logger.info(f"PII redacted (Cloud DLP): {pii_types}")
            
            return redacted_text, pii_types
            
        except Exception as e:
            logger.warning(f"Cloud DLP error: {e}. Returning original text.")
            return text, []


# =============================================================================
# No-op PII Redactor (Skip PII check)
# =============================================================================

class NoOpPIIRedactor:
    """No-op redactor - passes text through unchanged."""
    
    def redact(self, text: str) -> tuple[str, list[str]]:
        return text, []


def create_pii_redactor() -> PIIRedactor:
    """
    Factory function to create the appropriate PII redactor.
    
    Uses Cloud DLP in production (USE_VERTEX_AI=true), Presidio locally.
    Set USE_PII_REDACTION=false to disable entirely.
    """
    if not CONFIG.use_pii_redaction:
        logger.info("PII redaction disabled")
        return NoOpPIIRedactor()
    
    if CONFIG.use_cloud_dlp:
        logger.info("Using Cloud DLP for PII redaction")
        return CloudDLPRedactor()
    else:
        logger.info("Using Presidio for PII redaction")
        return PresidioPIIRedactor()

# =============================================================================
# Unified Guardrails Interface
# =============================================================================

class InputGuardrails:
    """
    Unified interface for all input safety checks.
    
    Runs PII redaction first (always), then classification on the 
    redacted text. This ensures the classifier never sees raw PII.
    
    PII redaction uses:
    - Cloud DLP in production (USE_CLOUD_DLP=true)
    - Presidio locally (USE_CLOUD_DLP=false, default)
    - Disabled entirely with USE_PII_REDACTION=false
    
    Usage:
        guardrails = InputGuardrails()
        result = guardrails.check("How is my plant doing?")
        
        if result.blocked:
            return f"I can't help with that: {result.reason}"
        
        # Use result.processed_input for the LLM call
        response = service.assess(result.processed_input)
    """
    
    def __init__(self):
        self.classifier = InputClassifier()
        self.pii_redactor = create_pii_redactor()
    
    def check(self, user_input: str) -> GuardrailResult:
        """
        Run all guardrail checks on user input.
        
        Order of operations:
        1. PII redaction (always runs)
        2. Classification (runs on redacted text)
        
        Args:
            user_input: Raw user input
            
        Returns:
            GuardrailResult with processed input and classification
        """
        # Step 1: Redact PII
        redacted_text, pii_types = self.pii_redactor.redact(user_input)
        pii_detected = len(pii_types) > 0
        
        # Step 2: Classify the redacted text
        classification = self.classifier.classify(redacted_text)
        
        return GuardrailResult(
            allowed=classification["allow"],
            original_input=user_input,
            processed_input=redacted_text,
            classification=classification["classification"],
            reason=classification["reason"],
            pii_detected=pii_detected,
            pii_types=pii_types,
        )
