"""Unit tests for Payment Card PII Masking."""

import pytest
from app.app_utils.pii import mask_card_pii, mask_data_structures


def test_mask_card_pii_hyphenated():
    text = "Customer paid using card 4532-1234-5678-9012 for their purchase."
    expected = "Customer paid using card XXXX-XXXX-XXXX-9012 for their purchase."
    assert mask_card_pii(text) == expected


def test_mask_card_pii_spaced():
    text = "Payment card: 5412 7534 8901 2345 confirmed."
    expected = "Payment card: XXXX-XXXX-XXXX-2345 confirmed."
    assert mask_card_pii(text) == expected


def test_mask_card_pii_raw_digits():
    text = "PAN 4111111111111111 authorized."
    expected = "PAN XXXX-XXXX-XXXX-1111 authorized."
    assert mask_card_pii(text) == expected


def test_preserves_transaction_and_store_ids():
    text = "Transaction TXN-20260910-0000715 at STORE_048 terminal POS_01"
    assert mask_card_pii(text) == text


def test_mask_nested_structures():
    data = {
        "txn": "TXN-123",
        "card": "4532-1234-5678-9012",
        "items": [
            {"name": "Watch", "notes": "Paid with 5412 7534 8901 2345"}
        ]
    }
    masked = mask_data_structures(data)
    assert masked["card"] == "XXXX-XXXX-XXXX-9012"
    assert masked["items"][0]["notes"] == "Paid with XXXX-XXXX-XXXX-2345"
    assert masked["txn"] == "TXN-123"
