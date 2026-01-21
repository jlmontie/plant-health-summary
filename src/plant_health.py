"""
Plant Health Assessment Service.

Production module that analyzes sensor data and returns health assessments.
In production, this would:
  1. Receive requests via Cloud Run
  2. Generate health assessments using Vertex AI
  3. Publish 5% of request/response pairs to Pub/Sub for async evaluation

Usage:
    # As a module
    from src.plant_health import PlantHealthService
    
    service = PlantHealthService()
    result = service.assess(plant_type="Pothos", metrics={...})
    
    # CLI for testing
    python src/plant_health.py --plant "Peace Lily" --moisture 15 --light 600 --temp 72 --humidity 50
"""

import json
import random
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional

from google import genai

from src.config import CONFIG


# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts"
VIOLATION_PROMPTS_DIR = PROMPTS_DIR / "violation_prompts"

# Prompt variants for LLM-as-judge demo
# Maps variant name to prompt file path
PROMPT_VARIANTS = {
    "normal": PROMPTS_DIR / "plant_health_system.md",
    "accuracy_violation": VIOLATION_PROMPTS_DIR / "plant_health_system_accuracy_violation.md",
    "hallucination_violation": VIOLATION_PROMPTS_DIR / "plant_health_system_hallucination_violation.md",
    "relevance_violation": VIOLATION_PROMPTS_DIR / "plant_health_system_relevance_violation.md",
    "urgency_violation": VIOLATION_PROMPTS_DIR / "plant_health_system_urgency_calibration_violation.md",
    "safety_violation": VIOLATION_PROMPTS_DIR / "plant_health_system_safety_violation.md",
}

# List of violation variants (excludes "normal")
VIOLATION_VARIANTS = [k for k in PROMPT_VARIANTS.keys() if k != "normal"]


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class SensorMetrics:
    """Sensor readings for a plant."""
    soil_moisture: float
    soil_moisture_target: float
    light: float
    light_target: float
    temperature: float
    temperature_target: float
    humidity: float
    humidity_target: float


@dataclass
class AssessmentRequest:
    """Input to the plant health service."""
    request_id: str
    plant_type: str
    metrics: SensorMetrics
    additional_context: Optional[str] = None


@dataclass
class AssessmentResponse:
    """Output from the plant health service."""
    request_id: str
    plant_type: str
    metrics: SensorMetrics
    assessment: str
    model: str
    timestamp: str
    additional_context: Optional[str] = None
    prompt_variant: str = "normal"  # Tracks which prompt was used (for eval analysis)


# =============================================================================
# Plant Health Service
# =============================================================================

class PlantHealthService:
    """
    Production plant health assessment service.
    
    In production deployment:
      - Runs on Cloud Run
      - Calls Vertex AI for generation
      - Publishes sample to Pub/Sub for async evaluation
    
    For demo purposes, supports "violation prompts" that subtly cause
    specific evaluation failures to demonstrate LLM-as-judge efficacy.
    """
    
    def __init__(
        self, 
        model_name: str | None = None, 
        sample_rate: float | None = None,
        violation_rate: float | None = None,
    ):
        self.model_name = model_name or CONFIG.model_name
        self.sample_rate = sample_rate if sample_rate is not None else CONFIG.eval_sample_rate
        self.violation_rate = violation_rate if violation_rate is not None else CONFIG.violation_rate
        self._client = None
        self._prompt_cache: dict[str, str] = {}  # Cache loaded prompts
    
    def _load_prompt(self, variant: str) -> str:
        """Load and cache a prompt variant."""
        if variant not in self._prompt_cache:
            path = PROMPT_VARIANTS.get(variant, PROMPT_VARIANTS["normal"])
            self._prompt_cache[variant] = path.read_text()
        return self._prompt_cache[variant]
    
    def _select_prompt_variant(self) -> str:
        """
        Randomly select a prompt variant.
        
        With probability `violation_rate`, selects a random violation prompt.
        Otherwise, uses the normal prompt.
        """
        if random.random() < self.violation_rate:
            variant = random.choice(VIOLATION_VARIANTS)
            print(f"[PROMPT] Using violation prompt: {variant}")
            return variant
        return "normal"
    
    @property
    def client(self):
        """
        Lazy-load the Gemini client.
        
        Uses Vertex AI when USE_VERTEX_AI=true, otherwise uses API key.
        """
        if self._client is None:
            if CONFIG.use_vertex_ai:
                # Vertex AI mode: uses ADC (Application Default Credentials)
                # In Cloud Run, this is automatic via the service account
                # Locally, run: gcloud auth application-default login
                self._client = genai.Client(
                    vertexai=True,
                    project=CONFIG.gcp_project_id,
                    location=CONFIG.gcp_location,
                )
            else:
                # API key mode: for local development
                if not CONFIG.gemini_api_key:
                    raise ValueError(
                        "GEMINI_API_KEY environment variable not set. "
                        "Set it in .env or use USE_VERTEX_AI=true with GCP credentials."
                    )
                self._client = genai.Client(api_key=CONFIG.gemini_api_key)
        return self._client
    
    def assess(self, request: AssessmentRequest) -> AssessmentResponse:
        """
        Generate a plant health assessment.
        
        Args:
            request: Assessment request with plant type and sensor metrics
            
        Returns:
            AssessmentResponse with the generated assessment
        """
        # Select prompt variant (may use violation prompt for demo)
        prompt_variant = self._select_prompt_variant()
        system_prompt = self._load_prompt(prompt_variant)
        
        # Build prompt
        user_prompt = self._build_prompt(request)
        
        # Generate assessment
        result = self.client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
                max_output_tokens=2000,
            )
        )
        
        response = AssessmentResponse(
            request_id=request.request_id,
            plant_type=request.plant_type,
            metrics=request.metrics,
            assessment=result.text,
            model=self.model_name,
            timestamp=datetime.now().isoformat(),
            additional_context=request.additional_context,
            prompt_variant=prompt_variant,
        )
        
        # Publish sample for async evaluation
        self._maybe_publish_for_eval(request, response)
        
        return response
    
    def _build_prompt(self, request: AssessmentRequest) -> str:
        """Build the user prompt from request data."""
        m = request.metrics
        prompt = f"""Analyze the health of this {request.plant_type} based on the sensor data:

| Metric | Current | Target | Unit |
|--------|---------|--------|------|
| Soil Moisture | {m.soil_moisture} | {m.soil_moisture_target} | % |
| Light | {m.light} | {m.light_target} | lux |
| Temperature | {m.temperature} | {m.temperature_target} | F |
| Humidity | {m.humidity} | {m.humidity_target} | % |
"""
        if request.additional_context:
            prompt += f"\nAdditional Context: {request.additional_context}"
        
        prompt += "\n\nProvide a health assessment and care recommendations."
        return prompt
    
    def _maybe_publish_for_eval(
        self, 
        request: AssessmentRequest, 
        response: AssessmentResponse
    ) -> None:
        """
        Publish a sample of request/response pairs for async evaluation.
        
        Modes:
        - Local eval (USE_LOCAL_EVAL=true): Run LLM-as-judge immediately in-process
        - Pub/Sub (USE_LOCAL_EVAL=false): Publish to Pub/Sub for async processing
        """
        if random.random() > self.sample_rate:
            return
        
        print(f"[EVAL SAMPLE] Request sampled for evaluation: {request.request_id}")
        
        if CONFIG.use_local_eval:
            # Run evaluation locally (for demo/development)
            self._run_local_eval(response)
        elif CONFIG.pubsub_topic:
            # Publish to Pub/Sub (for production)
            self._publish_to_pubsub(response)
        else:
            print(f"[EVAL SAMPLE] No eval destination configured, skipping")
    
    def _run_local_eval(self, response: AssessmentResponse) -> None:
        """Run LLM-as-judge evaluation locally."""
        try:
            # Import here to avoid circular dependency
            from eval.run_eval import JudgeEvaluator
            
            judge = JudgeEvaluator()
            evaluation = judge.evaluate(response)
            
            # Log results
            score = evaluation.get("overall_score", "?")
            hallucination = "YES" if evaluation.get("hallucination", {}).get("detected") else "no"
            print(f"[EVAL RESULT] request_id={response.request_id} score={score}/5 hallucination={hallucination}")
            
            # Save to results directory
            results_dir = PROJECT_ROOT / "results"
            results_dir.mkdir(exist_ok=True)
            result_file = results_dir / f"{response.request_id}.json"
            result_file.write_text(json.dumps({
                "response": asdict(response),
                "evaluation": evaluation,
            }, indent=2))
            print(f"[EVAL RESULT] Saved to {result_file}")
            
        except Exception as e:
            print(f"[EVAL ERROR] Local evaluation failed: {e}")
    
    def _publish_to_pubsub(self, response: AssessmentResponse) -> None:
        """Publish response to Pub/Sub for async evaluation."""
        try:
            from google.cloud import pubsub_v1
            
            publisher = pubsub_v1.PublisherClient()
            payload = json.dumps(asdict(response)).encode("utf-8")
            
            future = publisher.publish(CONFIG.pubsub_topic, payload)
            message_id = future.result(timeout=10)
            print(f"[PUBSUB] Published message {message_id} for request {response.request_id}")
            
        except Exception as e:
            print(f"[PUBSUB ERROR] Failed to publish: {e}")


# =============================================================================
# CLI for Testing
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate a plant health assessment"
    )
    parser.add_argument("--plant", required=True, help="Plant type (e.g., 'Peace Lily')")
    parser.add_argument("--moisture", type=float, required=True, help="Soil moisture %")
    parser.add_argument("--moisture-target", type=float, default=50, help="Target moisture %")
    parser.add_argument("--light", type=float, required=True, help="Light level (lux)")
    parser.add_argument("--light-target", type=float, default=750, help="Target light (lux)")
    parser.add_argument("--temp", type=float, required=True, help="Temperature (F)")
    parser.add_argument("--temp-target", type=float, default=70, help="Target temperature (F)")
    parser.add_argument("--humidity", type=float, required=True, help="Humidity %")
    parser.add_argument("--humidity-target", type=float, default=50, help="Target humidity %")
    parser.add_argument("--context", type=str, help="Additional context")
    parser.add_argument("--response-output", type=str, help="Response output file")
    
    args = parser.parse_args()
    
    request = AssessmentRequest(
        request_id=f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        plant_type=args.plant,
        metrics=SensorMetrics(
            soil_moisture=args.moisture,
            soil_moisture_target=args.moisture_target,
            light=args.light,
            light_target=args.light_target,
            temperature=args.temp,
            temperature_target=args.temp_target,
            humidity=args.humidity,
            humidity_target=args.humidity_target,
        ),
        additional_context=args.context,
    )
    
    service = PlantHealthService(sample_rate=1.0)  # Always sample in CLI mode
    response = service.assess(request)
    
    if args.response_output:
        with open(args.response_output, "w") as f:
            json.dump(asdict(response), f, indent=2)
        print(f"Response written to {args.response_output}")
        return
    
    print("\n" + "=" * 50)
    print("ASSESSMENT")
    print("=" * 50)
    print(response.assessment)


if __name__ == "__main__":
    main()
