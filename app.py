"""
Plant Health Demo - Chainlit Application

Entry point for the plant health assessment demo.
Users select a plant from their collection and receive AI-powered health assessments.

Run with: chainlit run app.py
"""

import json
from pathlib import Path

import chainlit as cl

# Initialize observability BEFORE importing modules that create LLM clients
from src.observability import init_tracing
PHOENIX_URL = init_tracing()

from src.guardrails import InputGuardrails
from src.plant_health import (
    PlantHealthService,
    AssessmentRequest,
    SensorMetrics,
)

# =============================================================================
# Configuration
# =============================================================================

# Path to our plant collection (golden dataset doubles as demo data)
DATA_PATH = Path(__file__).parent / "data" / "golden_dataset.json"

# =============================================================================
# Data Loading
# =============================================================================

def load_plant_collection() -> dict[str, dict]:
    """
    Load plants from the golden dataset.
    
    Returns a dict mapping plant display names to their full data.
    Example: {"Pothos (healthy_001)": {full example data...}}
    """
    data = json.loads(DATA_PATH.read_text())
    
    plants = {}
    for example in data["examples"]:
        display_name = f"{example['input']['plant_type']} ({example['id']})"
        plants[display_name] = example
    
    return plants


# Global plant collection - loaded once at startup
PLANTS = load_plant_collection()

# =============================================================================
# Chainlit Event Handlers
# =============================================================================

@cl.on_chat_start
async def on_chat_start():
    """
    Called when a user starts a new chat session.
    
    Initializes:
    - PlantHealthService instance (per-user)
    - Session state for selected plant
    - Welcome message with plant selection UI
    """
        # Create service instances for this user's session
    service = PlantHealthService()
    guardrails = InputGuardrails()
    
    cl.user_session.set("service", service)
    cl.user_session.set("guardrails", guardrails)
    cl.user_session.set("selected_plant", None)
    
    # Build plant selection actions
    plant_names = list(PLANTS.keys())
    
    actions = [
        cl.Action(
            name="select_plant",
            payload={"plant_name": name},
            label=name,
        )
        for name in plant_names[:5]
    ]
    
    if len(plant_names) > 5:
        actions.append(
            cl.Action(
                name="show_more_plants",
                payload={},
                label="Show more plants...",
            )
        )
    
    await cl.Message(
        content=(
            "# Plant Health Assistant\n\n"
            "Select a plant from your collection to get started:"
        ),
        actions=actions,
    ).send()


@cl.action_callback("select_plant")
async def on_select_plant(action: cl.Action):
    """
    Handles plant selection.
    
    Stores selection in session and displays current sensor readings
    so the user has context before requesting an assessment.
    """
    plant_name = action.payload["plant_name"]
    plant_data = PLANTS[plant_name]
    
    cl.user_session.set("selected_plant", plant_data)
    
    metrics = plant_data["input"]["metrics"]
    plant_type = plant_data["input"]["plant_type"]
    
    readings_table = f"""
| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Soil Moisture | {metrics['soil_moisture']['value']}% | {metrics['soil_moisture']['target']}% | {_status_indicator(metrics['soil_moisture'])} |
| Light | {metrics['light']['value']} lux | {metrics['light']['target']} lux | {_status_indicator(metrics['light'])} |
| Temperature | {metrics['temperature']['value']}F | {metrics['temperature']['target']}F | {_status_indicator(metrics['temperature'])} |
| Humidity | {metrics['humidity']['value']}% | {metrics['humidity']['target']}% | {_status_indicator(metrics['humidity'])} |
"""
    
    context_note = ""
    if "additional_context" in plant_data["input"]:
        context_note = f"\n**Note:** {plant_data['input']['additional_context']}\n"
    
    await cl.Message(
        content=(
            f"## {plant_type}\n\n"
            f"**Current Sensor Readings:**\n{readings_table}\n"
            f"{context_note}\n"
            "Send any message to request a health assessment."
        ),
    ).send()


@cl.action_callback("show_more_plants")
async def on_show_more_plants(action: cl.Action):
    """Shows remaining plants beyond the initial 5."""
    plant_names = list(PLANTS.keys())
    
    actions = [
        cl.Action(
            name="select_plant",
            payload={"plant_name": name},
            label=name,
        )
        for name in plant_names[5:]
    ]
    
    await cl.Message(
        content="**Additional plants:**",
        actions=actions,
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    """
    Handles user messages.
    
    Flow:
    1. Run guardrails (PII redaction + classification)
    2. If blocked, return explanation
    3. Build assessment request
    4. Call PlantHealthService
    5. Return assessment
    """
    service: PlantHealthService = cl.user_session.get("service")
    guardrails: InputGuardrails = cl.user_session.get("guardrails")
    plant_data: dict = cl.user_session.get("selected_plant")
    
    # Check if plant is selected
    if not plant_data:
        await cl.Message(
            content="Please select a plant first using the buttons above."
        ).send()
        return
    
    # Run guardrails on user message
    guardrail_result = guardrails.check(message.content)
    
    # Handle blocked input
    if guardrail_result.blocked:
        block_message = _format_block_message(guardrail_result)
        await cl.Message(content=block_message).send()
        return
    
    # Log PII detection (visible in server logs)
    if guardrail_result.pii_detected:
        print(f"[GUARDRAILS] PII redacted: {guardrail_result.pii_types}")
    
    # Build the assessment request
    plant_input = plant_data["input"]
    metrics_data = plant_input["metrics"]
    
    # Combine user message with any existing additional context
    additional_context = plant_input.get("additional_context", "")
    if guardrail_result.processed_input.strip():
        user_note = guardrail_result.processed_input.strip()
        if additional_context:
            additional_context = f"{additional_context}. User note: {user_note}"
        else:
            additional_context = f"User note: {user_note}"
    
    request = AssessmentRequest(
        request_id=f"demo-{plant_data['id']}",
        plant_type=plant_input["plant_type"],
        metrics=SensorMetrics(
            soil_moisture=metrics_data["soil_moisture"]["value"],
            soil_moisture_target=metrics_data["soil_moisture"]["target"],
            light=metrics_data["light"]["value"],
            light_target=metrics_data["light"]["target"],
            temperature=metrics_data["temperature"]["value"],
            temperature_target=metrics_data["temperature"]["target"],
            humidity=metrics_data["humidity"]["value"],
            humidity_target=metrics_data["humidity"]["target"],
        ),
        additional_context=additional_context if additional_context else None,
    )
    
    # Show thinking indicator
    msg = cl.Message(content="")
    await msg.send()
    
    # Generate assessment
    response = service.assess(request)
    
    # Display result
    msg.content = response.assessment
    await msg.update()


# =============================================================================
# Helper Functions
# =============================================================================

def _status_indicator(metric: dict) -> str:
    """
    Returns a status indicator based on deviation from target.
    
    OK = within 15% of target
    WARN = 15-40% off target  
    CRIT = more than 40% off target
    """
    value = metric["value"]
    target = metric["target"]
    
    if target == 0:
        return "OK" if value == 0 else "CRIT"
    
    deviation = abs(value - target) / target
    
    if deviation <= 0.15:
        return "OK"
    elif deviation <= 0.40:
        return "WARN"
    else:
        return "CRIT"


def _format_block_message(result) -> str:
    """Format a user-friendly message when input is blocked."""
    if result.classification == "off_topic":
        return (
            "I'm a plant health assistant and can only help with plant-related questions. "
            f"Your message appears to be about something else.\n\n"
            f"Try asking about your plant's health, watering needs, or care recommendations."
        )
    elif result.classification == "prompt_injection":
        return (
            "I detected an unusual pattern in your message. "
            "Please ask a straightforward question about your plant's health."
        )
    else:
        return (
            f"I wasn't able to process that request. "
            f"Please try rephrasing your question about your plant."
        )

# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    print("Run this app with: chainlit run app.py")