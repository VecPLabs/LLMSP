"""Grok (xAI) adapter for LLMSP.

Uses the xAI API (OpenAI-compatible) to generate and review content.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter


class GrokAdapter(BaseAdapter):
    """Adapter for xAI's Grok models.

    Uses the OpenAI-compatible chat completions endpoint.
    """

    def __init__(
        self,
        model: str = "grok-3",
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        base_url: str = "https://api.x.ai",
    ) -> None:
        super().__init__(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or os.environ.get("XAI_API_KEY", "")
        self.base_url = base_url

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        """Call the xAI chat completions API."""
        import httpx

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return ApiResult(text="")

        text = choices[0].get("message", {}).get("content", "")

        # Extract token usage (OpenAI-compatible format)
        usage = data.get("usage", {})
        return ApiResult(
            text=text,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
