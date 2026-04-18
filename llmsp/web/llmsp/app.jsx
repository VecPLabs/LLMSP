// App — top-level state, layout, tweaks, live simulation

const { useState: useS, useEffect: useE, useRef: useR } = React;

const TWEAK_DEFAULTS = {
  "theme": "light",
  "density": "comfortable",
  "show_finops": true,
  "show_integrity": true,
  "show_rag": true,
  "show_council": true,
  "show_agents": true,
  "show_ledger": true
};

function App() {
  const [tweaks, setTweaks] = useS(() => {
    try { const raw = localStorage.getItem("llmsp_tweaks"); if (raw) return { ...TWEAK_DEFAULTS, ...JSON.parse(raw) }; } catch(e){}
    return { ...TWEAK_DEFAULTS };
  });
  useE(() => {
    document.body.setAttribute("data-theme", tweaks.theme);
    document.body.setAttribute("data-density", tweaks.density);
    localStorage.setItem("llmsp_tweaks", JSON.stringify(tweaks));
  }, [tweaks]);

  const set = (k, v) => setTweaks(t => ({ ...t, [k]: v }));

  const [tweaksOpen, setTweaksOpen] = useS(false);
  const [shortcutsOpen, setShortcutsOpen] = useS(false);
  const [welcomeDismissed, setWelcomeDismissed] = useS(() => localStorage.getItem("llmsp_welcome_dismissed") === "1");

  // Settings
  const [settings, setSettings] = useS(() => loadSettings());
  const [settingsOpen, setSettingsOpen] = useS(false);

  // Live backend data
  const { stats: liveStats, error: statsError } = useLiveStats(5000);
  const liveAgents = useLiveAgents(15000);
  const { events: wsEvents, connected: wsConnected } = useLedgerStream(200);
  const { firstRun } = useOnboardingState(liveStats, settings);
  const connection = statsError ? "offline" : (liveStats ? "connected" : "connecting");

  // Live council state
  const { LIVE_COUNCIL } = window.LLMSP_DATA;
  const [liveTopic, setLiveTopic] = useS(LIVE_COUNCIL.topic);
  const [liveEvents, setLiveEvents] = useS([]);
  const [liveSynthesis, setLiveSynthesis] = useS(null);
  const [delibBusy, setDelibBusy] = useS(false);
  const [delibStatus, setDelibStatus] = useS("");
  const [delibError, setDelibError] = useS(null);
  const [usingReal, setUsingReal] = useS(false);
  const abortRef = useR({ aborted: false });
  const queueRef = useR([]);
  const [queueLen, setQueueLen] = useS(0);

  // Canned demo streaming (only when no real council is active)
  const [cannedShown, setCannedShown] = useS(3);
  const tick = useTick(2500);
  useE(() => {
    if (!usingReal && !delibBusy) setCannedShown(n => Math.min(LIVE_COUNCIL.events.length, n + 1));
  }, [tick]);
  const effectiveEvents = usingReal ? liveEvents : LIVE_COUNCIL.events.slice(0, cannedShown);
  const effectiveTopic  = usingReal ? liveTopic : LIVE_COUNCIL.topic;

  const runOne = async (query, backends) => {
    abortRef.current = { aborted: false };
    setUsingReal(true);
    setDelibBusy(true);
    setDelibError(null);
    setLiveTopic(query);
    setLiveEvents([]);
    setLiveSynthesis(null);
    setDelibStatus("routing query · agents responding…");
    try {
      await runDeliberation(query, backends, (ev) => {
        if (abortRef.current.aborted) throw new Error("aborted by user");
        setLiveEvents(prev => [...prev, ev]);
        if (ev.synthesis) setLiveSynthesis(ev.synthesis);
        setDelibStatus(`${ev.who} · ${ev.type}`);
      }, settings);
      setDelibStatus("council complete");
    } catch (e) {
      const msg = e?.message || String(e);
      setDelibError(msg);
      setDelibStatus("error · see banner");
    } finally {
      setDelibBusy(false);
    }
  };

  // Convene entry-point: runs immediately if idle, queues otherwise.
  const launch = async (query, backends) => {
    if (delibBusy) {
      queueRef.current.push({ query, backends });
      setQueueLen(queueRef.current.length);
      return;
    }
    await runOne(query, backends);
    while (queueRef.current.length && !abortRef.current.aborted) {
      const next = queueRef.current.shift();
      setQueueLen(queueRef.current.length);
      await runOne(next.query, next.backends);
    }
  };

  const abort = () => {
    abortRef.current.aborted = true;
    queueRef.current = [];
    setQueueLen(0);
    setDelibStatus("aborting…");
  };

  const resetToDemo = () => {
    setUsingReal(false); setLiveEvents([]); setLiveSynthesis(null);
    setCannedShown(3); setDelibError(null);
  };

  const [synthOpen, setSynthOpen]       = useS(false);
  const [agentOpen, setAgentOpen]       = useS(null);
  const [activeCouncil, setActiveCouncil] = useS(LIVE_COUNCIL.id);
  const [filterCh, setFilterCh]       = useS(null);
  const [filterAgent, setFilterAgent] = useS(null);
  const [filterType, setFilterType]   = useS(null);
  const [agentFilter, setAgentFilter] = useS(null);

  useE(() => {
    const onKey = (e) => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
      if (e.key === "Escape") {
        setSettingsOpen(false); setSynthOpen(false); setAgentOpen(null);
        setShortcutsOpen(false); setTweaksOpen(false);
      }
      if (e.key === "`" && (e.ctrlKey || e.metaKey)) { setTweaksOpen(o => !o); }
      if (inField) return;
      if (e.key === "?" || (e.shiftKey && e.key === "/")) { e.preventDefault(); setShortcutsOpen(o => !o); }
      if (e.key === "/") {
        const el = document.querySelector("input[data-convene-input]");
        if (el) { e.preventDefault(); el.focus(); }
      }
      if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        const el = document.querySelector("input[data-convene-input]");
        if (el) el.focus();
      }
      if (e.key === ",") { setSettingsOpen(true); }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);

  const dismissWelcome = () => { setWelcomeDismissed(true); localStorage.setItem("llmsp_welcome_dismissed", "1"); };

  return (
    <>
      <HeaderBar
        theme={tweaks.theme}
        onTheme={()=>set("theme", tweaks.theme==="light"?"dark":"light")}
        density={tweaks.density}
        onDensity={()=>set("density", tweaks.density==="compact"?"comfortable":"compact")}
        onOpenCouncil={()=>setSettingsOpen(true)}
        onShowShortcuts={()=>setShortcutsOpen(true)}
        live={true}
        connection={connection}
        stats={liveStats}
      />

      {firstRun && !welcomeDismissed && (
        <WelcomeBanner onDismiss={dismissWelcome}
                       onSettings={()=>setSettingsOpen(true)}
                       onShortcuts={()=>setShortcutsOpen(true)} />
      )}

      {delibError && (
        <ErrorBanner message={delibError} onClose={()=>setDelibError(null)} onSettings={()=>setSettingsOpen(true)} />
      )}

      <div className="grid-main">
        {tweaks.show_finops && (
          <div style={{gridColumn: tweaks.show_integrity ? "1 / span 1" : "1 / span 2"}}>
            <FinOpsPanel />
          </div>
        )}
        {tweaks.show_integrity && (
          <div style={{gridColumn: tweaks.show_finops ? "2 / span 1" : "1 / span 2"}}>
            <IntegrityPanel stats={liveStats} />
          </div>
        )}

        {tweaks.show_council && (
          <div className="col-wide">
            <CouncilPanel
              liveEvents={effectiveEvents}
              liveTopic={effectiveTopic}
              liveSynthesis={liveSynthesis}
              usingReal={usingReal}
              onReset={resetToDemo}
              onExpandSynth={()=>setSynthOpen(true)}
              onAgentClick={(n)=>setAgentOpen(n)}
              onPickCouncil={setActiveCouncil}
              activeCouncilId={activeCouncil}
            />
          </div>
        )}

        {tweaks.show_agents && (
          <div style={{gridColumn: tweaks.show_rag ? "1 / span 1" : "1 / span 2"}}>
            <AgentsPanel onAgentClick={(n)=>setAgentOpen(n)} filter={agentFilter} onFilter={setAgentFilter} liveAgents={liveAgents} />
          </div>
        )}
        {tweaks.show_rag && (
          <div style={{gridColumn: tweaks.show_agents ? "2 / span 1" : "1 / span 2"}}>
            <RAGPanel />
          </div>
        )}

        {tweaks.show_ledger && (
          <div className="col-wide">
            <LedgerPanel
              filterCh={filterCh}       onSetCh={setFilterCh}
              filterAgent={filterAgent} onSetAgent={setFilterAgent}
              filterType={filterType}   onSetType={setFilterType}
              tick={tick}
              liveEvents={wsEvents}
              connected={wsConnected}
            />
          </div>
        )}
      </div>

      <div style={{marginTop:16, marginBottom:48, fontSize:10, color:"var(--ink-4)", textAlign:"center", letterSpacing:".08em"}}>
        └── LLMSP v0.1.0 · EVENT-SOURCED SWARM · ZERO FRAMEWORK DEPS · MIT ──┘
      </div>

      <SynthesisModal open={synthOpen} onClose={()=>setSynthOpen(false)} overrideSynthesis={liveSynthesis} overrideTopic={usingReal ? liveTopic : null} />
      <AgentDrawer name={agentOpen} onClose={()=>setAgentOpen(null)} />
      <SettingsModal open={settingsOpen} onClose={()=>setSettingsOpen(false)} settings={settings} setSettings={setSettings} />
      <ShortcutsModal open={shortcutsOpen} onClose={()=>setShortcutsOpen(false)} />

      <ConveneBar
        onOpenSettings={()=>setSettingsOpen(true)}
        settings={settings}
        onLaunch={launch}
        onAbort={abort}
        busy={delibBusy}
        status={delibStatus}
        queueLen={queueLen}
      />

      {tweaksOpen && <TweaksPanel tweaks={tweaks} set={set} onClose={()=>setTweaksOpen(false)} />}
    </>
  );
}

// ───────────────────────────────────────────── Welcome banner (first run)
function WelcomeBanner({ onDismiss, onSettings, onShortcuts }) {
  return (
    <div style={{
      border:"1px solid var(--accent)", background:"var(--panel)",
      padding:"14px 18px", marginBottom:10, position:"relative",
      display:"grid", gridTemplateColumns:"1fr auto", gap:16, alignItems:"center",
    }}>
      <div>
        <div className="serif" style={{fontSize:20, color:"var(--ink)", lineHeight:1.2}}>
          Welcome to your swarm.
        </div>
        <div style={{fontSize:12, color:"var(--ink-3)", marginTop:6, lineHeight:1.6}}>
          Your ledger is empty. Paste a question in the <span className="kbd">Convene</span> bar
          below and hit <span className="kbd">⏎</span> — Alice, Bob, and Carol will deliberate.
          <br/>
          The dashboard panels show canned fixtures until real councils populate the ledger.
          Add provider keys in <a onClick={onSettings} style={{color:"var(--accent)", cursor:"pointer"}}>Settings</a> for
          direct Anthropic/Google/xAI calls, or use the built-in Haiku for free.
        </div>
      </div>
      <div style={{display:"flex", gap:6}}>
        <button onClick={onShortcuts}>? shortcuts</button>
        <button onClick={onSettings}>⚙ keys</button>
        <button className="primary" onClick={onDismiss}>Got it</button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Deliberation error banner
function ErrorBanner({ message, onClose, onSettings }) {
  const hintKeys = /401|403|unauthor|api[- ]?key|invalid[_ ]?key/i.test(message);
  const hintRate = /429|rate.?limit|quota/i.test(message);
  return (
    <div style={{
      border:"1px solid var(--accent-3)", background:"var(--panel)",
      padding:"10px 14px", marginBottom:10,
      display:"grid", gridTemplateColumns:"auto 1fr auto", gap:12, alignItems:"center",
    }}>
      <SevPill sev="HIGH" />
      <div style={{fontSize:12, color:"var(--ink-2)"}}>
        <span style={{color:"var(--accent-3)", fontWeight:600}}>Deliberation failed · </span>
        <span style={{fontFamily:"var(--mono)"}}>{message}</span>
        {hintKeys && <div style={{fontSize:11, color:"var(--ink-3)", marginTop:3}}>
          Looks like a key issue — check your provider key in Settings.
        </div>}
        {hintRate && <div style={{fontSize:11, color:"var(--ink-3)", marginTop:3}}>
          Provider rate-limited — wait a few seconds and try again.
        </div>}
      </div>
      <div style={{display:"flex", gap:6}}>
        {hintKeys && <button onClick={onSettings}>⚙ Fix keys</button>}
        <button onClick={onClose}>Dismiss</button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Shortcuts cheat sheet
function ShortcutsModal({ open, onClose }) {
  if (!open) return null;
  const rows = [
    ["?", "Toggle this shortcut sheet"],
    ["/", "Focus the Convene input"],
    ["⌘K / Ctrl+K", "Focus the Convene input"],
    [",", "Open Settings · API keys"],
    ["⏎", "Submit a council (inside Convene)"],
    ["Shift+⏎", "Newline in Convene"],
    ["⌘` / Ctrl+`", "Toggle Tweaks panel"],
    ["Esc", "Close any modal / drawer"],
  ];
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{maxWidth:480}}>
        <div className="panel-title">
          <div className="t-left"><span className="ascii-corner">┌─</span><span>Keyboard shortcuts</span></div>
          <div className="t-right"><span className="kbd">esc</span></div>
        </div>
        <div style={{padding:"18px 22px"}}>
          {rows.map(([k, desc]) => (
            <div key={k} style={{display:"grid", gridTemplateColumns:"130px 1fr", padding:"6px 0", borderTop:"1px dotted var(--rule)", alignItems:"center"}}>
              <div><span className="kbd">{k}</span></div>
              <div style={{fontSize:12, color:"var(--ink-2)"}}>{desc}</div>
            </div>
          ))}
          <div style={{marginTop:14, fontSize:10, color:"var(--ink-4)"}}>
            Tip: the dashboard is fully interactive while a council streams — agent clicks, filters, and panel toggles all work.
          </div>
        </div>
      </div>
    </div>
  );
}

function TweaksPanel({ tweaks, set, onClose }) {
  return (
    <div className="tweaks" style={{bottom:96}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6}}>
        <h4 style={{margin:0}}>Tweaks</h4>
        <span style={{cursor:"pointer", color:"var(--ink-3)"}} onClick={onClose}>×</span>
      </div>
      <div className="hairline" style={{margin:"4px 0 8px"}}></div>

      <div className="lbl" style={{marginBottom:4}}>appearance</div>
      <label>
        <span>theme</span>
        <select value={tweaks.theme} onChange={e=>set("theme", e.target.value)} style={{fontSize:11, padding:"2px 4px"}}>
          <option value="light">light</option>
          <option value="dark">dark</option>
        </select>
      </label>
      <label>
        <span>density</span>
        <select value={tweaks.density} onChange={e=>set("density", e.target.value)} style={{fontSize:11, padding:"2px 4px"}}>
          <option value="comfortable">comfortable</option>
          <option value="compact">compact</option>
        </select>
      </label>

      <div className="lbl" style={{marginTop:10, marginBottom:4}}>panels</div>
      {[
        ["show_finops","FinOps · cost tracker"],
        ["show_integrity","Scarred Ledger · integrity"],
        ["show_council","Live council deliberation"],
        ["show_agents","Agent registry"],
        ["show_rag","RAG retrieval health"],
        ["show_ledger","Event stream"],
      ].map(([k,lbl]) => (
        <label key={k}>
          <span style={{color: tweaks[k] ? "var(--ink)" : "var(--ink-4)"}}>{lbl}</span>
          <input type="checkbox" checked={!!tweaks[k]} onChange={e=>set(k, e.target.checked)} />
        </label>
      ))}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
