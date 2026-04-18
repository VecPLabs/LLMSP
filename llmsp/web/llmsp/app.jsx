// App — top-level state, layout, tweaks, live simulation

const { useState: useS, useEffect: useE } = React;

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

  // Settings
  const [settings, setSettings] = useS(() => loadSettings());
  const [settingsOpen, setSettingsOpen] = useS(false);

  // Live council — either the canned demo, OR a real deliberation driven by the orchestrator
  const { LIVE_COUNCIL } = window.LLMSP_DATA;
  const [liveTopic, setLiveTopic] = useS(LIVE_COUNCIL.topic);
  const [liveEvents, setLiveEvents] = useS([]);
  const [liveSynthesis, setLiveSynthesis] = useS(null);
  const [delibBusy, setDelibBusy] = useS(false);
  const [delibStatus, setDelibStatus] = useS("");
  const [usingReal, setUsingReal] = useS(false);

  // Canned demo streaming (only when no real council is active)
  const [cannedShown, setCannedShown] = useS(3);
  const tick = useTick(2500);
  useE(() => {
    if (!usingReal && !delibBusy) setCannedShown(n => Math.min(LIVE_COUNCIL.events.length, n + 1));
  }, [tick]);
  const effectiveEvents = usingReal ? liveEvents : LIVE_COUNCIL.events.slice(0, cannedShown);
  const effectiveTopic  = usingReal ? liveTopic : LIVE_COUNCIL.topic;

  // Launch a real deliberation
  const launch = async (query, backends) => {
    setUsingReal(true);
    setDelibBusy(true);
    setLiveTopic(query);
    setLiveEvents([]);
    setLiveSynthesis(null);
    setDelibStatus("routing query · agents responding…");
    try {
      await runDeliberation(query, backends, (ev) => {
        setLiveEvents(prev => [...prev, ev]);
        if (ev.synthesis) setLiveSynthesis(ev.synthesis);
        setDelibStatus(`${ev.who} · ${ev.type}`);
      });
      setDelibStatus("council complete");
    } catch (e) {
      setDelibStatus("error: " + String(e).slice(0,80));
    } finally {
      setDelibBusy(false);
    }
  };

  const resetToDemo = () => { setUsingReal(false); setLiveEvents([]); setLiveSynthesis(null); setCannedShown(3); };

  const [synthOpen, setSynthOpen]       = useS(false);
  const [agentOpen, setAgentOpen]       = useS(null);
  const [activeCouncil, setActiveCouncil] = useS(LIVE_COUNCIL.id);
  const [filterCh, setFilterCh]       = useS(null);
  const [filterAgent, setFilterAgent] = useS(null);
  const [filterType, setFilterType]   = useS(null);
  const [agentFilter, setAgentFilter] = useS(null);

  useE(() => {
    const onKey = (e) => {
      if (e.key === "Escape") { setSettingsOpen(false); setSynthOpen(false); setAgentOpen(null); }
      if (e.key === "`" && (e.ctrlKey || e.metaKey)) { setTweaksOpen(o => !o); }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <>
      <HeaderBar
        theme={tweaks.theme}
        onTheme={()=>set("theme", tweaks.theme==="light"?"dark":"light")}
        density={tweaks.density}
        onDensity={()=>set("density", tweaks.density==="compact"?"comfortable":"compact")}
        onOpenCouncil={()=>setSettingsOpen(true)}
        live={true}
      />

      <div className="grid-main">
        {tweaks.show_finops && (
          <div style={{gridColumn: tweaks.show_integrity ? "1 / span 1" : "1 / span 2"}}>
            <FinOpsPanel />
          </div>
        )}
        {tweaks.show_integrity && (
          <div style={{gridColumn: tweaks.show_finops ? "2 / span 1" : "1 / span 2"}}>
            <IntegrityPanel />
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
            <AgentsPanel onAgentClick={(n)=>setAgentOpen(n)} filter={agentFilter} onFilter={setAgentFilter} />
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

      <ConveneBar
        onOpenSettings={()=>setSettingsOpen(true)}
        settings={settings}
        onLaunch={launch}
        busy={delibBusy}
        status={delibStatus}
      />

      {tweaksOpen && <TweaksPanel tweaks={tweaks} set={set} onClose={()=>setTweaksOpen(false)} />}
    </>
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
