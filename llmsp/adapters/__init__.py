"""LLM backend adapters for LLMSP agent principals.

Each adapter implements the AgentAdapter protocol, translating between
the LLMSP event model and a specific LLM API.
"""

from llmsp.adapters.claude import ClaudeAdapter
from llmsp.adapters.gemini import GeminiAdapter
from llmsp.adapters.grok import GrokAdapter
from llmsp.adapters.base import ApiResult, BaseAdapter

__all__ = [
    "ApiResult",
    "BaseAdapter",
    "ClaudeAdapter",
    "GeminiAdapter",
    "GrokAdapter",
]
