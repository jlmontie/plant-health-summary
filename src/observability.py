"""
Observability Module.

Initializes Phoenix tracing for LLM call monitoring.
Must be imported and initialized before any LLM clients are created.

Two modes:
1. Local: Starts a local Phoenix server at http://localhost:6006
2. Remote: Sends traces to Arize Cloud (when ARIZE_API_KEY is set)

Phoenix provides:
- Automatic tracing of all google-genai LLM calls
- Latency, token usage, and request/response logging
"""

import logging

from src.config import CONFIG

logger = logging.getLogger(__name__)

# Track initialization state
_initialized = False
_phoenix_url = None


def init_tracing(project_name: str = "plant-health-demo") -> str | None:
    """
    Initialize Phoenix tracing.
    
    If ARIZE_API_KEY is set, traces go to Arize Cloud.
    Otherwise, starts a local Phoenix server.
    
    Safe to call multiple times - only initializes once.
    
    Args:
        project_name: Name for this project in Phoenix/Arize UI
    
    Returns:
        URL of the Phoenix UI (local or Arize Cloud), or None if initialization fails
    """
    global _initialized, _phoenix_url
    
    if _initialized:
        logger.debug("Phoenix tracing already initialized")
        return _phoenix_url
    
    try:
        from arize.otel import register
        from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor
        
        # Determine mode: remote (Arize Cloud) or local
        use_remote = CONFIG.arize_api_key and CONFIG.arize_space_id
        
        if use_remote:
            # Remote mode: send traces to Arize Cloud
            tracer_provider = register(
                space_id=CONFIG.arize_space_id,
                api_key=CONFIG.arize_api_key,
                project_name=project_name,
            )
            _phoenix_url = "https://app.arize.com"
            print(f"Arize Cloud tracing initialized (project: {project_name})")
            logger.info(f"Arize Cloud tracing initialized (project: {project_name})")
        else:
            # Local mode: start local Phoenix server
            import phoenix as px
            from phoenix.otel import register as phoenix_register
            
            session = px.launch_app()
            _phoenix_url = session.url
            
            # Register local Phoenix as the trace collector
            base_url = _phoenix_url.rstrip("/")
            tracer_provider = phoenix_register(
                project_name=project_name,
                endpoint=f"{base_url}/v1/traces",
            )
            print(f"Local Phoenix tracing initialized: {_phoenix_url} (project: {project_name})")
            logger.info(f"Local Phoenix tracing initialized: {_phoenix_url} (project: {project_name})")
        
        # Instrument google-genai with the registered tracer
        GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)
        
        _initialized = True
        return _phoenix_url
        
    except Exception as e:
        print(f"Failed to initialize tracing: {e}")
        logger.warning(f"Failed to initialize tracing: {e}")
        return None


def get_trace_url() -> str | None:
    """Get the Phoenix/Arize UI URL if tracing is active."""
    return _phoenix_url