"""HTTP/WebSocket API server for LLMSP.

Exposes the full LLMSP stack over HTTP + WebSocket:

REST endpoints:
  POST   /api/council          — Start a council deliberation
  GET    /api/council/{id}     — Get session status/results
  GET    /api/events/{channel} — Query event log
  GET    /api/events/{id}      — Get single event
  POST   /api/agents           — Register an agent
  GET    /api/agents           — List registered agents
  GET    /api/search           — RAG semantic search
  GET    /api/stats            — Swarm statistics
  POST   /api/audit            — Run security audit on channel

WebSocket:
  WS     /ws/events            — Live event stream (subscribe to channels)

Built on raw asyncio + httpx for zero framework dependencies.
The server is intentionally minimal — no Flask, no FastAPI, just
the standard library's http.server with async upgrades.
"""

from __future__ import annotations

import asyncio
import json
import time
import weakref
from dataclasses import asdict, dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Optional

WEB_ROOT = Path(__file__).parent / "web"

_STATIC_MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".jsx":  "text/babel; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg":  "image/svg+xml",
    ".png":  "image/png",
    ".ico":  "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


def _resolve_static(path: str) -> Optional[Path]:
    """Map a URL path to a safe file under WEB_ROOT, or None if not served."""
    rel = path.lstrip("/") or "index.html"
    candidate = (WEB_ROOT / rel).resolve()
    try:
        candidate.relative_to(WEB_ROOT.resolve())
    except ValueError:
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    if not candidate.is_file():
        return None
    return candidate

from llmsp.clerk import Clerk, SynthesisResult
from llmsp.council import CouncilPhase, CouncilSession
from llmsp.async_council import AsyncCouncil
from llmsp.event_store import EventStore
from llmsp.models import EventType, SignedEvent, TextBlock
from llmsp.persistent_registry import PersistentRegistry
from llmsp.principal import AgentPrincipal
from llmsp.rag import RAGEngine
from llmsp.router import ContextRouter
from llmsp.security_auditor import SecurityAuditor


# ---------------------------------------------------------------------------
# WebSocket client tracking
# ---------------------------------------------------------------------------


@dataclass
class WSClient:
    """A connected WebSocket client."""
    writer: asyncio.StreamWriter
    subscribed_channels: set[str]
    client_id: str


class EventBus:
    """Pub/sub bus for live event streaming to WebSocket clients."""

    def __init__(self) -> None:
        self._clients: dict[str, WSClient] = {}
        self._global_subscribers: set[str] = set()

    def add_client(self, client: WSClient) -> None:
        self._clients[client.client_id] = client

    def remove_client(self, client_id: str) -> None:
        self._clients.pop(client_id, None)
        self._global_subscribers.discard(client_id)

    def subscribe(self, client_id: str, channel: str) -> None:
        client = self._clients.get(client_id)
        if client:
            if channel == "*":
                self._global_subscribers.add(client_id)
            else:
                client.subscribed_channels.add(channel)

    async def publish(self, event: SignedEvent) -> None:
        """Broadcast an event to all subscribed clients."""
        payload = json.dumps({
            "type": "event",
            "event_id": event.event_id,
            "channel_id": event.channel_id,
            "author_id": event.author_id,
            "event_type": event.event_type.value,
            "timestamp": event.timestamp,
            "blocks": [b.model_dump(mode="json") for b in event.blocks],
        })

        dead_clients: list[str] = []
        for client_id, client in self._clients.items():
            should_send = (
                client_id in self._global_subscribers
                or event.channel_id in client.subscribed_channels
            )
            if should_send:
                try:
                    # Simple WebSocket-style line protocol
                    client.writer.write((payload + "\n").encode())
                    await client.writer.drain()
                except Exception:
                    dead_clients.append(client_id)

        for cid in dead_clients:
            self.remove_client(cid)

    @property
    def client_count(self) -> int:
        return len(self._clients)


# ---------------------------------------------------------------------------
# API Server
# ---------------------------------------------------------------------------


class LLMSPServer:
    """Async HTTP + WebSocket server for the LLMSP swarm.

    Wraps the full stack: event store, registry, council, RAG, auditor.
    """

    def __init__(
        self,
        event_store: EventStore,
        registry: PersistentRegistry,
        host: str = "0.0.0.0",
        port: int = 8420,
    ) -> None:
        self._store = event_store
        self._registry = registry
        self._router = ContextRouter(event_store)
        self._clerk_principal = AgentPrincipal("Clerk", "clerk")
        self._registry.register(self._clerk_principal)
        self._clerk = Clerk(self._clerk_principal)
        self._council = AsyncCouncil(
            event_store=event_store,
            registry=registry,
            router=self._router,
            clerk=self._clerk,
        )
        self._rag = RAGEngine(event_store)
        self._auditor = SecurityAuditor(event_store, registry=registry)
        self._bus = EventBus()
        self._host = host
        self._port = port
        self._sessions: dict[str, CouncilSession] = {}

    # ------------------------------------------------------------------
    # Request routing
    # ------------------------------------------------------------------

    async def handle_request(self, method: str, path: str, body: dict) -> tuple[int, dict]:
        """Route an HTTP request to the appropriate handler."""
        # Strip trailing slash
        path = path.rstrip("/")

        routes: dict[tuple[str, str], Any] = {
            ("POST", "/api/council"): self._handle_council,
            ("GET", "/api/agents"): self._handle_list_agents,
            ("POST", "/api/agents"): self._handle_register_agent,
            ("GET", "/api/stats"): self._handle_stats,
            ("POST", "/api/audit"): self._handle_audit,
        }

        handler = routes.get((method, path))
        if handler:
            return await handler(body)

        # Parameterized routes
        if method == "GET" and path.startswith("/api/events/"):
            param = path[len("/api/events/"):]
            return await self._handle_events(param, body)

        if method == "GET" and path.startswith("/api/council/"):
            session_id = path[len("/api/council/"):]
            return await self._handle_get_session(session_id)

        if method == "GET" and path.startswith("/api/search"):
            return await self._handle_search(body)

        return 404, {"error": "Not found"}

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_council(self, body: dict) -> tuple[int, dict]:
        """POST /api/council — Start a council deliberation."""
        query = body.get("query")
        if not query:
            return 400, {"error": "Missing 'query' field"}

        channel_id = body.get("channel_id", f"council_{int(time.time())}")

        session = await self._council.deliberate(query, channel_id)
        self._sessions[session.session_id] = session

        # Publish all events to the bus
        for event in session.responses + session.objections:
            await self._bus.publish(event)

        return 200, self._serialize_session(session)

    async def _handle_get_session(self, session_id: str) -> tuple[int, dict]:
        """GET /api/council/{id} — Get session status."""
        session = self._sessions.get(session_id) or self._council.get_session(session_id)
        if not session:
            return 404, {"error": f"Session {session_id} not found"}
        return 200, self._serialize_session(session)

    async def _handle_events(self, param: str, body: dict) -> tuple[int, dict]:
        """GET /api/events/{channel_or_id} — Query events."""
        # Try as event_id first
        event = self._store.get(param)
        if event:
            return 200, {"event": json.loads(event.model_dump_json())}

        # Try as channel_id
        limit = int(body.get("limit", 50)) if body else 50
        events = self._store.get_channel(param, limit=limit)
        return 200, {
            "channel_id": param,
            "count": len(events),
            "events": [json.loads(e.model_dump_json()) for e in events],
        }

    async def _handle_register_agent(self, body: dict) -> tuple[int, dict]:
        """POST /api/agents — Register a new agent."""
        name = body.get("name")
        role = body.get("role")
        if not name or not role:
            return 400, {"error": "Missing 'name' or 'role'"}

        principal = AgentPrincipal(name, role)
        record = self._registry.register(principal)
        event = self._registry.create_registration_event(principal)
        self._store.append(event)

        return 201, {
            "agent_id": record.agent_id,
            "name": record.name,
            "role": record.role,
        }

    async def _handle_list_agents(self, body: dict) -> tuple[int, dict]:
        """GET /api/agents — List all registered agents."""
        agents = self._registry.agents
        return 200, {
            "count": len(agents),
            "agents": [
                {
                    "agent_id": r.agent_id,
                    "name": r.name,
                    "role": r.role,
                    "key_type": r.key_type.value,
                }
                for r in agents.values()
            ],
        }

    async def _handle_search(self, body: dict) -> tuple[int, dict]:
        """GET /api/search?q=...&top_k=5 — RAG semantic search."""
        query = body.get("q") or body.get("query", "")
        if not query:
            return 400, {"error": "Missing 'q' or 'query' parameter"}

        top_k = int(body.get("top_k", 5))
        self._rag.build_index()
        results = self._rag.search(query, top_k=top_k)

        return 200, {
            "query": query,
            "results": [
                {
                    "event_id": r.event_id,
                    "score": round(r.score, 4),
                    "event": json.loads(r.event.model_dump_json()) if r.event else None,
                }
                for r in results
            ],
        }

    async def _handle_stats(self, body: dict) -> tuple[int, dict]:
        """GET /api/stats — Swarm statistics."""
        mismatches = self._store.verify_integrity()
        return 200, {
            "total_events": len(self._store),
            "total_agents": len(self._registry),
            "integrity": "ok" if not mismatches else f"failed ({len(mismatches)} mismatches)",
            "ws_clients": self._bus.client_count,
            "active_sessions": len(self._sessions),
        }

    async def _handle_audit(self, body: dict) -> tuple[int, dict]:
        """POST /api/audit — Run security audit."""
        channel_id = body.get("channel_id")
        if channel_id:
            alerts = self._auditor.scan_channel(channel_id)
        else:
            alerts = self._auditor.scan_all()

        return 200, {
            "alert_count": len(alerts),
            "alerts": [
                {
                    "threat_type": a.threat_type.value,
                    "severity": a.severity.value,
                    "event_id": a.event_id,
                    "author_id": a.author_id,
                    "description": a.description,
                }
                for a in alerts
            ],
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def _serialize_session(self, session: CouncilSession) -> dict:
        result: dict[str, Any] = {
            "session_id": session.session_id,
            "channel_id": session.channel_id,
            "query": session.query,
            "phase": session.phase.value,
            "participants": session.participants,
            "response_count": len(session.responses),
            "objection_count": len(session.objections),
            "started_at": session.started_at,
            "completed_at": session.completed_at,
        }
        if session.synthesis:
            result["synthesis"] = {
                "agreements": session.synthesis.agreements,
                "disagreements": [
                    {"topic": d.topic, "positions": d.positions}
                    for d in session.synthesis.disagreements
                ],
                "decisions": [
                    {"decision": d.decision, "rationale": d.rationale}
                    for d in session.synthesis.decisions
                ],
                "action_items": [
                    {"task": t.task, "assignee": t.assignee, "status": t.status}
                    for t in session.synthesis.action_items
                ],
                "summary": [
                    b.content if hasattr(b, "content") else str(b)
                    for b in session.synthesis.summary_blocks
                ],
            }
        return result

    # ------------------------------------------------------------------
    # TCP server (minimal, no framework dependency)
    # ------------------------------------------------------------------

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single TCP connection (HTTP or WebSocket upgrade)."""
        try:
            raw = await asyncio.wait_for(reader.read(65536), timeout=30.0)
            if not raw:
                writer.close()
                return

            text = raw.decode("utf-8", errors="replace")
            lines = text.split("\r\n")
            request_line = lines[0] if lines else ""
            parts = request_line.split(" ")
            if len(parts) < 3:
                writer.close()
                return

            method, path, _ = parts[0], parts[1], parts[2]

            # Parse headers
            headers: dict[str, str] = {}
            body_start = text.find("\r\n\r\n")
            for line in lines[1:]:
                if ": " in line:
                    key, val = line.split(": ", 1)
                    headers[key.lower()] = val

            # WebSocket upgrade
            if headers.get("upgrade", "").lower() == "websocket":
                await self._handle_ws_upgrade(reader, writer, headers)
                return

            # Parse body
            body: dict = {}
            if body_start >= 0:
                body_text = text[body_start + 4:]
                if body_text.strip():
                    try:
                        body = json.loads(body_text)
                    except json.JSONDecodeError:
                        pass

            # Parse query params into body
            if "?" in path:
                path, qs = path.split("?", 1)
                for param in qs.split("&"):
                    if "=" in param:
                        k, v = param.split("=", 1)
                        body.setdefault(k, v)

            # Static file serving for the dashboard — everything outside /api and /ws.
            if method == "GET" and not path.startswith("/api/") and not path.startswith("/ws/"):
                if await self._serve_static(path, writer):
                    return

            status_code, response = await self.handle_request(method, path, body)
            response_body = json.dumps(response, indent=2)

            http_response = (
                f"HTTP/1.1 {status_code} {HTTPStatus(status_code).phrase}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                f"Access-Control-Allow-Origin: *\r\n"
                f"Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                f"Access-Control-Allow-Headers: Content-Type\r\n"
                f"\r\n"
                f"{response_body}"
            )
            writer.write(http_response.encode())
            await writer.drain()

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            try:
                err = json.dumps({"error": str(e)})
                writer.write(f"HTTP/1.1 500 Internal Server Error\r\nContent-Type: application/json\r\n\r\n{err}".encode())
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()

    async def _serve_static(self, path: str, writer: asyncio.StreamWriter) -> bool:
        """Serve a static file from the dashboard bundle. Returns True if handled."""
        target = _resolve_static(path)
        if target is None:
            return False
        try:
            data = target.read_bytes()
        except OSError:
            return False

        mime = _STATIC_MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        header = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {mime}\r\n"
            f"Content-Length: {len(data)}\r\n"
            f"Cache-Control: no-cache\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"\r\n"
        ).encode()
        writer.write(header + data)
        await writer.drain()
        return True

    async def _handle_ws_upgrade(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
    ) -> None:
        """Handle WebSocket upgrade and event streaming."""
        import hashlib
        import base64

        ws_key = headers.get("sec-websocket-key", "")
        magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
        accept = base64.b64encode(
            hashlib.sha1((ws_key + magic).encode()).digest()
        ).decode()

        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()

        client_id = f"ws_{int(time.time()*1000)}"
        client = WSClient(
            writer=writer,
            subscribed_channels=set(),
            client_id=client_id,
        )
        self._bus.add_client(client)
        self._bus.subscribe(client_id, "*")

        try:
            while True:
                await asyncio.sleep(30)  # Keep alive
        except Exception:
            pass
        finally:
            self._bus.remove_client(client_id)

    async def start(self) -> None:
        """Start the API server."""
        server = await asyncio.start_server(
            self._handle_connection,
            self._host,
            self._port,
        )
        print(f"LLMSP API server running on {self._host}:{self._port}")
        print(f"  Dashboard: http://{self._host}:{self._port}/")
        print(f"  REST:      http://{self._host}:{self._port}/api/")
        print(f"  WebSocket: ws://{self._host}:{self._port}/ws/events")
        async with server:
            await server.serve_forever()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_server(
    db_dir: str = "~/.llmsp",
    host: str = "0.0.0.0",
    port: int = 8420,
) -> None:
    """Start the LLMSP API server."""
    from pathlib import Path

    db_path = Path(db_dir).expanduser()
    db_path.mkdir(parents=True, exist_ok=True)

    store = EventStore(db_path / "events.db")
    registry = PersistentRegistry(db_path / "principals.db")

    server = LLMSPServer(store, registry, host=host, port=port)
    asyncio.run(server.start())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LLMSP API Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8420)
    parser.add_argument("--db-dir", default="~/.llmsp")
    args = parser.parse_args()

    run_server(args.db_dir, args.host, args.port)
