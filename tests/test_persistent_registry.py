"""Tests for LLMSP persistent (SQLite-backed) principal registry."""

from llmsp.crypto import KeyType
from llmsp.models import EventType, TextBlock
from llmsp.persistent_registry import PersistentRegistry
from llmsp.principal import AgentPrincipal


def test_register_and_persist():
    """Register a principal, close, reopen, and verify it persists."""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_principals.db")

        # Register
        reg1 = PersistentRegistry(db_path)
        p = AgentPrincipal("Alice", "developer")
        reg1.register(p)
        assert len(reg1) == 1
        reg1.close()

        # Reopen and check persistence
        reg2 = PersistentRegistry(db_path)
        assert len(reg2) == 1
        record = reg2.get("pr_alice_developer")
        assert record is not None
        assert record.name == "Alice"
        assert record.role == "developer"
        reg2.close()


def test_register_multiple():
    reg = PersistentRegistry()
    p1 = AgentPrincipal("Alice", "dev")
    p2 = AgentPrincipal("Bob", "security")
    reg.register(p1)
    reg.register(p2)
    assert len(reg) == 2


def test_remove_principal():
    reg = PersistentRegistry()
    p = AgentPrincipal("Alice", "dev")
    reg.register(p)
    assert len(reg) == 1

    removed = reg.remove("pr_alice_dev")
    assert removed is True
    assert len(reg) == 0
    assert reg.get("pr_alice_dev") is None


def test_remove_nonexistent():
    reg = PersistentRegistry()
    assert reg.remove("pr_nobody_nothing") is False


def test_verify_event_after_reload():
    """Verify that signature verification works after reloading from disk."""
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_principals.db")

        # Register and create event
        reg1 = PersistentRegistry(db_path)
        p = AgentPrincipal("Alice", "developer")
        reg1.register(p)

        event = p.create_event(
            channel_id="test",
            event_type=EventType.MESSAGE,
            blocks=[TextBlock(content="verify after reload")],
        )

        # Verify in original registry
        assert reg1.verify_event(event) is True
        reg1.close()

        # Reopen and verify — public key reloaded from DB
        reg2 = PersistentRegistry(db_path)
        assert reg2.verify_event(event) is True
        reg2.close()


def test_context_manager():
    with PersistentRegistry() as reg:
        p = AgentPrincipal("Alice", "dev")
        reg.register(p)
        assert len(reg) == 1


def test_registration_event():
    reg = PersistentRegistry()
    p = AgentPrincipal("Alice", "dev")
    event = reg.create_registration_event(p)
    assert event.event_type == EventType.REGISTRATION
    assert reg.verify_event(event) is True
