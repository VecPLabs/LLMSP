"""Claude (Anthropic) adapter for LLMSP.

Uses the Anthropic Messages API to generate and review content.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter


class ClaudeAdapter(BaseAdapter):
    """Adapter for Anthropic's Claude models.

    Supports Claude 4.5 Sonnet, Claude Opus 4.6, etc.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-5-20250929",
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        super().__init__(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = base_url

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        """Call the Anthropic Messages API."""
        import httpx

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        # Extract text from response content blocks
        text_parts = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])

        # Extract token usage
        usage = data.get("usage", {})
        return ApiResult(
            text="\n".join(text_parts),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
