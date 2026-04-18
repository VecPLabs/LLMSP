// Bottom row: agents registry, ledger stream, new council composer, agent drawer, synth modal

function AgentsPanel({ onAgentClick, filter, onFilter, liveAgents }) {
  const { AGENTS } = window.LLMSP_DATA;
  // If the backend reports real agents, merge them over fixtures (match by name)
  // so the table keeps its rich columns but reflects who's actually registered.
  const source = useMemo(() => {
    if (!liveAgents || liveAgents.length === 0) return AGENTS;
    const colors = ["amber","sage","rust"];
    return liveAgents.map((a, i) => {
      const fx = AGENTS.find(x => x.name.toLowerCase() === (a.name || "").toLowerCase());
      return fx ? { ...fx, id: a.agent_id, role: a.role }
                : { id: a.agent_id, name: a.name, role: a.role,
                    model: "—", tier: "standard",
                    events: 0, objections: 0, agreement: 1,
                    status: "active", color: colors[i % colors.length] };
    });
  }, [liveAgents]);
  const filtered = filter ? source.filter(a => a.role===filter || a.name===filter) : source;
  const liveTag = liveAgents ? <span className="chip sage">LIVE · {liveAgents.length}</span> : null;
  return (
    <Panel title="Agent Registry" right={<>{liveTag}<span className="chip ghost">{source.length} principals · ed25519</span></>}>
      <table className="tbl">
        <thead>
          <tr><th>Agent</th><th>Role</th><th>Model</th><th style={{textAlign:"right"}}>Events</th>
              <th style={{textAlign:"right"}}>Obj.</th><th style={{textAlign:"right"}}>Agree</th><th></th></tr>
        </thead>
        <tbody>
          {filtered.length === 0 && (
            <tr><td colSpan={7} style={{color:"var(--ink-4)", textAlign:"center", padding:"14px"}}>
              no agents registered · <span style={{color:"var(--ink-3)"}}>POST /api/agents or run <span className="kbd">llmsp register</span></span>
            </td></tr>
          )}
          {filtered.map(a => (
            <tr key={a.id} onClick={()=>onAgentClick(a.name)}>
              <td style={{display:"flex", alignItems:"center", gap:8}}>
                <AgentGlyph name={a.name} color={a.color} size={20} />
                <span style={{color:"var(--ink)"}}>{a.name}</span>
              </td>
              <td><span style={{color:"var(--ink-3)"}}>{a.role}</span></td>
              <td style={{fontSize:11, color:"var(--ink-3)"}}>{a.model}</td>
              <td style={{textAlign:"right"}}>{fmt.num(a.events)}</td>
              <td style={{textAlign:"right", color: a.objections > 50 ? "var(--accent-3)" : "var(--ink-3)"}}>{a.objections}</td>
              <td style={{textAlign:"right"}}>
                <span style={{color: a.agreement > 0.85 ? "var(--good)" : a.agreement < 0.70 ? "var(--accent-3)" : "var(--ink-2)"}}>
                  {(a.agreement*100).toFixed(0)}%
                </span>
              </td>
              <td style={{textAlign:"right"}}>
                <span className={"dot " + (a.status==="active"?"green pulse":"ghost")}></span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {filter && <div style={{fontSize:10, marginTop:6, color:"var(--ink-4)"}}>filtered · <a onClick={()=>onFilter(null)} style={{color:"var(--accent)", cursor:"pointer"}}>clear</a></div>}
    </Panel>
  );
}

// Ledger stream
function LedgerPanel({ filterCh, filterAgent, filterType, onSetCh, onSetAgent, onSetType, tick, liveEvents, connected }) {
  const { LEDGER_SAMPLE, AGENTS, COUNCILS } = window.LLMSP_DATA;
  const hasLive = Array.isArray(liveEvents) && liveEvents.length > 0;

  // Fixture-backed synthetic stream for the demo when no real events exist.
  const extra = useMemo(() => {
    if (hasLive) return [];
    const out = [];
    const agents = AGENTS.map(a => a.name);
    const channels = COUNCILS.map(c => c.channel);
    const types = ["MESSAGE","CLAIM","OBJECTION","MESSAGE","MESSAGE","DECISION","MESSAGE"];
    const blurbs = [
      "Verified signature on parent event.",
      "Proposing rate-bucket at 500 req/s per tenant.",
      "Objection: hash-range sharding creates hotspots.",
      "Concur with prior claim; adding evidence[].",
      "Embedding vector retrieved · 3 refs.",
      "Token budget soft-warn — routing to sonnet.",
      "Cross-channel reference to ch_auth_v2.",
    ];
    for (let i=0; i<tick && i<30; i++) {
      const d = new Date(Date.now() - i*1500);
      out.push({
        ts: `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}:${String(d.getSeconds()).padStart(2,"0")}.${String(d.getMilliseconds()).padStart(3,"0")}`,
        ch: channels[(i*3)%channels.length],
        who: agents[(i*5)%agents.length],
        type: types[i%types.length],
        txt: blurbs[i%blurbs.length],
      });
    }
    return out.reverse();
  }, [tick, hasLive]);

  const all = hasLive ? liveEvents : [...extra, ...LEDGER_SAMPLE];
  const filtered = all.filter(r =>
    (!filterCh || r.ch===filterCh) &&
    (!filterAgent || r.who===filterAgent) &&
    (!filterType || r.type===filterType)
  );

  const channels = [...new Set(all.map(r=>r.ch).filter(Boolean))];
  const agents = [...new Set(all.map(r=>r.who).filter(Boolean))];
  const types = ["MESSAGE","CLAIM","OBJECTION","DECISION","PHASE"];

  const statusChip = hasLive
    ? <span className="chip sage"><span className="dot green pulse"></span>TAILING · WS</span>
    : connected === false
      ? <span className="chip ghost"><span className="dot ghost"></span>OFFLINE · fixtures</span>
      : <span className="chip"><span className="dot green pulse"></span>TAILING</span>;

  return (
    <Panel
      title="Ledger · Signed Event Stream"
      right={<>
        {statusChip}
        <span className="chip ghost">append-only · sha-256</span>
      </>}
    >
      <div style={{display:"flex", gap:6, flexWrap:"wrap", marginBottom:8}}>
        <FilterSelect label="channel" value={filterCh}    options={channels} onChange={onSetCh} />
        <FilterSelect label="agent"   value={filterAgent} options={agents}   onChange={onSetAgent} />
        <FilterSelect label="type"    value={filterType}  options={types}    onChange={onSetType} />
        {(filterCh||filterAgent||filterType) && (
          <button onClick={()=>{onSetCh(null);onSetAgent(null);onSetType(null);}}>Clear</button>
        )}
      </div>
      <div style={{maxHeight:300, overflowY:"auto", fontFamily:"var(--mono)", fontSize:11.5}}>
        {filtered.slice(0, 40).map((r,i)=>(
          <div key={i} className={i<2 && extra.length>0 ? "fade-in" : ""}
               style={{display:"grid", gridTemplateColumns:"100px 120px 80px auto 1fr",
                       gap:10, padding:"3px 4px", borderBottom:"1px dotted var(--rule)", alignItems:"center"}}>
            <span style={{color:"var(--ink-4)"}}>{r.ts}</span>
            <span style={{color:"var(--ink-3)", cursor:"pointer"}} onClick={()=>onSetCh(r.ch)}>{r.ch}</span>
            <span style={{color:"var(--ink-2)", cursor:"pointer"}} onClick={()=>onSetAgent(r.who)}>{r.who}</span>
            <span onClick={()=>onSetType(r.type)} style={{cursor:"pointer"}}><TypePill type={r.type} /></span>
            <span style={{color:"var(--ink-2)", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap"}}>{r.txt}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function FilterSelect({ label, value, options, onChange }) {
  return (
    <div style={{display:"inline-flex", alignItems:"center", gap:4, border:"1px solid var(--rule)", background:"var(--bg)", padding:"2px 6px", fontSize:11}}>
      <span className="lbl">{label}</span>
      <select value={value || ""} onChange={e=>onChange(e.target.value || null)}
              style={{border:"none", background:"transparent", padding:"2px 0", color:"var(--ink)"}}>
        <option value="">all</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

// New council composer (inline)
function ComposerModal({ open, onClose }) {
  const [q, setQ] = useState("");
  const [backends, setBackends] = useState(["claude","gemini"]);
  const [sent, setSent] = useState(false);
  if (!open) return null;
  const toggle = (b) => setBackends(bs => bs.includes(b) ? bs.filter(x=>x!==b) : [...bs,b]);
  const submit = () => {
    if (!q.trim()) return;
    setSent(true);
    setTimeout(()=>{ setSent(false); setQ(""); onClose(); }, 1600);
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()}>
        <div className="panel-title">
          <div className="t-left"><span className="ascii-corner">┌─</span><span>CONVENE · New Council</span></div>
          <div className="t-right"><span className="kbd">esc</span></div>
        </div>
        <div style={{padding:"18px 20px"}}>
          <div className="lbl" style={{marginBottom:4}}>query</div>
          <textarea autoFocus value={q} onChange={e=>setQ(e.target.value)}
            placeholder="e.g. Should we use Ed25519 or RSA-PSS for agent signing?"
            style={{width:"100%", minHeight:84, padding:10, fontFamily:"var(--mono)", fontSize:13}} />
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:18, marginTop:14}}>
            <div>
              <div className="lbl" style={{marginBottom:6}}>backends</div>
              {["claude","gemini","grok"].map(b => (
                <label key={b} style={{display:"flex", justifyContent:"space-between", padding:"3px 0", cursor:"pointer"}}>
                  <span style={{color: backends.includes(b) ? "var(--ink)" : "var(--ink-3)"}}>
                    <span style={{color:"var(--accent)", marginRight:6}}>{backends.includes(b) ? "▣" : "□"}</span>
                    {b}
                  </span>
                  <span style={{fontSize:10, color:"var(--ink-4)"}} onClick={(e)=>{e.preventDefault(); toggle(b);}}>toggle</span>
                </label>
              ))}
            </div>
            <div>
              <div className="lbl" style={{marginBottom:6}}>configuration</div>
              <div style={{fontSize:11, color:"var(--ink-3)"}}>
                <div>max rounds · <span style={{color:"var(--ink)"}}>3</span></div>
                <div>router · <span style={{color:"var(--ink)"}}>keyword + tf-idf</span></div>
                <div>clerk · <span style={{color:"var(--ink)"}}>deterministic</span></div>
                <div>budget · <span style={{color:"var(--ink)"}}>$2.50 soft cap</span></div>
              </div>
            </div>
          </div>
          <div className="hairline" style={{margin:"18px 0"}}></div>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
            <div style={{fontSize:10, color:"var(--ink-4)"}}>
              {sent ? <span className="caret" style={{color:"var(--accent)"}}>deliberation opened · routing query</span>
                    : "est. cost $0.18 – $0.42 · est. latency 42s – 118s"}
            </div>
            <div style={{display:"flex", gap:6}}>
              <button onClick={onClose}>Cancel</button>
              <button className="primary" onClick={submit} disabled={!q.trim()}>Convene Council ↵</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// Agent drawer — click agent to view activity + behavior
function AgentDrawer({ name, onClose }) {
  if (!name) return null;
  const { AGENTS, LIVE_COUNCIL } = window.LLMSP_DATA;
  const a = AGENTS.find(x => x.name === name);
  if (!a) return null;
  const msgs = LIVE_COUNCIL.events.filter(e => e.who === name);
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{maxWidth:520}}>
        <div className="panel-title">
          <div className="t-left"><span className="ascii-corner">┌─</span><span>{a.name} · {a.role}</span></div>
          <div className="t-right"><span className="kbd">esc</span></div>
        </div>
        <div style={{padding:"18px 20px"}}>
          <div style={{display:"flex", alignItems:"center", gap:14, marginBottom:14}}>
            <AgentGlyph name={a.name} color={a.color} size={56} />
            <div>
              <div className="serif" style={{fontSize:28, lineHeight:1, color:"var(--ink)"}}>{a.name}</div>
              <div style={{fontSize:11, color:"var(--ink-3)", marginTop:4}}>{a.id} · {a.model}</div>
            </div>
          </div>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10, marginBottom:14}}>
            <Metric label="Events"      value={fmt.num(a.events)} sub="all-time" />
            <Metric label="Objections"  value={a.objections}      sub={`${(a.objections/a.events*100).toFixed(1)}%`} />
            <Metric label="Agreement"   value={(a.agreement*100).toFixed(0)+"%"} sub="inter-agent" good={a.agreement>0.8} />
          </div>
          <div className="lbl" style={{marginBottom:4}}>behavior signals</div>
          <div style={{fontSize:11.5, color:"var(--ink-2)", lineHeight:1.6}}>
            {a.agreement > 0.88 && <div>• High agreement — watch for rubber-stamping patterns.</div>}
            {a.objections/a.events > 0.07 && <div>• Elevated objection rate — critical reviewer.</div>}
            <div>• Last active · 14s ago</div>
            <div>• Key · ed25519 · rotated 34d ago</div>
          </div>
          <div className="hairline" style={{margin:"14px 0"}}></div>
          <div className="lbl" style={{marginBottom:4}}>recent messages · {LIVE_COUNCIL.channel}</div>
          {msgs.length ? msgs.map((m,i) => (
            <div key={i} style={{padding:"6px 0", borderTop:"1px dotted var(--rule)", fontSize:12}}>
              <TypePill type={m.type} /> <span style={{color:"var(--ink-2)", marginLeft:6}}>{m.text}</span>
            </div>
          )) : <div style={{fontSize:11, color:"var(--ink-4)"}}>no recent messages in active channel</div>}
        </div>
      </div>
    </div>
  );
}

// Synthesis modal
function SynthesisModal({ open, onClose, overrideSynthesis, overrideTopic }) {
  const [copied, setCopied] = useState(false);
  if (!open) return null;
  const { LIVE_COUNCIL } = window.LLMSP_DATA;
  const s = overrideSynthesis || LIVE_COUNCIL.synthesis;
  const topic = overrideTopic || LIVE_COUNCIL.topic;
  const copyMarkdown = async () => {
    const md = synthesisToMarkdown(topic, s);
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(()=>setCopied(false), 1800);
    } catch (e) {
      // Fallback: select-all textarea trick
      const ta = document.createElement("textarea");
      ta.value = md; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); setCopied(true); setTimeout(()=>setCopied(false), 1800); } catch(_) {}
      document.body.removeChild(ta);
    }
  };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{maxWidth:760}}>
        <div className="panel-title">
          <div className="t-left"><span className="ascii-corner">┌─</span><span>Clerk · Synthesis · {LIVE_COUNCIL.id}</span></div>
          <div className="t-right">
            <button onClick={copyMarkdown} style={{padding:"3px 8px"}}>
              {copied ? "✓ copied" : "⧉ copy md"}
            </button>
            <span className="chip sage">ZERO-HALLUCINATION</span>
            <span className="kbd">esc</span>
          </div>
        </div>
        <div style={{padding:"20px 22px"}}>
          <div style={{borderLeft:"2px solid var(--accent)", paddingLeft:12, marginBottom:16}}>
            <div className="lbl">topic</div>
            <div className="serif" style={{fontSize:22, color:"var(--ink)"}}>{topic}</div>
          </div>

          <Section title={`Agreements · ${s.agreements.length}`} accent="sage">
            {s.agreements.map((g,i) => (
              <div key={i} style={{padding:"5px 0", borderTop:"1px dotted var(--rule)", fontSize:12.5, color:"var(--ink-2)"}}>
                <span style={{color:"var(--accent-2)", marginRight:8}}>✓</span>{g}
              </div>
            ))}
          </Section>

          <Section title={`Disagreements · ${s.disagreements.length}`} accent="rust">
            {s.disagreements.map((d,i) => (
              <div key={i} style={{padding:"6px 0", borderTop:"1px dotted var(--rule)"}}>
                <div style={{fontSize:12, color:"var(--ink)"}}><span style={{color:"var(--accent-3)", marginRight:8}}>⚠</span>{d.topic}</div>
                {d.positions.map((p,j) => (
                  <div key={j} style={{marginLeft:18, fontSize:11.5, color:"var(--ink-3)", marginTop:3}}>
                    <span style={{color:"var(--ink-2)"}}>{p.agent}:</span> {p.view}
                  </div>
                ))}
              </div>
            ))}
          </Section>

          <Section title={`Decisions · ${s.decisions.length}`} accent="amber">
            {s.decisions.map((d,i) => (
              <div key={i} style={{padding:"6px 0", borderTop:"1px dotted var(--rule)"}}>
                <div style={{fontSize:13, color:"var(--ink)"}}><span style={{color:"var(--accent)", marginRight:8}}>▸</span>{d.decision}</div>
                <div style={{marginLeft:18, fontSize:11.5, color:"var(--ink-3)", marginTop:3}}>rationale · {d.rationale}</div>
              </div>
            ))}
          </Section>

          <Section title={`Action Items · ${s.tasks.length}`} accent="amber">
            {s.tasks.map((t,i) => (
              <div key={i} style={{padding:"5px 0", borderTop:"1px dotted var(--rule)", display:"flex", justifyContent:"space-between", fontSize:12}}>
                <span><span style={{color:"var(--accent)", marginRight:8}}>○</span>{t.task}</span>
                <span style={{color:"var(--ink-3)"}}>{t.assignee} · {t.status}</span>
              </div>
            ))}
          </Section>

          <div style={{marginTop:18, fontSize:10, color:"var(--ink-4)", borderTop:"1px dashed var(--rule)", paddingTop:8, display:"flex", justifyContent:"space-between"}}>
            <span>provenance · {LIVE_COUNCIL.events.length} source events · all signatures verified</span>
            <span>clerk · deterministic · 0 LLM calls</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children, accent }) {
  return (
    <div style={{marginBottom:14}}>
      <div className="lbl" style={{borderBottom:"1px solid var(--rule)", paddingBottom:4, marginBottom:6, color: accent==="sage"?"var(--accent-2)": accent==="rust"?"var(--accent-3)":"var(--accent)"}}>{title}</div>
      {children}
    </div>
  );
}

function synthesisToMarkdown(topic, s) {
  const lines = [];
  lines.push(`# LLMSP Council Synthesis`, "");
  lines.push(`**Topic:** ${topic}`, "");
  if (s.agreements?.length) {
    lines.push(`## Agreements (${s.agreements.length})`);
    s.agreements.forEach(g => lines.push(`- ${g}`));
    lines.push("");
  }
  if (s.disagreements?.length) {
    lines.push(`## Disagreements (${s.disagreements.length})`);
    s.disagreements.forEach(d => {
      lines.push(`- **${d.topic}**`);
      (d.positions || []).forEach(p => lines.push(`  - *${p.agent}:* ${p.view}`));
    });
    lines.push("");
  }
  if (s.decisions?.length) {
    lines.push(`## Decisions (${s.decisions.length})`);
    s.decisions.forEach(d => {
      lines.push(`- **${d.decision}**`);
      if (d.rationale) lines.push(`  - _rationale:_ ${d.rationale}`);
    });
    lines.push("");
  }
  if (s.tasks?.length) {
    lines.push(`## Action Items (${s.tasks.length})`);
    s.tasks.forEach(t => lines.push(`- [ ] ${t.task} — _${t.assignee} · ${t.status}_`));
    lines.push("");
  }
  return lines.join("\n");
}

Object.assign(window, { AgentsPanel, LedgerPanel, ComposerModal, AgentDrawer, SynthesisModal, synthesisToMarkdown });
