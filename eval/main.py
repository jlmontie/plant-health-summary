"""
Cloud Function Entry Point for Async Evaluation.

This module provides the entry point for the Cloud Function that processes
evaluation requests from Pub/Sub. It receives AssessmentResponse payloads,
runs LLM-as-judge evaluation, and writes results to BigQuery.

Deployment:
    Deployed automatically via Cloud Build when pushing to main.
    See cloudbuild.yaml for the deployment configuration.

Local Testing:
    python -c "from eval.main import evaluate_pubsub; ..."
"""

import base64
import json
import functions_framework
from cloudevents.http import CloudEvent

# Import the evaluation logic
from eval.run_eval import evaluate_single


@functions_framework.cloud_event
def evaluate_pubsub(cloud_event: CloudEvent) -> None:
    """
    Cloud Function entry point for Pub/Sub-triggered evaluation.
    
    This function is triggered by messages published to the eval-queue topic.
    Each message contains an AssessmentResponse that needs to be evaluated.
    
    Args:
        cloud_event: CloudEvent containing the Pub/Sub message
        
    The Pub/Sub message data should be a JSON-encoded AssessmentResponse dict:
    {
        "request_id": "...",
        "plant_type": "...",
        "metrics": {...},
        "assessment": "...",
        "model": "...",
        "timestamp": "...",
        "prompt_variant": "normal"
    }
    """
    # Decode the Pub/Sub message
    message_data = cloud_event.data.get("message", {}).get("data", "")
    
    if not message_data:
        print("[EVAL] Received empty message, skipping")
        return
    
    try:
        # Decode base64 and parse JSON
        payload_bytes = base64.b64decode(message_data)
        payload = json.loads(payload_bytes.decode("utf-8"))
        
        request_id = payload.get("request_id", "unknown")
        print(f"[EVAL] Processing evaluation for request_id={request_id}")
        
        # Run evaluation (this calls LLM judge and writes to BigQuery)
        evaluation = evaluate_single(payload)
        
        score = evaluation.get("overall_score", "?")
        hallucination = "YES" if evaluation.get("hallucination", {}).get("detected") else "no"
        variant = evaluation.get("_metadata", {}).get("prompt_variant", "normal")
        
        print(f"[EVAL] Completed: request_id={request_id} score={score}/5 hallucination={hallucination} variant={variant}")
        
    except json.JSONDecodeError as e:
        print(f"[EVAL ERROR] Failed to parse message JSON: {e}")
        raise  # Re-raise to trigger retry
        
    except Exception as e:
        print(f"[EVAL ERROR] Evaluation failed: {e}")
        raise  # Re-raise to trigger retry (will eventually go to dead letter queue)
