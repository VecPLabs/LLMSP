// Live data — hooks that pull real state from /api/* and /ws/events
// Panels that receive these props should prefer live data, falling back
// to fixtures from window.LLMSP_DATA when the backend is empty or offline.

function useLiveStats(pollMs = 5000) {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch("/api/stats", { cache: "no-store" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const j = await r.json();
        if (!cancelled) { setStats(j); setError(null); }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    };
    poll();
    const id = setInterval(poll, pollMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollMs]);
  return { stats, error };
}

function useLiveAgents(pollMs = 15000) {
  const [agents, setAgents] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch("/api/agents", { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setAgents(j.agents || []);
      } catch (e) {}
    };
    poll();
    const id = setInterval(poll, pollMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollMs]);
  return agents;
}

// Live ledger stream via WebSocket /ws/events.
// Returns { events, connected }. Events are the most-recent first, capped.
function useLedgerStream(maxBuffer = 200) {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    let ws;
    let closed = false;
    let retryMs = 1000;
    const connect = () => {
      if (closed) return;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      try {
        ws = new WebSocket(`${proto}://${location.host}/ws/events`);
      } catch (e) {
        setConnected(false);
        setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 15000);
        return;
      }
      ws.onopen = () => { setConnected(true); retryMs = 1000; };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, 15000);
      };
      ws.onerror = () => { /* handled by onclose */ };
      ws.onmessage = (msg) => {
        try {
          const ev = JSON.parse(msg.data);
          if (ev.type !== "event") return;
          const row = normalizeEvent(ev);
          setEvents(prev => [row, ...prev].slice(0, maxBuffer));
        } catch (e) {}
      };
    };
    connect();
    return () => { closed = true; if (ws) ws.close(); };
  }, [maxBuffer]);
  return { events, connected };
}

// Convert a raw /ws/events payload into the row shape the LedgerPanel renders.
function normalizeEvent(ev) {
  const d = new Date((ev.timestamp || Date.now()/1000) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  const ts = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3,"0")}`;
  // author_id is "pr_<name>_<role>" — extract a display name.
  const who = (ev.author_id || "").replace(/^pr_/, "").split("_")[0] || "?";
  const first = Array.isArray(ev.blocks) && ev.blocks[0] ? ev.blocks[0] : {};
  const txt = first.content || first.claim || first.decision || first.task || "";
  return {
    ts,
    ch: ev.channel_id || "",
    who: who.charAt(0).toUpperCase() + who.slice(1),
    type: (ev.event_type || "MESSAGE").toUpperCase(),
    txt: String(txt).slice(0, 160),
    _id: ev.event_id,
  };
}

// Summary of whether the backend has any real state yet — drives onboarding.
function useOnboardingState(stats, settings) {
  const empty = !!stats && stats.total_events === 0 && stats.total_agents <= 1;
  const hasKeys = ["anthropic_key","google_key","xai_key"].some(k => settings?.[k]);
  return { empty, hasKeys, firstRun: empty };
}

// Generic JSON polling helper used by the panel-specific hooks below.
function usePolledJson(url, pollMs) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const r = await fetch(url, { cache: "no-store" });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setData(j);
      } catch (e) {}
    };
    poll();
    const id = setInterval(poll, pollMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [url, pollMs]);
  return data;
}

function useLiveFinops(pollMs = 15000)   { return usePolledJson("/api/finops",    pollMs); }
function useLiveRag(pollMs = 30000)      { return usePolledJson("/api/rag/stats", pollMs); }
function useLiveCouncils(pollMs = 8000)  { return usePolledJson("/api/councils",  pollMs); }

// /api/audit is a POST; we wrap it in a custom hook that triggers a scan
// on mount and on a slow interval. Returns the alert list or null.
function useLiveThreats(pollMs = 60000) {
  const [alerts, setAlerts] = useState(null);
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const r = await fetch("/api/audit", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setAlerts(j.alerts || []);
      } catch (e) {}
    };
    run();
    const id = setInterval(run, pollMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollMs]);
  return alerts;
}

Object.assign(window, {
  useLiveStats, useLiveAgents, useLedgerStream, useOnboardingState, normalizeEvent,
  useLiveFinops, useLiveRag, useLiveCouncils, useLiveThreats,
});
