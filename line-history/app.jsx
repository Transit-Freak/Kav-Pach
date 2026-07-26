/* הקו בזמן — היסטוריית מסלולים ותחנות מהשוואת GTFS יומית.
   הנתונים: line-history/data, נוצר ע"י tools/linehistory.py ב-GitHub Actions. */
const { useState, useEffect, useMemo, useRef } = React;
const BUILD = window.LH_BUILD || "0";

const KINDS = {
  baseline:    { label: "תיעוד ראשון", color: "#64748b" },
  new:         { label: "וריאנט חדש", color: "#16a34a" },
  route:       { label: "שינוי מסלול", color: "#7c3aed" },
  redraw:      { label: "תיקון שרטוט", color: "#0891b2" },
  terminal:    { label: "שינוי קצה המסלול", color: "#c026d3" },
  extend:      { label: "הארכת קו", color: "#15803d" },
  shorten:     { label: "קיצור קו", color: "#ea580c" },
  "stops-add": { label: "תחנות נוספו", color: "#65a30d" },
  "stops-del": { label: "תחנות ירדו", color: "#e11d48" },
  stops:       { label: "שינוי תחנות", color: "#d97706" },
  operator:    { label: "החלפת מפעיל", color: "#0f766e" },
  dest:        { label: "שינוי יעד", color: "#9333ea" },
  renum:       { label: "שינוי מספר", color: "#be185d" },
  removed:     { label: "בוטל (חודש ומעלה)", color: "#dc2626" },
  "removed-year": { label: "בוטל — מעל שנה לא חזר", color: "#7f1d1d" },
};

// ביטול שנשאר בתוקף מעל שנה (הגרסה האחרונה היא removed וישנה משנה) מקבל קטגוריה משלו
function dispKind(x, i, vs) {
  if (x.k === "removed" && i === vs.length - 1 && (Date.now() - new Date(x.d)) / 864e5 >= 365) return "removed-year";
  return x.k;
}
// אותו כלל ברמת האינדקס (lk/ld = הרשומה האחרונה של הווריאנט)
function isRemovedYear(l) {
  return l.lk === "removed" && (Date.now() - new Date(l.ld)) / 864e5 >= 365;
}
// סדר הקטגוריות בתפריט הראשי
const CATS = ["new", "removed-year", "removed", "operator", "dest", "renum",
  "route", "redraw", "terminal", "extend", "shorten", "stops-add", "stops-del", "stops"];
const SKINDS = {
  new:     { label: "חדשה", color: "#16a34a" },
  del:     { label: "בוטלה", color: "#dc2626" },
  renamed: { label: "שינוי שם", color: "#d97706" },
  moved:   { label: "הזזת מיקום", color: "#2563eb" },
};

// פענוח polyline (precision 5)
function decodeShape(str) {
  const pts = []; let i = 0, la = 0, lo = 0;
  while (i < str.length) {
    for (const which of [0, 1]) {
      let b, shift = 0, result = 0;
      do { b = str.charCodeAt(i++) - 63; result |= (b & 0x1f) << shift; shift += 5; } while (b >= 0x20);
      const d = (result & 1) ? ~(result >> 1) : (result >> 1);
      if (which === 0) la += d; else lo += d;
    }
    pts.push([la / 1e5, lo / 1e5]);
  }
  return pts;
}

function fsafe(rd) { return rd.replace(/#/g, "H").replace(/\//g, "_"); }
function fmtD(d) { return (d || "").split("-").reverse().join("."); }

/* ---------- איתור הקטעים ששונו בין שתי גאומטריות ----------
   לכל נקודה בגרסה אחת מחשבים את המרחק (במטרים) לקטע הקרוב ביותר בגרסה
   השנייה; רצף נקודות רחוקות = קטע ששונה. עמיד גם כשכל המסלול נדגם מחדש
   בנקודות אחרות (המרחק נשאר ~0 בקטעים שלא זזו באמת). */
function segDiff(cur, prev) {
  if (!cur || cur.length < 2 || !prev || prev.length < 2) return null;
  const ky = 110540, kx = 111320 * Math.cos((cur[0][0] * Math.PI) / 180);
  const M = (p) => [p[1] * kx, p[0] * ky];
  const A = cur.map(M), B = prev.map(M);
  const CS = 60; // גודל תא הרשת במטרים
  function buildGrid(S) {
    const g = new Map();
    for (let i = 0; i < S.length - 1; i++) {
      const x0 = Math.min(S[i][0], S[i + 1][0]) - 20, x1 = Math.max(S[i][0], S[i + 1][0]) + 20;
      const y0 = Math.min(S[i][1], S[i + 1][1]) - 20, y1 = Math.max(S[i][1], S[i + 1][1]) + 20;
      for (let gx = Math.floor(x0 / CS); gx <= Math.floor(x1 / CS); gx++)
        for (let gy = Math.floor(y0 / CS); gy <= Math.floor(y1 / CS); gy++) {
          const k = gx + ":" + gy;
          if (!g.has(k)) g.set(k, []);
          g.get(k).push(i);
        }
    }
    return g;
  }
  function segd(p, s0, s1) {
    const dx = s1[0] - s0[0], dy = s1[1] - s0[1];
    const l2 = dx * dx + dy * dy;
    let t = l2 ? ((p[0] - s0[0]) * dx + (p[1] - s0[1]) * dy) / l2 : 0;
    t = Math.max(0, Math.min(1, t));
    const x = s0[0] + t * dx - p[0], y = s0[1] + t * dy - p[1];
    return Math.sqrt(x * x + y * y);
  }
  function dists(P, S, g) {
    return P.map((p) => {
      const gx = Math.floor(p[0] / CS), gy = Math.floor(p[1] / CS);
      let best = Infinity;
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const segs = g.get((gx + dx) + ":" + (gy + dy));
        if (segs) for (const i of segs) { const d = segd(p, S[i], S[i + 1]); if (d < best) best = d; }
      }
      return best;
    });
  }
  function runsOf(ds, th, pts) {
    const idx = [];
    ds.forEach((d, i) => { if (d > th) idx.push(i); });
    if (!idx.length) return [];
    const out = [];
    let s = idx[0], e = idx[0];
    for (let i = 1; i < idx.length; i++) {
      if (idx[i] - e <= 12) e = idx[i];
      else { out.push([s, e]); s = e = idx[i]; }
    }
    out.push([s, e]);
    return out.map(([a, b]) => pts.slice(Math.max(0, a - 6), Math.min(pts.length, b + 7)));
  }
  const gB = buildGrid(B), gA = buildGrid(A);
  const da = dists(A, B, gB), db = dists(B, A, gA);
  let th = 12;
  let curSegs = runsOf(da, th, cur), prevSegs = runsOf(db, th, prev);
  if (!curSegs.length && !prevSegs.length) {
    th = 3;
    curSegs = runsOf(da, th, cur); prevSegs = runsOf(db, th, prev);
  }
  if (!curSegs.length && !prevSegs.length) return null;
  return { curSegs, prevSegs };
}

/* ---------- מפת לפני/אחרי ---------- */
function DiffMap({ cur, prev, curStops, prevStops }) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  // הקטעים ששונו + התחנות ששונו — היעד של מצב "התמקדות" (בקשת המשתמש:
  // בתיקון באג לראות רק את הקטע שהשתנה, לא את כל המסלול)
  const diff = useMemo(() => (prev ? segDiff(cur, prev) : null), [cur, prev]);
  const chStops = useMemo(() => {
    if (!prevStops) return [];
    const curCodes = new Set((curStops || []).map((s) => s[0]));
    const prevCodes = new Set((prevStops || []).map((s) => s[0]));
    return (curStops || []).filter((s) => !prevCodes.has(s[0])).map((s) => [s[2], s[3]])
      .concat((prevStops || []).filter((s) => !curCodes.has(s[0])).map((s) => [s[2], s[3]]));
  }, [curStops, prevStops]);
  const focusPts = useMemo(() => {
    const pts = [];
    if (diff) { diff.curSegs.forEach((sg) => pts.push(...sg)); diff.prevSegs.forEach((sg) => pts.push(...sg)); }
    pts.push(...chStops);
    return pts;
  }, [diff, chStops]);
  const [focus, setFocus] = useState(true);
  const canFocus = focusPts.length > 0;
  useEffect(() => {
    if (!ref.current) return;
    const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    const map = L.map(ref.current, { scrollWheelZoom: !coarse });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 19,
    }).addTo(map);
    const focused = canFocus && focus;
    const all = focused ? focusPts : cur.concat(prev || []);
    map.fitBounds(L.latLngBounds(all.length ? all : [[32.08, 34.78]]).pad(focused ? 0.35 : 0.1), { maxZoom: 16 });
    if (prev && prev.length > 1) {
      L.polyline(prev, { color: "#dc2626", weight: focused ? 3 : 4, opacity: focused ? 0.25 : 0.75, dashArray: "8 7" }).addTo(map);
    }
    if (cur.length > 1) {
      L.polyline(cur, { color: prev ? "#16a34a" : "#4c1d95", weight: focused ? 3 : 5, opacity: focused ? 0.3 : 0.9 }).addTo(map);
    }
    if (focused && diff) {
      diff.prevSegs.forEach((sg) => L.polyline(sg, { color: "#dc2626", weight: 6, opacity: 0.95, dashArray: "9 8" }).addTo(map));
      diff.curSegs.forEach((sg) => L.polyline(sg, { color: "#16a34a", weight: 7, opacity: 0.95 }).addTo(map));
    }
    const curCodes = new Set((curStops || []).map((s) => s[0]));
    const prevCodes = new Set((prevStops || []).map((s) => s[0]));
    (curStops || []).forEach((s) => {
      const isNew = prevStops && !prevCodes.has(s[0]);
      L.circleMarker([s[2], s[3]], {
        radius: isNew ? 8 : 5, color: isNew ? "#fff" : "#4c1d95", weight: 2,
        fillColor: isNew ? "#16a34a" : "#fff", fillOpacity: 1, opacity: focused && !isNew ? 0.4 : 1,
      }).addTo(map).bindTooltip((isNew ? "נוספה: " : "") + s[1], { direction: "top", className: "lh-tip" });
    });
    (prevStops || []).forEach((s) => {
      if (curCodes.has(s[0])) return;
      L.circleMarker([s[2], s[3]], { radius: 8, color: "#dc2626", weight: 3, fillColor: "#fff", fillOpacity: 1 })
        .addTo(map).bindTooltip("ירדה: " + s[1], { direction: "top", className: "lh-tip" });
    });
    return () => { mapRef.current = null; map.remove(); };
  }, [cur, prev, curStops, prevStops, focus, diff, chStops, focusPts, canFocus]);
  return (
    <div className="mapwrap">
      <div className="map" ref={ref} />
      {canFocus && (
        <button className="focusbtn" onClick={() => setFocus(!focus)}>
          {focus ? "🗺️ כל המסלול" : "🔍 רק הקטע ששונה"}
        </button>
      )}
    </div>
  );
}

/* ---------- עמוד קו ---------- */
function LinePage({ rd, onBack }) {
  const [lf, setLf] = useState(null);
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState(null);   // אינדקס גרסה נבחרת
  const [mon, setMon] = useState("");
  useEffect(() => {
    setLf(null); setErr(null); setSel(null); setMon("");
    fetch("data/lines/" + fsafe(rd) + ".json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => { setLf(d); setSel(d.versions.length - 1); })
      .catch(setErr);
  }, [rd]);
  if (err) return <div className="card"><button className="back" onClick={onBack}>→ חזרה</button><div className="empty">לא נמצאו נתונים לוריאנט הזה.</div></div>;
  if (!lf) return <div className="card">טוען…</div>;
  const vs = lf.versions;
  const months = [...new Set(vs.map((v) => v.d.slice(0, 7)))].reverse();
  const shown = vs.map((v, i) => ({ v, i })).filter((x) => !mon || x.v.d.slice(0, 7) === mon).reverse();
  const v = vs[sel] || vs[vs.length - 1];
  const pi = vs.indexOf(v) - 1;
  const pv = pi >= 0 ? vs[pi] : null;
  const cur = decodeShape(v.shp);
  const prev = pv && v.k !== "baseline" ? decodeShape(pv.shp) : null;
  return (
    <div className="linewrap">
      <div className="card side">
        <button className="back" onClick={onBack}>→ חזרה לחיפוש</button>
        <div className="linehead"><span className="badge">{lf.line}</span><span className="dest">{lf.dest}</span></div>
        <div className="facts">{lf.op}{lf.ty ? " · " + lf.ty : ""} · מק״ט {lf.rd} · {vs.length} גרסאות מתועדות</div>
        {vs.length > 0 && vs[vs.length - 1].k === "removed" && (
          <div className="facts" style={{ color: (KINDS[dispKind(vs[vs.length - 1], vs.length - 1, vs)] || {}).color, fontWeight: 700 }}>
            ❌ הווריאנט מבוטל מאז {fmtD(vs[vs.length - 1].d)}{dispKind(vs[vs.length - 1], vs.length - 1, vs) === "removed-year" ? " — מעל שנה ולא חזר" : ""}
          </div>
        )}
        {months.length > 1 && (
          <div className="months">
            <button className={"mchip" + (!mon ? " on" : "")} onClick={() => setMon("")}>הכול</button>
            {months.map((m) => (
              <button key={m} className={"mchip" + (mon === m ? " on" : "")} onClick={() => setMon(m)}>
                {m.split("-").reverse().join(".")} <b>{vs.filter((x) => x.d.slice(0, 7) === m).length}</b>
              </button>
            ))}
          </div>
        )}
        <div className="tl">
          {shown.map(({ v: x, i }) => (
            <div key={x.d + x.k} className={"ev" + (i === vs.indexOf(v) ? " sel" : "")} onClick={() => setSel(i)}>
              <div className="d">{fmtD(x.d)}</div>
              <div className="t">
                <span className="k" style={{ background: (KINDS[dispKind(x, i, vs)] || {}).color || "#64748b" }}>{(KINDS[dispKind(x, i, vs)] || { label: x.k }).label}</span>
                {x.k === "redraw" && " הגאומטריה תוקנה — רצף התחנות לא השתנה"}
                {x.note && <span className="evnote"> {x.note}</span>}
              </div>
              {(x.add || x.rem) && (
                <div className="sub">
                  {x.add && <div>➕ נוספו: {x.add.join(", ")}</div>}
                  {x.rem && <div>➖ ירדו: {x.rem.join(", ")}</div>}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="card main">
        <div className="vhead">
          גרסת <b>{fmtD(v.d)}</b>{prev ? <> מול הגרסה שלפניה (<b>{fmtD(pv.d)}</b>)</> : " — הגרסה המתועדת הראשונה"}
        </div>
        {!v.shp ? (
          <div className="nogeo">
            🛈 {v.note || "אין פירוט לגרסה זו"}<br />
            <span className="mut">רשומת-עבר מארכיון אופן באס (הסדנא לידע ציבורי) — המסלול המדויק לא זמין לתקופה זו. רצפי התחנות יתווספו בשלב ב׳ של המילוי-לאחור.</span>
          </div>
        ) : (
        <DiffMap key={v.d + v.k} cur={cur} prev={prev} curStops={v.stops} prevStops={pv && v.k !== "baseline" && pv.shp ? pv.stops : null} />
        )}
        <div className="legend">
          {prev && <span><i style={{ borderColor: "#dc2626", borderStyle: "dashed" }} /> המסלול הקודם</span>}
          <span><i style={{ borderColor: prev ? "#16a34a" : "#4c1d95" }} /> {prev ? "המסלול החדש" : "המסלול"}</span>
          <span><span className="dot" style={{ background: "#16a34a" }} /> תחנה שנוספה</span>
          <span><span className="dot" style={{ background: "#fff", border: "3px solid #dc2626" }} /> תחנה שירדה</span>
        </div>
        <div className="mut">🔍 הגאומטריה נשמרת במלואה, בלי דילול — גם תיקון שרטוט של כמה מטרים ייראה כאן. {v.stops.length} תחנות בגרסה זו.</div>
      </div>
    </div>
  );
}

/* ---------- טאב תחנות ---------- */
function StopsTab() {
  const [months, setMonths] = useState(null);
  const [mon, setMon] = useState("");
  const [chs, setChs] = useState(null);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {
    fetch("data/months.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => r.json())
      .then((d) => { const ms = d.stopMonths || []; setMonths(ms); if (ms.length) setMon(ms[0]); })
      .catch(() => setMonths([]));
  }, []);
  useEffect(() => {
    if (!mon) return;
    setChs(null);
    fetch("data/changes/stops-" + mon + ".json?v=" + BUILD)
      .then((r) => (r.ok ? r.json() : { changes: [] }))
      .then((d) => setChs(d.changes || []))
      .catch(() => setChs([]));
  }, [mon]);
  if (months === null) return <div className="card">טוען…</div>;
  if (!months.length) return <div className="card"><div className="empty">עדיין אין נתוני שינויי תחנות — הם יצטברו מהריצות היומיות הקרובות.</div></div>;
  const needle = q.trim();
  const list = (chs || []).filter((c) => (!kind || c.k === kind) &&
    (!needle || (c.n || "").includes(needle) || (c.nn || "").includes(needle) || (c.on || "").includes(needle) || (c.t || "").includes(needle) || c.c === needle));
  const counts = {};
  (chs || []).forEach((c) => { counts[c.k] = (counts[c.k] || 0) + 1; });
  return (
    <div className="card">
      <div className="months">
        {months.slice(0, 18).map((m) => (
          <button key={m} className={"mchip" + (mon === m ? " on" : "")} onClick={() => setMon(m)}>{m.split("-").reverse().join(".")}</button>
        ))}
      </div>
      <div className="months">
        <button className={"mchip" + (!kind ? " on" : "")} onClick={() => setKind("")}>הכול {(chs || []).length}</button>
        {Object.entries(SKINDS).map(([k, v]) => (
          <button key={k} className={"mchip" + (kind === k ? " on" : "")} onClick={() => setKind(k)}>{v.label} <b>{counts[k] || 0}</b></button>
        ))}
        <input className="search sm" type="search" placeholder="חיפוש תחנה / עיר / מק״ט…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {chs === null ? "טוען…" : (
        <div className="slist">
          {list.slice(0, 300).map((c, i) => (
            <div className="srow" key={c.c + c.k + i}>
              <span className="k" style={{ background: (SKINDS[c.k] || {}).color }}>{(SKINDS[c.k] || { label: c.k }).label}</span>
              <span className="nm">
                {c.k === "renamed" ? <><s>{c.on}</s> ← <b>{c.nn}</b></> : <b>{c.n}</b>}
                <span className="code"> ({c.c})</span>
              </span>
              <span className="meta">
                {c.t} · {fmtD(c.d)}
                {c.k === "moved" && <> · הוזזה <b>{c.dist} מ׳</b></>}
                {c.k === "del" && c.lines && c.lines.length > 0 && <> · שירתה: {c.lines.slice(0, 8).join(", ")}</>}
              </span>
            </div>
          ))}
          {list.length === 0 && <div className="empty">אין שינויים תואמים בחודש הזה.</div>}
          {list.length > 300 && <div className="empty">מוצגים 300 הראשונים מתוך {list.length}.</div>}
        </div>
      )}
    </div>
  );
}

/* ---------- אפליקציה ---------- */
function App() {
  const [idx, setIdx] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("lines");
  const [q, setQ] = useState("");
  const [kat, setKat] = useState("");
  const [rd, setRd] = useState(null);
  useEffect(() => {
    fetch("data/lines.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setIdx)
      .catch(setErr);
  }, []);
  const counts = useMemo(() => {
    const c = {};
    if (idx) idx.lines.forEach((l) => {
      (l.ks || []).forEach((k) => { c[k] = (c[k] || 0) + 1; });
      if (isRemovedYear(l)) c["removed-year"] = (c["removed-year"] || 0) + 1;
    });
    return c;
  }, [idx]);
  if (err) return <div className="boot">הנתונים עוד לא נוצרו — הריצה הראשונה של הצינור תיצור אותם. נסו לרענן מאוחר יותר.</div>;
  if (!idx) return <div className="boot">טוען נתונים…</div>;
  const needle = q.trim();
  const inKat = (l) => !kat || (kat === "removed-year" ? isRemovedYear(l) : (l.ks || []).includes(kat));
  let list = [], total = 0;
  if (needle || kat) {
    list = idx.lines.filter((l) => inKat(l) &&
      (!needle || l.line === needle || l.rd.startsWith(needle) || (l.dest || "").includes(needle) || (l.op || "").includes(needle)));
    if (kat === "removed" || kat === "removed-year") list.sort((a, b) => (b.ld || "").localeCompare(a.ld || ""));
    else if (kat) list.sort((a, b) => ((parseInt(a.line) || 1e9) - (parseInt(b.line) || 1e9)) || a.line.localeCompare(b.line));
    total = list.length;
    list = list.slice(0, 200);
  }
  const changed = idx.lines.filter((l) => l.v > 1).length;
  return (
    <div className="wrap">
      <header>
        <h1>🕰️ הקו בזמן <span className="beta">ניסוי</span></h1>
        <p className="tag">כל שינוי שנכנס לתוקף במסלולי הקווים ובתחנות — מסלול, שרטוט, תחנות ושמות. מהשוואת ה-GTFS של משרד התחבורה, יום מול יום.</p>
        <div className="stats">
          <span className="stat"><b>{idx.lines.length.toLocaleString()}</b> וריאנטים מתועדים</span>
          <span className="stat"><b>{changed.toLocaleString()}</b> עם שינויים</span>
          <span className="stat mut">עודכן: {idx.gen}</span>
        </div>
      </header>
      <div className="tabs">
        <button className={"tab" + (tab === "lines" ? " on" : "")} onClick={() => { setTab("lines"); setRd(null); }}>🚌 קווים</button>
        <button className={"tab" + (tab === "stops" ? " on" : "")} onClick={() => { setTab("stops"); setRd(null); }}>🚏 תחנות</button>
      </div>
      {tab === "stops" ? <StopsTab /> : rd ? (
        <LinePage rd={rd} onBack={() => setRd(null)} />
      ) : (
        <div className="card">
          <input className="search" type="search" dir="rtl" autoFocus
            placeholder="חיפוש קו: מספר קו, מק״ט, יעד או מפעיל…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="months">
            <button className={"mchip" + (!kat ? " on" : "")} onClick={() => setKat("")}>הכול</button>
            {CATS.map((k) => (
              <button key={k} className={"mchip" + (kat === k ? " on" : "")}
                style={kat === k ? { background: KINDS[k].color, borderColor: KINDS[k].color } : {}}
                onClick={() => setKat(kat === k ? "" : k)}>
                {KINDS[k].label} <b>{counts[k] || 0}</b>
              </button>
            ))}
          </div>
          {(needle || kat) ? (
            <div className="llist">
              {list.map((l) => (
                <button key={l.rd} className="lrow" onClick={() => setRd(l.rd)}>
                  <span className="badge sm">{l.line}</span>
                  {l.lk === "removed" && (
                    <span className="k" style={{ background: isRemovedYear(l) ? "#7f1d1d" : "#dc2626" }}>
                      {isRemovedYear(l) ? "מבוטל מעל שנה" : "מבוטל"}
                    </span>
                  )}
                  <span className="ldest">{l.dest}</span>
                  <span className="lmeta">{l.op} · מק״ט {l.rd} · {l.v > 1 ? (l.v - 1) + " שינויים" : "ללא שינויים עדיין"}
                    {l.lk === "removed" && <> · מבוטל מאז {fmtD(l.ld)}</>}</span>
                </button>
              ))}
              {list.length === 0 && (
                <div className="empty">{kat && !needle
                  ? "אין עדיין קווים בקטגוריה הזו — קטגוריות של מסלול ותחנות מצטברות מההשוואות היומיות מכאן והלאה."
                  : "לא נמצא קו תואם."}</div>
              )}
              {total > list.length && <div className="empty">מוצגים 200 הראשונים מתוך {total.toLocaleString()}.</div>}
            </div>
          ) : (
            <div className="empty">הקלידו מספר קו, או בחרו קטגוריה כדי לראות את כל הקווים שעברו שינוי כזה.<br />
              <span className="mut">התיעוד המלא מתחיל מהריצה הראשונה של הצינור; היסטוריה מ-2022 תתווסף בהמשך ממאגר אופן באס.</span></div>
          )}
        </div>
      )}
      <footer>
        ניסוי במסגרת <a href="../">הקו הבוחן</a> · הנתונים: GTFS משרד התחבורה · קרדיט היסטורי עתידי: אופן באס, הסדנא לידע ציבורי
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
