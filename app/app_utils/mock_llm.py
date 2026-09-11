"""Mock LLM for isolated/offline testing without requiring live Vertex AI or GCP credentials."""

from typing import AsyncGenerator
from google.adk.models import BaseLlm, LlmResponse, LlmRequest
from google.genai import types


class MockLlm(BaseLlm):
    """Deterministic Mock LLM supporting standard and streaming generation for testing."""

    model: str = "mock-llm-testing"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        user_text = ""
        if llm_request and llm_request.contents:
            for content in llm_request.contents:
                if content.parts:
                    for part in content.parts:
                        if getattr(part, "text", None):
                            user_text = part.text

        reply = "Mocked operational response: Store operations are running nominally."
        if "ERR-" in user_text:
            reply = "Verified POS Hardware Diagnostic Runbook: Error resolution in progress."

        content = types.Content(
            role="model",
            parts=[types.Part.from_text(text=reply)],
        )

        if stream:
            yield LlmResponse(content=content, partial=False)
        else:
            yield LlmResponse(content=content, partial=False)
