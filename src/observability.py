"""
Observability Module.

Initializes Phoenix tracing for LLM call monitoring.
Must be imported and initialized before any LLM clients are created.

Phoenix provides:
- Automatic tracing of all google-genai LLM calls
- Local UI at http://localhost:6006 to explore traces
- Latency, token usage, and request/response logging
"""

import logging
import os

logger = logging.getLogger(__name__)

# Track initialization state
_initialized = False
_phoenix_url = None


def init_tracing(project_name: str = "plant-health-demo") -> str | None:
    """
    Initialize Phoenix tracing.
    
    Starts a local Phoenix server and instruments the google-genai library.
    Safe to call multiple times - only initializes once.
    
    Args:
        project_name: Name for this project in Phoenix UI
    
    Returns:
        URL of the Phoenix UI, or None if initialization fails
    """
    global _initialized, _phoenix_url
    
    if _initialized:
        logger.debug("Phoenix tracing already initialized")
        return _phoenix_url
    
    try:
        import phoenix as px
        from phoenix.otel import register
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
        
        # Launch Phoenix app
        session = px.launch_app()
        _phoenix_url = session.url
        
        # Register Phoenix as the trace collector
        # Remove trailing slash from URL to avoid double-slash in endpoint
        base_url = _phoenix_url.rstrip("/")
        tracer_provider = register(
            project_name=project_name,
            endpoint=f"{base_url}/v1/traces",
        )
        
        # Instrument google-genai with the registered tracer
        GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        
        _initialized = True
        print(f"Phoenix tracing initialized: {_phoenix_url} (project: {project_name})")
        logger.info(f"Phoenix tracing initialized: {_phoenix_url} (project: {project_name})")
        return _phoenix_url
        
    except Exception as e:
        print(f"Failed to initialize Phoenix tracing: {e}")
        logger.warning(f"Failed to initialize Phoenix tracing: {e}")
        return None


def get_trace_url() -> str | None:
    """Get the Phoenix UI URL if tracing is active."""
    return _phoenix_url