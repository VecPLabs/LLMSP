"""Gemini (Google) adapter for LLMSP.

Uses the Gemini API to generate and review content.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from llmsp.adapters.base import ApiResult, BaseAdapter


class GeminiAdapter(BaseAdapter):
    """Adapter for Google's Gemini models.

    Supports Gemini 2.0 Flash, Gemini 2.0 Pro, etc.
    """

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        base_url: str = "https://generativelanguage.googleapis.com",
    ) -> None:
        super().__init__(model=model, api_key=api_key, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        self.base_url = base_url

    async def _call_api(self, system_prompt: str, user_prompt: str) -> ApiResult:
        """Call the Gemini generateContent API."""
        import httpx

        url = (
            f"{self.base_url}/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )

        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {
                    "parts": [{"text": user_prompt}],
                },
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        # Extract text from Gemini response
        candidates = data.get("candidates", [])
        if not candidates:
            return ApiResult(text="")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "\n".join(p.get("text", "") for p in parts)

        # Extract token usage from usageMetadata
        usage_meta = data.get("usageMetadata", {})
        return ApiResult(
            text=text,
            input_tokens=usage_meta.get("promptTokenCount", 0),
            output_tokens=usage_meta.get("candidatesTokenCount", 0),
        )
