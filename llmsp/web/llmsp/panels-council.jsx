// Council panels — live deliberation (featured) + council list

function CouncilPanel({ liveEvents, liveTopic, liveSynthesis, usingReal, onReset, onExpandSynth, onAgentClick, onPickCouncil, activeCouncilId }) {
  const { LIVE_COUNCIL, COUNCILS } = window.LLMSP_DATA;
  const active = COUNCILS.find(c => c.id === activeCouncilId) || LIVE_COUNCIL;
  const isLive = active.id === LIVE_COUNCIL.id;
  const events = isLive ? liveEvents : [];
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [events.length]);

  const shownTopic = isLive && usingReal ? liveTopic : active.topic;
  const shownChannel = isLive && usingReal ? "ad_hoc_" + Math.abs(hashStr(liveTopic||"")).toString(16).slice(0,6) : active.channel;

  return (
    <Panel
      title="Live Council · Deliberation Stream"
      subtitle={isLive && usingReal ? "LIVE · user-convened" : active.id}
      right={<>
        <PhaseBadge phase={active.phase} />
        <span className="chip ghost">ROUND {active.rounds || LIVE_COUNCIL.round}/{LIVE_COUNCIL.maxRounds}</span>
        {usingReal && isLive && <button onClick={onReset} style={{padding:"3px 8px"}}>← demo</button>}
      </>}
    >
      {/* Topic card */}
      <div style={{borderLeft:"2px solid var(--accent)", paddingLeft:12, marginBottom:12}}>
        <div className="lbl">channel · {shownChannel}</div>
        <div className="serif" style={{fontSize:22, lineHeight:1.25, marginTop:2, color:"var(--ink)"}}>
          {shownTopic}
        </div>
        <div style={{display:"flex", gap:14, marginTop:6, fontSize:11, color:"var(--ink-3)"}}>
          <span><span className="lbl">elapsed</span> {fmt.time(active.elapsed)}</span>
          <span><span className="lbl">events</span> {isLive && usingReal ? events.length : active.events}</span>
          <span><span className="lbl">agents</span> {(active.agents||active.participants).join(" · ")}</span>
        </div>
      </div>

      {/* Council picker tabs */}
      <div style={{display:"flex", gap:4, borderBottom:"1px solid var(--rule)", marginBottom:10, flexWrap:"wrap"}}>
        {COUNCILS.map(c => (
          <div key={c.id}
            onClick={()=>onPickCouncil(c.id)}
            style={{
              padding:"5px 9px", fontSize:11,
              cursor:"pointer",
              borderBottom: c.id===active.id ? "2px solid var(--accent)" : "2px solid transparent",
              color: c.id===active.id ? "var(--ink)" : "var(--ink-3)",
              marginBottom:-1,
            }}
          >
            {c.id===LIVE_COUNCIL.id && <span className="dot amber pulse" style={{marginRight:5}}></span>}
            {c.channel}
            <span style={{color:"var(--ink-4)", marginLeft:6, fontSize:10}}>{c.phase}</span>
          </div>
        ))}
      </div>

      {/* Event stream */}
      {isLive ? (
        <div ref={scrollRef} style={{maxHeight:340, overflowY:"auto", paddingRight:4}}>
          {events.map((e, i) => <CouncilEvent key={i} e={e} onAgentClick={onAgentClick} />)}
          <div style={{display:"flex", alignItems:"center", gap:8, padding:"6px 0", color:"var(--ink-4)", fontSize:11}}>
            <span className="dot amber pulse"></span>
            <span className="caret">awaiting next response</span>
          </div>
        </div>
      ) : (
        <div style={{padding:"20px 0", textAlign:"center", color:"var(--ink-3)", fontSize:12, borderTop:"1px dashed var(--rule)"}}>
          <div className="serif" style={{fontSize:15, color:"var(--ink-2)"}}>Completed · see synthesis below</div>
          <div style={{marginTop:4, fontSize:11, color:"var(--ink-4)"}}>full event log available via `llmsp log {active.channel}`</div>
        </div>
      )}

      {/* Synthesis preview */}
      <SynthesisBlock onExpand={onExpandSynth} overrideSynthesis={liveSynthesis} />
    </Panel>
  );
}

function hashStr(s) { let h=0; for (let i=0;i<s.length;i++) h = (h*31 + s.charCodeAt(i)) | 0; return h; }

function CouncilEvent({ e, onAgentClick }) {
  const color = e.role === "security" ? "amber" : e.role === "architecture" ? "sage" : e.role === "performance" ? "rust" : e.role==="clerk" ? "sage" : "amber";
  const isSystem = e.type === "COUNCIL_START" || e.type === "PHASE";
  if (isSystem) {
    return (
      <div className="fade-in" style={{padding:"5px 0", fontSize:11, color:"var(--ink-4)", fontStyle:"italic", borderTop:"1px dashed var(--rule)"}}>
        <span style={{color:"var(--ink-3)"}}>[{fmt.time(e.t)}]</span> — {e.text}
      </div>
    );
  }
  return (
    <div className="fade-in" style={{display:"grid", gridTemplateColumns:"40px auto 1fr auto", gap:10, padding:"8px 0", borderTop:"1px dotted var(--rule)", alignItems:"flex-start"}}>
      <div style={{fontSize:10, color:"var(--ink-4)", paddingTop:3}}>{fmt.time(e.t)}</div>
      <div style={{display:"flex", gap:8, alignItems:"center"}} onClick={()=>onAgentClick(e.who)} >
        <AgentGlyph name={e.who} color={color} size={22} />
        <span style={{fontSize:12, color:"var(--ink)", cursor:"pointer"}}>{e.who}</span>
      </div>
      <div>
        <div style={{display:"flex", alignItems:"center", gap:8, marginBottom:3, flexWrap:"wrap"}}>
          <TypePill type={e.type} />
          {e.conf != null && <span style={{fontSize:10, color:"var(--ink-4)", whiteSpace:"nowrap"}}>conf · {e.conf.toFixed(2)}</span>}
          {e.reply != null && <span style={{fontSize:10, color:"var(--ink-4)", whiteSpace:"nowrap"}}>↳ reply to #{e.reply}</span>}
        </div>
        <div style={{fontSize:12.5, color: e.type==="OBJECTION" ? "var(--accent-3)" : "var(--ink-2)", lineHeight:1.5}}>
          {e.text}
        </div>
      </div>
      <div style={{fontSize:10, color:"var(--ink-4)", textAlign:"right", paddingTop:3}}>
        sig · {(Math.random()*1e6|0).toString(16)}…
      </div>
    </div>
  );
}

function SynthesisBlock({ onExpand, overrideSynthesis }) {
  const { LIVE_COUNCIL } = window.LLMSP_DATA;
  const s = overrideSynthesis || LIVE_COUNCIL.synthesis;
  return (
    <div style={{marginTop:14, border:"1px solid var(--rule)", background:"var(--bg)", padding:"10px 12px"}}>
      <div style={{display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:6}}>
        <div className="lbl">Clerk · provisional synthesis</div>
        <button onClick={onExpand}>Expand →</button>
      </div>
      <div style={{display:"grid", gridTemplateColumns:"auto 1fr auto 1fr", gap:"4px 14px", fontSize:11, alignItems:"center"}}>
        <span className="lbl">✓ agree</span><span style={{color:"var(--ink-2)"}}>{s.agreements.length} claims</span>
        <span className="lbl">⚠ disagree</span><span style={{color:"var(--ink-2)"}}>{s.disagreements.length} open</span>
        <span className="lbl">▸ decisions</span><span style={{color:"var(--ink-2)"}}>{s.decisions.length} resolved</span>
        <span className="lbl">○ tasks</span><span style={{color:"var(--ink-2)"}}>{s.tasks.length} queued</span>
      </div>
    </div>
  );
}

Object.assign(window, { CouncilPanel });
