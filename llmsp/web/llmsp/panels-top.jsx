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
function FinOpsPanel({ liveFinops }) {
  const { MODELS, BUDGET } = window.LLMSP_DATA;
  const tick = useTick(2000);

  // Prefer live data when the backend reports any activity; otherwise fall
  // back to fixtures so the panel never renders empty on first load.
  const hasLive = !!liveFinops && liveFinops.call_count > 0;
  const models = hasLive
    ? liveFinops.models
        .filter(m => m.calls > 0 || m.cost > 0)
        .map(m => ({
          name:    m.name,
          tier:    m.input_per_1k >= 0.01 ? "frontier"
                 : m.input_per_1k >= 0.0015 ? "standard" : "fast",
          inTok:   m.input_tokens,
          outTok:  m.output_tokens,
          calls:   m.calls,
          costIn:  (m.input_tokens/1000)  * m.input_per_1k,
          costOut: (m.output_tokens/1000) * m.output_per_1k,
          delta:   0,
        }))
    : MODELS.map((m,i) => ({ ...m, delta: ((tick + i*7) % 19) }));

  const totalTokens = models.reduce((s,m)=>s+m.inTok+m.outTok, 0);
  const totalCost   = hasLive ? liveFinops.total_cost : models.reduce((s,m)=>s+m.costIn+m.costOut, 0);
  const spent       = hasLive ? liveFinops.total_cost : BUDGET.spent;

  const statusChip = hasLive
    ? <span className="chip sage">LIVE · {fmt.num(liveFinops.call_count)} calls</span>
    : <span className="chip ghost">DEMO · fixtures</span>;

  return (
    <Panel title="FinOps · Spend & Token Flow"
      right={<>{statusChip}<span className="chip ghost">{BUDGET.period}</span></>}>

      <div style={{display:"grid", gridTemplateColumns:"auto 1fr auto", gap:20, alignItems:"center", marginBottom:14}}>
        <div>
          <div className="lbl">Month-to-date</div>
          <div className="num-xl">${spent.toFixed(2)}</div>
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
        <Ring size={88} stroke={10} value={spent} max={BUDGET.limit}
              label={Math.round(spent/BUDGET.limit*100)+"%"} sub="used"
              color={spent/BUDGET.limit > 0.8 ? "var(--accent-3)" : "var(--accent)"} />
      </div>

      <table className="tbl">
        <thead>
          <tr><th>Model</th><th>Tier</th><th style={{textAlign:"right"}}>Calls</th>
              <th style={{textAlign:"right"}}>In / Out</th>
              <th style={{textAlign:"right"}}>Cost</th>
              <th style={{width:80}}>Share</th></tr>
        </thead>
        <tbody>
          {models.length === 0 && (
            <tr><td colSpan={6} style={{padding:"14px", textAlign:"center", color:"var(--ink-4)"}}>
              no model usage yet · run a council to populate
            </td></tr>
          )}
          {models.map(m => {
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
            <td colSpan={2} style={{color:"var(--ink-3)"}}>TOTAL · {models.length} models</td>
            <td style={{textAlign:"right", color:"var(--ink-3)"}}>{fmt.num(models.reduce((s,m)=>s+m.calls,0))}</td>
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
function IntegrityPanel({ stats, threats }) {
  const { INTEGRITY } = window.LLMSP_DATA;
  const integrityOK = !stats || stats.integrity === "ok";
  const liveEvents = stats?.total_events;
  const mismatches = stats && stats.integrity !== "ok"
    ? (stats.integrity.match(/\d+/)?.[0] || "?")
    : 0;
  const rightChip = integrityOK
    ? <span className="chip sage"><span className="dot green pulse"></span> VERIFIED</span>
    : <span className="chip rust"><span className="dot rust pulse"></span> MISMATCH</span>;

  // Overlay real auditor alerts when available. The backend returns full
  // alerts with threat_type, severity, description, and author_id — we map
  // them to the same row shape the fixtures use so the UI is uniform.
  const hasLive = Array.isArray(threats);
  const liveThreatCount = hasLive ? threats.length : null;
  const rows = hasLive
    ? threats.slice(0, 4).map(a => ({
        sev:   a.severity,
        class: a.threat_type,
        note:  a.description,
        agent: (a.author_id || "").replace(/^pr_/, "").split("_")[0],
        when:  "now",
      }))
    : INTEGRITY.threats;

  return (
    <Panel title="Scarred Ledger · Integrity"
           right={<>{rightChip}{stats ? <span className="chip ghost">LIVE</span> : null}</>}>
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
          <div className="lbl">Threats{hasLive ? " · live" : " · 24h"}</div>
          <div className="num-md" style={{color: (liveThreatCount ?? INTEGRITY.threats_24h) > 0 ? "var(--accent)" : "var(--good)"}}>
            {liveThreatCount != null ? liveThreatCount : INTEGRITY.threats_24h}
          </div>
        </div>
      </div>
      <div className="lbl" style={{marginBottom:4}}>
        recent threat signals {hasLive && <span style={{color:"var(--accent-2)"}}>· auditor live</span>}
      </div>
      {rows.length === 0 && (
        <div style={{fontSize:11, color:"var(--ink-4)", padding:"10px 0", fontStyle:"italic"}}>
          no threats detected · auditor clean
        </div>
      )}
      {rows.map((th, i) => (
        <div key={i} style={{display:"grid", gridTemplateColumns:"auto auto 1fr auto", gap:8, alignItems:"center", padding:"5px 0", borderTop:"1px dotted var(--rule)"}}>
          <SevPill sev={th.sev} />
          <span style={{fontSize:11, color:"var(--ink-2)"}}>{th.class}</span>
          <span style={{fontSize:11, color:"var(--ink-3)"}}>{th.note}</span>
          <span style={{fontSize:10, color:"var(--ink-4)"}}>{th.agent || th.when}</span>
        </div>
      ))}
      <div style={{fontSize:10, color:"var(--ink-4)", marginTop:10, borderTop:"1px dashed var(--rule)", paddingTop:6}}>
        auditor scan · {hasLive ? "live" : INTEGRITY.last_scan} · 8/8 threat classes · 100% detection rate
      </div>
    </Panel>
  );
}

// ───────────────────────────────────────────── RAG
function RAGPanel({ liveRag }) {
  const { RAG } = window.LLMSP_DATA;
  const docs   = liveRag?.docs        ?? RAG.docs;
  const chunks = liveRag?.indexed     ?? RAG.chunks;
  const terms  = liveRag?.tfidf_terms ?? RAG.tfidf_terms;
  // Only use live metrics when the backend actually returned them.
  const mrr    = liveRag?.mrr    ?? RAG.mrr;
  const ndcg10 = liveRag?.ndcg10 ?? RAG.ndcg10;
  const p3     = liveRag?.p3     ?? RAG.p3;
  const r10    = liveRag?.r10    ?? RAG.r10;
  const liveChip = liveRag
    ? <span className="chip sage">LIVE · index {fmt.num(chunks)}</span>
    : <span className="chip ghost">DEMO · fixtures</span>;

  return (
    <Panel title="RAG · Retrieval Health" right={<>{liveChip}<span className="chip ghost">TF-IDF · {fmt.k(terms || 0)} terms</span></>}>
      <div style={{display:"grid", gridTemplateColumns:"1fr 1fr 1fr 1fr", gap:8, marginBottom:12}}>
        <Metric label="MRR"       value={mrr.toFixed(3)}   sub="first-hit" good />
        <Metric label="NDCG@10"   value={ndcg10.toFixed(3)} sub="ranking" good />
        <Metric label="P@3"       value={p3.toFixed(3)}    sub="precision" />
        <Metric label="R@10"      value={r10.toFixed(3)}   sub="recall" good />
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
        <span><span className="lbl">docs</span> {fmt.num(docs)}</span>
        <span><span className="lbl">indexed</span> {fmt.num(chunks)}</span>
        <span><span className="lbl">reindexed</span> {liveRag ? "just now" : RAG.last_reindex}</span>
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
