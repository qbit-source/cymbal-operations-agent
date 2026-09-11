"""Payment Card PII Masking Utilities for Cymbal Operations Agent.

Detects and redacts payment card (credit/debit/gift card) PANs into 'XXXX-XXXX-XXXX-9999'
across chat feeds, tool query inputs/outputs, and database streams.
"""

import re
from typing import Any, Dict, List, Union

# Matches 13 to 19 digit payment card numbers (formatted with spaces/hyphens or raw digits)
# using negative lookaround so it does not collide with timestamps, store IDs, or transaction IDs.
_CARD_PAN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}|\d{13,19})(?![A-Za-z0-9_-])"
)


def mask_card_pii(text: str) -> str:
    """Masks payment card numbers in text into 'XXXX-XXXX-XXXX-9999'.

    Preserves the last 4 digits for operational verification while obscuring
    the preceding digits for PCI-DSS compliance.

    Args:
        text: The input string possibly containing payment card numbers.

    Returns:
        The sanitized string with card PANs redacted.
    """
    if not text or not isinstance(text, str):
        return text

    def _replace_match(match: re.Match) -> str:
        raw_val = match.group(0)
        digits = re.sub(r"\D", "", raw_val)
        if 13 <= len(digits) <= 19:
            last4 = digits[-4:]
            return f"XXXX-XXXX-XXXX-{last4}"
        return raw_val

    return _CARD_PAN_PATTERN.sub(_replace_match, text)


def mask_data_structures(data: Any) -> Any:
    """Recursively walks dicts/lists to mask payment card numbers in string values."""
    if isinstance(data, str):
        return mask_card_pii(data)
    elif isinstance(data, dict):
        return {k: mask_data_structures(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [mask_data_structures(item) for item in data]
    return data
