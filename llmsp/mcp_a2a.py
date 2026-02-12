"""MCP Client + A2A Interop — protocol standardization layer.

MCP (Model Context Protocol):
  Allows LLMSP agents to connect to external tools (GitHub, Jira,
  Slack, databases) through a standardized tool interface. Any MCP
  server becomes instantly accessible to all agents.

A2A (Agent-to-Agent Protocol):
  Standardizes the SignedEvent envelope format so agents from different
  vendors and runtimes can securely join an LLMSP council. Handles
  format negotiation, capability exchange, and trust verification.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from llmsp.models import (
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TextBlock,
)
from llmsp.principal import AgentPrincipal


# ===========================================================================
# MCP Client — connect agents to external tools
# ===========================================================================


class MCPToolType(str, Enum):
    """Categories of MCP tools."""
    READ = "read"        # Read data from external source
    WRITE = "write"      # Write/modify external data
    EXECUTE = "execute"  # Execute actions (CI, deploy, etc.)
    SEARCH = "search"    # Search external systems


@dataclass
class MCPTool:
    """An external tool exposed via MCP."""

    name: str
    description: str
    tool_type: MCPToolType
    input_schema: dict[str, Any]
    server_url: str = ""
    requires_auth: bool = False

    def validate_input(self, params: dict) -> list[str]:
        """Validate tool input against schema. Returns error messages."""
        errors: list[str] = []
        required = self.input_schema.get("required", [])
        properties = self.input_schema.get("properties", {})

        for req in required:
            if req not in params:
                errors.append(f"Missing required parameter: {req}")

        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type", "string")
                type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
                expected = type_map.get(expected_type, str)
                if not isinstance(value, expected):
                    errors.append(f"Parameter '{key}' expected {expected_type}, got {type(value).__name__}")

        return errors


@dataclass
class MCPToolResult:
    """Result from an MCP tool invocation."""

    tool_name: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class MCPToolRegistry:
    """Registry of available MCP tools.

    In a production system this would connect to actual MCP servers
    via stdio/SSE transport. Here we model the protocol interface
    so agents can discover and invoke tools.
    """

    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}
        self._handlers: dict[str, Any] = {}

    def register_tool(
        self,
        tool: MCPTool,
        handler: Any = None,
    ) -> None:
        """Register an MCP tool with an optional local handler."""
        self._tools[tool.name] = tool
        if handler:
            self._handlers[tool.name] = handler

    def list_tools(self) -> list[MCPTool]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> Optional[MCPTool]:
        return self._tools.get(name)

    def get_tools_by_type(self, tool_type: MCPToolType) -> list[MCPTool]:
        return [t for t in self._tools.values() if t.tool_type == tool_type]

    async def invoke(self, tool_name: str, params: dict) -> MCPToolResult:
        """Invoke an MCP tool with given parameters."""
        tool = self._tools.get(tool_name)
        if not tool:
            return MCPToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' not found",
            )

        # Validate input
        errors = tool.validate_input(params)
        if errors:
            return MCPToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Validation failed: {'; '.join(errors)}",
            )

        t0 = time.time()

        handler = self._handlers.get(tool_name)
        if handler:
            try:
                if callable(handler):
                    import asyncio
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(params)
                    else:
                        result = handler(params)
                    return MCPToolResult(
                        tool_name=tool_name,
                        success=True,
                        data=result,
                        execution_time_ms=(time.time() - t0) * 1000,
                    )
            except Exception as e:
                return MCPToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=str(e),
                    execution_time_ms=(time.time() - t0) * 1000,
                )

        # No handler — return stub
        return MCPToolResult(
            tool_name=tool_name,
            success=False,
            error="No handler registered (remote MCP transport not connected)",
        )

    def tools_schema_for_prompt(self) -> str:
        """Format all tools into a prompt-injectable schema description."""
        if not self._tools:
            return "No external tools available."

        lines = ["=== Available MCP Tools ==="]
        for tool in self._tools.values():
            lines.append(f"\n[{tool.name}] ({tool.tool_type.value})")
            lines.append(f"  {tool.description}")
            props = tool.input_schema.get("properties", {})
            required = set(tool.input_schema.get("required", []))
            if props:
                lines.append("  Parameters:")
                for pname, pschema in props.items():
                    req = " (required)" if pname in required else ""
                    ptype = pschema.get("type", "any")
                    pdesc = pschema.get("description", "")
                    lines.append(f"    - {pname}: {ptype}{req} — {pdesc}")

        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._tools)


# ---------------------------------------------------------------------------
# Built-in MCP tool templates
# ---------------------------------------------------------------------------


def github_issues_tool(owner: str = "", repo: str = "") -> MCPTool:
    """MCP tool template for GitHub Issues."""
    return MCPTool(
        name="github_issues",
        description="Search and manage GitHub issues",
        tool_type=MCPToolType.SEARCH,
        input_schema={
            "properties": {
                "action": {"type": "string", "description": "list|get|create|comment"},
                "issue_number": {"type": "integer", "description": "Issue number (for get/comment)"},
                "query": {"type": "string", "description": "Search query (for list)"},
                "body": {"type": "string", "description": "Issue body or comment text"},
            },
            "required": ["action"],
        },
        server_url=f"https://api.github.com/repos/{owner}/{repo}",
        requires_auth=True,
    )


def slack_tool() -> MCPTool:
    """MCP tool template for Slack messaging."""
    return MCPTool(
        name="slack",
        description="Send messages to Slack channels",
        tool_type=MCPToolType.WRITE,
        input_schema={
            "properties": {
                "channel": {"type": "string", "description": "Slack channel name"},
                "message": {"type": "string", "description": "Message text"},
            },
            "required": ["channel", "message"],
        },
        requires_auth=True,
    )


def database_query_tool() -> MCPTool:
    """MCP tool template for database queries."""
    return MCPTool(
        name="database_query",
        description="Execute read-only SQL queries against the project database",
        tool_type=MCPToolType.READ,
        input_schema={
            "properties": {
                "query": {"type": "string", "description": "SQL query (SELECT only)"},
                "database": {"type": "string", "description": "Database name"},
            },
            "required": ["query"],
        },
    )


# ===========================================================================
# A2A Protocol — cross-vendor agent interoperability
# ===========================================================================


class A2ACapability(str, Enum):
    """Capabilities an agent can advertise."""
    DELIBERATE = "deliberate"      # Can participate in councils
    REVIEW = "review"              # Can review proposals
    SYNTHESIZE = "synthesize"      # Can merge/summarize
    EXECUTE = "execute"            # Can run code/tools
    PLAN = "plan"                  # Can decompose goals


@dataclass
class A2AAgentCard:
    """Agent capability advertisement for A2A discovery.

    Published by each agent so other agents (even cross-vendor)
    can discover capabilities and establish trust.
    """

    agent_id: str
    name: str
    vendor: str
    model: str
    capabilities: list[A2ACapability]
    supported_block_types: list[str]
    protocol_version: str = "1.0"
    public_key_hex: str = ""
    endpoint: str = ""
    max_context_tokens: int = 0
    cost_per_1k_tokens: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "vendor": self.vendor,
            "model": self.model,
            "capabilities": [c.value for c in self.capabilities],
            "supported_block_types": self.supported_block_types,
            "protocol_version": self.protocol_version,
            "public_key_hex": self.public_key_hex,
            "endpoint": self.endpoint,
            "max_context_tokens": self.max_context_tokens,
            "cost_per_1k_tokens": self.cost_per_1k_tokens,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> A2AAgentCard:
        data["capabilities"] = [A2ACapability(c) for c in data.get("capabilities", [])]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def supports(self, capability: A2ACapability) -> bool:
        return capability in self.capabilities


@dataclass
class A2AEnvelope:
    """Cross-vendor message envelope for the A2A protocol.

    Wraps an LLMSP SignedEvent with vendor-neutral metadata so agents
    from different systems can exchange messages securely.
    """

    envelope_id: str
    protocol_version: str
    sender: A2AAgentCard
    recipient_filter: dict   # {"capability": "deliberate"} or {"agent_id": "..."}
    payload: dict            # Serialized SignedEvent
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: int = 300
    require_signature: bool = True

    def to_json(self) -> str:
        return json.dumps({
            "envelope_id": self.envelope_id,
            "protocol_version": self.protocol_version,
            "sender": self.sender.to_dict(),
            "recipient_filter": self.recipient_filter,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
            "require_signature": self.require_signature,
        })

    @classmethod
    def from_json(cls, raw: str) -> A2AEnvelope:
        data = json.loads(raw)
        data["sender"] = A2AAgentCard.from_dict(data["sender"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @property
    def is_expired(self) -> bool:
        return time.time() > self.timestamp + self.ttl_seconds


class A2ADirectory:
    """Registry of A2A agent cards for discovery and routing.

    Agents register their cards here. The directory supports
    capability-based discovery for cross-vendor interop.
    """

    def __init__(self) -> None:
        self._cards: dict[str, A2AAgentCard] = {}

    def register(self, card: A2AAgentCard) -> None:
        self._cards[card.agent_id] = card

    def unregister(self, agent_id: str) -> None:
        self._cards.pop(agent_id, None)

    def discover(
        self,
        capability: Optional[A2ACapability] = None,
        vendor: Optional[str] = None,
    ) -> list[A2AAgentCard]:
        """Find agents by capability and/or vendor."""
        results = list(self._cards.values())

        if capability:
            results = [c for c in results if c.supports(capability)]
        if vendor:
            results = [c for c in results if c.vendor == vendor]

        return results

    def get(self, agent_id: str) -> Optional[A2AAgentCard]:
        return self._cards.get(agent_id)

    @property
    def all_cards(self) -> list[A2AAgentCard]:
        return list(self._cards.values())

    def __len__(self) -> int:
        return len(self._cards)


def create_agent_card(
    principal: AgentPrincipal,
    vendor: str = "llmsp",
    model: str = "local",
    capabilities: Optional[list[A2ACapability]] = None,
) -> A2AAgentCard:
    """Create an A2A agent card from an LLMSP principal."""
    return A2AAgentCard(
        agent_id=principal.agent_id,
        name=principal.name,
        vendor=vendor,
        model=model,
        capabilities=capabilities or [A2ACapability.DELIBERATE, A2ACapability.REVIEW],
        supported_block_types=["text", "claim", "code", "task", "decision"],
        public_key_hex=principal.public_key_bytes.hex(),
    )


def wrap_event_as_envelope(
    event: SignedEvent,
    sender_card: A2AAgentCard,
    recipient_filter: Optional[dict] = None,
) -> A2AEnvelope:
    """Wrap an LLMSP SignedEvent in an A2A envelope for cross-vendor transport."""
    return A2AEnvelope(
        envelope_id=f"a2a_{event.event_id}",
        protocol_version="1.0",
        sender=sender_card,
        recipient_filter=recipient_filter or {"capability": "deliberate"},
        payload=json.loads(event.model_dump_json()),
    )


def unwrap_envelope(envelope: A2AEnvelope) -> SignedEvent:
    """Extract an LLMSP SignedEvent from an A2A envelope."""
    return SignedEvent.model_validate(envelope.payload)
