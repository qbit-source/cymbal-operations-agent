"""Unit tests for POS Troubleshooting RAG Tool threshold and fallback behavior.

Tests verification of:
1. Cosine similarity score > 0.70 -> verified diagnostic runbook procedure returned.
2. Cosine similarity score == 0.70 -> verified diagnostic runbook procedure returned.
3. Cosine similarity score < 0.70 (e.g. 0.69) without error code -> certified mandatory decline string returned.
4. Cosine similarity score < 0.70 (e.g. 0.45) with error code token match -> fallback code match runbook returned.
5. Cosine similarity score < 0.70 (e.g. 0.50) with unmatched error code -> certified mandatory decline string returned.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.tools.rag_tool import (
    MANDATORY_DECLINE_STRING,
    SIMILARITY_THRESHOLD,
    pos_troubleshooting_rag_tool,
)


class MockRow:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.fixture
def mock_bq_client():
    with patch("google.cloud.bigquery.Client") as mock_cls:
        client_instance = MagicMock()
        mock_cls.return_value = client_instance
        yield client_instance


def test_rag_similarity_above_threshold(mock_bq_client):
    """Cosine similarity score 0.85 (> 0.70) returns verified diagnostic runbook."""
    mock_row = MockRow(
        document_title="Toshiba TCx 810 Field Service Manual",
        equipment_covered="Toshiba TCx 810 POS",
        source_pdf_uri="gs://cymbal-ops-docs/toshiba_tcx810_manual.pdf",
        similarity_score=0.8500,
        chunk_index=12,
        stitched_runbook="Step 1: Check power supply cable.\nStep 2: Reseat touchscreen ribbon connector.",
    )
    mock_job = MagicMock()
    mock_job.result.return_value = [mock_row]
    mock_bq_client.query.return_value = mock_job

    result = pos_troubleshooting_rag_tool("Touchscreen flickers on Toshiba terminal")

    assert "Verified POS Hardware Diagnostic Runbook" in result
    assert "Toshiba TCx 810 POS" in result
    assert "0.8500" in result
    assert "Step 1: Check power supply cable" in result
    assert "https://storage.cloud.google.com/cymbal-ops-docs/toshiba_tcx810_manual.pdf" in result
    assert MANDATORY_DECLINE_STRING not in result


def test_rag_similarity_exactly_at_threshold(mock_bq_client):
    """Cosine similarity score 0.70 (== 0.70) meets certified threshold and returns runbook."""
    mock_row = MockRow(
        document_title="Diebold Nixdorf BEETLE A1150 Hardware Guide",
        equipment_covered="Diebold Nixdorf BEETLE A1150",
        source_pdf_uri="gs://cymbal-ops-docs/beetle_a1150_guide.pdf",
        similarity_score=0.7000,
        chunk_index=5,
        stitched_runbook="Step 1: Inspect 24V PoweredUSB port.\nStep 2: Replace thermal printer cable.",
    )
    mock_job = MagicMock()
    mock_job.result.return_value = [mock_row]
    mock_bq_client.query.return_value = mock_job

    result = pos_troubleshooting_rag_tool("Printer port voltage drops on Diebold")

    assert "Verified POS Hardware Diagnostic Runbook" in result
    assert "Diebold Nixdorf BEETLE A1150" in result
    assert "0.7000" in result
    assert "Step 1: Inspect 24V PoweredUSB port" in result
    assert MANDATORY_DECLINE_STRING not in result


def test_rag_similarity_below_threshold_triggers_decline(mock_bq_client):
    """Cosine similarity score 0.69 (< 0.70) without error code triggers mandatory decline string."""
    mock_row = MockRow(
        document_title="General Retail Store Guidelines",
        equipment_covered="Generic Retail Fixtures",
        source_pdf_uri="gs://cymbal-ops-docs/general_guidelines.pdf",
        similarity_score=0.6900,
        chunk_index=2,
        stitched_runbook="General store opening checklist.",
    )
    mock_job = MagicMock()
    mock_job.result.return_value = [mock_row]
    mock_bq_client.query.return_value = mock_job

    result = pos_troubleshooting_rag_tool("How do I arrange the merchandise display shelf?")

    assert result == MANDATORY_DECLINE_STRING


def test_rag_similarity_below_threshold_with_error_code_fallback_success(mock_bq_client):
    """Cosine similarity score 0.45 (< 0.70) but query has valid error code token resolves via full-text fallback."""
    mock_vector_row = MockRow(
        document_title="General Diagnostics",
        equipment_covered="Generic Terminal",
        source_pdf_uri="gs://cymbal-ops-docs/general.pdf",
        similarity_score=0.4500,
        chunk_index=1,
        stitched_runbook="Low relevance runbook",
    )
    mock_vector_job = MagicMock()
    mock_vector_job.result.return_value = [mock_vector_row]

    mock_fallback_row = MockRow(
        document_title="Diebold Nixdorf BEETLE A1150 Hardware Guide",
        equipment_covered="Diebold Nixdorf BEETLE A1150",
        source_pdf_uri="gs://cymbal-ops-docs/beetle_a1150_guide.pdf",
        stitched_runbook="Replace 24V power supply module FRU-DN-9921 for ERR-DN-PRNT-24V.",
    )
    mock_fallback_job = MagicMock()
    mock_fallback_job.result.return_value = [mock_fallback_row]

    mock_bq_client.query.side_effect = [mock_vector_job, mock_fallback_job]

    result = pos_troubleshooting_rag_tool("Cashier got error ERR-DN-PRNT-24V at register")

    assert "Verified POS Hardware Diagnostic Runbook (Exact Code Match)" in result
    assert "ERR-DN-PRNT-24V" in result
    assert "FRU-DN-9921" in result
    assert MANDATORY_DECLINE_STRING not in result


def test_rag_similarity_below_threshold_with_unmatched_error_code_triggers_decline(mock_bq_client):
    """Cosine similarity score 0.50 (< 0.70) with error code that has no manual match returns decline string."""
    mock_vector_row = MockRow(
        document_title="General Diagnostics",
        equipment_covered="Generic Terminal",
        source_pdf_uri="gs://cymbal-ops-docs/general.pdf",
        similarity_score=0.5000,
        chunk_index=1,
        stitched_runbook="Low relevance runbook",
    )
    mock_vector_job = MagicMock()
    mock_vector_job.result.return_value = [mock_vector_row]

    mock_fallback_job = MagicMock()
    mock_fallback_job.result.return_value = []

    mock_bq_client.query.side_effect = [mock_vector_job, mock_fallback_job]

    result = pos_troubleshooting_rag_tool("POS displayed mysterious code ERR-UNKNOWN-99999")

    assert result == MANDATORY_DECLINE_STRING
