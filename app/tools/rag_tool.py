"""POS Troubleshooting RAG Tool over BigQuery Vector Search and Full-Text Search."""

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import google.auth
from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "project-elevate-503005")
CHUNK_TABLE = f"{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings"
SIMILARITY_THRESHOLD = 0.70


def _gcs_to_https(gcs_uri: str) -> str:
    """Converts a gs:// URI to an authenticated clickable HTTPS URL."""
    if not gcs_uri:
        return ""
    if gcs_uri.startswith("gs://"):
        return gcs_uri.replace("gs://", "https://storage.cloud.google.com/")
    return gcs_uri


def _extract_error_code(query: str) -> Optional[str]:
    """Extracts common hardware/payment error code tokens (e.g. ERR-PAY-4001, ERR-DN-PRNT-24V)."""
    match = re.search(r"\b(ERR-[A-Za-z0-9\-_]+)\b", query, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def pos_troubleshooting_rag_tool(query: str) -> str:
    """Performs vector similarity search and runbook retrieval over POS terminal technical manuals.

    Use this tool to look up:
    - Hardware troubleshooting protocols, field service steps, and component replacement.
    - Diagnostics and error codes (e.g. ERR-PAY-4001 EMV contactless payment freeze, ERR-DN-PRNT-24V).
    - Device claim locks, thermal emergency shutdowns, power budgets, and FRU part numbers.
    - Toshiba TCx 810, Diebold Nixdorf BEETLE A1150, HP Engage One Pro, and Clover Station systems.

    Args:
        query: The technical error code, hardware fault description, or equipment runbook question.

    Returns:
        The verified diagnostic procedure, adjacent runbook steps, FRU recommendations,
        and certified clickable documentation link from Cloud Storage.
    """
    client = bigquery.Client(project=PROJECT_ID)
    max_retries = 3
    base_delay = 1.0

    # 1. Primary Vector Search with Adjacent Context Window Stitching (N-1 to N+1)
    vector_sql = f"""
    WITH top_match AS (
      SELECT
        base.document_filename,
        base.document_title,
        base.equipment_covered,
        base.source_pdf_uri,
        base.chunk_index,
        ROUND(1 - distance, 4) AS similarity_score
      FROM VECTOR_SEARCH(
        TABLE `{CHUNK_TABLE}`,
        'embedding',
        (SELECT AI.EMBED(@user_query, endpoint => 'text-embedding-005').result AS embedding),
        top_k => 1,
        distance_type => 'COSINE'
      )
    )
    SELECT
      m.document_title,
      m.equipment_covered,
      m.source_pdf_uri,
      m.similarity_score,
      m.chunk_index,
      STRING_AGG(c.chunk_content, '\\n' ORDER BY c.chunk_index ASC) AS stitched_runbook
    FROM top_match m
    JOIN `{CHUNK_TABLE}` c
      ON m.document_filename = c.document_filename
      AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
    GROUP BY m.document_title, m.equipment_covered, m.source_pdf_uri, m.similarity_score, m.chunk_index;
    """

    for attempt in range(1, max_retries + 1):
        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("user_query", "STRING", query)
                ]
            )
            query_job = client.query(vector_sql, job_config=job_config)
            rows = list(query_job.result())

            if rows:
                row = rows[0]
                similarity = float(row.similarity_score)
                title = row.document_title
                equipment = row.equipment_covered
                doc_url = _gcs_to_https(row.source_pdf_uri)
                runbook = row.stitched_runbook

                # If score meets certified threshold, return procedure
                if similarity >= SIMILARITY_THRESHOLD:
                    return (
                        f"### Verified POS Hardware Diagnostic Runbook\n\n"
                        f"- **Equipment:** {equipment}\n"
                        f"- **Manual:** [{title}]({doc_url})\n"
                        f"- **Relevance Score:** {similarity:.4f} *(Certified Threshold >= 0.70)*\n\n"
                        f"#### Troubleshooting & Field Recovery Procedure:\n"
                        f"{runbook}\n\n"
                        f"📄 **Certified Documentation Link:** [{doc_url}]({doc_url})"
                    )

            # If vector score was below threshold or no vector rows, proceed to fallback check
            break
        except Exception as e:
            logger.warning(f"Vector search attempt {attempt} failed: {e}")
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** (attempt - 1)))
            else:
                return f"Notice: BigQuery vector search service is temporarily unreachable: {e}"

    # 2. Secondary Full-Text SEARCH Fallback for specific Error Codes
    error_code = _extract_error_code(query)
    if error_code:
        fallback_sql = f"""
        WITH match AS (
          SELECT
            document_filename,
            document_title,
            equipment_covered,
            source_pdf_uri,
            chunk_index
          FROM `{CHUNK_TABLE}`
          WHERE SEARCH(chunk_content, @err_token)
          ORDER BY chunk_index DESC
          LIMIT 1
        )
        SELECT
          m.document_title,
          m.equipment_covered,
          m.source_pdf_uri,
          STRING_AGG(c.chunk_content, '\\n' ORDER BY c.chunk_index ASC) AS stitched_runbook
        FROM match m
        JOIN `{CHUNK_TABLE}` c
          ON m.document_filename = c.document_filename
          AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
        GROUP BY m.document_title, m.equipment_covered, m.source_pdf_uri;
        """
        try:
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("err_token", "STRING", f"`{error_code}`")
                ]
            )
            fb_rows = list(client.query(fallback_sql, job_config=job_config).result())
            if fb_rows:
                fb_row = fb_rows[0]
                doc_url = _gcs_to_https(fb_row.source_pdf_uri)
                return (
                    f"### Verified POS Hardware Diagnostic Runbook (Exact Code Match)\n\n"
                    f"- **Error Code:** `{error_code}`\n"
                    f"- **Equipment:** {fb_row.equipment_covered}\n"
                    f"- **Manual:** [{fb_row.document_title}]({doc_url})\n\n"
                    f"#### Troubleshooting & Field Recovery Procedure:\n"
                    f"{fb_row.stitched_runbook}\n\n"
                    f"📄 **Certified Documentation Link:** [{doc_url}]({doc_url})"
                )
        except Exception as e:
            logger.warning(f"Full text search fallback failed: {e}")

    # 3. Certified Safety Warning for Out-of-Scope Inquiries
    return (
        "⚠️ **Safety Warning / Out of Scope:** The requested issue does not match certified "
        "in-store POS hardware equipment manuals (relevance score < 0.70). "
        "No certified technical runbook was found for this query. "
        "Please consult store operations or verified technical documentation."
    )
