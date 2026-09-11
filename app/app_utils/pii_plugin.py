"""PII Redaction Plugin for ADK Agent and Runner.

Sanitizes model outputs and tool outputs dynamically, ensuring payment card
numbers are never exposed in conversation streams, UI logs, or event storage.
"""

from typing import Any, Optional
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.models import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.adk.agents.callback_context import CallbackContext

from app.app_utils.pii import mask_card_pii, mask_data_structures


class PiiRedactionPlugin(BasePlugin):
    """ADK Plugin that redacts payment card PANs from model and tool responses."""

    def __init__(self, name: str = "pii_redaction_plugin"):
        super().__init__(name=name)

    async def after_model_callback(
        self, *, callback_context: CallbackContext, llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        """Redacts card PANs in raw LLM response content."""
        if llm_response and llm_response.content and llm_response.content.parts:
            for part in llm_response.content.parts:
                if getattr(part, "text", None):
                    part.text = mask_card_pii(part.text)
        return llm_response

    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: dict[str, Any],
        tool_context: ToolContext,
        result: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Redacts card PANs from tool return values."""
        if result is not None:
            return mask_data_structures(result)
        return result
