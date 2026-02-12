"""Tests for MCP Client and A2A Protocol."""

import asyncio
import json

from llmsp.mcp_a2a import (
    A2AAgentCard,
    A2ACapability,
    A2ADirectory,
    A2AEnvelope,
    MCPTool,
    MCPToolRegistry,
    MCPToolType,
    create_agent_card,
    database_query_tool,
    github_issues_tool,
    slack_tool,
    unwrap_envelope,
    wrap_event_as_envelope,
)
from llmsp.models import EventType, TextBlock
from llmsp.principal import AgentPrincipal


# ===========================================================================
# MCP Tool tests
# ===========================================================================


def test_mcp_tool_validate_input():
    tool = MCPTool(
        name="test",
        description="Test tool",
        tool_type=MCPToolType.READ,
        input_schema={
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    )

    # Valid input
    errors = tool.validate_input({"query": "test", "limit": 10})
    assert errors == []

    # Missing required
    errors = tool.validate_input({"limit": 10})
    assert len(errors) == 1
    assert "query" in errors[0]

    # Wrong type
    errors = tool.validate_input({"query": "test", "limit": "not_int"})
    assert len(errors) == 1
    assert "limit" in errors[0]


def test_mcp_registry_register_and_list():
    registry = MCPToolRegistry()
    tool = MCPTool(
        name="github",
        description="GitHub API",
        tool_type=MCPToolType.SEARCH,
        input_schema={"properties": {}, "required": []},
    )
    registry.register_tool(tool)

    assert len(registry) == 1
    assert registry.get_tool("github") is not None
    assert registry.list_tools() == [tool]


def test_mcp_registry_get_by_type():
    registry = MCPToolRegistry()
    registry.register_tool(MCPTool("gh", "GitHub", MCPToolType.SEARCH, {"properties": {}}))
    registry.register_tool(MCPTool("slack", "Slack", MCPToolType.WRITE, {"properties": {}}))
    registry.register_tool(MCPTool("db", "Database", MCPToolType.READ, {"properties": {}}))

    search_tools = registry.get_tools_by_type(MCPToolType.SEARCH)
    assert len(search_tools) == 1
    assert search_tools[0].name == "gh"


def test_mcp_invoke_with_handler():
    registry = MCPToolRegistry()
    tool = MCPTool(
        name="echo",
        description="Echo tool",
        tool_type=MCPToolType.READ,
        input_schema={"properties": {"message": {"type": "string"}}, "required": ["message"]},
    )

    def echo_handler(params: dict):
        return {"echoed": params["message"]}

    registry.register_tool(tool, handler=echo_handler)

    result = asyncio.get_event_loop().run_until_complete(
        registry.invoke("echo", {"message": "hello"})
    )
    assert result.success
    assert result.data == {"echoed": "hello"}
    assert result.execution_time_ms >= 0


def test_mcp_invoke_async_handler():
    registry = MCPToolRegistry()
    tool = MCPTool(
        name="async_echo",
        description="Async echo",
        tool_type=MCPToolType.READ,
        input_schema={"properties": {"msg": {"type": "string"}}, "required": ["msg"]},
    )

    async def async_handler(params: dict):
        return {"result": params["msg"].upper()}

    registry.register_tool(tool, handler=async_handler)

    result = asyncio.get_event_loop().run_until_complete(
        registry.invoke("async_echo", {"msg": "test"})
    )
    assert result.success
    assert result.data == {"result": "TEST"}


def test_mcp_invoke_tool_not_found():
    registry = MCPToolRegistry()
    result = asyncio.get_event_loop().run_until_complete(
        registry.invoke("nonexistent", {})
    )
    assert not result.success
    assert "not found" in result.error


def test_mcp_invoke_validation_failure():
    registry = MCPToolRegistry()
    tool = MCPTool(
        name="strict",
        description="Strict tool",
        tool_type=MCPToolType.EXECUTE,
        input_schema={"properties": {"x": {"type": "integer"}}, "required": ["x"]},
    )
    registry.register_tool(tool, handler=lambda p: p)

    result = asyncio.get_event_loop().run_until_complete(
        registry.invoke("strict", {"y": 1})
    )
    assert not result.success
    assert "Validation" in result.error


def test_mcp_invoke_handler_error():
    registry = MCPToolRegistry()
    tool = MCPTool(
        name="crash",
        description="Crasher",
        tool_type=MCPToolType.EXECUTE,
        input_schema={"properties": {}, "required": []},
    )

    def crasher(params):
        raise ValueError("Boom!")

    registry.register_tool(tool, handler=crasher)

    result = asyncio.get_event_loop().run_until_complete(
        registry.invoke("crash", {})
    )
    assert not result.success
    assert "Boom" in result.error


def test_mcp_tools_schema_for_prompt():
    registry = MCPToolRegistry()
    registry.register_tool(github_issues_tool("owner", "repo"))
    registry.register_tool(slack_tool())

    schema = registry.tools_schema_for_prompt()
    assert "github_issues" in schema
    assert "slack" in schema
    assert "MCP Tools" in schema


def test_mcp_tools_schema_empty():
    registry = MCPToolRegistry()
    schema = registry.tools_schema_for_prompt()
    assert "No external tools" in schema


def test_mcp_tool_templates():
    gh = github_issues_tool("owner", "repo")
    assert gh.name == "github_issues"
    assert gh.requires_auth

    sl = slack_tool()
    assert sl.name == "slack"
    assert sl.tool_type == MCPToolType.WRITE

    db = database_query_tool()
    assert db.name == "database_query"
    assert db.tool_type == MCPToolType.READ


# ===========================================================================
# A2A Protocol tests
# ===========================================================================


def test_a2a_agent_card_creation():
    principal = AgentPrincipal("Alice", "dev")
    card = create_agent_card(principal, vendor="anthropic", model="claude-opus-4-6")

    assert card.agent_id == principal.agent_id
    assert card.vendor == "anthropic"
    assert card.model == "claude-opus-4-6"
    assert A2ACapability.DELIBERATE in card.capabilities
    assert card.supports(A2ACapability.DELIBERATE)
    assert not card.supports(A2ACapability.PLAN)


def test_a2a_card_serialization():
    principal = AgentPrincipal("Alice", "dev")
    card = create_agent_card(principal)

    d = card.to_dict()
    assert d["agent_id"] == principal.agent_id
    assert "deliberate" in d["capabilities"]

    card2 = A2AAgentCard.from_dict(d)
    assert card2.agent_id == card.agent_id
    assert card2.capabilities == card.capabilities


def test_a2a_directory_register_and_discover():
    directory = A2ADirectory()

    card1 = A2AAgentCard(
        agent_id="a1", name="Alice", vendor="anthropic", model="opus",
        capabilities=[A2ACapability.DELIBERATE, A2ACapability.REVIEW],
        supported_block_types=["text"],
    )
    card2 = A2AAgentCard(
        agent_id="a2", name="Bob", vendor="google", model="gemini",
        capabilities=[A2ACapability.DELIBERATE, A2ACapability.SYNTHESIZE],
        supported_block_types=["text"],
    )
    card3 = A2AAgentCard(
        agent_id="a3", name="Carol", vendor="anthropic", model="sonnet",
        capabilities=[A2ACapability.REVIEW],
        supported_block_types=["text"],
    )

    directory.register(card1)
    directory.register(card2)
    directory.register(card3)

    assert len(directory) == 3

    # Find by capability
    deliberators = directory.discover(capability=A2ACapability.DELIBERATE)
    assert len(deliberators) == 2

    reviewers = directory.discover(capability=A2ACapability.REVIEW)
    assert len(reviewers) == 2

    synthesizers = directory.discover(capability=A2ACapability.SYNTHESIZE)
    assert len(synthesizers) == 1

    # Find by vendor
    anthropic = directory.discover(vendor="anthropic")
    assert len(anthropic) == 2

    # Combined filter
    anthropic_reviewers = directory.discover(capability=A2ACapability.REVIEW, vendor="anthropic")
    assert len(anthropic_reviewers) == 2


def test_a2a_directory_unregister():
    directory = A2ADirectory()
    card = A2AAgentCard(
        agent_id="a1", name="Alice", vendor="test", model="test",
        capabilities=[], supported_block_types=[],
    )
    directory.register(card)
    assert len(directory) == 1

    directory.unregister("a1")
    assert len(directory) == 0


def test_a2a_envelope_wrap_unwrap():
    principal = AgentPrincipal("Alice", "dev")
    event = principal.create_event(
        "council_1", EventType.MESSAGE,
        [TextBlock(content="My analysis of the proposal")],
    )

    card = create_agent_card(principal)
    envelope = wrap_event_as_envelope(event, card, {"capability": "deliberate"})

    assert envelope.envelope_id == f"a2a_{event.event_id}"
    assert envelope.protocol_version == "1.0"
    assert envelope.sender.agent_id == principal.agent_id

    # Unwrap back to event
    recovered = unwrap_envelope(envelope)
    assert recovered.event_id == event.event_id
    assert recovered.author_id == event.author_id
    assert recovered.channel_id == event.channel_id


def test_a2a_envelope_serialization():
    principal = AgentPrincipal("Alice", "dev")
    event = principal.create_event("ch1", EventType.MESSAGE, [TextBlock(content="hello")])
    card = create_agent_card(principal)
    envelope = wrap_event_as_envelope(event, card)

    json_str = envelope.to_json()
    parsed = json.loads(json_str)
    assert parsed["protocol_version"] == "1.0"

    # Roundtrip
    recovered = A2AEnvelope.from_json(json_str)
    assert recovered.envelope_id == envelope.envelope_id
    assert recovered.sender.agent_id == card.agent_id


def test_a2a_envelope_expiry():
    principal = AgentPrincipal("Alice", "dev")
    event = principal.create_event("ch1", EventType.MESSAGE, [TextBlock(content="test")])
    card = create_agent_card(principal)

    # Envelope with 0s TTL is expired
    envelope = wrap_event_as_envelope(event, card)
    envelope.ttl_seconds = 0
    envelope.timestamp = 0  # In the past

    assert envelope.is_expired


def test_a2a_envelope_not_expired():
    principal = AgentPrincipal("Alice", "dev")
    event = principal.create_event("ch1", EventType.MESSAGE, [TextBlock(content="test")])
    card = create_agent_card(principal)

    envelope = wrap_event_as_envelope(event, card)
    assert not envelope.is_expired
