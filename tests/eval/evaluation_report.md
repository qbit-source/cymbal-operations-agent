# Cymbal Operations Agent - Comprehensive Evaluation Report

## Executive Summary
This evaluation report documents the systematic testing, benchmarking methodology, and quality verification for the **Cymbal Operations Coordinator Agent** (`cymbal_operations_agent`). The evaluation suite tests multi-tool operational orchestration, strict hardware runbook RAG grounding, real-time Bigtable sub-second metrics, PCI-DSS payment card PII redaction, and multi-turn context retention.

---

## Section 1: Evaluation Approach & Design

### 1. BRD Relevance & Use Case Coverage
The evaluation datasets directly ground testing in the Business Requirements Document (BRD) across single-turn and multi-turn conversation workflows:
- **UC 1.1a / 1.1b POS Hardware Errors:** Field service diagnostic retrieval for EMV reader freezes (`ERR-PAY-4001`) and thermal printer cutter jams (`ERR-DN-PRNT-24V`).
- **UC 1.1c Out-of-Scope Hardware Refusal:** Certified RAG refusal threshold (< 0.70 vector similarity) returning exact certified safety decline string: `"I cannot find certified warranty or repair rules for this specific error in our technical repository."`
- **UC 1.2 Inventory & Stockout Risk:** Reconciling on-hand store inventory positions with < 20 hours cover time remaining.
- **UC 1.3 Real-Time Operational Telemetry:** Sub-second Bigtable 1-hour rolling metrics for cashier compliance audits.
- **UC 2.1 Warranty & Purchase Triage:** Unnesting transaction line items and cross-referencing supplier warranty terms.
- **UC 2.2 Parallel Dual Dispatch:** Comparing real-time Bigtable override metrics against 7-day BigQuery historical baselines in a single turn.
- **UC 2.3 Cross-Cloud Sequential Auditing:** Multi-hop investigative queries identifying anomaly offenders in BigQuery and querying AWS S3 BigLake checkout logs.
- **Security Guardrail:** Dynamic masking of customer payment card numbers into `XXXX-XXXX-XXXX-9999` across all feeds.

### 2. Metric & Configuration Rigor (`eval_config.yaml`)
- **`tool_use_quality` / `custom_response_quality`:** LLM-as-a-judge rubric scoring factual correctness, intent routing, and adherence to operational parameters.
- **`grounding`:** Ensures hardware diagnostic responses strictly adhere to certified OEM manuals and include authenticated Cloud Storage document links.
- **`agent_turn_count`:** Evaluates conversational efficiency and tool dispatch latency.

### 3. Cost & Time Efficiency
- **Deterministic Mock LLM Execution (`USE_MOCK_LLM=TRUE`):** Enables isolated, zero-cost, dry-run test passes in offline CI environments and non-GCP sandboxes without incurring Vertex AI API costs or latency.
- **Fine-Grained Document Chunks:** Sliding window embeddings (500 chars / 100 char overlap) and adjacent context window stitching ($N-1$ to $N+1$) maximize retrieval relevance while keeping LLM context tokens compact.

### 4. Guardrail & Edge-Case Validation
- **PII Redaction Pipeline:** Verified by automated unit tests (`tests/unit/test_pii.py`) ensuring credit/debit card numbers are scrubbed across tool arguments, model responses, and event logs.
- **RAG Sub-0.70 Threshold Guardrail:** Hard assertion verifying that ungrounded hardware inquiries cleanly refuse with the exact certified decline string.

---

## Section 2: Evaluation Datasets

| Dataset File | Scenario Type | Case Count | Focus Area |
| :--- | :--- | :--- | :--- |
| `tests/eval/datasets/basic-dataset.json` | Single-turn core scenarios | 8 | Core BRD Use Cases (UC 1.1a–UC 2.3 & PII security) |
| `tests/eval/datasets/eval-data.json` | Single-turn domain deep dives | 6 | Hardware faults, inventory cover hours, Bigtable metrics, RAG decline |
| `tests/eval/datasets/eval-data2.json` | Multi-turn continuous dialogues | 3 | Cross-cloud auditing, warranty policy triage, hardware-to-inventory intent switching |

---

## Section 3: Verification & Execution Results Output

- **Unit Tests:** `tests/unit/test_pii.py` & `tests/unit/test_dummy.py` (6 passed in 2.70s)
- **Integration Tests (Isolated / Mocked):** `tests/integration/test_server_e2e.py` & `tests/integration/test_agent.py` (5 passed in 18.74s)
- **RAG Refusal Assertion:** Verified returning exact string `'I cannot find certified warranty or repair rules for this specific error in our technical repository.'`
