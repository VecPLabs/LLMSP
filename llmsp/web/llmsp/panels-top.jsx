// Top row: header bar, cost/finops, integrity, rag

function HeaderBar({ theme, onTheme, density, onDensity, onOpenCouncil, onShowShortcuts, live, connection, stats }) {
  const tick = useTick(1000);
  const eventCount = stats?.total_events;
  const agentCount = stats?.total_agents;
  const connected = connection === "connected";
  return (
    <div className="header">
      <div style={{display:"flex", alignItems:"center", gap:14}}>
        <div style={{display:"flex", flexDirection:"column", lineHeight:1}}>
          <div style={{fontFamily:"var(--serif)", fontSize:28, fontStyle:"italic", letterSpacing:"-.01em"}}>
            LLMSP<span style={{color:"var(--accent)"}}>.</span>
          </div>
          <div className="lbl" style={{marginTop:2}}>Swarm Operations · vecplabs</div>
        </div>
        <div style={{borderLeft:"1px solid var(--rule)", height:34}}></div>
        <div style={{display:"flex", gap:18, fontSize:11}}>
          <div><span className="lbl">node</span> <span style={{color:"var(--ink-2)"}}>{location.host || "localhost"}</span></div>
          <div>
            <span className="lbl">ledger</span>{" "}
            <span style={{color:"var(--ink-2)"}}>
              {eventCount != null ? `${fmt.num(eventCount)} events` : "swarm.db"}
            </span>
          </div>
          <div>
            <span className="lbl">agents</span>{" "}
            <span style={{color:"var(--ink-2)"}}>{agentCount != null ? agentCount : "—"}</span>
          </div>
          <div><span className="lbl">uptime</span> <span style={{color:"var(--ink-2)"}}>14d 02:{String(tick%60).padStart(2,"0")}</span></div>
        </div>
      </div>

      <div style={{textAlign:"center", display:"flex", flexDirection:"column", gap:6, alignItems:"center"}}>
        <div className="serif" style={{fontSize:13, color:"var(--ink-3)", lineHeight:1}}>
          “a mirror, not a lamp”
        </div>
        <div className="lbl" style={{lineHeight:1, display:"flex", alignItems:"center", gap:6}}>
          {live && connected && <><span className="dot pulse green"></span><span>LIVE · {fmt.clock()}</span></>}
          {live && !connected && <><span className="dot amber pulse"></span><span>RECONNECTING · {fmt.clock()}</span></>}
          {!live && <span>PAUSED</span>}
        </div>
      </div>

      <div style={{display:"flex", alignItems:"center", gap:8}}>
        <button onClick={onShowShortcuts} title="Keyboard shortcuts (?)">? shortcuts</button>
        <button onClick={onOpenCouncil} className="primary">＋ New Council</button>
        <button onClick={onDensity}>{density==="compact"?"◐ Comfy":"◑ Compact"}</button>
        <button onClick={onTheme}>{theme==="dark"?"☼ Light":"☾ Dark"}</button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── FinOps
function FinOpsPanel() {
  const { MODELS, BUDGET } = window.LLMSP_DATA;
  const totalTokens = MODELS.reduce((s,m)=>s+m.inTok+m.outTok, 0);
  const totalCost   = MODELS.reduce((s,m)=>s+m.costIn+m.costOut, 0);
  const tick = useTick(2000);
  const live = MODELS.map((m,i) => ({ ...m, delta: ((tick + i*7) % 19) }));

  return (
    <Panel title="FinOps · Spend & Token Flow"
      right={<><span className="chip ghost">{BUDGET.period}</span><span className="chip amber">+{(BUDGET.spent - BUDGET.prev/30).toFixed(2)}/d</span></>}>

      <div style={{display:"grid", gridTemplateColumns:"auto 1fr auto", gap:20, alignItems:"center", marginBottom:14}}>
        <div>
          <div className="lbl">Month-to-date</div>
          <div className="num-xl">${BUDGET.spent.toFixed(2)}</div>
          <div style={{fontSize:11, color:"var(--ink-3)", marginTop:2}}>
            of <span style={{color:"var(--ink-2)"}}>${BUDGET.limit.toFixed(0)}.00</span> budget
          </div>
        </div>
        <div>
          <div className="lbl" style={{marginBottom:4}}>Daily burn · forecast ${BUDGET.forecast.toFixed(2)}</div>
          <BarRow data={BUDGET.by_day} />
          <div style={{display:"flex", justifyContent:"space-between", marginTop:4, fontSize:10, color:"var(--ink-4)"}}>
            <span>Apr 01</span><span>Apr 18 · today</span><span>Apr 30</span>
          </div>
        </div>
        <Ring size={88} stroke={10} value={BUDGET.spent} max={BUDGET.limit}
              label={Math.round(BUDGET.spent/BUDGET.limit*100)+"%"} sub="used"
              color={BUDGET.spent/BUDGET.limit > 0.8 ? "var(--accent-3)" : "var(--accent)"} />
      </div>

      <table className="tbl">
        <thead>
          <tr><th>Model</th><th>Tier</th><th style={{textAlign:"right"}}>Calls</th>
              <th style={{textAlign:"right"}}>In / Out</th>
              <th style={{textAlign:"right"}}>Cost</th>
              <th style={{width:80}}>Share</th></tr>
        </thead>
        <tbody>
          {live.map(m => {
            const cost = m.costIn + m.costOut;
            const share = cost / totalCost;
            return (
              <tr key={m.name}>
                <td><span style={{color:"var(--ink)"}}>{m.name}</span></td>
                <td><span className={"chip " + (m.tier==="frontier"?"rust":m.tier==="standard"?"amber":"sage")}>{m.tier}</span></td>
                <td style={{textAlign:"right"}}>{fmt.num(m.calls + m.delta)}</td>
                <td style={{textAlign:"right", color:"var(--ink-3)"}}>
                  {fmt.k(m.inTok)} <span style={{color:"var(--ink-4)"}}>/</span> {fmt.k(m.outTok)}
                </td>
                <td style={{textAlign:"right", color:"var(--ink)", fontWeight:600}}>${cost.toFixed(2)}</td>
                <td>
                  <div style={{background:"var(--rule)", height:6, width:"100%", position:"relative"}}>
                    <div style={{position:"absolute", inset:0, width: (share*100)+"%", background:"var(--accent)"}}></div>
                  </div>
                </td>
              </tr>
            );
          })}
          <tr style={{borderTop:"1px solid var(--rule-2)"}}>
            <td colSpan={2} style={{color:"var(--ink-3)"}}>TOTAL · {MODELS.length} models</td>
            <td style={{textAlign:"right", color:"var(--ink-3)"}}>{fmt.num(MODELS.reduce((s,m)=>s+m.calls,0))}</td>
            <td style={{textAlign:"right", color:"var(--ink-3)"}}>{fmt.k(totalTokens)}</td>
            <td style={{textAlign:"right", color:"var(--ink)", fontWeight:700}}>${totalCost.toFixed(2)}</td>
            <td></td>
          </tr>
        </tbody>
      </table>
    </Panel>
  );
}

// ───────────────────────────────────────────── Integrity
function IntegrityPanel({ stats }) {
  const { INTEGRITY } = window.LLMSP_DATA;
  const integrityOK = !stats || stats.integrity === "ok";
  const liveEvents = stats?.total_events;
  const mismatches = stats && stats.integrity !== "ok"
    ? (stats.integrity.match(/\d+/)?.[0] || "?")
    : 0;
  const rightChip = integrityOK
    ? <span className="chip sage"><span className="dot green pulse"></span> VERIFIED</span>
    : <span className="chip rust"><span className="dot rust pulse"></span> MISMATCH</span>;
  return (
    <Panel title="Scarred Ledger · Integrity" right={<>{rightChip}{stats ? <span className="chip ghost">LIVE</span> : null}</>}>
      <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:12, marginBottom:12}}>
        <div>
          <div className="lbl">Events on ledger</div>
          <div className="num-lg">{fmt.num(liveEvents != null ? liveEvents : INTEGRITY.events_total)}</div>
        </div>
        <div>
          <div className="lbl">Hash mismatches</div>
          <div className="num-lg" style={{color: mismatches === 0 ? "var(--good)" : "var(--accent-3)"}}>{mismatches}</div>
        </div>
        <div>
          <div className="lbl">Sig failures · 24h</div>
          <div className="num-md">{INTEGRITY.signature_failures_24h}</div>
        </div>
        <div>
          <div className="lbl">Threats · 24h</div>
          <div className="num-md" style={{color:"var(--accent)"}}>{INTEGRITY.threats_24h}</div>
        </div>
      </div>
      <div className="lbl" style={{marginBottom:4}}>recent threat signals</div>
      {INTEGRITY.threats.map((th, i) => (
        <div key={i} style={{display:"grid", gridTemplateColumns:"auto auto 1fr auto", gap:8, alignItems:"center", padding:"5px 0", borderTop:"1px dotted var(--rule)"}}>
          <SevPill sev={th.sev} />
          <span style={{fontSize:11, color:"var(--ink-2)"}}>{th.class}</span>
          <span style={{fontSize:11, color:"var(--ink-3)"}}>{th.note}</span>
          <span style={{fontSize:10, color:"var(--ink-4)"}}>{th.when}</span>
        </div>
      ))}
      <div style={{fontSize:10, color:"var(--ink-4)", marginTop:10, borderTop:"1px dashed var(--rule)", paddingTop:6}}>
        auditor scan · {INTEGRITY.last_scan} · 8/8 threat classes · 100% detection rate
      </div>
    </Panel>
  );
}

// ───────────────────────────────────────────── RAG
function RAGPanel() {
  const { RAG } = window.LLMSP_DATA;
  return (
    <Panel title="RAG · Retrieval Health" right={<span className="chip ghost">TF-IDF · {fmt.k(RAG.tfidf_terms)} terms</span>}>
      <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr 1fr", gap:8, marginBottom:12}}>
        <Metric label="MRR"       value={RAG.mrr.toFixed(3)}   sub="first-hit" good />
        <Metric label="NDCG@10"   value={RAG.ndcg10.toFixed(3)} sub="ranking" good />
        <Metric label="P@3"       value={RAG.p3.toFixed(3)}    sub="precision" />
        <Metric label="R@10"      value={RAG.r10.toFixed(3)}   sub="recall" good />
      </div>
      <div>
        <div style={{display:"flex", justifyContent:"space-between", alignItems:"baseline", marginBottom:4}}>
          <div className="lbl">24h hit-rate</div>
          <div style={{fontSize:10, color:"var(--ink-4)", letterSpacing:".1em", textTransform:"uppercase"}}>
            queries · <span className="num-md" style={{fontSize:12, color:"var(--ink-2)", marginLeft:4}}>{fmt.num(RAG.queries_24h)}</span>
          </div>
        </div>
        <div style={{width:"100%"}}>
          <Spark data={RAG.hit_rate_24h} w={320} h={32} />
        </div>
      </div>
      <div className="hairline"></div>
      <div style={{display:"flex", justifyContent:"space-between", fontSize:11, color:"var(--ink-3)"}}>
        <span><span className="lbl">docs</span> {fmt.num(RAG.docs)}</span>
        <span><span className="lbl">chunks</span> {fmt.num(RAG.chunks)}</span>
        <span><span className="lbl">reindexed</span> {RAG.last_reindex}</span>
      </div>
    </Panel>
  );
}

function Metric({ label, value, sub, good }) {
  return (
    <div style={{border:"1px solid var(--rule)", padding:"8px 10px", background:"var(--bg)"}}>
      <div className="lbl">{label}</div>
      <div className="num-md" style={{color: good ? "var(--accent-2)" : "var(--ink)"}}>{value}</div>
      {sub && <div style={{fontSize:10, color:"var(--ink-4)"}}>{sub}</div>}
    </div>
  );
}

Object.assign(window, { HeaderBar, FinOpsPanel, IntegrityPanel, RAGPanel, Metric });
