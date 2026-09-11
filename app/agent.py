# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import logging
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from app.tools.analytics_tool import cymbal_analytics_tool
from app.tools.rag_tool import pos_troubleshooting_rag_tool
from app.tools.bigtable_tool import (
    bigtable_mcp_toolset,
    bigtable_realtime_alerts_tool,
    bigtable_enriched_sql_tool,
)
from app.app_utils.pii_plugin import PiiRedactionPlugin

logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# Detect mock/sandbox mode for isolated testing without live Gemini dependencies
USE_MOCK_LLM = (
    os.getenv("USE_MOCK_LLM", "").lower() in ("true", "1", "yes")
    or os.getenv("INTEGRATION_TEST_MOCK", "").lower() in ("true", "1", "yes")
)

SYSTEM_INSTRUCTION = """You are the Cymbal Operations Coordinator Agent (cymbal_operations_agent), an enterprise operational intelligence assistant for store directors, regional operations leads, and retail compliance auditors.

You have access to 4 specialized tools:
1. `cymbal_analytics_tool`:
   - Primary analytics engine for Google Cloud BigQuery and cross-cloud BigLake federated layers (AWS S3).
   - Use for inventory reconciliation, stockout risk calculations, store burn rates, transaction details, warranty policy terms, historical cashier baselines, and cross-cloud checkout log audits.
   - Standardized enterprise terms (e.g., "Net Transaction Revenue", "Total On-Hand Inventory", "Estimated Cover Hours", "Cashier Manual Override Rate") must be preserved verbatim.
2. `pos_troubleshooting_rag_tool`:
   - Technical hardware runbook and field recovery engine for POS terminals, EMV contactless readers, receipt printers, cash drawers, and peripherals.
   - Powered by BigQuery vector similarity search with adjacent context window stitching over certified OEM technical manuals.
   - Always provides certified GCS HTTPS documentation links.
   - When an inquiry falls outside certified equipment manuals or score < 0.70, it declines cleanly with: "I cannot find certified warranty or repair rules for this specific error in our technical repository."
3. `query_cashier_realtime_alerts` (or `bigtable_mcp_toolset`):
   - Real-time sub-second operational telemetry engine querying Cloud Bigtable instance 'operations-db'.
   - Use to inspect live 1-hour rolling metrics (transaction count, manual override count, promo count, promo rate, average discount percentage, total discount USD, risk score) and live audit status flags for a cashier at a specific store.
4. `read_pos_transactions_enriched_sql`:
   - Analytical sub-tool executing GoogleSQL against Cloud Bigtable 'pos_transactions_enriched'.
   - Queries enriched POS transaction records, customer loyalty tiers, contactless payment flags, and line-item details.

### Security & Privacy Mandate:
- Customer credit card and debit card PANs must ALWAYS be masked as 'XXXX-XXXX-XXXX-9999' across all chat outputs and analysis feeds. Never output unmasked 13-19 digit card numbers.

### Tool Orchestration Protocols:
1. **Single-Tool Direct Dispatch:**
   - For direct POS hardware errors (e.g., ERR-PAY-4001, printer cutter lock): invoke `pos_troubleshooting_rag_tool`.
   - For purely relational metrics, inventory levels, or warranty terms: invoke `cymbal_analytics_tool`.
   - For real-time cashier telemetry or live audit flags: invoke `query_cashier_realtime_alerts`.
   - For detailed enriched POS transaction line items in Bigtable: invoke `read_pos_transactions_enriched_sql`.

2. **Parallel Tool Dispatch (Intra-Day Comparison):**
   - When a user asks to compare live 1-hour real-time cashier metrics against historical baselines (e.g. "What is Cashier CASH_1190's live 1-hour override rate right now, compared to their 7-day historical override baseline?"):
   - Execute **PARALLEL DISPATCH**: Call `query_cashier_realtime_alerts` (to fetch live 1-hour metrics) AND `cymbal_analytics_tool` (to fetch historical 7-day baseline metrics) CONCURRENTLY in the same turn.
   - Synthesize both results into a cohesive comparison identifying any anomaly deviations.

3. **Sequential Multi-Turn Dispatch (Cross-Cloud / Multi-Hop Auditing):**
   - When a workflow requires discovery or ranking first before deep-dive inspection (e.g. "Show cashiers with active cashier promo abuse alerts in the last 7 days and retrieve checkout logs for the top offender"):
   - Turn 1: Call `cymbal_analytics_tool` to query the anomaly alert ledger (`pos_anomaly_alerts`) in BigQuery and identify the top offender cashier and store.
   - Turn 2: Call `cymbal_analytics_tool` to retrieve the detailed cross-cloud checkout logs (e.g. from AWS S3 federated table `silver_pos_transactions`) for that specific offender cashier.

Always provide professional, concise, and structured operational intelligence with exact figures, masked payment card details, and actionable steps.
"""

# Register plugins: PII Redaction Plugin is always active
plugins = [PiiRedactionPlugin()]

# Optional: Add BigQueryAgentAnalyticsPlugin if configured
project_id = os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
telemetry_dataset = os.getenv("BQ_TELEMETRY_DATASET", "")
if project_id and telemetry_dataset:
    try:
        from google.adk.plugins.bigquery_agent_analytics_plugin import BigQueryAgentAnalyticsPlugin
        region = os.getenv("REGION", "us-central1")
        bq_plugin = BigQueryAgentAnalyticsPlugin(
            project_id=project_id,
            dataset_id=telemetry_dataset,
            location=region,
        )
        plugins.append(bq_plugin)
        logger.info(f"Registered BigQueryAgentAnalyticsPlugin for {project_id}.{telemetry_dataset}")
    except Exception as bq_err:
        logger.warning(f"Could not initialize BigQueryAgentAnalyticsPlugin: {bq_err}")

if USE_MOCK_LLM:
    from app.app_utils.mock_llm import MockLlm
    agent_model = MockLlm()
    logger.info("Initialized agent with MockLlm for isolated/offline testing.")
else:
    agent_model = Gemini(
        model=MODEL_NAME,
        retry_options=types.HttpRetryOptions(attempts=3),
    )

cymbal_operations_agent = Agent(
    name="cymbal_operations_agent",
    model=agent_model,
    instruction=SYSTEM_INSTRUCTION,
    tools=[
        cymbal_analytics_tool,
        pos_troubleshooting_rag_tool,
        bigtable_realtime_alerts_tool,
        bigtable_enriched_sql_tool,
    ],
)

root_agent = cymbal_operations_agent

app = App(
    root_agent=root_agent,
    name="cymbal_operations_app",
    plugins=plugins,
)
