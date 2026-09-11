"""Analytics tool wrapping the BigQuery Conversational Data Agent for Cymbal Retail."""

import json
import logging
import os
import time
from typing import Any, Dict, List

import google.auth
import google.auth.transport.requests

from google.adk.tools.data_agent.data_agent_tool import (
    DataAgentToolConfig,
    ask_data_agent,
)

from app.app_utils.pii import mask_card_pii

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", os.getenv("GOOGLE_CLOUD_PROJECT", "project-elevate-503005"))
DATA_AGENT_ID = os.getenv("DATA_AGENT_ID", "cymbal-retail-analytics-data-agent")
DATA_AGENT_RESOURCE_NAME = os.getenv(
    "DATA_AGENT_RESOURCE_NAME",
    f"projects/{PROJECT_ID}/locations/global/dataAgents/{DATA_AGENT_ID}",
)


def _format_data_agent_response(response_steps: List[Dict[str, Any]]) -> str:
    """Formats the multi-step stream response from the Data Agent into clean markdown."""
    generated_sql = ""
    data_summary = ""
    final_text_parts: List[str] = []

    for step in response_steps:
        # Check for generated SQL
        if isinstance(step, dict):
            if "data" in step and isinstance(step["data"], dict) and "generatedSql" in step["data"]:
                generated_sql = step["data"]["generatedSql"].strip()

            # Check for tabular data results
            if "Data Retrieved" in step and isinstance(step["Data Retrieved"], dict):
                dr = step["Data Retrieved"]
                headers = dr.get("headers", [])
                rows = dr.get("rows", [])
                summary = dr.get("summary", "")
                if headers and rows:
                    header_line = " | ".join(str(h) for h in headers)
                    sep_line = " | ".join(["---"] * len(headers))
                    row_lines = [" | ".join(str(cell) for cell in row) for row in rows[:15]]
                    data_summary = f"{header_line}\n{sep_line}\n" + "\n".join(row_lines)
                    if summary:
                        data_summary += f"\n\n*({summary})*"

            # Check for text or final response parts
            if "text" in step and isinstance(step["text"], dict):
                text_type = step["text"].get("textType", "")
                parts = step["text"].get("parts", [])
                if text_type == "FINAL_RESPONSE" and parts:
                    final_text_parts.extend(parts)

    output_sections: List[str] = []

    if final_text_parts:
        output_sections.append("\n".join(final_text_parts))

    if generated_sql:
        output_sections.append(f"### Generated GoogleSQL Query:\n```sql\n{generated_sql}\n```")

    if data_summary:
        output_sections.append(f"### Query Results:\n{data_summary}")

    if not output_sections:
        return "Query completed successfully, but no data records were returned matching the criteria."

    full_output = "\n\n".join(output_sections)
    return mask_card_pii(full_output)


def cymbal_analytics_tool(query: str) -> str:
    """Queries the Cymbal Retail BigQuery Conversational Data Agent for enterprise retail analytics.

    Use this tool for:
    - Intraday and historical sales transactions, customer purchase history.
    - Store inventory positions, stockout risks, and cover hours remaining (< 20 hours).
    - Warranty coverage triage (joining past purchases with supplier warranty terms).
    - Cashier promo abuse anomalies and federated cross-cloud AWS S3 checkout audit logs.
    - Questions involving standardized enterprise glossary metrics (e.g., Net Transaction Revenue,
      Total On-Hand Inventory, Estimated Cover Hours, Cashier Promo Override Rate).

    Args:
        query: The natural language analytical question to ask. Pass user questions verbatim
               to preserve standardized business glossary terms and parameter filters.

    Returns:
        A formatted string containing the generated SQL, query result data summary, and analysis.
    """
    sanitized_query = mask_card_pii(query)
    max_retries = 3
    base_delay = 1.0

    for attempt in range(1, max_retries + 1):
        try:
            creds, _ = google.auth.default()
            auth_req = google.auth.transport.requests.Request()
            creds.refresh(auth_req)

            config = DataAgentToolConfig(location="global", max_query_result_rows=50)

            result = ask_data_agent(
                data_agent_name=DATA_AGENT_RESOURCE_NAME,
                query=sanitized_query,
                credentials=creds,
                settings=config,
                tool_context=None,
            )

            if result.get("status") == "SUCCESS":
                return _format_data_agent_response(result.get("response", []))

            error_msg = result.get("error_details", "Unknown error from Data Agent")
            logger.warning(f"Data Agent query attempt {attempt} failed: {error_msg}")

        except Exception as e:
            logger.warning(f"Data Agent network attempt {attempt} failed: {e}")

        if attempt < max_retries:
            time.sleep(base_delay * (2 ** (attempt - 1)))

    return (
        "Notice: The store analytics data service is temporarily unreachable after multiple retries. "
        "Please verify your query or try again in a few moments."
    )
