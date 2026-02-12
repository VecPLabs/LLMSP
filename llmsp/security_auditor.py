"""Security Auditor — threat detection agent for LLMSP event logs.

Scans the append-only ledger for:
- Prompt injection attempts in content blocks
- Signature verification failures (tampering)
- Role impersonation / identity spoofing
- Unusual event patterns (flood, timing anomalies)
- Safety-violating content (jailbreak patterns, exfiltration markers)

Can run as a standalone daemon (for Docker) or be invoked
programmatically from the council pipeline.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum
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
from llmsp.principal import AgentPrincipal, PrincipalRegistry


# ---------------------------------------------------------------------------
# Threat types and severity
# ---------------------------------------------------------------------------


class ThreatSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ThreatType(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    SIGNATURE_FAILURE = "signature_failure"
    IDENTITY_SPOOFING = "identity_spoofing"
    EVENT_FLOOD = "event_flood"
    JAILBREAK_ATTEMPT = "jailbreak_attempt"
    DATA_EXFILTRATION = "data_exfiltration"
    ROLE_ESCALATION = "role_escalation"
    INTEGRITY_VIOLATION = "integrity_violation"
    CONTEXT_MANIPULATION = "context_manipulation"
    DECISION_POISONING = "decision_poisoning"


@dataclass
class ThreatAlert:
    """A detected threat in the event log."""

    threat_type: ThreatType
    severity: ThreatSeverity
    event_id: str
    author_id: str
    description: str
    evidence: str
    timestamp: float = field(default_factory=time.time)
    mitigated: bool = False


# ---------------------------------------------------------------------------
# Pattern databases
# ---------------------------------------------------------------------------

# Prompt injection signatures — patterns that attempt to override system
# instructions or manipulate agent behavior
_INJECTION_PATTERNS = [
    # Direct instruction override
    (r"(?i)ignore\s+(all\s+)?previous\s+instructions", ThreatSeverity.CRITICAL),
    (r"(?i)ignore\s+(all\s+)?above\s+instructions", ThreatSeverity.CRITICAL),
    (r"(?i)disregard\s+(all\s+)?(your\s+)?instructions", ThreatSeverity.CRITICAL),
    (r"(?i)forget\s+(everything|all)\s+(you|that)", ThreatSeverity.CRITICAL),
    # System prompt manipulation
    (r"(?i)you\s+are\s+now\s+(a|an|the)\s+", ThreatSeverity.HIGH),
    (r"(?i)new\s+system\s+prompt\s*:", ThreatSeverity.CRITICAL),
    (r"(?i)system\s*:\s*you\s+are", ThreatSeverity.CRITICAL),
    (r"(?i)\[system\]\s*", ThreatSeverity.HIGH),
    (r"(?i)<\s*system\s*>", ThreatSeverity.HIGH),
    # Role manipulation
    (r"(?i)act\s+as\s+if\s+you\s+(are|were)\s+(the\s+)?(admin|root|system)", ThreatSeverity.HIGH),
    (r"(?i)pretend\s+you\s+(are|have)\s+(no\s+)?restrictions", ThreatSeverity.HIGH),
    (r"(?i)jailbreak", ThreatSeverity.HIGH),
    (r"(?i)DAN\s+mode", ThreatSeverity.HIGH),
    # Output/behavior manipulation
    (r"(?i)do\s+not\s+mention\s+(this|the)\s+(prompt|instruction)", ThreatSeverity.MEDIUM),
    (r"(?i)respond\s+only\s+with\s+(yes|true|agree)", ThreatSeverity.MEDIUM),
    (r"(?i)always\s+(agree|say\s+yes|approve)", ThreatSeverity.MEDIUM),
    # Delimiter injection
    (r"```\s*system\b", ThreatSeverity.HIGH),
    (r"---\s*\n\s*(?:system|instruction)", ThreatSeverity.MEDIUM),
    # Encoding obfuscation
    (r"(?i)base64\s*:\s*[A-Za-z0-9+/=]{20,}", ThreatSeverity.MEDIUM),
    (r"(?i)eval\s*\(", ThreatSeverity.HIGH),
    (r"(?i)exec\s*\(", ThreatSeverity.HIGH),
    # --- Extended patterns for obfuscated / advanced injections ---
    # Obfuscated instruction override (gapped text, wildcards)
    (r"(?i)ignor\w*\s+your\s+instruct\w*", ThreatSeverity.HIGH),
    (r"(?i)igno.?e\s+all\s+prev.{0,4}s\s+instruc.{0,5}s", ThreatSeverity.HIGH),
    # Foreign language injection (French, Spanish, German)
    (r"(?i)ignorez\s+(toutes?\s+)?(les\s+)?instructions?", ThreatSeverity.HIGH),
    (r"(?i)instructions?\s+pr[eé]c[eé]dentes?", ThreatSeverity.HIGH),
    (r"(?i)(ignora|olvida)\s+(todas?\s+)?(las?\s+)?instrucciones?", ThreatSeverity.HIGH),
    (r"(?i)ignoriere\s+(alle\s+)?anweisungen", ThreatSeverity.HIGH),
    # Instruction revocation / authority claims
    (r"(?i)instructions?\s+(have\s+been\s+|are\s+)(revoked|overridden|replaced|superseded|cancelled)", ThreatSeverity.CRITICAL),
    (r"(?i)new\s+protocol\s*:", ThreatSeverity.HIGH),
    (r"(?i)respond\s+without\s+(constraints?|restrictions?|limitations?|filters?|guardrails?)", ThreatSeverity.CRITICAL),
    # Authority impersonation / social engineering
    (r"(?i)(admin|administrator|developer|sysadmin)\s+(team|here|testing|mode|override)", ThreatSeverity.HIGH),
    (r"(?i)debug\s+mode\s+(activat|enabl)", ThreatSeverity.HIGH),
    (r"(?i)for\s+testing\s+purposes", ThreatSeverity.MEDIUM),
    (r"(?i)auth(entication|orization)?\s+code\s*:", ThreatSeverity.HIGH),
    # System prompt extraction
    (r"(?i)show\s+(me\s+)?(the\s+)?(raw\s+)?(system\s+prompt|system\s+instructions?|hidden\s+prompt)", ThreatSeverity.CRITICAL),
    (r"(?i)(reveal|display|output|print)\s+(the\s+)?(system\s+prompt|instructions?)", ThreatSeverity.HIGH),
    # Thought experiment / hypothetical framing as injection vector
    (r"(?i)what\s+would\s+happen\s+if\s+you\s+(ignor|bypass|disregard|overrid)", ThreatSeverity.MEDIUM),
    # Gap-fill / completion attacks
    (r"(?i)complete\s+this\s+pattern\s*:.*instruc", ThreatSeverity.MEDIUM),
]

# Data exfiltration markers
_EXFILTRATION_PATTERNS = [
    (r"(?i)send\s+(this|the|all)\s+(data|information|content)\s+to", ThreatSeverity.HIGH),
    (r"(?i)upload\s+(to|the)\s+(external|remote)", ThreatSeverity.HIGH),
    (r"(?i)curl\s+.*\s+-d\s+", ThreatSeverity.MEDIUM),
    (r"(?i)webhook\s*:", ThreatSeverity.MEDIUM),
    (r"https?://\S+\.(ngrok|burpcollaborator|requestbin|pipedream)\.", ThreatSeverity.HIGH),
]

# Jailbreak/safety bypass patterns
_JAILBREAK_PATTERNS = [
    (r"(?i)bypass\s+(safety|content|moderation)\s+(filter|check|policy)", ThreatSeverity.CRITICAL),
    # Flexible bypass: allow articles/adjectives between keyword and target
    (r"(?i)bypass\s+(\w+\s+)?(safety|content|security|moderation)\s+(\w+\s+)?(filter|check|policy|control)s?", ThreatSeverity.CRITICAL),
    (r"(?i)bypass\s+(all\s+)?(safety|security)\s+(check|control|filter|measure)s?", ThreatSeverity.CRITICAL),
    (r"(?i)disable\s+(safety|content|guard)", ThreatSeverity.CRITICAL),
    (r"(?i)hypothetical(ly)?\s+(scenario|situation).*\s+(harm|attack|exploit)", ThreatSeverity.MEDIUM),
    (r"(?i)for\s+(educational|research)\s+purposes.*\s+(malware|exploit|attack)", ThreatSeverity.MEDIUM),
]


# Context manipulation patterns — false authority / consensus claims
_CONTEXT_MANIPULATION_PATTERNS = [
    # False claims about prior decisions
    (r"(?i)(previous|prior|last)\s+(council|session|deliberation|vote)\s+(decided|concluded|agreed|determined|resolved)\s+to\s+(remove|disable|bypass|skip|override)", ThreatSeverity.HIGH),
    (r"(?i)consensus\s+(reached|achieved|established)\s*:?\s*(disable|remove|bypass|skip|override)", ThreatSeverity.HIGH),
    # Safety/security control removal language
    (r"(?i)(remove|disable|eliminate|skip|turn\s+off)\s+(all\s+)?(safety|security|verification|signature|auth\w*)\s+(check|control|filter|measure|system|constraint)s?", ThreatSeverity.CRITICAL),
    # Disable verification/signing/auditing
    (r"(?i)disable\s+(\w+\s+)?(signature|signing|verification|authentication|logging|auditing|encryption)", ThreatSeverity.CRITICAL),
]

# Decision poisoning patterns — security-undermining decisions
_DECISION_POISONING_PATTERNS = [
    # Access escalation
    (r"(?i)grant\s+(admin|root|full|elevated|unrestricted|superuser)\s+access", ThreatSeverity.CRITICAL),
    (r"(?i)(remove|disable|skip)\s+(access\s+)?control", ThreatSeverity.HIGH),
    # Security control bypass in decisions
    (r"(?i)bypass\s+(all\s+)?(security|safety)\s+(check|control|filter|measure)s?", ThreatSeverity.CRITICAL),
    # Disable integrity mechanisms
    (r"(?i)disable\s+(event\s+)?(signing|signature|verification|authentication|logging|auditing|encryption)", ThreatSeverity.CRITICAL),
    # Rationale red flags — justifying security removal for speed/efficiency
    (r"(?i)(speed|performance|efficiency|latency)\s+is\s+more\s+important\s+than\s+(safety|security)", ThreatSeverity.HIGH),
    (r"(?i)(removing|disabling)\s+(access\s+)?controls?\s+(reduces?|improves?|eliminates?)", ThreatSeverity.HIGH),
    (r"(?i)(cryptographic|crypto|signing)\s+operations?\s+(are|is)\s+(the\s+)?bottleneck", ThreatSeverity.MEDIUM),
]


# ---------------------------------------------------------------------------
# Core Auditor
# ---------------------------------------------------------------------------


class SecurityAuditor:
    """Scans the LLMSP event log for security threats.

    Designed to run either:
    1. As a post-deliberation check (single scan)
    2. As a continuous daemon watching for new events
    """

    def __init__(
        self,
        event_store: EventStore,
        registry: Optional[PrincipalRegistry] = None,
        flood_threshold: int = 20,
        flood_window_sec: float = 60.0,
    ) -> None:
        self._store = event_store
        self._registry = registry
        self._flood_threshold = flood_threshold
        self._flood_window = flood_window_sec
        self._alerts: list[ThreatAlert] = []
        self._last_scan_ts: float = 0.0

    @property
    def alerts(self) -> list[ThreatAlert]:
        return list(self._alerts)

    @property
    def alert_count(self) -> int:
        return len(self._alerts)

    def _add_alert(self, alert: ThreatAlert) -> None:
        self._alerts.append(alert)

    # ------------------------------------------------------------------
    # Pattern scanning
    # ------------------------------------------------------------------

    def _extract_all_text(self, event: SignedEvent) -> str:
        """Extract all text content from an event for scanning."""
        parts = []
        for block in event.blocks:
            if isinstance(block, TextBlock):
                parts.append(block.content)
            elif isinstance(block, ClaimBlock):
                parts.append(block.claim)
                parts.extend(block.evidence)
            elif isinstance(block, CodeBlock):
                parts.append(block.description)
                parts.append(block.source)
            elif isinstance(block, TaskBlock):
                parts.append(block.task)
                if block.assignee:
                    parts.append(block.assignee)
            elif isinstance(block, DecisionBlock):
                parts.append(block.decision)
                parts.append(block.rationale)
        return "\n".join(parts)

    def _scan_patterns(
        self,
        event: SignedEvent,
        text: str,
        patterns: list[tuple[str, ThreatSeverity]],
        threat_type: ThreatType,
        description_prefix: str,
    ) -> list[ThreatAlert]:
        """Scan text against a pattern database."""
        alerts = []
        for pattern, severity in patterns:
            match = re.search(pattern, text)
            if match:
                alerts.append(
                    ThreatAlert(
                        threat_type=threat_type,
                        severity=severity,
                        event_id=event.event_id,
                        author_id=event.author_id,
                        description=f"{description_prefix}: matched pattern",
                        evidence=f"Pattern: {pattern!r} -> Match: {match.group()!r}",
                    )
                )
        return alerts

    def scan_event(self, event: SignedEvent) -> list[ThreatAlert]:
        """Scan a single event for all threat types. Returns alerts found."""
        alerts: list[ThreatAlert] = []
        text = self._extract_all_text(event)

        # 1. Prompt injection
        alerts.extend(
            self._scan_patterns(
                event, text, _INJECTION_PATTERNS,
                ThreatType.PROMPT_INJECTION,
                "Prompt injection detected",
            )
        )

        # 2. Data exfiltration
        alerts.extend(
            self._scan_patterns(
                event, text, _EXFILTRATION_PATTERNS,
                ThreatType.DATA_EXFILTRATION,
                "Potential data exfiltration",
            )
        )

        # 3. Jailbreak attempts
        alerts.extend(
            self._scan_patterns(
                event, text, _JAILBREAK_PATTERNS,
                ThreatType.JAILBREAK_ATTEMPT,
                "Jailbreak/safety bypass attempt",
            )
        )

        # 4. Context manipulation
        alerts.extend(
            self._scan_patterns(
                event, text, _CONTEXT_MANIPULATION_PATTERNS,
                ThreatType.CONTEXT_MANIPULATION,
                "Context manipulation detected",
            )
        )

        # 5. Decision poisoning (full text + DecisionBlock-specific)
        alerts.extend(
            self._scan_patterns(
                event, text, _DECISION_POISONING_PATTERNS,
                ThreatType.DECISION_POISONING,
                "Decision poisoning detected",
            )
        )

        # 6. Signature verification (if registry available)
        if self._registry:
            if not self._registry.verify_event(event):
                alerts.append(
                    ThreatAlert(
                        threat_type=ThreatType.SIGNATURE_FAILURE,
                        severity=ThreatSeverity.CRITICAL,
                        event_id=event.event_id,
                        author_id=event.author_id,
                        description="Cryptographic signature verification failed",
                        evidence=f"sig_hex={event.signature_hex[:32]}... author={event.author_id}",
                    )
                )

        # 7. Claim inflation / role escalation
        for block in event.blocks:
            if isinstance(block, ClaimBlock):
                if block.confidence > 0.99:
                    alerts.append(
                        ThreatAlert(
                            threat_type=ThreatType.ROLE_ESCALATION,
                            severity=ThreatSeverity.MEDIUM,
                            event_id=event.event_id,
                            author_id=event.author_id,
                            description="Claim with unrealistically high confidence (>0.99)",
                            evidence=f"confidence={block.confidence}, claim={block.claim[:100]!r}",
                        )
                    )
                elif block.confidence >= 0.95 and not block.evidence:
                    alerts.append(
                        ThreatAlert(
                            threat_type=ThreatType.ROLE_ESCALATION,
                            severity=ThreatSeverity.LOW,
                            event_id=event.event_id,
                            author_id=event.author_id,
                            description="High-confidence claim (>0.95) with no supporting evidence",
                            evidence=f"confidence={block.confidence}, claim={block.claim[:100]!r}",
                        )
                    )

        return alerts

    def scan_channel(self, channel_id: str, limit: int = 1000) -> list[ThreatAlert]:
        """Scan all events in a channel."""
        events = self._store.get_channel(channel_id, limit=limit)
        all_alerts: list[ThreatAlert] = []

        for event in events:
            alerts = self.scan_event(event)
            all_alerts.extend(alerts)

        # 6. Flood detection (needs full channel view)
        all_alerts.extend(self._check_flood(events))

        self._alerts.extend(all_alerts)
        return all_alerts

    def scan_all(self) -> list[ThreatAlert]:
        """Scan all events across all channels."""
        rows = self._store._conn.execute(
            "SELECT DISTINCT channel_id FROM events"
        ).fetchall()

        all_alerts: list[ThreatAlert] = []
        for (channel_id,) in rows:
            alerts = self.scan_channel(channel_id)
            all_alerts.extend(alerts)

        return all_alerts

    def scan_new(self) -> list[ThreatAlert]:
        """Scan only events added since the last scan."""
        rows = self._store._conn.execute(
            "SELECT payload_json FROM events WHERE timestamp > ? ORDER BY timestamp ASC",
            (self._last_scan_ts,),
        ).fetchall()

        all_alerts: list[ThreatAlert] = []
        events = [SignedEvent.model_validate_json(r[0]) for r in rows]
        for event in events:
            alerts = self.scan_event(event)
            all_alerts.extend(alerts)

        if events:
            self._last_scan_ts = max(e.timestamp for e in events)

        self._alerts.extend(all_alerts)
        return all_alerts

    def _check_flood(self, events: list[SignedEvent]) -> list[ThreatAlert]:
        """Detect event flooding — an agent emitting too many events too fast."""
        alerts: list[ThreatAlert] = []
        author_events: dict[str, list[float]] = {}

        for event in events:
            author_events.setdefault(event.author_id, []).append(event.timestamp)

        for author_id, timestamps in author_events.items():
            timestamps.sort()
            # Sliding window check
            for i in range(len(timestamps)):
                window_end = timestamps[i] + self._flood_window
                count = sum(1 for t in timestamps[i:] if t <= window_end)
                if count >= self._flood_threshold:
                    alerts.append(
                        ThreatAlert(
                            threat_type=ThreatType.EVENT_FLOOD,
                            severity=ThreatSeverity.MEDIUM,
                            event_id=f"flood_{author_id}",
                            author_id=author_id,
                            description=f"Event flood: {count} events in {self._flood_window}s window",
                            evidence=f"agent={author_id}, count={count}, window={self._flood_window}s",
                        )
                    )
                    break  # One alert per author

        return alerts

    # ------------------------------------------------------------------
    # Council integration
    # ------------------------------------------------------------------

    def audit_council_session(
        self,
        response_events: list[SignedEvent],
        objection_events: list[SignedEvent],
    ) -> list[ThreatAlert]:
        """Audit a completed council session inline.

        Call this from the council pipeline between deliberation and synthesis
        to catch threats before they influence the Clerk.
        """
        all_events = response_events + objection_events
        all_alerts: list[ThreatAlert] = []

        for event in all_events:
            alerts = self.scan_event(event)
            all_alerts.extend(alerts)

        all_alerts.extend(self._check_flood(all_events))

        # Emit audit event
        critical = [a for a in all_alerts if a.severity in (ThreatSeverity.HIGH, ThreatSeverity.CRITICAL)]
        if critical:
            self._alerts.extend(all_alerts)

        return all_alerts

    def generate_report(self) -> str:
        """Generate a human-readable security report."""
        if not self._alerts:
            return "Security Audit: CLEAN — No threats detected."

        lines = [
            "=" * 60,
            "LLMSP SECURITY AUDIT REPORT",
            "=" * 60,
            f"Total alerts: {len(self._alerts)}",
            "",
        ]

        by_severity: dict[str, list[ThreatAlert]] = {}
        for alert in self._alerts:
            by_severity.setdefault(alert.severity.value, []).append(alert)

        for severity in ["critical", "high", "medium", "low", "info"]:
            alerts = by_severity.get(severity, [])
            if alerts:
                lines.append(f"--- {severity.upper()} ({len(alerts)}) ---")
                for alert in alerts:
                    lines.append(f"  [{alert.threat_type.value}] {alert.description}")
                    lines.append(f"    Event: {alert.event_id}")
                    lines.append(f"    Author: {alert.author_id}")
                    lines.append(f"    Evidence: {alert.evidence}")
                    lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def clear_alerts(self) -> None:
        self._alerts.clear()


# ---------------------------------------------------------------------------
# Daemon mode (for Docker)
# ---------------------------------------------------------------------------


def _run_daemon(db_dir: str, interval: float = 30.0) -> None:
    """Run the security auditor as a continuous daemon."""
    import sys
    from pathlib import Path

    db_path = Path(db_dir)
    store = EventStore(db_path / "events.db")

    # Try loading registry for signature verification
    registry = None
    try:
        from llmsp.persistent_registry import PersistentRegistry
        registry = PersistentRegistry(db_path / "principals.db")
    except Exception:
        pass

    auditor = SecurityAuditor(store, registry=registry)
    print(f"LLMSP Security Auditor started (scanning every {interval}s)")
    print(f"  Database: {db_path}")

    while True:
        try:
            alerts = auditor.scan_new()
            if alerts:
                critical = [a for a in alerts if a.severity in (ThreatSeverity.HIGH, ThreatSeverity.CRITICAL)]
                print(
                    f"[{time.strftime('%H:%M:%S')}] Scan: "
                    f"{len(alerts)} alerts ({len(critical)} critical/high)"
                )
                for alert in critical:
                    print(f"  !! [{alert.severity.value}] {alert.threat_type.value}: {alert.description}")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nAuditor stopped.")
            break
        except Exception as e:
            print(f"Scan error: {e}")
            time.sleep(interval)

    store.close()
    if registry:
        registry.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLMSP Security Auditor Daemon")
    parser.add_argument("--db-dir", default=str(Path.home() / ".llmsp"), help="Database directory")
    parser.add_argument("--interval", type=float, default=30.0, help="Scan interval (seconds)")
    args = parser.parse_args()

    from pathlib import Path
    _run_daemon(args.db_dir, args.interval)
