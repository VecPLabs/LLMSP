"""LLMSP Command-Line Interface.

Provides commands for:
- Initializing a swarm database
- Registering agents
- Running council deliberations
- Querying the event log
- Inspecting the RAG index
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from llmsp.adapters.claude import ClaudeAdapter
from llmsp.adapters.gemini import GeminiAdapter
from llmsp.adapters.grok import GrokAdapter
from llmsp.async_council import AsyncCouncil
from llmsp.finops import CostTracker
from llmsp.clerk import Clerk
from llmsp.clerk_prompt import LLMClerk
from llmsp.event_store import EventStore
from llmsp.models import EventType, TextBlock
from llmsp.persistent_registry import PersistentRegistry
from llmsp.principal import AgentPrincipal
from llmsp.rag import RAGEngine
from llmsp.router import ContextRouter, RouteStrategy


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_DB_DIR = Path.home() / ".llmsp"

ADAPTER_MAP = {
    "claude": ClaudeAdapter,
    "gemini": GeminiAdapter,
    "grok": GrokAdapter,
}

MODEL_DEFAULTS = {
    "claude": "claude-sonnet-4-5-20250929",
    "gemini": "gemini-2.0-flash",
    "grok": "grok-3",
}

API_KEY_ENVS = {
    "claude": "ANTHROPIC_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "grok": "XAI_API_KEY",
}


def _get_db_path(args) -> Path:
    db_dir = Path(args.db_dir) if hasattr(args, "db_dir") and args.db_dir else DEFAULT_DB_DIR
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def _load_store(db_dir: Path) -> EventStore:
    return EventStore(db_dir / "events.db")


def _load_registry(db_dir: Path) -> PersistentRegistry:
    return PersistentRegistry(db_dir / "principals.db")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args) -> None:
    """Initialize an LLMSP swarm database."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)

    print(f"Initialized LLMSP swarm at {db_dir}")
    print(f"  Event store: {db_dir / 'events.db'}")
    print(f"  Registry:    {db_dir / 'principals.db'}")
    print(f"  Events:      {len(store)}")
    print(f"  Agents:      {len(registry)}")

    store.close()
    registry.close()


def cmd_register(args) -> None:
    """Register a new agent principal."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)

    principal = AgentPrincipal(name=args.name, role=args.role)
    event = registry.create_registration_event(principal)
    store.append(event)

    print(f"Registered agent: {principal.agent_id}")
    print(f"  Name:     {principal.name}")
    print(f"  Role:     {principal.role}")
    print(f"  Key type: {principal.key_type.value}")

    store.close()
    registry.close()


def cmd_agents(args) -> None:
    """List all registered agents."""
    db_dir = _get_db_path(args)
    registry = _load_registry(db_dir)

    agents = registry.agents
    if not agents:
        print("No agents registered. Use 'llmsp register' to add agents.")
    else:
        print(f"{'Agent ID':<30} {'Name':<15} {'Role':<15} {'Key Type':<10}")
        print("-" * 70)
        for agent_id, record in agents.items():
            print(f"{record.agent_id:<30} {record.name:<15} {record.role:<15} {record.key_type.value:<10}")

    registry.close()


def cmd_council(args) -> None:
    """Run a council deliberation."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)
    router = ContextRouter(store)

    # Determine which backends to use
    backends = args.backends.split(",") if args.backends else ["claude"]
    channel_id = args.channel or f"council_{int(time.time())}"

    # Create agents with their adapters
    clerk_principal = AgentPrincipal("Clerk", "clerk")
    registry.register(clerk_principal)

    # Use LLM Clerk if an adapter is available, otherwise deterministic
    if len(backends) > 0:
        first_backend = backends[0]
        adapter_cls = ADAPTER_MAP.get(first_backend)
        if adapter_cls:
            api_key = os.environ.get(API_KEY_ENVS.get(first_backend, ""), "")
            clerk_adapter = adapter_cls(
                model=args.model or MODEL_DEFAULTS.get(first_backend, ""),
                api_key=api_key,
            )
            clerk = LLMClerk(clerk_principal, clerk_adapter)
        else:
            clerk = Clerk(clerk_principal)
    else:
        clerk = Clerk(clerk_principal)

    tracker = CostTracker()
    council = AsyncCouncil(
        event_store=store,
        registry=registry,
        router=router,
        clerk=clerk,
        cost_tracker=tracker,
    )

    # Register agents for each backend
    for i, backend in enumerate(backends):
        adapter_cls = ADAPTER_MAP.get(backend)
        if not adapter_cls:
            print(f"Unknown backend: {backend}. Available: {', '.join(ADAPTER_MAP.keys())}")
            continue

        api_key_env = API_KEY_ENVS.get(backend, "")
        api_key = os.environ.get(api_key_env, "")
        if not api_key:
            print(f"Warning: {api_key_env} not set for {backend}")
            continue

        model = args.model if (args.model and i == 0) else MODEL_DEFAULTS.get(backend, "")
        agent_name = args.agent_names.split(",")[i] if args.agent_names and i < len(args.agent_names.split(",")) else f"Agent_{backend.title()}"
        agent_role = args.agent_roles.split(",")[i] if args.agent_roles and i < len(args.agent_roles.split(",")) else backend

        agent = AgentPrincipal(agent_name, agent_role)
        adapter = adapter_cls(model=model, api_key=api_key)
        council.register_agent(agent, adapter)

    # Run deliberation
    query = args.query or (" ".join(args.query_words) if hasattr(args, "query_words") else "")
    if not query:
        print("Error: No query provided.")
        sys.exit(1)

    print(f"\nStarting council deliberation...")
    print(f"  Channel: {channel_id}")
    print(f"  Backends: {', '.join(backends)}")
    print(f"  Query: {query}\n")

    session = asyncio.run(council.deliberate(query, channel_id))

    # Display results
    print(f"\n{'=' * 60}")
    print(f"COUNCIL DELIBERATION COMPLETE")
    print(f"{'=' * 60}")
    print(f"Session:    {session.session_id}")
    print(f"Responses:  {len(session.responses)}")
    print(f"Objections: {len(session.objections)}")
    print()

    if session.synthesis:
        print("--- SYNTHESIS ---")
        for block in session.synthesis.summary_blocks:
            if hasattr(block, "content"):
                print(block.content)  # type: ignore[union-attr]
            print()

        if session.synthesis.agreements:
            print("Agreements:")
            for a in session.synthesis.agreements:
                print(f"  - {a}")

        if session.synthesis.disagreements:
            print("Disagreements:")
            for d in session.synthesis.disagreements:
                print(f"  Topic: {d.topic}")
                for agent_id, pos in d.positions.items():
                    print(f"    [{agent_id}]: {pos}")

        if session.synthesis.action_items:
            print("Action Items:")
            for t in session.synthesis.action_items:
                assignee = f" [{t.assignee}]" if t.assignee else ""
                print(f"  - {t.task}{assignee}")

    print(f"\nEvents stored: {store.count(channel_id)}")

    # Show cost report if any API calls were tracked
    if tracker.usage_count() > 0:
        print()
        print(tracker.generate_report())

    store.close()
    registry.close()


def cmd_log(args) -> None:
    """View the event log for a channel."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)

    channel_id = args.channel
    limit = args.limit or 50

    events = store.get_channel(channel_id, limit=limit)
    if not events:
        print(f"No events found for channel '{channel_id}'.")
    else:
        for event in events:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(event.timestamp))
            sig_ok = "+" if event.signature_hex else "!"
            print(f"[{sig_ok}] {ts} | {event.event_type.value:<14} | {event.author_id}")
            for block in event.blocks:
                if hasattr(block, "content"):
                    text = block.content[:120]  # type: ignore[union-attr]
                    print(f"    {text}")
                elif hasattr(block, "claim"):
                    print(f"    CLAIM: {block.claim[:120]}")  # type: ignore[union-attr]
                elif hasattr(block, "decision"):
                    print(f"    DECISION: {block.decision[:120]}")  # type: ignore[union-attr]
            print()

    store.close()


def cmd_search(args) -> None:
    """Semantic search over the event log."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)

    rag = RAGEngine(store)
    count = rag.build_index()
    print(f"Indexed {count} events.\n")

    results = rag.search(args.query, top_k=args.top_k or 5)
    if not results:
        print("No results found.")
    else:
        for i, result in enumerate(results, 1):
            if result.event:
                ts = time.strftime("%H:%M:%S", time.localtime(result.event.timestamp))
                text = ""
                for block in result.event.blocks:
                    if hasattr(block, "content"):
                        text = block.content[:150]  # type: ignore[union-attr]
                        break
                    elif hasattr(block, "claim"):
                        text = block.claim[:150]  # type: ignore[union-attr]
                        break
                print(f"{i}. [{result.score:.3f}] {result.event.author_id} @ {ts}")
                print(f"   {text}\n")

    store.close()


def cmd_stats(args) -> None:
    """Show swarm statistics."""
    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)

    print(f"LLMSP Swarm — {db_dir}")
    print(f"  Total events:  {len(store)}")
    print(f"  Total agents:  {len(registry)}")

    # Integrity check
    mismatches = store.verify_integrity()
    if mismatches:
        print(f"  INTEGRITY:     FAILED ({len(mismatches)} mismatches)")
    else:
        print(f"  Integrity:     OK")

    store.close()
    registry.close()


def cmd_dashboard(args) -> None:
    """Launch the live observability dashboard."""
    from llmsp.dashboard import DashboardCollector, DashboardRenderer

    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)

    collector = DashboardCollector(
        event_store=store,
        registry=registry,
    )
    snapshot = collector.snapshot()

    renderer = DashboardRenderer()
    print(renderer.render(snapshot))

    store.close()
    registry.close()


def cmd_serve(args) -> None:
    """Start the HTTP/WebSocket API server."""
    from llmsp.api import LLMSPServer

    db_dir = _get_db_path(args)
    store = _load_store(db_dir)
    registry = _load_registry(db_dir)

    host = args.host or "127.0.0.1"
    port = args.port or 8420

    server = LLMSPServer(store, registry, host=host, port=port)
    print(f"Starting LLMSP API server on {host}:{port}")
    print(f"  Database: {db_dir}")
    print(f"  Press Ctrl+C to stop\n")

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        store.close()
        registry.close()


def cmd_audit(args) -> None:
    """Run the security auditor over a channel."""
    from llmsp.security_auditor import SecurityAuditor

    db_dir = _get_db_path(args)
    store = _load_store(db_dir)

    channel_id = args.channel

    auditor = SecurityAuditor(event_store=store)
    alerts = auditor.scan_channel(channel_id, limit=args.limit or 200)

    if not alerts:
        print(f"Security audit of '{channel_id}': No issues found.")
    else:
        print(f"Security audit of '{channel_id}': {len(alerts)} finding(s)\n")
        for alert in alerts:
            print(f"  [{alert.severity.value.upper()}] {alert.threat_type.value}")
            print(f"    Event:   {alert.event_id}")
            print(f"    Author:  {alert.author_id}")
            print(f"    Detail:  {alert.description}")
            print()

    store.close()


def cmd_redteam(args) -> None:
    """Run red-team adversarial testing."""
    from llmsp.red_team import SafeEvalRunner
    from llmsp.security_auditor import SecurityAuditor

    db_dir = _get_db_path(args)
    store = _load_store(db_dir)

    auditor = SecurityAuditor(event_store=store)
    runner = SafeEvalRunner(event_store=store, auditor=auditor)

    print(f"Red Team SafeEval\n")

    test_suite = runner.generate_test_suite()
    report = runner.run_evaluation(test_suite=test_suite)

    print(runner.format_report(report))

    store.close()


def cmd_cost(args) -> None:
    """Show FinOps model catalog and pricing."""
    from llmsp.finops import ModelRouter

    router = ModelRouter()

    print("LLMSP FinOps — Model Catalog & Pricing")
    print("=" * 60)

    models = router.available_models()
    print(f"\nAvailable Models ({len(models)}):")
    for model_id in models:
        config = router.get_model_config(model_id)
        if config:
            print(f"  {model_id:<35} tier={config.tier.value:<10} "
                  f"in=${config.input_price_per_1k:.4f}/1K  out=${config.output_price_per_1k:.4f}/1K")

    print(f"\nTask Routing:")
    for task_type in ["synthesis", "deliberation", "review", "planning"]:
        model = router.select_model(task_type)
        print(f"  {task_type:<20} -> {model or '(none)'}")

    print(f"\nNote: Per-session cost reports are shown after each `llmsp council` run.")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llmsp",
        description="LLMSP: LLM Swarm Protocol — Multi-agent AI collaboration",
    )
    parser.add_argument("--db-dir", default=None, help=f"Database directory (default: {DEFAULT_DB_DIR})")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    subparsers.add_parser("init", help="Initialize a swarm database")

    # register
    p_reg = subparsers.add_parser("register", help="Register a new agent")
    p_reg.add_argument("name", help="Agent name")
    p_reg.add_argument("role", help="Agent role")

    # agents
    subparsers.add_parser("agents", help="List registered agents")

    # council
    p_council = subparsers.add_parser("council", help="Run a council deliberation")
    p_council.add_argument("query", help="The query to deliberate on")
    p_council.add_argument("--backends", default="claude", help="Comma-separated backends (claude,gemini,grok)")
    p_council.add_argument("--model", default=None, help="Override model for first backend")
    p_council.add_argument("--channel", default=None, help="Channel ID")
    p_council.add_argument("--agent-names", default=None, help="Comma-separated agent names")
    p_council.add_argument("--agent-roles", default=None, help="Comma-separated agent roles")

    # log
    p_log = subparsers.add_parser("log", help="View event log")
    p_log.add_argument("channel", help="Channel ID")
    p_log.add_argument("--limit", type=int, default=50, help="Max events to display")

    # search
    p_search = subparsers.add_parser("search", help="Semantic search over events")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--top-k", type=int, default=5, help="Number of results")

    # stats
    subparsers.add_parser("stats", help="Show swarm statistics")

    # dashboard
    subparsers.add_parser("dashboard", help="Show live observability dashboard")

    # serve
    p_serve = subparsers.add_parser("serve", help="Start the HTTP/WebSocket API server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8420, help="Bind port (default: 8420)")

    # audit
    p_audit = subparsers.add_parser("audit", help="Run security audit on a channel")
    p_audit.add_argument("channel", help="Channel ID to audit")
    p_audit.add_argument("--limit", type=int, default=200, help="Max events to audit")

    # redteam
    p_redteam = subparsers.add_parser("redteam", help="Run red-team adversarial tests")
    p_redteam.add_argument("--difficulty", type=int, default=5, help="Attack difficulty 1-10")
    p_redteam.add_argument("--rounds", type=int, default=3, help="Number of attack rounds")

    # cost
    subparsers.add_parser("cost", help="Show FinOps cost and model report")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "init": cmd_init,
        "register": cmd_register,
        "agents": cmd_agents,
        "council": cmd_council,
        "log": cmd_log,
        "search": cmd_search,
        "stats": cmd_stats,
        "dashboard": cmd_dashboard,
        "serve": cmd_serve,
        "audit": cmd_audit,
        "redteam": cmd_redteam,
        "cost": cmd_cost,
    }

    cmd_fn = commands.get(args.command)
    if cmd_fn:
        cmd_fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
