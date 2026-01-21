# Plant Health Demo: Implementation Plan

> **Purpose:** Production-ready demo showcasing AI safety architecture for plant health assessments.  
> **Target:** Live demo for employer evaluation + sandbox for production patterns.

---

## Architecture Overview

```
User Input (Chainlit)
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│              INPUT GUARDRAILS (src/guardrails.py)       │
├─────────────────────────────────────────────────────────┤
│  1. LLM Classifier (Gemini Flash)                       │
│     • Prompt injection detection                        │
│     • Topic boundary enforcement                        │
│                                                         │
│  2. PII Redaction                                       │
│     • Local: Microsoft Presidio                         │
│     • Production: Google Cloud DLP (optional)           │
└───────────────────────┬─────────────────────────────────┘
                        │ Validated input
                        ▼
┌─────────────────────────────────────────────────────────┐
│              MAIN LLM (Vertex AI / Gemini 2.5 Flash)    │
│              + Phoenix Observability Tracing            │
└───────────────────────┬─────────────────────────────────┘
                        │ Raw response
                        ▼
┌─────────────────────────────────────────────────────────┐
│              OUTPUT GUARDRAILS                          │
├─────────────────────────────────────────────────────────┤
│  3. Structure Validation                                │
│     • Required sections present                         │
│     • Response format compliance                        │
└───────────────────────┬─────────────────────────────────┘
                        │ Validated response
                        ▼
                   User receives response
                        │
                        ▼ (5% sampled, async)
┌─────────────────────────────────────────────────────────┐
│              ASYNC EVALUATION PIPELINE                  │
├─────────────────────────────────────────────────────────┤
│  Pub/Sub → Cloud Function → LLM-as-Judge → BigQuery     │
│  • Hallucination detection                              │
│  • Accuracy scoring                                     │
│  • Relevance scoring                                    │
│  • Safety validation                                    │
└─────────────────────────────────────────────────────────┘
```

---

## AI Safety Components

### Why These Choices?

| Component | Approach | Rationale |
|-----------|----------|-----------|
| **Prompt Injection Detection** | LLM-based classifier | Regex is trivially bypassed. LLM classification is robust to paraphrasing, unicode tricks, and indirect injection. Industry standard. |
| **Topic Boundaries** | LLM-based classifier | Semantic understanding required. "My fern looks sad" and "fern health status" mean the same thing—keywords fail here. |
| **PII Detection** | Presidio (local) / Cloud DLP (prod) | Production-grade tools. Presidio is Microsoft's open-source solution used in enterprise. Cloud DLP is Google's gold standard. |
| **Output Validation** | Structural parsing | Rule-based validation IS appropriate for structure checks (has required sections, valid format). Not content judgment. |
| **Hallucination Detection** | LLM-as-Judge (async) | Already implemented. Continuous evaluation pipeline catches hallucinations at scale without blocking user requests. |

### What We Explicitly Avoid

| Approach | Why Avoided |
|----------|-------------|
| Regex-based prompt injection | Brittle. Bypassed with unicode, paraphrasing, encoding tricks. Not production-worthy. |
| Keyword blocklists | Same brittleness issues. Users don't speak in keywords. |
| Regex-only PII detection | Misses context-dependent PII (names, addresses). Acceptable only as supplement. |
| Perspective API | Designed for user-to-user toxicity (social platforms), not LLM output analysis. Wrong tool. |

---

## Implementation Phases

### Phase 1: Chainlit Foundation
**Goal:** Working chat UI with plant selection and assessment generation.

| Task | Description |
|------|-------------|
| 1.1 | Create `app.py` with Chainlit boilerplate |
| 1.2 | Load `golden_dataset.json` as "My Plants" collection |
| 1.3 | Plant selection interface (sidebar or dropdown) |
| 1.4 | Wire existing `PlantHealthService` to chat |
| 1.5 | Display formatted assessment in chat |

**Deliverable:** `chainlit run app.py` shows working demo.

---

### Phase 2: Vertex AI Migration
**Goal:** Production-ready authentication via service accounts.

| Task | Description |
|------|-------------|
| 2.1 | Update `plant_health.py` with Vertex AI client option |
| 2.2 | Add `USE_VERTEX_AI` environment toggle |
| 2.3 | Update `run_eval.py` for Vertex AI compatibility |
| 2.4 | Test both local (API key) and Vertex (service account) modes |

**Deliverable:** Same functionality, production auth when deployed.

---

### Phase 3: Input Guardrails
**Goal:** Production-grade input safety layer.

| Task | Description |
|------|-------------|
| 3.1 | Create `src/guardrails.py` module |
| 3.2 | Implement `InputClassifier` using Gemini Flash |
| 3.3 | Prompt injection detection with clear refusal messages |
| 3.4 | Topic boundary enforcement (plant-related queries only) |
| 3.5 | Integrate Presidio for PII detection/redaction |
| 3.6 | Add Cloud DLP as optional production upgrade |
| 3.7 | Wire guardrails into Chainlit app flow |
| 3.8 | Write tests for guardrail edge cases |

**Deliverable:** Off-topic and injection attempts are blocked with clear messages.

---

### Phase 4: Phoenix Observability
**Goal:** Full request tracing and audit trail.

| Task | Description |
|------|-------------|
| 4.1 | Create `src/observability.py` module |
| 4.2 | Add Phoenix instrumentation to `PlantHealthService` |
| 4.3 | Trace spans: input processing, guardrails, LLM call, output validation |
| 4.4 | Add trace links in Chainlit UI (optional) |
| 4.5 | Configure local Phoenix server startup |

**Deliverable:** Every request traced with full context in Phoenix UI.

---

### Phase 5: Pub/Sub + Async Evaluation
**Goal:** Functional continuous evaluation pipeline.

| Task | Description |
|------|-------------|
| 5.1 | Make `_maybe_publish_for_eval` functional with real Pub/Sub |
| 5.2 | Add Pub/Sub emulator support for local development |
| 5.3 | Create `eval/cloud_function/main.py` wrapper |
| 5.4 | Implement BigQuery write (or structured logging for demo) |
| 5.5 | Test end-to-end: request → Pub/Sub → eval → storage |

**Deliverable:** Sampled requests flow through async evaluation pipeline.

---

### Phase 6: Terraform Infrastructure
**Goal:** Complete, deployable infrastructure as code.

| Task | Description |
|------|-------------|
| 6.1 | Cloud Run service for Chainlit app |
| 6.2 | Artifact Registry for container images |
| 6.3 | Pub/Sub topic + subscription |
| 6.4 | Cloud Function (2nd gen) for async eval |
| 6.5 | BigQuery dataset + evaluation results table |
| 6.6 | IAM: service accounts and minimal permissions |
| 6.7 | Secret Manager for API keys |
| 6.8 | Variables file with sensible defaults |
| 6.9 | Outputs for deployed URLs |

**Deliverable:** `terraform apply` deploys complete infrastructure.

---

### Phase 7: Output Validation + Polish
**Goal:** Demo-ready with structural output validation.

| Task | Description |
|------|-------------|
| 7.1 | Add response structure validation (required sections) |
| 7.2 | Graceful handling of malformed LLM responses |
| 7.3 | Loading states and UX polish in Chainlit |
| 7.4 | Error handling for all failure modes |
| 7.5 | Demo walkthrough script |

**Deliverable:** Polished, resilient demo ready for presentation.

---

## File Structure

```
plant-health-summary/
├── app.py                        # Chainlit entry point
├── Dockerfile                    # Container for Cloud Run
├── .env.example                  # Environment template
│
├── src/
│   ├── __init__.py
│   ├── plant_health.py           # Core assessment service (update)
│   ├── guardrails.py             # Input/output safety layer (new)
│   ├── observability.py          # Phoenix instrumentation (new)
│   ├── config.py                 # Environment config + feature flags (new)
│   └── pubsub.py                 # Pub/Sub client wrapper (new)
│
├── eval/
│   ├── run_eval.py               # LLM-as-judge harness (update)
│   └── cloud_function/
│       ├── main.py               # Cloud Function entry point (new)
│       └── requirements.txt
│
├── prompts/
│   ├── plant_health_system.md    # Assessment system prompt
│   ├── llm_judge.md              # Evaluation prompt
│   └── guardrails.md             # Guardrail classifier prompt (new)
│
├── data/
│   └── golden_dataset.json       # Test examples + demo plant collection
│
├── terraform/
│   ├── main.tf                   # Core resources (expand)
│   ├── variables.tf              # Input variables (new)
│   ├── outputs.tf                # Output values (new)
│   ├── iam.tf                    # Service accounts + permissions (new)
│   └── pubsub.tf                 # Pub/Sub resources (new)
│
├── tests/
│   ├── test_response_structure.py
│   └── test_guardrails.py        # Safety layer tests (new)
│
├── docs/
│   └── implementation-plan.md    # This document
│
├── requirements.txt              # Python dependencies (update)
└── README.md                     # Project overview (update)
```

---

## Configuration Modes

The application supports multiple runtime modes for development flexibility:

| Mode | Guardrails | LLM | PII | Pub/Sub | Phoenix |
|------|------------|-----|-----|---------|---------|
| **Local Dev** | LLM classifier | API key | Presidio | Emulator or mock | Local server |
| **Production** | LLM classifier | Vertex AI | Cloud DLP | Cloud Pub/Sub | Local or hosted |

Environment variables control mode switching:

```bash
# Local development
USE_VERTEX_AI=false
USE_CLOUD_DLP=false
PUBSUB_EMULATOR_HOST=localhost:8085
PHOENIX_ENDPOINT=http://localhost:6006

# Production
USE_VERTEX_AI=true
USE_CLOUD_DLP=true
GOOGLE_CLOUD_PROJECT=your-project-id
```

---

## Cost Estimates

### Per-Request Costs (Production)

| Component | Cost per 1,000 requests |
|-----------|------------------------|
| Guardrail LLM call (Flash, ~100 tokens) | ~$0.01 |
| Main assessment (Flash, ~500 tokens) | ~$0.05 |
| Presidio PII detection | $0 (local) |
| Cloud DLP (if enabled) | ~$0.01 |
| Phoenix tracing | $0 (local) |
| Async eval (5% sample) | ~$0.003 |
| **Total** | **~$0.07 per 1,000 requests** |

### Infrastructure Costs (Monthly, minimal usage)

| Resource | Estimated Cost |
|----------|---------------|
| Cloud Run (minimal) | ~$0 (free tier) |
| Pub/Sub | ~$0 (free tier) |
| Cloud Functions | ~$0 (free tier) |
| BigQuery (1GB) | ~$0.02 |
| Secret Manager | ~$0.06 |
| **Total** | **< $1/month for demo usage** |

---

## Deployment Region

- **Primary:** `us-central1`
- **Rationale:** Lowest latency for most US users, best free tier availability

---

## Success Criteria

### Functional Requirements
- [ ] User can select a plant from their collection
- [ ] User can request health assessment
- [ ] Off-topic queries are politely refused
- [ ] Prompt injection attempts are blocked
- [ ] PII in user input is redacted before LLM processing
- [ ] Responses are traced in Phoenix
- [ ] 5% of requests are evaluated asynchronously
- [ ] Terraform deploys complete infrastructure

### AI Safety Demonstration
- [ ] LLM-based guardrails catch sophisticated attacks
- [ ] Defense-in-depth architecture is clear
- [ ] Continuous evaluation pipeline monitors quality
- [ ] All decisions are auditable via traces
- [ ] Graceful degradation when components fail

---

## Next Steps

1. **Confirm plan** - Review and approve this document
2. **Begin Phase 1** - Create Chainlit app with basic flow
3. **Iterate** - Each phase produces working, testable code

---

*Last updated: 2026-01-19*
