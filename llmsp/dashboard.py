"""Live Observability Dashboard for LLMSP.

Terminal-based real-time dashboard showing:
- Swarm status (event count, agent count, integrity)
- Active council sessions and their phases
- Recent events stream
- Security alerts
- RAG index health

Uses only stdlib — renders ANSI-colored output to the terminal.
No curses, no rich, no external dependencies.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

from llmsp.event_store import EventStore
from llmsp.models import (
    ClaimBlock,
    CodeBlock,
    ContentBlock,
    DecisionBlock,
    EventType,
    SignedEvent,
    TaskBlock,
    TextBlock,
)
from llmsp.persistent_registry import PersistentRegistry
from llmsp.rag import RAGEngine
from llmsp.security_auditor import SecurityAuditor, ThreatSeverity


# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------

class _C:
    """ANSI escape codes."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"

    @staticmethod
    def clear_screen() -> str:
        return "\033[2J\033[H"


def _colorize(text: str, color: str) -> str:
    return f"{color}{text}{_C.RESET}"


def _severity_color(severity: ThreatSeverity) -> str:
    return {
        ThreatSeverity.CRITICAL: _C.BG_RED + _C.WHITE,
        ThreatSeverity.HIGH: _C.RED,
        ThreatSeverity.MEDIUM: _C.YELLOW,
        ThreatSeverity.LOW: _C.CYAN,
        ThreatSeverity.INFO: _C.DIM,
    }.get(severity, _C.WHITE)


def _event_type_color(etype: EventType) -> str:
    return {
        EventType.MESSAGE: _C.WHITE,
        EventType.OBJECTION: _C.YELLOW,
        EventType.DECISION: _C.GREEN,
        EventType.REGISTRATION: _C.BLUE,
        EventType.COUNCIL_START: _C.CYAN,
        EventType.COUNCIL_END: _C.MAGENTA,
    }.get(etype, _C.WHITE)


def _phase_indicator(phase: str) -> str:
    indicators = {
        "idle": _colorize("IDLE", _C.DIM),
        "deliberating": _colorize("DELIBERATING", _C.YELLOW + _C.BOLD),
        "reviewing": _colorize("REVIEWING", _C.CYAN + _C.BOLD),
        "synthesizing": _colorize("SYNTHESIZING", _C.MAGENTA + _C.BOLD),
        "complete": _colorize("COMPLETE", _C.GREEN + _C.BOLD),
    }
    return indicators.get(phase, phase)


# ---------------------------------------------------------------------------
# Dashboard Snapshot
# ---------------------------------------------------------------------------


@dataclass
class DashboardSnapshot:
    """Point-in-time state of the swarm for rendering."""

    timestamp: float
    total_events: int
    total_agents: int
    integrity_ok: bool
    integrity_failures: int
    recent_events: list[SignedEvent]
    security_alerts: list[dict]
    rag_index_size: int
    channels: list[str]
    events_per_channel: dict[str, int]


class DashboardCollector:
    """Collects swarm state into renderable snapshots."""

    def __init__(
        self,
        event_store: EventStore,
        registry: PersistentRegistry,
        auditor: Optional[SecurityAuditor] = None,
        rag: Optional[RAGEngine] = None,
    ) -> None:
        self._store = event_store
        self._registry = registry
        self._auditor = auditor or SecurityAuditor(event_store, registry=registry)
        self._rag = rag or RAGEngine(event_store)

    def snapshot(self) -> DashboardSnapshot:
        """Collect current swarm state."""
        # Recent events (last 10 across all channels)
        rows = self._store._conn.execute(
            "SELECT payload_json FROM events ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()
        recent = [SignedEvent.model_validate_json(r[0]) for r in rows]
        recent.reverse()

        # Integrity
        mismatches = self._store.verify_integrity()

        # Channels
        channel_rows = self._store._conn.execute(
            "SELECT channel_id, COUNT(*) FROM events GROUP BY channel_id ORDER BY COUNT(*) DESC"
        ).fetchall()
        channels = [r[0] for r in channel_rows]
        events_per_channel = {r[0]: r[1] for r in channel_rows}

        # Security scan (incremental)
        new_alerts = self._auditor.scan_new()
        alert_dicts = [
            {
                "type": a.threat_type.value,
                "severity": a.severity.value,
                "author": a.author_id,
                "description": a.description[:80],
            }
            for a in self._auditor.alerts[-10:]  # Last 10 alerts
        ]

        return DashboardSnapshot(
            timestamp=time.time(),
            total_events=len(self._store),
            total_agents=len(self._registry),
            integrity_ok=len(mismatches) == 0,
            integrity_failures=len(mismatches),
            recent_events=recent,
            security_alerts=alert_dicts,
            rag_index_size=self._rag.index_size,
            channels=channels[:10],
            events_per_channel=events_per_channel,
        )


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class DashboardRenderer:
    """Renders a DashboardSnapshot to the terminal."""

    def __init__(self, width: int = 80) -> None:
        self._width = width

    def render(self, snap: DashboardSnapshot) -> str:
        """Render a full dashboard frame."""
        lines: list[str] = []
        w = self._width

        # Header
        lines.append(_C.clear_screen())
        lines.append(_colorize("=" * w, _C.BLUE))
        title = "LLMSP SWARM DASHBOARD"
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.timestamp))
        pad = w - len(title) - len(ts) - 4
        lines.append(
            _colorize(f"  {title}", _C.BOLD + _C.CYAN)
            + " " * max(pad, 1)
            + _colorize(ts, _C.DIM)
        )
        lines.append(_colorize("=" * w, _C.BLUE))

        # Status bar
        integrity = (
            _colorize("OK", _C.GREEN + _C.BOLD)
            if snap.integrity_ok
            else _colorize(f"FAILED ({snap.integrity_failures})", _C.RED + _C.BOLD)
        )
        lines.append(
            f"  Events: {_colorize(str(snap.total_events), _C.BOLD)}"
            f"  |  Agents: {_colorize(str(snap.total_agents), _C.BOLD)}"
            f"  |  Integrity: {integrity}"
            f"  |  RAG Index: {_colorize(str(snap.rag_index_size), _C.BOLD)}"
        )
        lines.append("")

        # Channels
        if snap.channels:
            lines.append(_colorize("  CHANNELS", _C.BOLD))
            lines.append(_colorize("  " + "-" * (w - 4), _C.DIM))
            for ch in snap.channels[:5]:
                count = snap.events_per_channel.get(ch, 0)
                bar_len = min(count, 30)
                bar = _colorize("█" * bar_len, _C.CYAN)
                lines.append(f"    {ch:<30} {bar} {count}")
            lines.append("")

        # Recent Events
        lines.append(_colorize("  RECENT EVENTS", _C.BOLD))
        lines.append(_colorize("  " + "-" * (w - 4), _C.DIM))
        if snap.recent_events:
            for event in snap.recent_events[-8:]:
                ts_short = time.strftime("%H:%M:%S", time.localtime(event.timestamp))
                etype_color = _event_type_color(event.event_type)
                etype = event.event_type.value

                text = ""
                for block in event.blocks:
                    if isinstance(block, TextBlock):
                        text = block.content[:50]
                        break
                    elif isinstance(block, ClaimBlock):
                        text = f"CLAIM: {block.claim[:40]}"
                        break
                    elif isinstance(block, DecisionBlock):
                        text = f"DECISION: {block.decision[:40]}"
                        break

                lines.append(
                    f"    {_colorize(ts_short, _C.DIM)} "
                    f"{_colorize(etype, etype_color):<24} "
                    f"{_colorize(event.author_id, _C.CYAN):<25} "
                    f"{text}"
                )
        else:
            lines.append(_colorize("    (no events)", _C.DIM))
        lines.append("")

        # Security Alerts
        lines.append(_colorize("  SECURITY ALERTS", _C.BOLD))
        lines.append(_colorize("  " + "-" * (w - 4), _C.DIM))
        if snap.security_alerts:
            for alert in snap.security_alerts[-5:]:
                sev = alert["severity"]
                sev_color = _severity_color(ThreatSeverity(sev))
                lines.append(
                    f"    {_colorize(sev.upper(), sev_color):<22} "
                    f"{alert['type']:<22} "
                    f"{alert['description']}"
                )
        else:
            lines.append(_colorize("    No threats detected", _C.GREEN))
        lines.append("")

        # Footer
        lines.append(_colorize("=" * w, _C.BLUE))
        lines.append(
            _colorize("  Press Ctrl+C to exit  |  Refresh: 2s", _C.DIM)
        )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dashboard runner
# ---------------------------------------------------------------------------


def run_dashboard(
    db_dir: str = "~/.llmsp",
    refresh_interval: float = 2.0,
) -> None:
    """Run the live terminal dashboard."""
    from pathlib import Path

    db_path = Path(db_dir).expanduser()
    if not db_path.exists():
        print(f"Error: LLMSP database not found at {db_path}")
        print("Run 'llmsp init' first.")
        sys.exit(1)

    store = EventStore(db_path / "events.db")
    registry = PersistentRegistry(db_path / "principals.db")
    collector = DashboardCollector(store, registry)
    renderer = DashboardRenderer(width=min(os.get_terminal_size().columns, 100))

    print("Starting LLMSP Dashboard...")
    try:
        while True:
            snap = collector.snapshot()
            frame = renderer.render(snap)
            sys.stdout.write(frame)
            sys.stdout.flush()
            time.sleep(refresh_interval)
    except KeyboardInterrupt:
        print("\n\nDashboard stopped.")
    finally:
        store.close()
        registry.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLMSP Live Dashboard")
    parser.add_argument("--db-dir", default="~/.llmsp")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    run_dashboard(args.db_dir, args.interval)
