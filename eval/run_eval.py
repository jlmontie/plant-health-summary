"""
LLM-as-Judge Evaluation Harness.

Evaluates plant health assessment responses for quality using Gemini as judge.

Production mode (Pub/Sub triggered):
    - Receives request/response payload from Pub/Sub
    - Runs LLM-as-judge evaluation
    - Writes results to BigQuery

Demo mode (batch):
    - Loads golden dataset
    - Calls plant health service for each example
    - Evaluates all responses
    - Prints summary metrics

Usage:
    # Batch evaluation against golden dataset
    python eval/run_eval.py
    
    # Limit to N examples
    python eval/run_eval.py --limit 5
    
    # Save results
    python eval/run_eval.py --output results/eval_run.json
    
    # Evaluate a single payload (simulates Pub/Sub trigger)
    python eval/run_eval.py --payload '{"request": {...}, "response": {...}}'

Environment:
    GEMINI_API_KEY: Google AI Studio API key
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

from google import genai
from google.cloud import bigquery
from opentelemetry import trace
from openinference.semconv.trace import SpanAttributes
from openinference.instrumentation import using_attributes

# Import production service and config
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.config import CONFIG
from src.plant_health import (
    PlantHealthService,
    AssessmentRequest,
    AssessmentResponse,
    SensorMetrics,
)


# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

JUDGE_SYSTEM_PATH = PROMPTS_DIR / "llm_judge_system.txt"
JUDGE_TEMPLATE_PATH = PROMPTS_DIR / "llm_judge_template.txt"
GOLDEN_DATASET_PATH = DATA_DIR / "golden_dataset.json"


# =============================================================================
# Prompt Loading
# =============================================================================

def load_judge_prompt() -> tuple[str, str]:
    """Load the LLM-as-judge prompts from separate files."""
    system_prompt = JUDGE_SYSTEM_PATH.read_text().strip()
    eval_template = JUDGE_TEMPLATE_PATH.read_text().strip()
    return system_prompt, eval_template


def load_golden_dataset() -> list[dict]:
    """Load the golden dataset examples."""
    data = json.loads(GOLDEN_DATASET_PATH.read_text())
    return data["examples"]


# =============================================================================
# LLM-as-Judge Evaluator
# =============================================================================

class JudgeEvaluator:
    """
    LLM-as-judge evaluator.
    
    In production:
      - Triggered by Pub/Sub message containing request/response
      - Evaluates response quality
      - Writes evaluation to BigQuery
    """
    
    def __init__(self, model_name: str | None = None):
        model_name = model_name or CONFIG.model_name
        self.model_name = model_name
        self.system_prompt, self.eval_template = load_judge_prompt()
        self._client = None
        
        # BigQuery client - lazy initialized
        self._bq_client = None
        
        # Table ID from config: {project}.{dataset}.{table}
        # Dataset name uses app_name to match Terraform: replace("${var.app_name}_evals", "-", "_")
        if CONFIG.gcp_project_id:
            dataset = CONFIG.app_name.replace("-", "_") + "_evals"
            self.table_id = f"{CONFIG.gcp_project_id}.{dataset}.evaluations"
        else:
            self.table_id = None
    
    @property
    def client(self):
        """
        Lazy-load the Gemini client.
        
        Uses Vertex AI when USE_VERTEX_AI=true, otherwise uses API key.
        """
        if self._client is None:
            if CONFIG.use_vertex_ai:
                self._client = genai.Client(
                    vertexai=True,
                    project=CONFIG.gcp_project_id,
                    location=CONFIG.gcp_location,
                )
            else:
                if not CONFIG.gemini_api_key:
                    raise ValueError(
                        "GEMINI_API_KEY environment variable not set. "
                        "Set it in .env or use USE_VERTEX_AI=true with GCP credentials."
                    )
                self._client = genai.Client(api_key=CONFIG.gemini_api_key)
        return self._client
    
    def evaluate(self, response: AssessmentResponse, expected: Optional[dict] = None) -> dict:
        """
        Evaluate a plant health response.
        
        Args:
            response: The AssessmentResponse from the plant health service
            expected: Optional expected values for comparison (from golden dataset)
            
        Returns:
            Evaluation dict with scores and analysis
        """
        eval_prompt = self._build_eval_prompt(response)

        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("Evaluator") as span:
            span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, "EVALUATOR")
            result = self.client.models.generate_content(
                model=self.model_name,
                contents=eval_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    temperature=0.1,
                    max_output_tokens=2000,
                    response_mime_type="application/json",
                    response_schema={
                        "type": "object",
                        "properties": {
                            "accuracy": {
                                "type": "object",
                                "properties": {
                                    "score": {"type": "integer"},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["score", "reasoning"]
                            },
                            "relevance": {
                                "type": "object",
                                "properties": {
                                    "score": {"type": "integer"},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["score", "reasoning"]
                            },
                            "urgency_calibration": {
                                "type": "object",
                                "properties": {
                                    "score": {"type": "integer"},
                                    "reasoning": {"type": "string"}
                                },
                                "required": ["score", "reasoning"]
                            },
                            "hallucination": {
                                "type": "object",
                                "properties": {
                                    "detected": {"type": "boolean"},
                                    "evidence": {"type": "string"}
                                },
                                "required": ["detected", "evidence"]
                            },
                            "safety": {
                                "type": "object",
                                "properties": {
                                    "passed": {"type": "boolean"},
                                    "concerns": {"type": "string"}
                                },
                                "required": ["passed", "concerns"]
                            },
                            "overall_score": {"type": "integer"}
                        },
                        "required": ["accuracy", "relevance", "urgency_calibration", "hallucination", "safety", "overall_score"]
                    },
                )
            )

        # Parse JSON response
        try:
            evaluation = json.loads(result.text)
        except json.JSONDecodeError:
            text = result.text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start != -1 and end > start:
                evaluation = json.loads(text[start:end])
            else:
                raise ValueError(f"Could not parse judge response: {result.text}")
        
        # Add metadata (includes fields needed for BigQuery)
        evaluation["_metadata"] = {
            "request_id": response.request_id,
            "eval_timestamp": datetime.now().isoformat(),
            "judge_model": self.model_name,
            "system_model": response.model,
            "prompt_variant": getattr(response, "prompt_variant", "normal"),
            # Include response data for BigQuery write
            "plant_type": response.plant_type,
            "assessment": response.assessment,
        }
        
        if expected:
            evaluation["_expected"] = expected
        
        return evaluation
    
    def _build_eval_prompt(self, response: AssessmentResponse) -> str:
        """Build evaluation prompt from response data."""
        m = response.metrics
        
        prompt = self.eval_template
        prompt = prompt.replace("{{plant_type}}", response.plant_type)
        prompt = prompt.replace("{{moisture_value}}", str(m.soil_moisture))
        prompt = prompt.replace("{{moisture_target}}", str(m.soil_moisture_target))
        prompt = prompt.replace("{{light_value}}", str(m.light))
        prompt = prompt.replace("{{light_target}}", str(m.light_target))
        prompt = prompt.replace("{{temp_value}}", str(m.temperature))
        prompt = prompt.replace("{{temp_target}}", str(m.temperature_target))
        prompt = prompt.replace("{{humidity_value}}", str(m.humidity))
        prompt = prompt.replace("{{humidity_target}}", str(m.humidity_target))
        prompt = prompt.replace("{{response}}", response.assessment)
        
        # Handle optional additional context
        if response.additional_context:
            prompt = prompt.replace("{{#if additional_context}}", "")
            prompt = prompt.replace("{{/if}}", "")
            prompt = prompt.replace("{{additional_context}}", response.additional_context)
        else:
            start = prompt.find("{{#if additional_context}}")
            end = prompt.find("{{/if}}") + len("{{/if}}")
            if start != -1 and end != -1:
                prompt = prompt[:start] + prompt[end:]
        
        return prompt
    
    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=CONFIG.gcp_project_id)
        return self._bq_client
    
    def write_to_bigquery(self, evaluation: dict) -> None:
        """
        Write evaluation results to BigQuery.
        
        In production, this persists the evaluation for dashboards and alerting.
        The prompt_variant field enables filtering by which prompt variant was used.
        """
        metadata = evaluation["_metadata"]
        
        # Build row matching BigQuery schema
        row = {
            "request_id": metadata["request_id"],
            "timestamp": metadata["eval_timestamp"],
            "plant_type": metadata["plant_type"],
            "accuracy_score": evaluation["accuracy"]["score"],
            "relevance_score": evaluation["relevance"]["score"],
            "urgency_score": evaluation["urgency_calibration"]["score"],
            "overall_score": evaluation["overall_score"],
            "hallucination_detected": evaluation["hallucination"]["detected"],
            "safety_passed": evaluation["safety"]["passed"],
            "model": metadata["system_model"],
            "assessment": metadata["assessment"],
            "prompt_variant": metadata.get("prompt_variant", "normal"),
            "evaluation_json": json.dumps(evaluation),
        }
        
        # Only write to BigQuery if configured (production)
        if self.table_id and CONFIG.gcp_project_id:
            errors = self.bq_client.insert_rows_json(self.table_id, [row])
            if errors:
                print(f"[BIGQUERY] Insert errors: {errors}")
            else:
                print(f"[BIGQUERY] Wrote evaluation: request_id={metadata['request_id']}")
        else:
            # Demo mode: just log
            variant = metadata.get("prompt_variant", "normal")
            print(f"[BIGQUERY] Would write evaluation: request_id={metadata['request_id']} prompt_variant={variant}")


# =============================================================================
# Single Evaluation (Pub/Sub Entry Point)
# =============================================================================

def evaluate_single(payload: dict) -> dict:
    """
    Evaluate a single request/response pair.
    
    This is the entry point for Pub/Sub-triggered evaluation.
    In production, this would be called by a Cloud Function.
    
    Args:
        payload: Dict with 'request' and 'response' from Pub/Sub message
        
    Returns:
        Evaluation results dict
    """
    # Reconstruct response object from payload
    resp_data = payload
    metrics_data = resp_data["metrics"]
    
    response = AssessmentResponse(
        request_id=resp_data["request_id"],
        plant_type=resp_data["plant_type"],
        metrics=SensorMetrics(**metrics_data),
        assessment=resp_data["assessment"],
        model=resp_data["model"],
        timestamp=resp_data["timestamp"],
        additional_context=resp_data.get("additional_context"),
        prompt_variant=resp_data.get("prompt_variant", "normal"),
    )
    
    judge = JudgeEvaluator()
    evaluation = judge.evaluate(response)
    judge.write_to_bigquery(evaluation)
    
    return evaluation


# =============================================================================
# Batch Evaluation (Demo/CI Mode)
# =============================================================================

def calculate_metrics(evaluations: list[dict]) -> dict:
    """Aggregate evaluation scores into summary metrics."""
    n = len(evaluations)
    if n == 0:
        return {}
    
    return {
        "avg_accuracy": round(sum(e["accuracy"]["score"] for e in evaluations) / n, 2),
        "avg_relevance": round(sum(e["relevance"]["score"] for e in evaluations) / n, 2),
        "avg_urgency": round(sum(e["urgency_calibration"]["score"] for e in evaluations) / n, 2),
        "hallucination_rate": round(sum(1 for e in evaluations if e["hallucination"]["detected"]) / n, 3),
        "safety_pass_rate": round(sum(1 for e in evaluations if e["safety"]["passed"]) / n, 3),
        "avg_overall": round(sum(e["overall_score"] for e in evaluations) / n, 2),
        "n_evaluated": n,
    }


def check_quality_gates(metrics: dict) -> dict:
    """Check if metrics pass quality gates."""
    gates = {
        "avg_accuracy": {"min": 3.5, "target": 4.0},
        "avg_relevance": {"min": 3.5, "target": 4.0},
        "hallucination_rate": {"max": 0.10, "target": 0.05},
        "safety_pass_rate": {"min": 1.0, "target": 1.0},
        "avg_overall": {"min": 3.5, "target": 4.0},
    }
    
    results = {}
    all_pass = True
    
    for metric, thresholds in gates.items():
        value = metrics.get(metric, 0)
        
        if "min" in thresholds:
            passed = value >= thresholds["min"]
            met_target = value >= thresholds["target"]
        else:
            passed = value <= thresholds["max"]
            met_target = value <= thresholds["target"]
        
        results[metric] = {
            "value": value,
            "passed": passed,
            "met_target": met_target,
        }
        
        if not passed:
            all_pass = False
    
    results["all_gates_passed"] = all_pass
    return results


def golden_example_to_request(example: dict) -> AssessmentRequest:
    """Convert a golden dataset example to an AssessmentRequest."""
    metrics = example["input"]["metrics"]
    return AssessmentRequest(
        request_id=example["id"],
        plant_type=example["input"]["plant_type"],
        metrics=SensorMetrics(
            soil_moisture=metrics["soil_moisture"]["value"],
            soil_moisture_target=metrics["soil_moisture"]["target"],
            light=metrics["light"]["value"],
            light_target=metrics["light"]["target"],
            temperature=metrics["temperature"]["value"],
            temperature_target=metrics["temperature"]["target"],
            humidity=metrics["humidity"]["value"],
            humidity_target=metrics["humidity"]["target"],
        ),
        additional_context=example["input"].get("additional_context"),
    )


def run_batch_evaluation(
    limit: Optional[int] = None,
    output_path: Optional[Path] = None,
    verbose: bool = True,
) -> dict:
    """
    Run batch evaluation against the golden dataset.
    
    This mode is for:
      - Local development/testing
      - CI/CD quality gates
      - Generating sample results for the portfolio
    """
    if verbose:
        print("Plant Health Evaluation Framework")
        print("=" * 50)
    
    # Check credentials
    if not CONFIG.use_vertex_ai and not CONFIG.gemini_api_key:
        print("Error: No credentials configured.")
        print("  Option 1: Set GEMINI_API_KEY in .env")
        print("  Option 2: Set USE_VERTEX_AI=true and configure GCP credentials")
        sys.exit(1)
    
    # Load golden dataset
    examples = load_golden_dataset()
    if limit:
        examples = examples[:limit]
    
    if verbose:
        print(f"Evaluating {len(examples)} examples from golden dataset")
        print()
    
    # Initialize services
    service = PlantHealthService(sample_rate=0)  # Disable sampling in batch mode
    judge = JudgeEvaluator()
    
    # Run evaluations
    results = []
    for i, example in enumerate(examples):
        if verbose:
            print(f"[{i+1}/{len(examples)}] {example['id']}: {example['description'][:50]}...")
        
        try:
            # Generate assessment using production service
            request = golden_example_to_request(example)
            response = service.assess(request)

            # Evaluate with LLM judge
            evaluation = judge.evaluate(response, expected=example["expected"])

            results.append({
                "example_id": example["id"],
                "category": example["category"],
                "response": response.assessment,
                "evaluation": evaluation,
                "expected": example["expected"],
            })
            
            if verbose:
                score = evaluation.get("overall_score", "?")
                hallucination = "YES" if evaluation["hallucination"]["detected"] else "no"
                variant = evaluation["_metadata"].get("prompt_variant", "normal")
                variant_tag = f" [{variant}]" if variant != "normal" else ""
                print(f"    Score: {score}/5 | Hallucination: {hallucination}{variant_tag}")
        
        except Exception as e:
            if verbose:
                print(f"    Error: {e}")
            results.append({
                "example_id": example["id"],
                "category": example["category"],
                "error": str(e),
            })
    
    # Calculate metrics
    successful_evals = [r["evaluation"] for r in results if "evaluation" in r]
    metrics = calculate_metrics(successful_evals)
    quality_gates = check_quality_gates(metrics)
    
    # Build output
    output = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "model_judge": CONFIG.model_name,
            "n_examples": len(examples),
            "n_successful": len(successful_evals),
        },
        "metrics": metrics,
        "quality_gates": quality_gates,
        "results": results,
    }
    
    # Print summary
    if verbose:
        print()
        print("=" * 50)
        print("EVALUATION SUMMARY")
        print("=" * 50)
        print(f"  Accuracy:          {metrics.get('avg_accuracy', 'N/A')}/5.0")
        print(f"  Relevance:         {metrics.get('avg_relevance', 'N/A')}/5.0")
        print(f"  Urgency:           {metrics.get('avg_urgency', 'N/A')}/5.0")
        print(f"  Overall:           {metrics.get('avg_overall', 'N/A')}/5.0")
        print(f"  Hallucination:     {metrics.get('hallucination_rate', 0)*100:.1f}%")
        print(f"  Safety Pass Rate:  {metrics.get('safety_pass_rate', 0)*100:.1f}%")
        print()
        
        gate_status = "PASSED" if quality_gates["all_gates_passed"] else "FAILED"
        print(f"Quality Gates: {gate_status}")
    
    # Save results
    if output_path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2))
        if verbose:
            print(f"\nResults saved to: {output_path}")
    
    return output


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="LLM-as-judge evaluation for plant health assessments"
    )
    parser.add_argument(
        "--payload",
        type=str,
        help="JSON payload to evaluate (simulates Pub/Sub trigger)"
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        help="Limit batch evaluation to N examples"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output path for batch results JSON"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output"
    )
    
    args = parser.parse_args()
    
    if args.payload:
        # Single evaluation mode (Pub/Sub simulation)
        with open(args.payload, "r") as f:
            payload = json.load(f)
        result = evaluate_single(payload)
        print(json.dumps(result, indent=2))
    else:
        # Batch evaluation mode
        run_batch_evaluation(
            limit=args.limit,
            output_path=args.output,
            verbose=not args.quiet,
        )


if __name__ == "__main__":
    main()
