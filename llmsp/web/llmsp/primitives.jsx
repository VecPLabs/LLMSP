// Shared primitives for the LLMSP dashboard

const { useState, useEffect, useRef, useMemo } = React;

// ───────────────────────────────────────────── Panel
function Panel({ title, subtitle, right, children, id, style }) {
  return (
    <section className="panel" id={id} style={style}>
      <header className="panel-title">
        <div className="t-left">
          <span className="ascii-corner">┌─</span>
          <span>{title}</span>
          {subtitle && <span style={{color:"var(--ink-4)", letterSpacing:".06em", textTransform:"none"}}>{subtitle}</span>}
        </div>
        <div className="t-right">{right}</div>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

// ───────────────────────────────────────────── Sparkline (SVG line)
function Spark({ data, w=120, h=28, stroke="var(--accent)", fill=true }) {
  if (!data?.length) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v,i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return [x,y];
  });
  const path = pts.map((p,i) => (i===0?"M":"L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const area = path + ` L ${w},${h} L 0,${h} Z`;
  return (
    <svg width={w} height={h} style={{display:"block"}}>
      {fill && <path d={area} fill={stroke} opacity="0.12" />}
      <path d={path} fill="none" stroke={stroke} strokeWidth="1.4" />
    </svg>
  );
}

// ───────────────────────────────────────────── Bars
function BarRow({ data, highlightLast=true }) {
  const max = Math.max(...data);
  return (
    <div className="bars">
      {data.map((v,i)=>(
        <div key={i} className={"b" + (highlightLast && i===data.length-1 ? " on":"")}
             style={{height: Math.max(3, (v/max)*100) + "%"}} />
      ))}
    </div>
  );
}

// ───────────────────────────────────────────── Ring
function Ring({ value, max, size=88, stroke=10, label, sub, color="var(--accent)" }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const pct = Math.min(1, value / max);
  return (
    <div className="ring-wrap" style={{width:size, height:size}}>
      <svg width={size} height={size}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--rule)" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
                strokeDasharray={`${c*pct} ${c}`} strokeLinecap="butt" />
      </svg>
      <div className="center">
        <div className="num-md">{label}</div>
        {sub && <div className="lbl" style={{marginTop:2}}>{sub}</div>}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────── Live clock / ticker hook
function useTick(interval=1000) {
  const [t, setT] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setT(x => x + 1), interval);
    return () => clearInterval(id);
  }, [interval]);
  return t;
}

// ───────────────────────────────────────────── fmt
const fmt = {
  num: (n) => n.toLocaleString("en-US"),
  usd: (n) => "$" + n.toFixed(2),
  pct: (n) => (n*100).toFixed(1) + "%",
  k:   (n) => n >= 1e6 ? (n/1e6).toFixed(2)+"M" : n >= 1e3 ? (n/1e3).toFixed(1)+"k" : String(n),
  time: (s) => {
    const m = Math.floor(s/60), ss = s%60;
    return `${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`;
  },
  ago: (s) => s<60?`${s}s ago`:s<3600?`${Math.floor(s/60)}m ago`:`${Math.floor(s/3600)}h ago`,
  clock: (d=new Date()) => {
    const p = (n)=>String(n).padStart(2,"0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
};

// ───────────────────────────────────────────── Event type pill
function TypePill({ type }) {
  const map = {
    MESSAGE:       { c: "var(--ink-3)",  bg: "transparent" },
    OBJECTION:     { c: "var(--accent-3)", bg: "transparent" },
    CLAIM:         { c: "var(--accent)", bg: "transparent" },
    DECISION:      { c: "var(--accent-2)", bg: "transparent" },
    PHASE:         { c: "var(--ink-4)",  bg: "transparent" },
    COUNCIL_START: { c: "var(--accent-2)", bg: "transparent" },
    COUNCIL_END:   { c: "var(--ink-3)",  bg: "transparent" },
    REGISTRATION:  { c: "var(--ink-3)",  bg: "transparent" },
  };
  const s = map[type] || map.MESSAGE;
  return (
    <span style={{
      fontSize:10, letterSpacing:".14em", textTransform:"uppercase",
      color: s.c, border: `1px solid ${s.c}`, padding:"1px 5px",
      whiteSpace:"nowrap"
    }}>{type}</span>
  );
}

// ───────────────────────────────────────────── Agent glyph (monogram badge)
function AgentGlyph({ name, color="amber", size=22 }) {
  const c = {
    amber: "var(--accent)",
    sage:  "var(--accent-2)",
    rust:  "var(--accent-3)",
  }[color] || "var(--ink-3)";
  return (
    <span style={{
      display:"inline-flex", width:size, height:size,
      alignItems:"center", justifyContent:"center",
      border:`1px solid ${c}`, color: c,
      fontFamily:"var(--mono)", fontSize: size*0.45,
      fontWeight: 600, letterSpacing:0,
      flexShrink:0,
    }}>{name[0].toUpperCase()}</span>
  );
}

// ───────────────────────────────────────────── Phase indicator
function PhaseBadge({ phase }) {
  const map = {
    idle:         { label:"IDLE",         dot:"ghost" },
    deliberating: { label:"DELIBERATING", dot:"amber" },
    reviewing:    { label:"REVIEWING",    dot:"amber" },
    synthesizing: { label:"SYNTHESIZING", dot:"amber" },
    complete:     { label:"COMPLETE",     dot:"green" },
  };
  const m = map[phase] || map.idle;
  return (
    <span className="chip" style={{color: m.dot==="amber"?"var(--accent)": m.dot==="green"?"var(--good)":"var(--ink-3)", borderColor: "currentColor"}}>
      <span className={`dot ${m.dot} ${phase!=="complete"?"pulse":""}`}></span>
      {m.label}
    </span>
  );
}

// ───────────────────────────────────────────── Sev pill
function SevPill({ sev }) {
  const map = {
    CRITICAL: "var(--bad)",
    HIGH:     "var(--accent-3)",
    MEDIUM:   "var(--warn)",
    LOW:      "var(--ink-3)",
    INFO:     "var(--ink-4)",
  };
  const c = map[sev] || "var(--ink-3)";
  return (
    <span style={{
      fontSize:10, letterSpacing:".14em", textTransform:"uppercase",
      color: c, border:`1px solid ${c}`, padding:"1px 5px",
    }}>{sev}</span>
  );
}

Object.assign(window, { Panel, Spark, BarRow, Ring, useTick, fmt, TypePill, AgentGlyph, PhaseBadge, SevPill });
