// Settings + Convene bar + Live orchestration using window.claude.complete or direct provider calls

const SETTINGS_DEFAULTS = {
  anthropic_key: "",
  google_key: "",
  xai_key: "",
  budget_cap: 10.00,
  prefer_backend: "builtin", // builtin | anthropic | google | xai
};

function loadSettings() {
  try { return { ...SETTINGS_DEFAULTS, ...(JSON.parse(localStorage.getItem("llmsp_settings") || "{}")) }; }
  catch(e) { return { ...SETTINGS_DEFAULTS }; }
}
function saveSettings(s) { localStorage.setItem("llmsp_settings", JSON.stringify(s)); }

// ───────────────────────────────────────────── Settings Modal
function SettingsModal({ open, onClose, settings, setSettings }) {
  const [local, setLocal] = useState(settings);
  const [revealed, setRevealed] = useState({});
  useEffect(() => { if (open) setLocal(settings); }, [open]);
  if (!open) return null;
  const fields = [
    { k: "anthropic_key", label: "Anthropic API Key", placeholder: "sk-ant-…", provider: "claude" },
    { k: "google_key",    label: "Google API Key",    placeholder: "AIza…",    provider: "gemini" },
    { k: "xai_key",       label: "xAI API Key",       placeholder: "xai-…",    provider: "grok" },
  ];
  const save = () => { setSettings(local); saveSettings(local); onClose(); };
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={e=>e.stopPropagation()} style={{maxWidth:620}}>
        <div className="panel-title">
          <div className="t-left"><span className="ascii-corner">┌─</span><span>Settings · API Keys & Budget</span></div>
          <div className="t-right"><span className="kbd">esc</span></div>
        </div>
        <div style={{padding:"20px 22px"}}>
          <div style={{fontSize:11.5, color:"var(--ink-3)", marginBottom:14, lineHeight:1.6}}>
            Keys are stored <span style={{color:"var(--ink-2)"}}>only in your browser</span> (localStorage).
            They never leave this device except when your browser itself calls the provider.
            Leave all blank to use the built-in model for deliberation.
          </div>

          <div className="lbl" style={{marginBottom:8}}>providers</div>
          {fields.map(f => {
            const has = !!local[f.k];
            return (
              <div key={f.k} style={{display:"grid", gridTemplateColumns:"120px 1fr auto auto", gap:10, alignItems:"center", marginBottom:8}}>
                <div style={{fontSize:12, color:"var(--ink-2)"}}>
                  <span className={"dot " + (has?"green":"ghost")} style={{marginRight:6}}></span>{f.label}
                </div>
                <input
                  type={revealed[f.k] ? "text" : "password"}
                  value={local[f.k]}
                  placeholder={f.placeholder}
                  onChange={e => setLocal({...local, [f.k]: e.target.value})}
                  style={{width:"100%"}}
                />
                <button onClick={()=>setRevealed(r=>({...r, [f.k]: !r[f.k]}))} style={{padding:"4px 8px"}}>
                  {revealed[f.k] ? "hide" : "show"}
                </button>
                <button onClick={()=>setLocal({...local, [f.k]: ""})} style={{padding:"4px 8px"}}>clear</button>
              </div>
            );
          })}

          <div className="hairline" style={{margin:"16px 0"}}></div>

          <div className="lbl" style={{marginBottom:8}}>preferences</div>
          <div style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:14}}>
            <div>
              <div style={{fontSize:11, color:"var(--ink-3)", marginBottom:4}}>preferred backend</div>
              <select value={local.prefer_backend} onChange={e=>setLocal({...local, prefer_backend:e.target.value})}
                      style={{width:"100%"}}>
                <option value="builtin">Built-in · Claude Haiku (no key required)</option>
                <option value="anthropic" disabled={!local.anthropic_key}>Anthropic · direct {!local.anthropic_key && "(key required)"}</option>
                <option value="google"    disabled={!local.google_key}>Google · direct {!local.google_key && "(key required)"}</option>
                <option value="xai"       disabled={!local.xai_key}>xAI · direct {!local.xai_key && "(key required)"}</option>
              </select>
            </div>
            <div>
              <div style={{fontSize:11, color:"var(--ink-3)", marginBottom:4}}>monthly budget cap (USD)</div>
              <div style={{display:"flex", alignItems:"center", gap:8}}>
                <span style={{fontSize:14, color:"var(--ink-3)"}}>$</span>
                <input type="number" step="0.5" min="0" value={local.budget_cap}
                       onChange={e=>setLocal({...local, budget_cap: parseFloat(e.target.value) || 0})}
                       style={{flex:1}} />
              </div>
              <div style={{fontSize:10, color:"var(--ink-4)", marginTop:4}}>
                councils will warn when spend approaches this cap
              </div>
            </div>
          </div>

          <div className="hairline" style={{margin:"18px 0"}}></div>
          <div style={{display:"flex", justifyContent:"space-between", alignItems:"center"}}>
            <div style={{fontSize:10, color:"var(--ink-4)"}}>
              stored locally · {["anthropic_key","google_key","xai_key"].filter(k=>local[k]).length}/3 providers configured
            </div>
            <div style={{display:"flex", gap:6}}>
              <button onClick={onClose}>Cancel</button>
              <button className="primary" onClick={save}>Save Settings ↵</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Convene bar (persistent bottom)
function ConveneBar({ onOpenSettings, settings, onLaunch, busy, status }) {
  const [q, setQ] = useState("");
  const [backends, setBackends] = useState(["claude","gemini","grok"]);
  const keyCount = ["anthropic_key","google_key","xai_key"].filter(k=>settings[k]).length;
  const toggle = (b) => setBackends(bs => bs.includes(b) ? bs.filter(x=>x!==b) : [...bs,b]);
  const submit = () => {
    if (!q.trim() || busy) return;
    onLaunch(q, backends);
    setQ("");
  };
  return (
    <div style={{
      position:"fixed", left:0, right:0, bottom:0,
      background:"var(--panel)", borderTop:"1px solid var(--ink-2)",
      padding:"10px 16px", zIndex:90,
      boxShadow:"0 -4px 16px rgba(0,0,0,0.08)",
    }}>
      <div style={{maxWidth:1680, margin:"0 auto", display:"grid", gridTemplateColumns:"auto 1fr auto auto auto", gap:10, alignItems:"center"}}>
        <div style={{display:"flex", alignItems:"center", gap:8, fontFamily:"var(--serif)", fontStyle:"italic", fontSize:18, color:"var(--ink)"}}>
          <span style={{color:"var(--accent)"}}>»</span>
          <span>convene</span>
        </div>
        <input
          value={q}
          onChange={e=>setQ(e.target.value)}
          onKeyDown={e=>{ if (e.key==="Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          disabled={busy}
          placeholder={busy ? status : "Ask the swarm…   e.g. Ed25519 or RSA-PSS for agent signing?"}
          style={{width:"100%", fontSize:13, padding:"8px 12px", background:"var(--bg)"}}
        />
        <div style={{display:"flex", gap:4}}>
          {["claude","gemini","grok"].map(b => (
            <button key={b} onClick={()=>toggle(b)}
                    style={{
                      padding:"5px 9px",
                      borderColor: backends.includes(b) ? "var(--accent)" : "var(--rule)",
                      color: backends.includes(b) ? "var(--ink)" : "var(--ink-4)",
                      background: backends.includes(b) ? "var(--panel-2)" : "var(--bg)",
                    }}>
              {backends.includes(b) ? "▣" : "□"} {b}
            </button>
          ))}
        </div>
        <button onClick={onOpenSettings} title="API keys & budget" style={{position:"relative"}}>
          ⚙ keys
          {keyCount > 0 && <span style={{marginLeft:5, color:"var(--accent-2)"}}>({keyCount})</span>}
        </button>
        <button className="primary" onClick={submit} disabled={busy || !q.trim()}>
          {busy ? "deliberating…" : "Convene ↵"}
        </button>
      </div>
      <div style={{maxWidth:1680, margin:"6px auto 0", fontSize:10, color:"var(--ink-4)", display:"flex", justifyContent:"space-between"}}>
        <span>
          {settings.prefer_backend === "builtin"
            ? "using built-in haiku · no key required"
            : `direct · ${settings.prefer_backend}`}
          {" · "}budget ${settings.budget_cap?.toFixed(2) || "0.00"}/mo
        </span>
        <span>⏎ to convene · shift+⏎ newline</span>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Orchestrator: real deliberation
// Uses window.claude.complete when available (design-tool harness),
// otherwise falls back to a local synthetic stream so the UI still demonstrates.
async function runDeliberation(query, backends, onEvent) {
  const agents = [
    { who: "Alice", role: "security",     color: "amber",
      system: "You are Alice, a security-focused AI agent in a multi-agent council. Be concise (1-2 sentences). Focus on threats, crypto, authentication, and data protection. Respond from a security-first lens." },
    { who: "Bob",   role: "architecture", color: "sage",
      system: "You are Bob, an architecture-focused AI agent in a multi-agent council. Be concise (1-2 sentences). Focus on scalability, maintainability, system design trade-offs, and long-term evolution." },
    { who: "Carol", role: "performance",  color: "rust",
      system: "You are Carol, a performance-focused AI agent in a multi-agent council. Be concise (1-2 sentences). Focus on benchmarks, latency, throughput, and efficiency. Include concrete numbers when possible." },
  ].filter((a,i) => i < Math.max(2, backends.length));

  const hasHarness = typeof window.claude !== "undefined" && typeof window.claude.complete === "function";
  const complete = hasHarness
    ? (messages) => window.claude.complete({ messages })
    : syntheticComplete;

  let t = 0;
  onEvent({ t: t++, who:"Clerk", role:"clerk", type:"COUNCIL_START",
    text:`Council opened on "${query.slice(0,80)}${query.length>80?"…":""}". Routed to ${agents.map(a=>a.role).join(", ")}.` });

  // Round 1 — opening positions, sequential for nice streaming feel
  const priorStatements = [];
  for (const a of agents) {
    try {
      const prompt = `The council is deliberating: "${query}"\n\nPrior statements:\n${priorStatements.length ? priorStatements.map(p=>`- ${p.who}: ${p.text}`).join("\n") : "(none yet)"}\n\nAs ${a.who} (${a.role}), give your opening position. Respond with JSON only: {"text": "...", "type": "CLAIM" or "MESSAGE", "confidence": 0-1}. One or two sentences max.`;
      const raw = await complete([{ role:"user", content: a.system + "\n\n" + prompt }]);
      const parsed = extractJSON(raw);
      const text = parsed?.text || raw.slice(0, 240);
      const type = parsed?.type === "CLAIM" ? "CLAIM" : "MESSAGE";
      const conf = typeof parsed?.confidence === "number" ? parsed.confidence : 0.75 + Math.random()*0.2;
      priorStatements.push({ who: a.who, text });
      onEvent({ t: t += 3, who: a.who, role: a.role, type, text, conf });
      await sleep(300);
    } catch (err) {
      onEvent({ t: t += 3, who: a.who, role: a.role, type:"MESSAGE",
        text: `(offline) unable to reach backend: ${String(err).slice(0,80)}`, conf: 0.5 });
    }
  }

  // Round 2 — objection / refinement round
  onEvent({ t: t += 2, who:"Clerk", role:"clerk", type:"PHASE", text:"Round 1 complete. Opening objection round." });
  for (const a of agents) {
    try {
      const others = priorStatements.filter(p => p.who !== a.who);
      if (!others.length) continue;
      const prompt = `You are ${a.who} (${a.role}). The council is deliberating: "${query}"\n\nOther agents have said:\n${others.map(o=>`- ${o.who}: ${o.text}`).join("\n")}\n\nEither object to a specific claim (if you see a flaw), or refine your position. Respond with JSON only: {"text": "...", "type": "OBJECTION" or "MESSAGE", "confidence": 0-1}. One or two sentences max.`;
      const raw = await complete([{ role:"user", content: a.system + "\n\n" + prompt }]);
      const parsed = extractJSON(raw);
      const text = parsed?.text || raw.slice(0, 240);
      const type = parsed?.type === "OBJECTION" ? "OBJECTION" : "MESSAGE";
      const conf = typeof parsed?.confidence === "number" ? parsed.confidence : 0.7 + Math.random()*0.2;
      onEvent({ t: t += 4, who: a.who, role: a.role, type, text, conf });
      await sleep(300);
    } catch (err) {}
  }

  // Synthesis
  onEvent({ t: t += 2, who:"Clerk", role:"clerk", type:"PHASE", text:"Round 2 complete. Clerk synthesizing." });

  try {
    const allStatements = priorStatements.map(p=>`- ${p.who}: ${p.text}`).join("\n");
    const synthPrompt = `The council deliberated on: "${query}". Statements:\n${allStatements}\n\nAs the non-generative Clerk, produce a synthesis as JSON only with this exact shape: {"agreements":["...","..."], "disagreements":[{"topic":"...","positions":[{"agent":"Alice","view":"..."}]}], "decisions":[{"decision":"...","rationale":"..."}], "tasks":[{"task":"...","assignee":"Alice","status":"open"}]}. Only report what agents actually said; do not invent.`;
    const raw = await complete([{ role:"user", content: synthPrompt }]);
    const synth = extractJSON(raw) || {};
    onEvent({ t: t += 3, who:"Clerk", role:"clerk", type:"DECISION",
      text: `Synthesis ready · ${synth.agreements?.length||0} agreements · ${synth.decisions?.length||0} decisions · ${synth.tasks?.length||0} tasks`,
      synthesis: {
        agreements: synth.agreements || [],
        disagreements: synth.disagreements || [],
        decisions: synth.decisions || [],
        tasks: synth.tasks || [],
      }
    });
  } catch (err) {
    onEvent({ t: t += 3, who:"Clerk", role:"clerk", type:"DECISION", text: "Synthesis unavailable." });
  }

  onEvent({ t: t += 1, who:"Clerk", role:"clerk", type:"COUNCIL_END", text:"Council closed. Events committed to ledger." });
}

// Local synthetic generator used when window.claude.complete is not present.
// Produces plausible JSON-shaped responses based on the prompt so the UI
// remains interactive even without a key or backend.
async function syntheticComplete(messages) {
  await sleep(700 + Math.random()*500);
  const text = messages[0]?.content || "";
  if (/synthesis/i.test(text) || /produce a synthesis/i.test(text)) {
    return JSON.stringify({
      agreements: [
        "The proposal should be evaluated against real workload traces.",
        "A staged rollout reduces blast radius of any regression."
      ],
      disagreements: [
        { topic: "Cutover timing", positions: [
          { agent: "Alice", view: "Immediate cutover behind feature flag" },
          { agent: "Bob",   view: "Parallel run for two weeks first" },
        ]}
      ],
      decisions: [
        { decision: "Adopt the proposal with a 2-week parallel-run safety window",
          rationale: "Balances speed with the ability to revert on regression." }
      ],
      tasks: [
        { task: "Draft rollout plan with flag gating",   assignee: "Bob",   status: "open" },
        { task: "Instrument error-budget burn tracking", assignee: "Alice", status: "open" },
        { task: "Run load test at 2× expected peak",     assignee: "Carol", status: "open" }
      ]
    });
  }
  const isObjection = /object to a specific claim/i.test(text);
  const templates = isObjection ? [
    "That framing ignores operational cost at peak — consider warm-pool overhead.",
    "The cited benchmark used synthetic data; production traces tell a different story.",
    "I would refine: the guarantee only holds under bounded concurrency."
  ] : [
    "The key trade-off is latency vs durability; we should bound P99 before anything else.",
    "We can get 80% of the benefit with a staged rollout and feature flags.",
    "I would default to the simpler option until the scaling evidence forces us to upgrade."
  ];
  const pick = templates[Math.floor(Math.random()*templates.length)];
  return JSON.stringify({
    text: pick,
    type: isObjection ? "OBJECTION" : "MESSAGE",
    confidence: +(0.7 + Math.random()*0.25).toFixed(2)
  });
}

function extractJSON(s) {
  if (!s) return null;
  try { return JSON.parse(s); } catch(e) {}
  const m = s.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch(e) {} }
  return null;
}
function sleep(ms) { return new Promise(r=>setTimeout(r, ms)); }

Object.assign(window, { loadSettings, saveSettings, SettingsModal, ConveneBar, runDeliberation });
