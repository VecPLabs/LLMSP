"""Tests for LLMSP agent principals and registry."""

from llmsp.crypto import KeyType
from llmsp.models import EventType, TextBlock, ClaimBlock
from llmsp.principal import AgentPrincipal, PrincipalRegistry


def test_principal_creation():
    p = AgentPrincipal("Alice", "developer")
    assert p.agent_id == "pr_alice_developer"
    assert p.name == "Alice"
    assert p.role == "developer"


def test_principal_sign_event():
    p = AgentPrincipal("Alice", "developer")
    event = p.create_event(
        channel_id="test",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="hello")],
    )
    assert event.signature_hex != ""
    assert event.author_id == "pr_alice_developer"


def test_principal_rsa_key():
    p = AgentPrincipal("Bob", "security", key_type=KeyType.RSA)
    event = p.create_event(
        channel_id="test",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="rsa signed")],
    )
    assert event.signature_hex != ""


def test_registry_register_and_lookup():
    registry = PrincipalRegistry()
    p = AgentPrincipal("Alice", "developer")
    record = registry.register(p)
    assert record.agent_id == "pr_alice_developer"
    assert registry.get("pr_alice_developer") is not None
    assert len(registry) == 1


def test_registry_verify_valid_event():
    registry = PrincipalRegistry()
    p = AgentPrincipal("Alice", "developer")
    registry.register(p)

    event = p.create_event(
        channel_id="test",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="verify me")],
    )
    assert registry.verify_event(event) is True


def test_registry_reject_unknown_author():
    registry = PrincipalRegistry()
    p = AgentPrincipal("Unknown", "rogue")
    # Don't register
    event = p.create_event(
        channel_id="test",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="who am I")],
    )
    assert registry.verify_event(event) is False


def test_registry_reject_tampered_event():
    registry = PrincipalRegistry()
    p = AgentPrincipal("Alice", "developer")
    registry.register(p)

    event = p.create_event(
        channel_id="test",
        event_type=EventType.MESSAGE,
        blocks=[TextBlock(content="original")],
    )
    # Tamper with the event content after signing
    tampered = event.model_copy(
        update={"blocks": [TextBlock(content="tampered")]}
    )
    assert registry.verify_event(tampered) is False


def test_registration_event():
    registry = PrincipalRegistry()
    p = AgentPrincipal("Alice", "developer")
    event = registry.create_registration_event(p)
    assert event.event_type == EventType.REGISTRATION
    assert registry.verify_event(event) is True
    assert len(registry) == 1
