"""
Application configuration.

Loads settings from environment variables with sensible defaults.
Provides a single source of truth for configuration across the application.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """
    Application configuration.
    
    frozen=True makes instances immutable, preventing accidental modification.
    """
    # Vertex AI settings
    use_vertex_ai: bool
    gcp_project_id: str | None
    gcp_location: str
    
    # Model settings
    model_name: str
    
    # API key (used when use_vertex_ai=False)
    gemini_api_key: str | None
    
    # Sampling rate for async evaluation (0.0 to 1.0)
    eval_sample_rate: float

    # Pub/Sub settings
    pubsub_topic: str | None
    use_local_eval: bool  # If True, run eval locally instead of via Pub/Sub
    
    # Violation prompt settings (for LLM-as-judge demo)
    # Rate at which to use violation prompts instead of normal prompt (0.0 to 1.0)
    violation_rate: float
    
    # PII redaction settings
    use_pii_redaction: bool  # If False, skip PII checks entirely
    use_cloud_dlp: bool      # If True, use Cloud DLP; if False, use Presidio
    
    # Arize Phoenix tracing (for remote monitoring)
    arize_api_key: str | None
    arize_space_id: str | None


def load_config() -> Config:
    """Load configuration from environment variables."""
    return Config(
        use_vertex_ai=os.getenv("USE_VERTEX_AI", "false").lower() == "true",
        gcp_project_id=os.getenv("GOOGLE_CLOUD_PROJECT"),
        gcp_location=os.getenv("GCP_LOCATION", "us-central1"),
        model_name=os.getenv("MODEL_NAME", "gemini-2.5-flash"),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        eval_sample_rate=float(os.getenv("EVAL_SAMPLE_RATE", "0.05")),
        pubsub_topic=os.getenv("PUBSUB_TOPIC"),
        use_local_eval=os.getenv("USE_LOCAL_EVAL", "true").lower() == "true",
        violation_rate=float(os.getenv("VIOLATION_RATE", "0.2")),
        use_pii_redaction=os.getenv("USE_PII_REDACTION", "true").lower() == "true",
        use_cloud_dlp=os.getenv("USE_CLOUD_DLP", "false").lower() == "true",
        arize_api_key=os.getenv("ARIZE_API_KEY"),
        arize_space_id=os.getenv("ARIZE_SPACE_ID"),
    )


# Global config instance - loaded once at import
CONFIG = load_config()
