/* הקו בזמן — היסטוריית מסלולים ותחנות מהשוואת GTFS יומית.
   הנתונים: line-history/data, נוצר ע"י tools/linehistory.py ב-GitHub Actions. */
const { useState, useEffect, useMemo, useRef } = React;
const BUILD = window.LH_BUILD || "0";

const KINDS = {
  baseline:    { label: "תיעוד ראשון", color: "#64748b" },
  snapshot:    { label: "צילום מהארכיון", color: "#94a3b8" },
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
  renamed:     { label: "שינוי שם תחנת קצה", color: "#d97706" },
  mode:        { label: "שינוי סוג הקו", color: "#0369a1" },
  removed:     { label: "בוטל", color: "#dc2626" },
  "removed-year": { label: "בוטל — מעל שנה לא חזר", color: "#7f1d1d" },
  freq:        { label: "שינוי מספר הרכבים באותה נסיעה", color: "#b45309" },
  sched:       { label: "שינוי לו\"ז", color: "#4338ca" },
  times:       { label: "הלו\"ז האחרון", color: "#0e7490" },
};
// הגדרת המשתמש: "שינוי מספר הרכבים" = רק תגבור (שני רכבים באותה דקה
// שהשתנו). כל שאר שינויי הכמות/שעות — תחת שינוי לו"ז.
function evKind(v) {
  if (v.k === "freq" && !/תגבור/.test(v.note || "")) return "sched";
  return v.k;
}

// ביטול שנשאר בתוקף מעל שנה (הגרסה האחרונה היא removed וישנה משנה) מקבל קטגוריה משלו
function dispKind(x, i, vs) {
  if (x.k === "removed" && i === vs.length - 1 && (Date.now() - new Date(x.d)) / 864e5 >= 365) return "removed-year";
  return evKind(x);
}
// אותו כלל ברמת האינדקס (lk/ld = הרשומה האחרונה של הווריאנט)
function isRemovedYear(l) {
  return l.lk === "removed" && (Date.now() - new Date(l.ld)) / 864e5 >= 365;
}
// קטגוריות הבחירה — מחולקות לקבוצות, בלי חפיפות: שלוש קטגוריות ביטול
// נפרדות (מעל שנה / פחות משנה / חזר), ותוויות שמסבירות את ההבדל.
// הקטגוריות אוחדו איפה שההפרדה הייתה שלנו ולא של העולם:
// · "מעל שנה" ו"פחות משנה" הן אותו דבר — קו מבוטל. משך הזמן כתוב בתאריך,
//   ואין סיבה לחייב סימון שתי תיבות כדי לראות קווים מבוטלים.
// · הארכה/קיצור/שינוי קצה הופרדו לפי סף שרירותי של שלוש תחנות: קו שקיבל
//   שתיים בקצה נפל לקטגוריה אחת ואחד שקיבל שלוש לאחרת. שלושתן "הקצה זז",
//   וההבחנה נשארת כתובה בתוך האירוע.
// · "תיקון שרטוט" הוא הקטגוריה הגדולה ביותר ואין בה שינוי לנוסע — משרד
//   התחבורה צייר מחדש בלי שאף תחנה זזה. הוצאה לקבוצה טכנית נפרדת.
// שלוש קטגוריות התחנות נשארו: ההבדל בין תחנה שנוספה לתחנה שירדה הוא
// בדיוק מה שמחפשים, ואיחודן היה חוסך שורה ועולה במידע.
const CAT_GROUPS = [
  { title: "ביטולים", items: ["removed-year", "removed-now", "removed-past"] },
  { title: "שינויי מסלול", items: ["route", "endpoint"] },
  { title: "שינויי תחנות", items: ["stops", "stops-add", "stops-del"] },
  { title: "תדירות ולוח זמנים", items: ["freq", "sched"] },
  { title: "רישום ופרטים", items: ["new", "operator", "dest", "renum", "mode"] },
  { title: "שינויים טכניים", items: ["redraw"] },
];
const CAT_LABELS = {
  "removed-year": "מבוטל — מעל שנה לא חזר",
  "removed-now": "מבוטל כרגע — פחות משנה",
  "removed-past": "בוטל בעבר וחזר לפעול",
  route: "שינוי מסלול (ציור וגם תחנות)",
  endpoint: "שינוי קצה הקו (הארכה, קיצור או החלפת קצה)",
  redraw: "תיקון שרטוט — התחנות לא השתנו",
  stops: "הוחלפו תחנות (נוספו וגם ירדו)",
  "stops-add": "רק נוספו תחנות",
  "stops-del": "רק ירדו תחנות",
  new: "וריאנט חדש ברישום",
  operator: "החלפת מפעיל",
  dest: "שינוי יעד",
  renum: "שינוי מספר קו",
  mode: "שינוי סוג הקו (למשל רגיל ↔ לפי דרישה)",
  freq: "שינוי מספר הרכבים באותה נסיעה (תגבור)",
  sched: "שינוי שעות היציאה (לו\"ז)",
};
const CAT_COLORS = { "removed-now": "#dc2626", "removed-past": "#f59e0b",
                     endpoint: "#c026d3" };
function catColor(k) { return CAT_COLORS[k] || (KINDS[k] || {}).color || "#64748b"; }
const ENDPOINT_KINDS = ["extend", "shorten", "terminal"];
// שלוש קטגוריות הביטול זרות זו לזו: קו שלא חזר מעל שנה הוא מבוטל בפועל,
// ואילו ביטול טרי עוד עשוי להתברר כהפסקה. ההבחנה נשארה לבקשת המשתמש.
function catMatch(l, k) {
  if (k === "removed-year") return isRemovedYear(l);
  if (k === "removed-now") return l.lk === "removed" && !isRemovedYear(l);
  if (k === "removed-past") return l.lk !== "removed" && (l.ks || []).includes("removed");
  if (k === "endpoint") return ENDPOINT_KINDS.some((x) => (l.ks || []).includes(x));
  return (l.ks || []).includes(k);
}
const REMOVAL_CATS = new Set(["removed-year", "removed-now", "removed-past"]);
const SKINDS = {
  new:     { label: "חדשה", color: "#16a34a" },
  del:     { label: "בוטלה", color: "#dc2626" },
  renamed: { label: "שינוי שם", color: "#d97706" },
  moved:   { label: "הזזת מיקום", color: "#2563eb" },
};

// פענוח polyline (precision 5)
// פורמט קובץ דחוס (חיסכון ~30MB, בקשת המשתמש): תחנות ומסלולים נשמרים
// פעם אחת במאגרי pool/spool והגרסאות מפנות באינדקס; כאן פותחים חזרה
// לצורה המלאה — שאר הקוד לא יודע שהקובץ היה דחוס. תאום-לאחור לקבצים ישנים.
function materializeLf(lf) {
  if (!lf) return lf;
  const pool = lf.pool, spool = lf.spool;
  (lf.versions || []).forEach((v) => {
    if (pool && Array.isArray(v.stops) && v.stops.length && typeof v.stops[0] === "number")
      v.stops = v.stops.map((i) => pool[i]);
    if (typeof v.shp === "number") v.shp = (spool && v.shp > 0 && spool[v.shp]) || "";
  });
  delete lf.pool; delete lf.spool;
  return lf;
}

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
function fmtM(d) { const p = (d || "").split("-"); return p[1] + "." + p[0]; }
function gapDays(a, b) { return Math.round((new Date(b) - new Date(a)) / 864e5); }

// דיוק התאריך נקבע לפי המרווח בין שני צילומי הארכיון שביניהם אותר השינוי.
// בארכיון של 2020 הצילומים יומיים והתאריך מדויק; ב-2017 הם במרחק שבועיים,
// ואז יום מדויק הוא המצאה — במקרה כזה נכתב החודש בלבד. (בקשת המשתמש.)
function evDate(v) {
  const sd = v.sd || (/(\d{4}-\d{2}-\d{2}) ל-(\d{4}-\d{2}-\d{2})/.exec(v.note || "") || [])[1];
  if (!sd || sd === v.d) return { txt: fmtD(v.d), exact: true };
  const g = gapDays(sd, v.d);
  // עד שלושה ימים התאריך נשאר: הוא נכון עד יום-יומיים, וסימון של עשרות
  // אלפי אירועים כ"לא ידוע" בגלל זה היה הופך את הציר לבלתי קריא בלי
  // להוסיף אמת. מעבר לזה היום הוא ניחוש, ואז נכתב החודש בלבד.
  if (g <= 3) return { txt: fmtD(v.d), exact: true,
                       tip: `אותר בין ${fmtD(sd)} ל-${fmtD(v.d)}` };
  if (fmtM(sd) === fmtM(v.d)) return { txt: fmtM(v.d), exact: false, tip: `אותר בין ${fmtD(sd)} ל-${fmtD(v.d)} — ${g} ימים בין צילומי הארכיון, ולכן היום המדויק אינו ידוע` };
  return { txt: `${fmtM(sd)}–${fmtM(v.d)}`, exact: false, tip: `אותר בין ${fmtD(sd)} ל-${fmtD(v.d)} — ${g} ימים בין צילומי הארכיון, ולכן היום המדויק אינו ידוע` };
}
function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }

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
/* טבלת "לפני / אחרי" ללוח היציאות — לאירועי תדירות/לו"ז שנשמרו עם
   הרשימות המלאות (tl/tn). ריבוי באותה שעה = תגבור, ומוצג כמונה. */
function TimesDiff({ tl, tn }) {
  const [open, setOpen] = useState(true);   // נפתחת מיד עם הלחיצה על האירוע
  const rows = useMemo(() => {
    const cnt = (s) => {
      const c = new Map();
      (s ? s.split(",") : []).forEach((t) => c.set(t, (c.get(t) || 0) + 1));
      return c;
    };
    const a = cnt(tl), b = cnt(tn);
    const times = [...new Set([...a.keys(), ...b.keys()])].sort();
    const out = [], oldOnly = [], newOnly = [];
    times.forEach((t) => {
      const x = a.get(t) || 0, y = b.get(t) || 0;
      if (x > 0 && y > 0) {
        if (x === y) out.push({ key: t, before: x > 1 ? `${t} (${x}×)` : t, cls: "same" });
        else out.push({ key: t, before: `${t} (${x}×)`, after: `${t} (${y}×)`, cls: "changed" });
      } else if (x > 0) oldOnly.push(t);
      else newOnly.push(t);
    });
    // התאמת יציאות שזזו: שעה שירדה מול שעה קרובה שנוספה (עד 20 דק' הפרש)
    const mins = (t) => +t.slice(0, 2) * 60 + +t.slice(3, 5);
    let i = 0, j = 0;
    while (i < oldOnly.length || j < newOnly.length) {
      const o = oldOnly[i], n = newOnly[j];
      if (o != null && n != null && Math.abs(mins(o) - mins(n)) <= 20) {
        out.push({ key: o + n, before: o, after: n, cls: "moved" }); i++; j++;
      } else if (o != null && (n == null || o < n)) {
        out.push({ key: o + "-", before: o, after: "—", cls: "removed" }); i++;
      } else {
        out.push({ key: "-" + n, before: "—", after: n, cls: "added" }); j++;
      }
    }
    out.sort((r, s) => (r.before !== "—" ? r.before : r.after).localeCompare(s.before !== "—" ? s.before : s.after));
    return out;
  }, [tl, tn]);
  const nOld = tl ? tl.split(",").length : 0, nNew = tn ? tn.split(",").length : 0;
  const changed = rows.filter((r) => r.cls !== "same").length;
  return (
    <div className="tdiff">
      <button className="tdiff-btn" onClick={() => setOpen(!open)}
        title="כל היציאות שורה-שורה: השעה לפני מול השעה אחרי; שעה שלא השתנתה מוצגת פעם אחת">
        📊 {open ? "הסתר את" : "הצג את"} טבלת הלפני/אחרי המלאה ({nOld} ← {nNew} יציאות · {changed} השתנו)
      </button>
      {open && (
        <div className="tdiff-wrap">
          <table className="tdiff-tbl">
            <thead><tr><th>לפני</th><th>אחרי</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={"td-" + r.cls}>
                  {r.cls === "same"
                    ? <td className="num" colSpan={2}>{r.before}</td>
                    : <><td className="num">{r.before}</td><td className="num">{r.after}</td></>}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="tdiff-leg">שורה ממוזגת = היציאה לא השתנתה · כתום = היציאה זזה (השעה הישנה מול החדשה) או תגבור שהשתנה · אדום = יציאה שירדה · ירוק = יציאה שנוספה · 2× = שני אוטובוסים באותה שעה</div>
        </div>
      )}
    </div>
  );
}

function DiffMap({ cur, prev, approx, prevApprox, curStops, prevStops, addedCodes, stops12 }) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  // הקטעים ששונו + התחנות ששונו — היעד של מצב "התמקדות" (בקשת המשתמש:
  // בתיקון באג לראות רק את הקטע שהשתנה, לא את כל המסלול).
  // השוואת קטעים רק כששני הצדדים מדויקים — קו מקורב בין תחנות ייתן רעש
  const diff = useMemo(() => (prev && !approx && !prevApprox ? segDiff(cur, prev) : null), [cur, prev, approx, prevApprox]);
  const chStops = useMemo(() => {
    if (addedCodes && (curStops || []).length) {
      return (curStops || []).filter((s) => addedCodes.has(s[0])).map((s) => [s[2], s[3]]);
    }
    if (!prevStops) return [];
    const curCodes = new Set((curStops || []).map((s) => s[0]));
    const prevCodes = new Set((prevStops || []).map((s) => s[0]));
    return (curStops || []).filter((s) => !prevCodes.has(s[0])).map((s) => [s[2], s[3]])
      .concat((prevStops || []).filter((s) => !curCodes.has(s[0])).map((s) => [s[2], s[3]]));
  }, [curStops, prevStops, addedCodes]);
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
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>', maxZoom: 19,
    }).addTo(map);
    const focused = canFocus && focus;
    const pts12 = (stops12 || []).map((s) => [s[1], s[2]]);
    const all = focused ? focusPts : cur.concat(prev || []).concat(pts12);
    map.fitBounds(L.latLngBounds(all.length ? all : [[32.08, 34.78]]).pad(focused ? 0.35 : 0.1), { maxZoom: 16 });
    if (prev && prev.length > 1) {
      L.polyline(prev, { color: "#dc2626", weight: focused ? 3 : 4, opacity: focused ? 0.25 : 0.75, dashArray: "8 7" }).addTo(map);
    }
    if (cur.length > 1) {
      L.polyline(cur, approx
        ? { color: "#7c3aed", weight: 4, opacity: 0.8, dashArray: "7 9" }   // קו מקורב בין תחנות
        : { color: prev ? "#16a34a" : "#4c1d95", weight: focused ? 3 : 5, opacity: focused ? 0.3 : 0.9 }).addTo(map);
    }
    if (focused && diff) {
      diff.prevSegs.forEach((sg) => L.polyline(sg, { color: "#dc2626", weight: 6, opacity: 0.95, dashArray: "9 8" }).addTo(map));
      diff.curSegs.forEach((sg) => L.polyline(sg, { color: "#16a34a", weight: 7, opacity: 0.95 }).addTo(map));
    }
    // מסלול 2012 — קו חום מקווקו דרך התחנות שהוצלבו למק"ט (מיקום לפי המאגר של היום)
    if (pts12.length > 1) {
      L.polyline(pts12, { color: "#78350f", weight: 3, opacity: 0.75, dashArray: "3 7" }).addTo(map);
      stops12.forEach((s) => {
        L.circleMarker([s[1], s[2]], { radius: 4, color: "#78350f", weight: 2, fillColor: "#fff", fillOpacity: 1 })
          .addTo(map).bindPopup(`<b>${esc(s[0])}</b><br><span class="pst">מסלול 2012</span>`, { className: "lh-pop", offset: [0, -4] });
      });
    }
    const curCodes = new Set((curStops || []).map((s) => s[0]));
    const prevCodes = new Set((prevStops || []).map((s) => s[0]));
    // שם התחנה נפתח בחלון קופץ (popup) — הוא מוצמד לעוגן של התחנה והמפה
    // זזה אליו לבד, אז השם תמיד מוצג במקום הנכון גם בקצה המפה ובנייד.
    const popHtml = (s, status) =>
      `<b>${esc(s[1])}</b>${status ? `<br><span class="pst">${status}</span>` : ""}<br><span class="pcode">מק״ט תחנה ${esc(s[0])}</span>`;
    (curStops || []).forEach((s) => {
      // הגרסה הקודמת עשויה להיות שינוי תדירות בלי רצף תחנות, ואז אין מול מה
      // להשוות. רשימת התחנות שנוספו כבר חושבה בצנרת ונשמרה על הגרסה — היא
      // המקור האמין לסימון, ולא השוואה מול גרסה שאין בה גאומטריה.
      const isNew = addedCodes ? addedCodes.has(s[0]) : (prevStops && !prevCodes.has(s[0]));
      const m = L.circleMarker([s[2], s[3]], {
        radius: isNew ? 8 : 5, color: isNew ? "#fff" : "#4c1d95", weight: 2,
        fillColor: isNew ? "#16a34a" : "#fff", fillOpacity: 1, opacity: focused && !isNew ? 0.4 : 1,
      }).addTo(map)
        .bindPopup(popHtml(s, isNew ? "🟢 תחנה שנוספה בגרסה זו" : ""), { className: "lh-pop", offset: [0, -4] });
      // שם התחנה מוצג רק בלחיצה (popup צמוד לתחנה) — תוויות ריחוף בוטלו
      // לגמרי: הן נתקעו פתוחות והציגו שם כפול/ישן במקום אחר על המפה
    });
    (prevStops || []).forEach((s) => {
      if (curCodes.has(s[0])) return;
      const m = L.circleMarker([s[2], s[3]], { radius: 8, color: "#dc2626", weight: 3, fillColor: "#fff", fillOpacity: 1 })
        .addTo(map)
        .bindPopup(popHtml(s, "🔴 תחנה שירדה מהקו בגרסה זו"), { className: "lh-pop", offset: [0, -4] });
    });
    return () => { mapRef.current = null; map.remove(); };
  }, [cur, prev, curStops, prevStops, addedCodes, focus, diff, chStops, focusPts, canFocus, stops12]);
  return (
    <div className="mapwrap">
      <div className="map" ref={ref} />
      {canFocus && (
        <button className="focusbtn" title="החלפה בין תצוגת כל המסלול לבין התקרבות רק לקטע שבו היה השינוי" onClick={() => setFocus(!focus)}>
          {focus ? "🗺️ כל המסלול" : "🔍 רק הקטע ששונה"}
        </button>
      )}
    </div>
  );
}

/* שורת קו כקישור אמיתי: קליק רגיל נשאר בתוך האפליקציה, Ctrl/קליק־אמצעי
   פותחים את דף הקו בכרטיסייה חדשה (לכל קו יש כתובת משלו אחרי ה-#) */
const lineHref = (r) => "#" + encodeURIComponent(r);
const plainClick = (e) => !(e.ctrlKey || e.metaKey || e.shiftKey || e.altKey);

/* חיפוש שנשמר בין ניווטים: חזרה מעמוד קו לא מוחקת את מה שהוקלד */
function usePersistedQ(key) {
  const [q, setQ] = useState(() => { try { return sessionStorage.getItem(key) || ""; } catch (e) { return ""; } });
  useEffect(() => { try { sessionStorage.setItem(key, q); } catch (e) { /* דפדפן חוסם אחסון */ } }, [key, q]);
  return [q, setQ];
}

/* עוגן 2012: rd -> תקציר המסלול דאז (נטען פעם אחת לכל הדפדוף) */
let ANC2012 = null;
let ANC_SET = new Set();   // המק"טים שהוצלבו — לסינון "2012" בחיפוש
const getAnchors2012 = () =>
  ANC2012 || (ANC2012 = fetch("data/anchor-2012.json?v=" + BUILD)
    .then((r) => (r.ok ? r.json() : { anchors: {} }))
    .then((d) => { ANC_SET = new Set(Object.keys(d.anchors || {})); return d; })
    .catch(() => ({ anchors: {} })));

/* ---------- עמוד קו ---------- */
function LinePage({ rd, lineGone, sibs, onSwitch, onBack }) {
  const [lf, setLf] = useState(null);
  const [err, setErr] = useState(null);
  const [sel, setSel] = useState(null);   // אינדקס גרסה נבחרת
  const [mon, setMon] = useState("");
  const [offK, setOffK] = useState(() => new Set());   // קטגוריות שכובו בעמוד הקו
  const [cmpI, setCmpI] = useState(null);              // גרסת בסיס להשוואה חופשית
  const [onlyCur, setOnlyCur] = useState(false);       // מפה בלי שכבת העבר
  const [anc, setAnc] = useState(null);   // עוגן 2012 לוריאנט הזה, אם הוצלב
  const [show12, setShow12] = useState(false);
  const [d12, setD12] = useState(null);   // קובץ הקו של 2012 (נטען בפתיחה)
  const [r12, setR12] = useState(0);      // וריאנט 2012 נבחר
  useEffect(() => {
    let ok = true;
    setAnc(null); setShow12(false); setD12(null); setR12(0);
    getAnchors2012().then((d) => { if (ok) setAnc((d.anchors || {})[rd] || null); });
    return () => { ok = false; };
  }, [rd]);
  useEffect(() => {
    if (!show12 || d12 || !anc) return;
    fetch("../magihim-2012/data/l" + anc.k + ".json?v=" + BUILD)
      .then((r) => r.json())
      .then((d) => {
        // בחירת וריאנט 2012 שתואם את כיוון הווריאנט הפתוח — לפי דמיון
        // תחנות הקצה (ולא סתם הווריאנט הראשון בקובץ)
        const routes = d.routes || [];
        const cur = ((lf || {}).versions || []).slice(-1)[0] || {};
        const st = cur.stops || [];
        let best = 0;
        if (st.length && routes.length > 1) {
          const tok = (x) => new Set(String(x || "").split(/[^א-ת0-9]+/).filter((w) => w.length >= 3));
          const f0 = tok(st[0][1]), l0 = tok(st[st.length - 1][1]);
          let bs = -1;
          routes.forEach((r, i) => {
            const sc = [...tok(r.f)].filter((w) => f0.has(w)).length * 2 +
              [...tok(r.l)].filter((w) => l0.has(w)).length * 2 + (r.n || 0) / 1000;
            if (sc > bs) { bs = sc; best = i; }
          });
        }
        setR12(best);
        setD12(d);
      })
      .catch(() => setD12({ routes: [] }));
  }, [show12, anc, d12, lf]);
  useEffect(() => {
    setLf(null); setErr(null); setSel(null); setMon(""); setOffK(new Set()); setCmpI(null); setOnlyCur(false);
    fetch("data/lines/" + fsafe(rd) + ".json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => { setLf(materializeLf(d)); setSel(d.versions.length - 1); })
      .catch(setErr);
  }, [rd]);
  if (err) return <div className="card"><button className="back" onClick={onBack}>→ חזרה</button><div className="empty">לא נמצאו נתונים לוריאנט הזה.</div></div>;
  if (!lf) return <div className="card">טוען…</div>;
  const vs = lf.versions;
  const months = [...new Set(vs.map((v) => v.d.slice(0, 7)))].reverse();
  const shown = vs.map((v, i) => ({ v, i }))
    .filter((x) => (!mon || x.v.d.slice(0, 7) === mon) && !offK.has(dispKind(x.v, x.i, vs))).reverse();
  // הקטגוריות שקיימות בקו הזה בפועל, לפי שכיחות — סרגל כיבוי/הדלקה
  const kindsHere = (() => {
    // התווית שעל האירוע נגזרת מ-dispKind ולא מ-k הגולמי; סינון לפי k היה
    // יוצר אי-התאמה — כפתור "שינוי מספר הרכבים" שמשאיר אירועים מתויגים
    // "שינוי לו״ז". הסינון והתוויות חייבים לדבר באותה שפה.
    const c = new Map();
    vs.forEach((x, i) => { const dk = dispKind(x, i, vs); c.set(dk, (c.get(dk) || 0) + 1); });
    return [...c.entries()].sort((a, b) => b[1] - a[1]);
  })();
  const toggleK = (k) => setOffK((prev) => {
    const n = new Set(prev);
    n.has(k) ? n.delete(k) : n.add(k);
    return n;
  });
  // מס' תחנה לרשימות ➕/➖: בהוספה מחפשים בגרסה עצמה, בהורדה בגרסאות שלפניה
  const codeOf = (name, i, isAdd) => {
    const scan = (l) => { const h = (l || []).find((s) => s && s[1] === name); return h ? h[0] : null; };
    if (isAdd) { const c = scan(vs[i].stops); if (c) return c; }
    for (let j = i - (isAdd ? 0 : 1); j >= 0; j--) { const c = scan(vs[j].stops); if (c) return c; }
    for (let j = i + 1; j < vs.length; j++) { const c = scan(vs[j].stops); if (c) return c; }
    return null;
  };
  const withCode = (name, i, isAdd) => { const c = codeOf(name, i, isAdd); return c ? `${name} (${c})` : name; };
  const v = vs[sel] || vs[vs.length - 1];
  // ברירת המחדל היא הגרסה הקודמת הסמוכה; במצב השוואה חופשית המשתמש בוחר
  // גרסת בסיס אחרת וכל ההפרש — הרשימה, המפה והמסלול — נמדד מולה.
  const vi = vs.indexOf(v);
  const cmpOn = cmpI != null && cmpI !== vi && cmpI >= 0 && cmpI < vs.length;
  const pi = cmpOn ? cmpI : vi - 1;
  const pv = pi >= 0 ? vs[pi] : null;
  // הפרש התחנות מחושב מהרשימות עצמן — במצב השוואה אי אפשר להסתמך על
  // add/rem ששמורים על הגרסה, כי הם נמדדו מול הגרסה הקודמת ולא מול הבסיס.
  const stopsAt = (idx, dir) => {
    for (let j = idx; dir < 0 ? j >= 0 : j < vs.length; j += dir) {
      if ((vs[j].stops || []).length) return vs[j].stops;
    }
    return null;
  };
  const cmpDiff = (() => {
    if (!cmpOn) return null;
    const a = stopsAt(pi, -1), b = stopsAt(vi, -1);
    if (!a || !b) return null;
    const ac = new Set(a.map((x) => x[0])), bc = new Set(b.map((x) => x[0]));
    return {
      add: b.filter((x) => !ac.has(x[0])),
      rem: a.filter((x) => !bc.has(x[0])),
      from: vs[pi].d, to: vs[vi].d,
    };
  })();
  // גרסת ארכיון בלי גאומטריה אך עם רצף תחנות (שלב ב') — קו מקורב בין התחנות.
  const toPts = (x) => (x.shp ? decodeShape(x.shp) : ((x.stops || []).length > 1 ? x.stops.map((s) => [s[2], s[3]]) : null));
  const approx = !v.shp && (v.stops || []).length > 1;
  // במצב השוואה מעניין מצב הקו בשני התאריכים, לא האירוע עצמו: אירוע לו"ז
  // אינו נושא גאומטריה, ובלי זה המפה לא הייתה נפתחת כלל בהשוואה.
  const geoAt = (idx) => {
    for (let j = idx; j >= 0; j--) if ((vs[j].stops || []).length || vs[j].shp) return vs[j];
    return null;
  };
  const gv = cmpOn ? (geoAt(vi) || v) : v;
  const cur = toPts(gv) || [];
  // המסלול הקודם מוצג רק כשיש באמת מה להשוות: הגרסה מתעדת שינוי תחנות
  // (כולל הפרש-פער מול "תיעוד ראשון") או שינוי מסלול, או ששתי הגרסאות
  // מדויקות. בלי זה, קירוב-לפי-תחנות מול גאומטריה מלאה מצייר "מסלול ישן"
  // אדום שנראה כמו שינוי אמיתי כשהמסלול בכלל לא השתנה (בקשת שלמה).
  const ROUTE_KINDS = new Set(["route", "redraw", "extend", "shorten", "terminal", "stops", "stops-add", "stops-del"]);
  const comparable = !!pv && (!!(v.add || v.rem) || ROUTE_KINDS.has(v.k) || !!(v.shp && pv.shp));
  const pgv = cmpOn ? (geoAt(pi) || pv) : pv;
  const prev = comparable ? toPts(pgv) : null;
  const prevApprox = !!(pgv && prev && !pgv.shp);
  // קובץ 2012 מקבץ את כל הווריאנטים הארציים של המספר — מציגים רק את
  // הרלוונטיים לקו הפתוח (חפיפת מילים עם התחנות/היעד), עם אפשרות לחשוף הכל
  const rel12 = (() => {
    const routes = (d12 && d12.routes) || [];
    if (routes.length <= 1) return routes.map((_, i) => i);
    // התאמת עיר: וריאנט 2012 רלוונטי רק אם עיר של תחנת קצה שלו ("שם - עיר")
    // מופיעה ביעד או בתחנות של הקו הפתוח. מילים גנריות ("תחנה מרכזית",
    // "הרצל") הטעו את הסינון הקודם והכניסו וריאנטים מערים אחרות.
    const hay = String(lf.dest || "") + " " +
      ((vs[vs.length - 1] || {}).stops || []).map((s) => s[1]).join(" ");
    const cityOf = (x) => { const p = String(x || "").split(" - "); return p.length > 1 ? p[p.length - 1].trim() : null; };
    const passCity = (r) => { const a = cityOf(r.f), b = cityOf(r.l); return !!((a && hay.includes(a)) || (b && hay.includes(b))); };
    let rel = routes.map((r, i) => [r, i]).filter((x) => passCity(x[0])).map((x) => x[1]);
    if (!rel.length) {
      const GEN = new Set(["תחנה", "תחנת", "מרכזית", "רכבת", "צומת", "מסוף", "מרכז",
        "קניון", "שוק", "בית", "שדרות", "כביש", "כיכר", "ככר", "דרך", "רחוב"]);
      const tokset = new Set(hay.split(/[^א-ת0-9]+/).filter((w) => w.length >= 3 && !GEN.has(w)));
      const sc = (r) => String((r.f || "") + " " + (r.l || "")).split(/[^א-ת0-9]+/)
        .filter((w) => w.length >= 3 && tokset.has(w)).length;
      rel = routes.map((r, i) => [sc(r), i]).filter((x) => x[0] > 0).map((x) => x[1]);
    }
    return rel.length ? rel : routes.map((_, i) => i);
  })();
  const vis12 = rel12;
  const sel12 = vis12.includes(r12) ? r12 : (vis12[0] ?? 0);
  // מסלול 2012 למפה: רק כשהפאנל פתוח, ורק תחנות שהוצלבו (יש להן קואורדינטות)
  const stops12 = (show12 && d12 && (d12.routes || []).length)
    ? ((d12.routes[sel12] || d12.routes[0]).stops || []).filter((s) => s.length >= 7).map((s) => [s[1], s[5], s[6]])
    : null;
  return (
    <div className="linewrap">
      <div className="card side">
        <button className="back" title="חזרה למסך החיפוש — הטקסט שחיפשתם נשמר" onClick={onBack}>→ חזרה לחיפוש</button>
        {/* לקווי הרכבת אין מספר קו ב-GTFS — הסמל ממלא את מקומו כדי שהתג לא יופיע ריק */}
        <div className="linehead"><span className="badge">{lf.line || TT_ICON[lf.tt] || "—"}</span><span className="dest">{lf.dest}</span></div>
        <div className="facts">{lf.op}{lf.ty ? " · " + lf.ty : ""}{lf.tt ? " · " + (TT_LABEL[lf.tt] || "") : ""} · מק״ט {lf.rd} · {vs.length} גרסאות מתועדות</div>
        {/* רק "שירות לפי דרישה" מקבל הערה, כי היא נושאת מידע שאינו במקום
            אחר: הקו יושב בין קווי האוטובוס ונראה רגיל לחלוטין, ואי אפשר
            לדעת ממנו שהנסיעה מותנית בהזמנה. לשאר הסוגים התווית בשורת
            הפרטים כבר אומרת הכל, והערה נוספת היא רעש. */}
        {lf.tt === "demand" && (
          <div className="ttnote">
            🚐 <b>שירות לפי דרישה</b> — הקו אינו יוצא בשעה קבועה: הנסיעה מבוצעת לפי הזמנה מראש.
          </div>
        )}
        {anc && (
          <div className="a2012">
            <b>2012</b> · {anc.f} ← {anc.l} · {anc.n} תחנות
            <button className="a2012btn" title="הצגת רשימת התחנות של הקו כפי שהייתה ב-2012 — כולל המסלול על המפה בקו מקווקו חום" onClick={() => setShow12(!show12)}>
              {show12 ? "הסתר ▲" : "רצף התחנות ▼"}
            </button>
            {show12 && (d12 ? (d12.routes || []).length ? (
              <div>
                {vis12.length > 1 && (
                  <div className="s12chips">{vis12.map((i) => (
                    <button key={i} className={"rchip12" + (i === sel12 ? " on" : "")} title="מסלול 2012 נוסף של אותו קו — לחיצה מציגה אותו"
                      onClick={() => setR12(i)}>{d12.routes[i].f} ← {d12.routes[i].l} ({d12.routes[i].n})</button>
                  ))}</div>
                )}
                <ol className="s12">
                  {((d12.routes[sel12] || d12.routes[0]).stops || []).map((s) => (
                    <li key={s[0]}>{s[1]}{" "}
                      {s[4] && s[4].length === 1 ? <span className="pcode">מק״ט {s[4][0]}</span>
                        : s[4] && s[4].length > 1 ? <span className="pcode">{s[4].length} מק״טים אפשריים</span>
                          : <span className="pcode">לא הוצלבה</span>}
                    </li>
                  ))}
                </ol>
              </div>
            ) : <div className="mut">הנתונים לא נטענו — נסו לרענן.</div>
              : <div className="mut">טוען…</div>)}
          </div>
        )}
        {sibs && sibs.length > 1 && (
          <div className="sibs">
            <span className="sibt">חלופות וכיוונים:</span>
            {sibs.map((s) => {
              const alt0 = (x) => x.rd.split("-").slice(2).join("-");
              const dir0 = (x) => x.rd.split("-")[1] || "";
              const dir = dir0(s), alt = alt0(s);
              const isBase = alt === "" || alt === "#" || alt === "0";
              const dupDir = sibs.filter((x) => dir0(x) === dir).length > 1;
              const dupBase = dupDir && isBase && sibs.some((x) => x.rd !== s.rd && dir0(x) === dir && ["", "#", "0"].includes(alt0(x)));
              const lbl = "כיוון " + dir + (isBase
                ? (dupDir ? " · ראשית" + (dupBase ? " (" + (alt || "־") + ")" : "") : "")
                : " · חלופה " + alt);
              return (
                <a key={s.rd} className={"sib" + (s.rd === rd ? " on" : "")} title={s.dest}
                  href={lineHref(s.rd)}
                  onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); if (s.rd !== rd) onSwitch(s.rd); }}>
                  {lbl}
                  {s.lk === "removed" && <span className="sibx">✖</span>}
                </a>
              );
            })}
          </div>
        )}
        {vs.length > 0 && vs[vs.length - 1].k === "removed" && (
          <div className="facts" style={{ color: lineGone ? (KINDS[dispKind(vs[vs.length - 1], vs.length - 1, vs)] || {}).color : "#c2410c", fontWeight: 700 }}>
            {lineGone
              ? <>❌ הקו בוטל — אין חלופות פעילות — מאז {fmtD(vs[vs.length - 1].d)}</>
              : <>⚠️ החלופה הזו מבוטלת מאז {fmtD(vs[vs.length - 1].d)} (לקו יש חלופות פעילות)</>}
            {dispKind(vs[vs.length - 1], vs.length - 1, vs) === "removed-year" ? " — מעל שנה ולא חזרה" : ""}
          </div>
        )}
        {cmpOn && (
          <div className="cmpbar">
            <b>השוואה</b> · {String(vs[pi].d).split("-").reverse().join(".")} ← {String(v.d).split("-").reverse().join(".")}
            {cmpDiff && (
              <span className="cmpsum">
                {cmpDiff.add.length ? ` · ➕ ${cmpDiff.add.length} תחנות` : ""}
                {cmpDiff.rem.length ? ` · ➖ ${cmpDiff.rem.length} תחנות` : ""}
                {!cmpDiff.add.length && !cmpDiff.rem.length ? " · אותן תחנות בדיוק" : ""}
              </span>
            )}
            <button className="cmpx" title="סיום ההשוואה — חזרה להפרש מול הגרסה הקודמת" onClick={() => setCmpI(null)}>✕ סיום</button>
            {cmpDiff && (cmpDiff.add.length || cmpDiff.rem.length) ? (
              <div className="cmplist">
                {cmpDiff.add.length ? <div className="ad">➕ {cmpDiff.add.map((x) => `${x[1]} (${x[0]})`).join(", ")}</div> : null}
                {cmpDiff.rem.length ? <div className="rm">➖ {cmpDiff.rem.map((x) => `${x[1]} (${x[0]})`).join(", ")}</div> : null}
              </div>
            ) : null}
          </div>
        )}
        {kindsHere.length > 1 && (
          <div className="kfilter">
            <button className={"kchip" + (offK.size ? "" : " on")}
              title="הצגת כל סוגי השינויים בקו הזה" onClick={() => setOffK(new Set())}>הכול</button>
            {kindsHere.map(([k, n]) => (
              <button key={k} className={"kchip" + (offK.has(k) ? " off" : " on")}
                style={offK.has(k) ? null : { borderColor: catColor(k), color: catColor(k) }}
                title={offK.has(k) ? "הדלקה — האירועים האלה יחזרו לרשימה" : "כיבוי — האירועים האלה ייעלמו מהרשימה"}
                onClick={() => toggleK(k)}>
                {(KINDS[k] || {}).label || k} <b>{n}</b>
              </button>
            ))}
          </div>
        )}
        {months.length > 1 && (
          <div className="months">
            <button className={"mchip" + (!mon ? " on" : "")} title="כל התקופה — בלי סינון לחודש" onClick={() => setMon("")}>הכול</button>
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
              <div className="d">
                <span title={evDate(x).tip || ""} className={evDate(x).exact ? "" : "approxd"}>
                  {evDate(x).txt}{evDate(x).exact ? "" : " ≈"}</span>
                {(x.shp || (x.stops || []).length > 1) ? " · 🗺️" : ""}
                {(x.shp || (x.stops || []).length > 1) && (
                <button className={"cmpbtn" + (cmpI === i ? " on" : "")}
                  title={cmpI === i ? "זו גרסת הבסיס להשוואה — לחיצה מבטלת" : "קביעת הגרסה הזו כבסיס, ואז לחיצה על אירוע אחר תשווה מולה"}
                  onClick={(e) => {
                    e.stopPropagation();
                    if (cmpI === i) { setCmpI(null); return; }
                    setCmpI(i);
                    // לחיצה אחת מספיקה: אם האירוע הפתוח הוא הבסיס עצמו אין מה
                    // להשוות, ולכן נפתחת מולו הגרסה העדכנית ביותר.
                    if (vs.indexOf(v) === i) {
                      const last = vs.length - 1;
                      setSel(last === i ? Math.max(0, i - 1) : last);
                    }
                  }}>
                  {cmpI === i ? "⇄ בסיס ההשוואה" : "⇄ השווה"}</button>)}
              </div>
              <div className="t">
                <span className="k" style={{ background: (KINDS[dispKind(x, i, vs)] || {}).color || "#64748b" }}>{(KINDS[dispKind(x, i, vs)] || { label: x.k }).label}</span>
                {x.k === "redraw" && " הגאומטריה תוקנה — רצף התחנות לא השתנה"}
                {x.note && <span className="evnote"> {x.note}</span>}
              </div>
              {/* מאיפה האירוע הזה הגיע. ההערות אמרו "מארכיון הפיד הארצי"
                  בלי לנקוב בשם, ואי אפשר היה לדעת מה נמדד ומי מדד. */}
              <div className="evsrc">{SRC_LABEL[x.src] || SRC_LABEL._daily}</div>
              {(x.add || x.rem) && (
                <div className="sub">
                  {x.add && <div>➕ נוספו: {x.add.map((n) => withCode(n, i, true)).join(", ")}</div>}
                  {x.rem && <div>➖ ירדו: {x.rem.map((n) => withCode(n, i, false)).join(", ")}</div>}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="card main">
        <div className="vhead">
          {cmpOn ? <>השוואה שביקשת: <b>{evDate(v).txt}</b> מול <b>{evDate(pv).txt}</b></>
            : <>גרסת <b>{evDate(v).txt}</b>{prev ? <> מול הגרסה שלפניה (<b>{evDate(pv).txt}</b>)</> : pv ? "" : " — הגרסה המתועדת הראשונה"}</>}
        </div>
        {/* אי-הוודאות אינה בפער שבין שתי הגרסאות: המנוע עובר על כל צילומי
            הארכיון, ולכן פער ארוך בין גרסאות פירושו שהמסלול באמת לא השתנה
            לאורכו. אי-הוודאות היחידה היא המרווח בין שני צילומים סמוכים,
            וזה בדיוק מה ש-'sd' מודד. */}
        {!cmpOn && !evDate(v).exact && (
          <div className="gapwarn">
            🛈 היום המדויק אינו ידוע: {evDate(v).tip}.
          </div>
        )}
        {v.k === "times" && v.tb ? (
          /* הלו"ז האחרון של קו מבוטל — צילום מהארכיון (בקשת המשתמש): קו
             שבוטל בלי שום אירוע לו"ז מקבל, שנה אחרי הביטול, את שעות-היציאה
             שלו מיום-הארכיון האחרון שבו פעל */
          <div className="tsnap-wrap">
            <div className="mut">🛈 {v.note} — נכון ל-{fmtD(v.d)}, היום האחרון שבו הקו מופיע בארכיון.</div>
            <table className="tsnap"><tbody>
              {v.tb.map(([label, ts]) => (
                <tr key={label}>
                  <th>{label}</th>
                  <td>{ts.split(",").map((t, ti) => <span key={ti} className="tt">{t}</span>)}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        ) : !gv.shp && !((gv.stops || []).length > 1) ? (
          <div className="nogeo">
            🛈 {v.note || "אין פירוט לגרסה זו"}<br />
            <span className="mut">רשומת-עבר מארכיון אופן באס (הסדנא לידע ציבורי) — המסלול המדויק לא זמין לתקופה זו. רצף התחנות יושלם במילוי הלילי משלב ב׳.</span>
          </div>
        ) : (<>
        {/* ההשוואה עונה על "מה השתנה", אבל לא על "איך הקו נראה עכשיו" —
            שתי השכבות יחד מקשות לקרוא את המסלול עצמו. הכפתור מסיר את
            שכבת העבר ומשאיר את המסלול המלא כפי שהוא אחרי השינוי. */}
        {prev && (
          <div className="onlycur">
            <button className={"kchip" + (onlyCur ? "" : " on")}
              style={onlyCur ? {} : { borderColor: "#7c3aed", color: "#5b21b6" }}
              onClick={() => setOnlyCur(false)}>⇄ מה השתנה</button>
            <button className={"kchip" + (onlyCur ? " on" : "")}
              style={onlyCur ? { borderColor: "#7c3aed", color: "#5b21b6" } : {}}
              onClick={() => setOnlyCur(true)}>🚌 המסלול המלא אחרי השינוי</button>
          </div>
        )}
        <DiffMap key={v.d + v.k + (cmpOn ? "c" + cmpI : "") + (onlyCur ? "o" : "")}
          cur={cur} prev={onlyCur ? null : prev}
          approx={cmpOn ? !gv.shp : approx} prevApprox={prevApprox} curStops={gv.stops}
          prevStops={!onlyCur && pgv && (pgv.stops || []).length ? pgv.stops : null}
          addedCodes={!onlyCur && (!pv || !(pv.stops || []).length) && (v.add || []).length
            ? new Set((v.add || []).map((n, i) => codeOf(n, i, true)).filter(Boolean)) : null}
          stops12={onlyCur ? null : stops12} />
        <div className="legend">
          {prev && !onlyCur && <span><i style={{ borderColor: "#dc2626", borderStyle: "dashed" }} /> המסלול הקודם{prevApprox ? " (מקורב לפי תחנות)" : ""}</span>}
          <span><i style={{ borderColor: prev && !onlyCur ? "#16a34a" : "#4c1d95" }} /> {prev && !onlyCur ? "המסלול החדש" : "המסלול"}</span>
          <span><span className="dot" style={{ background: "#16a34a" }} /> תחנה שנוספה</span>
          <span><span className="dot" style={{ background: "#fff", border: "3px solid #dc2626" }} /> תחנה שירדה</span>
          {stops12 && stops12.length > 1 && <span><i style={{ borderColor: "#78350f", borderStyle: "dashed" }} /> מסלול 2012 (דרך התחנות שהוצלבו)</span>}
        </div>
        {v.shpref
          ? <div className="mut">🛈 רצף התחנות בצילום זהה לגרסה הסמוכה — מוצג המסלול המלא שלה במקום קו מקורב. {(v.stops || []).length} תחנות בגרסה זו.</div>
          : approx
          ? <div className="mut">🛈 מסלול מקורב — קו ישר בין התחנות לפי רצף מארכיון אופן באס; הגאומטריה המלאה לא זמינה לתקופה זו. {(v.stops || []).length} תחנות בגרסה זו.</div>
          : <div className="mut">🔍 הגאומטריה נשמרת במלואה, בלי דילול — גם תיקון שרטוט של כמה מטרים ייראה כאן. {(v.stops || []).length} תחנות בגרסה זו.</div>}
        </>)}
        {(v.tl || v.tn) && <TimesDiff tl={v.tl} tn={v.tn} />}
      </div>
    </div>
  );
}

/* ---------- מפת אירוע תחנה: מיקום ישן מול חדש ---------- */
function StopEvMap({ ev }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current) return;
    const map = L.map(ref.current, { scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>', maxZoom: 19,
    }).addTo(map);
    const pts = [[ev.la, ev.lo]];
    if (ev.k === "moved" && ev.ola != null) {
      pts.push([ev.ola, ev.olo]);
      L.polyline([[ev.ola, ev.olo], [ev.la, ev.lo]], { color: "#2563eb", weight: 3, dashArray: "5 7", opacity: 0.9 }).addTo(map);
      L.circleMarker([ev.ola, ev.olo], { radius: 9, color: "#dc2626", weight: 3, fillColor: "#fff", fillOpacity: 1 })
        .addTo(map).bindPopup(`<b>המיקום הישן</b><br><span class="pcode">(${ev.ola}, ${ev.olo})</span>`, { className: "lh-pop" });
    }
    L.circleMarker([ev.la, ev.lo], { radius: 9, color: "#fff", weight: 2,
      fillColor: ev.k === "moved" ? "#16a34a" : ((SKINDS[ev.k] || {}).color || "#2563eb"), fillOpacity: 1 })
      .addTo(map).bindPopup(`<b>${esc(ev.n || ev.nn || "")}</b>${ev.k === "moved" ? "<br>המיקום החדש" : ""}<br><span class="pcode">(${ev.la}, ${ev.lo})</span>`, { className: "lh-pop" });
    map.fitBounds(L.latLngBounds(pts).pad(0.6), { maxZoom: 17 });
    return () => map.remove();
  }, [ev]);
  return <div className="smap" ref={ref} />;
}

/* ---------- שינויים לפי יום (כל הקווים) ---------- */
function DayFeed({ idx, openLine, onBack, init12 }) {
  const [months, setMonths] = useState(null);
  const [yr, setYr] = useState("");
  const [mon, setMon] = useState("");
  const [chs, setChs] = useState(null);
  const [q, setQ] = usePersistedQ("lh-q-day");
  const [lim, setLim] = useState(300);
  useEffect(() => setLim(300), [q, mon]);
  // יעד ומפעיל לא משוכפלים בקובצי החודש — נשלפים מהאינדקס לפי מק"ט
  const meta = useMemo(() => { const m = {}; ((idx && idx.lines) || []).forEach((l) => { m[l.rd] = l; }); return m; }, [idx]);
  // לשונית 2012: כל קווי הצילום — המקושרים נפתחים בעמוד הקו של היום,
  // והשאר (בוטלו / שונו ללא היכר) נפתחים במקום עם רצף התחנות
  const [a12, setA12] = useState(null);
  const [idx12, setIdx12] = useState(null);
  const [exp12, setExp12] = useState(null);   // k של שורה לא-מקושרת פתוחה
  const [expd, setExpd] = useState(null);     // הנתונים שנטענו לשורה הפתוחה
  useEffect(() => { getAnchors2012().then((d) => setA12(d.anchors || {})); }, []);
  useEffect(() => {
    fetch("../magihim-2012/data/index.json?v=" + BUILD)
      .then((r) => (r.ok ? r.json() : { lines: [] }))
      .then(setIdx12).catch(() => setIdx12({ lines: [] }));
  }, []);
  useEffect(() => {
    if (!exp12) return;
    setExpd(null);
    fetch("../magihim-2012/data/l" + exp12 + ".json?v=" + BUILD)
      .then((r) => r.json()).then(setExpd).catch(() => setExpd({ routes: [] }));
  }, [exp12]);
  // כניסה מכתובת ‎#2012/<k>‎ (כרטיסייה חדשה): פותחים את הפיד על 2012
  // עם הקו המבוקש פתוח, ומגדילים את הרשימה כדי שהשורה תופיע
  useEffect(() => {
    if (!init12) return;
    setYr("2012"); setMon(""); setExp12(init12); setLim(100000);
  }, [init12]);
  const k2rd = useMemo(() => {
    const m = {};
    for (const [rd, v] of Object.entries(a12 || {})) if (!(v.k in m)) m[v.k] = rd;
    return m;
  }, [a12]);
  const rows12 = useMemo(() =>
    (((idx12 && idx12.lines) || []).map((l) => ({ ...l, rd: k2rd[l.k] || null }))),
  [idx12, k2rd]);
  useEffect(() => {
    fetch("data/months.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => r.json())
      .then((d) => {
        const ms = d.months || []; setMonths(ms);
        // לא דורסים בחירה שכבר נעשתה — כניסה מכתובת ‎#2012/<k>‎ קובעת
        // את השנה לפני שהחודשים נטענים
        if (ms.length) { setYr((cur) => cur || ms[0].slice(0, 4)); if (!init12) setMon((cur) => cur || ms[0]); }
      })
      .catch(() => setMonths([]));
  }, []);
  useEffect(() => {
    if (!mon) return;
    setChs(null);
    fetch("data/changes/" + mon + ".json?v=" + BUILD)
      .then((r) => (r.ok ? r.json() : { changes: [] }))
      .then((d) => setChs(d.changes || []))
      .catch(() => setChs([]));
  }, [mon]);
  if (months === null) return <div className="card">טוען…</div>;
  const needle = q.trim();
  const list = (chs || []).filter((c) => { const m = meta[c.rd] || {}; return !needle || c.line.includes(needle) || (m.dest || "").includes(needle) || (m.op || "").includes(needle) || c.rd.includes(needle); });
  const days = []; const byd = new Map();
  for (const c of list) { let g = byd.get(c.d); if (!g) { g = []; byd.set(c.d, g); days.push(c.d); } g.push(c); }
  days.sort().reverse();
  const WD = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];
  let shown = 0;
  return (
    <div className="card">
      <button className="back" title="חזרה למסך החיפוש הראשי — הטקסט שחיפשתם נשמר" onClick={onBack}>→ חזרה לחיפוש הקווים</button>
      <div className="months">
        {/* מהחדשה לישנה, כמו החודשים בתוך כל שנה. 2012 אינה מגיעה
            מ-months.json אלא מצילום נפרד, ולכן היא נכתבת בנפרד — ובסדר
            יורד מקומה הנכון הוא בסוף, כשנה הישנה מכולן. */}
        {[...new Set(months.map((m) => m.slice(0, 4)))].sort().reverse().map((y) => (
          <button key={y} className={"mchip" + (yr === y ? " on" : "")}
            title={"הצגת השינויים של שנת " + y} onClick={() => { setYr(y); const ms = months.filter((m) => m.startsWith(y)); if (!ms.includes(mon)) setMon(ms[ms.length - 1]); }}>{y}</button>
        ))}
        <button className={"mchip" + (yr === "2012" ? " on" : "")} title="רשת הקווים המלאה כפי שצולמה ב-2012 — 3,214 קווים מאתר מגיעים"
          onClick={() => { setYr("2012"); setMon(""); }}>2012</button>
      </div>
      {yr && yr !== "2012" && (
        <div className="months">
          {months.filter((m) => m.startsWith(yr)).slice().reverse().map((m) => (
            <button key={m} className={"mchip" + (mon === m ? " on" : "")} title="הצגת השינויים של החודש הזה בלבד" onClick={() => setMon(m)}>{m.split("-").reverse().join(".")}</button>
          ))}
        </div>
      )}
      <input className="search" type="search" placeholder="סינון: מספר קו, יעד, מפעיל או מק״ט…" value={q} onChange={(e) => setQ(e.target.value)} />
      {yr === "2012" ? (() => {
        if (!a12 || !idx12) return "טוען…";
        const list12 = rows12.filter((v) =>
          !needle || String(v.no).includes(needle) || (v.dest || "").includes(needle) || (v.an || "").includes(needle));
        if (!list12.length) return <div className="empty">אין קווי 2012 תואמים.</div>;
        const linked = list12.filter((v) => v.rd).length;
        return (
          <div>
            <div className="dayhead">צילום מצב 2012 · {list12.length.toLocaleString()} קווים ·
              {" "}{linked.toLocaleString()} מקושרים לקווים של היום</div>
            {list12.slice(0, lim).map((v) => (
              <React.Fragment key={v.k}>
                {v.rd ? (
                  <a className="lrow" href={lineHref(v.rd)}
                    onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); openLine(v.rd); }}>
                    <span className="badge sm">{v.no}</span>
                    <span className="k" style={{ background: "#78350f" }}>2012</span>
                    <span className="ldest">{v.dest || "—"}</span>
                    <span className="lmeta">{v.an} · {v.nr} מסלולים</span>
                  </a>
                ) : (
                  <a className="lrow" href={"#2012/" + encodeURIComponent(v.k)}
                    onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); setExp12(exp12 === v.k ? null : v.k); }}>
                    <span className="badge sm">{v.no}</span>
                    <span className="k" style={{ background: "#57534e" }}>לא קיים היום</span>
                    <span className="ldest">{v.dest || "—"}</span>
                    <span className="lmeta">{v.an} · {v.nr} מסלולים · {exp12 === v.k ? "סגור ▲" : "רצף התחנות ▼"}</span>
                  </a>
                )}
                {exp12 === v.k && !v.rd && (
                  <div className="a2012">
                    {expd ? ((expd.routes || []).length ? (
                      <ol className="s12">
                        {(expd.routes[0].stops || []).map((s) => (
                          <li key={s[0]}>{s[1]}{" "}
                            {s[4] && s[4].length === 1 ? <span className="pcode">מק״ט {s[4][0]}</span> : null}</li>
                        ))}
                      </ol>
                    ) : <div className="mut">הנתונים לא נטענו.</div>) : <div className="mut">טוען…</div>}
                  </div>
                )}
              </React.Fragment>
            ))}
            {list12.length > lim && (
              <button className="morebtn" onClick={() => setLim(lim + 500)}>
                ⌄ הצג עוד — מוצגים {Math.min(lim, list12.length).toLocaleString()} מתוך {list12.length.toLocaleString()}
              </button>
            )}
            <div className="katnote">🛈 "לא קיים היום" — לא נמצא לקו הזה קו תואם ברשת הנוכחית: בוטל,
              או ששונה עד ללא היכר. לחיצה על השורה פותחת את רצף התחנות שלו מ-2012.</div>
          </div>
        );
      })() : chs === null ? "טוען…" : days.length === 0 ? <div className="empty">אין שינויים תואמים בחודש הזה.</div> : (
        <div>
          {days.map((d) => shown >= lim ? null : (
            <React.Fragment key={d}>
              <div className="dayhead">{fmtD(d)} · יום {WD[new Date(d).getDay()]} · {byd.get(d).length.toLocaleString()} שינויים</div>
              {byd.get(d).map((c, i) => {
                if (shown >= lim) return null;
                shown++;
                const m = meta[c.rd] || {};
                return (
                  <a key={c.rd + c.k + i} className="lrow" href={lineHref(c.rd)}
                    onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); openLine(c.rd); }}>
                    <span className="badge sm">{c.line}</span>
                    <span className="k" style={{ background: (KINDS[evKind(c)] || {}).color || "#64748b" }}>{(KINDS[evKind(c)] || { label: c.k }).label}</span>
                    <span className="ldest">{m.dest || c.rd}</span>
                    <span className="lmeta">{m.op || ""} · מק״ט {c.rd}</span>
                    {c.note ? <span className="lnote">{c.note}</span> : null}
                  </a>
                );
              })}
            </React.Fragment>
          ))}
          {list.length > lim && (
            <button className="morebtn" onClick={() => setLim(lim + 500)}>
              ⌄ הצג עוד — מוצגים {Math.min(lim, list.length).toLocaleString()} מתוך {list.length.toLocaleString()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ---------- טאב תחנות ---------- */
function StopsTab() {
  const [months, setMonths] = useState(null);
  const [mon, setMon] = useState("");
  const [yr, setYr] = useState("");   // שנה נבחרת בבוחר החודשים
  const [chs, setChs] = useState(null);
  const [hist, setHist] = useState(null);   // קורות-חיים מצטברים לכל תחנה
  const [kinds, setKinds] = useState(() => new Set());   // סימון מרובה, כמו בקווים
  const [katOpen, setKatOpen] = useState(false);
  const [q, setQ] = usePersistedQ("lh-q-stops");
  const [openKey, setOpenKey] = useState(null);   // שורת תחנה פתוחה עם מפה
  const [lim, setLim] = useState(250);   // "הצג עוד" מרחיב; סינון חדש מאפס
  useEffect(() => setLim(250), [q, mon, kinds]);
  const toggleKind = (k) => setKinds((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  useEffect(() => {
    fetch("data/stops-hist.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => (r.ok ? r.json() : {}))
      .then(setHist)
      .catch(() => setHist({}));
  }, []);
  // כללי התצוגה (בקשת המשתמש, בעקבות תחנות עונתיות כמו תחנות ההתרעננות):
  // "חדשה" — רק הרישום הראשון אי-פעם של התחנה; הרשמות חוזרות לא מוצגות.
  // "בוטלה" — רק אם עברה שנה בלי שחזרה; ומי שמופיעה ברישום הנוכחי
  // (גם בלי קווים שעוצרים בה) אינה מבוטלת.
  const keepEvent = (c) => {
    if (!hist) return true;
    const evs = hist[c.c] || [];
    if (c.k === "new") {
      // "חדשה" = לידת התחנה: האירוע הראשון בכלל בקורות-החיים שלה. תחנה
      // שההיסטוריה שלה מתחילה בביטול קיימת מלפני התיעוד — ה"חדשה" שאחריו
      // היא חזרה לרישום, לא לידה
      return !evs.length || (evs[0].k === "new" && evs[0].d === c.d);
    }
    if (c.k === "del") {
      if (evs.some((e) => e.d > c.d && e.k === "new")) return false;   // חזרה לפעול
      const last = evs[evs.length - 1];
      if (last && last.k === "del" && last.now) return false;          // עדיין ברישום
      return Date.now() - new Date(c.d) >= 365 * 864e5;                // מבוטלת = מעל שנה
    }
    return true;
  };
  useEffect(() => {
    fetch("data/months.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => r.json())
      .then((d) => { const ms = d.stopMonths || [];
        setMonths(ms);
        // ברירת המחדל: החודש האחרון — נטען מיידית. "כל התקופה" (פירוק
        // ומיון של כל קורות-החיים, מאות אלפי אירועים) רק בבחירה מפורשת
        if (ms.length) { setMon(ms[0]); setYr(ms[0].slice(0, 4)); } })
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
  // ממואם: בלי זה כל הקלדה בחיפוש בנתה ומיינה מחדש את כל האירועים (לאגים).
  // "כל התקופה": כל האירועים מכל הזמנים מתוך קורות-החיים, עם תאריך ליד כל אחד
  const source = useMemo(() => {
    const raw = mon === "all"
      ? (hist ? Object.entries(hist).flatMap(([c, evs]) => evs.map((e) => ({ ...e, c }))).sort((a, b) => b.d.localeCompare(a.d)) : null)
      : chs;
    return raw === null ? null : raw.filter(keepEvent);
  }, [mon, hist, chs]);
  const counts = useMemo(() => {
    const cn = {};
    (source || []).forEach((c) => { cn[c.k] = (cn[c.k] || 0) + 1; });
    return cn;
  }, [source]);
  if (months === null) return <div className="card">טוען…</div>;
  if (!months.length) return <div className="card"><div className="empty">עדיין אין נתוני שינויי תחנות — הם יצטברו מהריצות היומיות הקרובות.</div></div>;
  const needle = q.trim();
  const list = (source || []).filter((c) => (!kinds.size || kinds.has(c.k)) &&
    (!needle || (c.n || "").includes(needle) || (c.nn || "").includes(needle) || (c.on || "").includes(needle) || (c.t || "").includes(needle) || c.c === needle));
  return (
    <div className="card">
      {/* בוחר לפי שנה: slice(0,18) הישן הסתיר את כל מה שלפני 02.2025 —
          עכשיו כל שנה נגישה בלחיצה, והחודשים שלה נפתחים מתחתיה */}
      <div className="months">
        <button className={"mchip" + (mon === "all" ? " on" : "")} title="כל האירועים מכל השנים ברצף אחד" onClick={() => { setYr(""); setMon("all"); }}>🗓️ כל התקופה</button>
        {/* מהחדשה לישנה, באותו כיוון של החודשים בתוך כל שנה */}
        {[...new Set(months.map((m) => m.slice(0, 4)))].sort().reverse().map((y) => (
          <button key={y} className={"mchip" + (yr === y ? " on" : "")}
            title={"הצגת השינויים של שנת " + y} onClick={() => { setYr(y); const ms = months.filter((m) => m.startsWith(y)); if (!ms.includes(mon)) setMon(ms[ms.length - 1]); }}>{y}</button>
        ))}
      </div>
      {yr && (
        <div className="months">
          {months.filter((m) => m.startsWith(yr)).slice().reverse().map((m) => (
            <button key={m} className={"mchip" + (mon === m ? " on" : "")} title="הצגת השינויים של החודש הזה בלבד" onClick={() => setMon(m)}>{m.split("-").reverse().join(".")}</button>
          ))}
        </div>
      )}
      <input className="search" type="search" placeholder="חיפוש תחנה / עיר / מק״ט…" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="katbox">
        <button className="kathead" onClick={() => setKatOpen(!katOpen)}>
          <span className="katarrow">{katOpen ? "▼" : "◀"}</span>
          🗂️ קטגוריות לבחירה
          {kinds.size > 0 && <b className="katn">{kinds.size} מסומנות</b>}
        </button>
        {katOpen && (
          <div className="katlist">
            {Object.entries(SKINDS).map(([k, v]) => (
              <label key={k} className="katrow">
                <input type="checkbox" checked={kinds.has(k)} onChange={() => toggleKind(k)} />
                <i className="katdot" style={{ background: v.color }} />
                <span className="katlab">{v.label}</span>
                <b className="katc">{(counts[k] || 0).toLocaleString()}</b>
              </label>
            ))}
            {kinds.size > 0 && (
              <button className="katclear" onClick={() => setKinds(new Set())}>✖ נקה את הבחירה</button>
            )}
          </div>
        )}
      </div>
      {source === null ? "טוען…" : (
        <div className="slist">
          {(() => {
            // כל השינויים של אותה תחנה מקובצים יחד (בקשת המשתמש)
            const groups = [];
            const byCode = new Map();
            for (const c of list) {
              let g = byCode.get(c.c);
              if (!g) { g = { code: c.c, evs: [] }; byCode.set(c.c, g); groups.push(g); }
              g.evs.push(c);
            }
            const shown = groups.slice(0, lim);
            const evRow = (c, one) => {
              const k0 = c.c + c.k + c.d;
              return (
                <React.Fragment key={k0}>
                <div className={"srow" + (one ? "" : " sub") + (c.la != null ? " clk" : "")}
                  onClick={() => { if (c.la != null) setOpenKey(openKey === k0 ? null : k0); }}>
                  <span className="k" style={{ background: (SKINDS[c.k] || {}).color }}>{(SKINDS[c.k] || { label: c.k }).label}</span>
                  {one ? (
                    <span className="nm">
                      {c.k === "renamed" ? <><s>{c.on}</s> ← <b>{c.nn}</b></> : <b>{c.n}</b>}
                      <span className="code"> ({c.c})</span>
                    </span>
                  ) : (c.k === "renamed" && <span className="nm"><s>{c.on}</s> ← <b>{c.nn}</b></span>)}
                  <span className="meta">
                    {one && c.t ? c.t + " · " : ""}{fmtD(c.d)}
                    {c.k === "moved" && <> · הוזזה <b>{c.dist} מ׳</b> · <s>({c.ola}, {c.olo})</s> ← <b>({c.la}, {c.lo})</b></>}
                    {c.lines && c.lines.length > 0 && <> · {c.k === "new" ? "קווים שעצרו בה מהפתיחה" : "קווים שעצרו בה אז"}: {c.lines.slice(0, 10).join(", ")}</>}
                    {c.la != null && <> · 🗺️</>}
                  </span>
                </div>
                {openKey === k0 && c.la != null && <StopEvMap ev={c} />}
                </React.Fragment>
              );
            };
            const rows = shown.map((g) => {
              if (g.evs.length === 1) return evRow(g.evs[0], true);
              const head = g.evs[0];
              const nm = head.nn || head.n || (g.evs.find((e) => e.n || e.nn) || {}).n || "";
              return (
                <div className="sgroup" key={g.code}>
                  <div className="srow ghead">
                    <span className="nm"><b>{nm}</b><span className="code"> ({g.code})</span></span>
                    <span className="meta">{head.t ? head.t + " · " : ""}{g.evs.length} שינויים</span>
                  </div>
                  {g.evs.map((c) => evRow(c, false))}
                </div>
              );
            });
            return (
              <React.Fragment>
                {rows}
                {groups.length > lim && (
                  <button className="morebtn" onClick={() => setLim(lim + 300)}>
                    ⌄ הצג עוד — מוצגות {shown.length.toLocaleString()} מתוך {groups.length.toLocaleString()} תחנות
                  </button>
                )}
              </React.Fragment>
            );
          })()}
          {list.length === 0 && <div className="empty">אין שינויים תואמים בחודש הזה.</div>}
        </div>
      )}
    </div>
  );
}

/* ---------- אפליקציה ---------- */
// סוגי תחבורה שאינם אוטובוס. עד יולי 2026 הסורק סינן כל route_type שאינו 3,
// ולכן הרכבת, מוניות השירות והרכבת הקלה לא היו באתר כלל — למרות שהם יושבים
// באותו פיד ונושאים route_desc באותו פורמט. הרכבת הקלה והכרמלית מוצגות
// כקבוצה אחת (בקשת המשתמש).
// כל סוג תחבורה הוא קטגוריה עומדת בפני עצמה — רכבת ומוניות שירות אינן
// אותו דבר ואינן חולקות מסך (בקשת המשתמש). "שירות לפי דרישה" אינו כאן:
// הוא מופעל בידי חברות האוטובוס ויושב תחת "קווים".
const TABS = [
  { k: "rail", icon: "🚆", label: "רכבת", tts: ["rail", "lightrail", "cable"],
    tip: "רכבת ישראל, הרכבת הקלה בירושלים, הכרמלית וכבל אקספרס — היסטוריית מסלולים ותחנות",
    groups: [
      { k: "heavy", icon: "🚆", label: "רכבת ישראל", tts: ["rail"] },
      { k: "light", icon: "🚊", label: "רכבת קלה וכרמלית", tts: ["lightrail", "cable"] },
    ] },
  { k: "taxi", icon: "🚕", label: "מוניות שירות", tts: ["taxi"],
    tip: "קווי מוניות השירות שבפיד הארצי — מסלולים, תחנות והשינויים בהם",
    groups: [] },
];
const TT_ICON = { rail: "🚆", taxi: "🚕", lightrail: "🚊", cable: "🚡", demand: "🚐" };
// מקור האירוע — שלושה מקורות שונים לחלוטין, וכל אחד עם דיוק אחר. בלי
// לנקוב בשם, "מארכיון הפיד הארצי" לא אומר מי מדד ומתי.
const SRC_LABEL = {
  tf: "מקור: ארכיון TransitFeeds / OpenMobilityData — צילומי הפיד הארצי של משרד התחבורה, 2017–2022",
  tf17: "מקור: ארכיון TransitFeeds / OpenMobilityData — צילום 16.3.2017, הישן ביותר שקיים",
  ob: "מקור: ארכיון הסדנא לידע ציבורי (Open Bus) — צילומים יומיים מ-2022",
  _daily: "מקור: הסריקה היומית שלנו — השוואת הפיד הארצי, יום מול יום",
};
const TT_LABEL = { rail: "רכבת", taxi: "מונית שירות", lightrail: "רכבת קלה",
                   cable: "רכבל/כרמלית", demand: "שירות לפי דרישה" };

function ModesTab({ idx, openLine, spec }) {
  const [sel, setSel] = useState(() => new Set());
  const [q, setQ] = usePersistedQ("lh-q-" + spec.k);
  const [lim, setLim] = useState(200);
  useEffect(() => { setLim(200); setSel(new Set()); }, [spec.k]);
  useEffect(() => setLim(200), [q, sel]);

  const mine = useMemo(() => idx.lines.filter((l) => spec.tts.includes(l.tt)), [idx, spec]);
  const counts = useMemo(() => {
    const c = {};
    spec.groups.forEach((m) => { c[m.k] = mine.filter((l) => m.tts.includes(l.tt)).length; });
    return c;
  }, [mine, spec]);
  const toggle = (k) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  const needle = q.trim();
  const allowed = sel.size ? new Set(spec.groups.filter((m) => sel.has(m.k)).flatMap((m) => m.tts)) : null;
  let list = mine.filter((l) => !allowed || allowed.has(l.tt));
  if (needle) {
    const toks = needle.split(/\s+/).filter(Boolean);
    list = list.filter((l) => toks.every((t) =>
      (l.line || "").startsWith(t) || l.rd.startsWith(t) ||
      (l.dest || "").includes(t) || (l.op || "").includes(t)));
  }
  const lnum = (l) => parseInt(l.line) || 1e9;
  list = list.slice().sort((a, b) => lnum(a) - lnum(b) || (a.line || "").localeCompare(b.line || "") || a.rd.localeCompare(b.rd));
  const total = list.length;
  list = list.slice(0, lim);

  return (
    <div className="card">
      {spec.groups.length > 1 && (
        <div className="kfilter">
          <button className={"kchip" + (sel.size ? "" : " on")}
            style={sel.size ? {} : { borderColor: "#7c3aed", color: "#5b21b6" }}
            onClick={() => setSel(new Set())}>הכל<b>{mine.length.toLocaleString()}</b></button>
          {spec.groups.map((m) => (
            <button key={m.k} className={"kchip" + (sel.size && !sel.has(m.k) ? " off" : "")}
              style={sel.has(m.k) ? { borderColor: "#7c3aed", color: "#5b21b6" } : {}}
              onClick={() => toggle(m.k)}>
              {m.icon} {m.label}<b>{(counts[m.k] || 0).toLocaleString()}</b>
            </button>
          ))}
        </div>
      )}
      <input className="search" type="search" dir="rtl"
        placeholder="חיפוש: מספר קו, מק״ט, יעד או מפעיל…"
        value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="llist">
        {list.map((l) => (
          <a key={l.rd} className="lrow" href={lineHref(l.rd)}
            onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); openLine(l.rd); }}>
            <span className="badge sm">{l.line || TT_ICON[l.tt] || "—"}</span>
            {l.lk === "removed" && (
              <span className="k" style={{ background: isRemovedYear(l) ? "#7f1d1d" : "#dc2626" }}>
                {isRemovedYear(l) ? "בוטל — מעל שנה" : "בוטל"}
              </span>
            )}
            <span className="ldest">{l.dest}</span>
            <span className="lmeta">{l.op} · מק״ט {l.rd} · {l.v > 1 ? (l.v - 1) + " שינויים" : "ללא שינויים עדיין"}</span>
          </a>
        ))}
        {list.length === 0 && <div className="empty">לא נמצא קו תואם.</div>}
        {total > list.length && (
          <button className="morebtn" onClick={() => setLim(lim + 300)}>
            ⌄ הצג עוד — מוצגים {list.length.toLocaleString()} מתוך {total.toLocaleString()}
          </button>
        )}
      </div>
    </div>
  );
}

function App() {
  const [idx, setIdx] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("lines");
  const [q, setQ] = usePersistedQ("lh-q-main");
  const [kats, setKats] = useState(() => new Set());   // קטגוריות מסומנות (בחירה מרובה)
  const [katOpen, setKatOpen] = useState(false);
  // דף קו נכנס להיסטוריית הדפדפן (וגם לקישור, אחרי ה-#) — כפתור "אחורה"
  // בטלפון חוזר לרשימה במקום לצאת מהאתר, וקישור לקו נפתח ישירות עליו.
  // ‎#2012/<k>‎ הוא כתובת של קו 2012 בלי מקבילה של היום — נפתח בפיד.
  const H0 = decodeURIComponent((location.hash || "").slice(1));
  const [rd, setRd] = useState(() => (H0 && !H0.startsWith("2012/") ? H0 : null));
  const [byDay, setByDay] = useState(() => H0.startsWith("2012/"));   // תצוגת "שינויים לפי יום"
  const [lim, setLim] = useState(200);   // "הצג עוד" מרחיב; חיפוש חדש מאפס
  useEffect(() => setLim(200), [q, kats]);
  useEffect(() => {
    const onPop = (e) => setRd((e.state && e.state.rd) || null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const openLine = (r) => { history.pushState({ rd: r }, "", "#" + encodeURIComponent(r)); setRd(r); };
  const switchLine = (r) => { history.replaceState({ rd: r }, "", "#" + encodeURIComponent(r)); setRd(r); };
  const backToList = () => {
    setRd(null);
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
  };
  const toggleKat = (k) => setKats((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  useEffect(() => {
    fetch("data/lines.json?v=" + BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setIdx)
      .catch(setErr);
  }, []);
  const counts = useMemo(() => {
    const c = {};
    if (idx) {
      const keys = CAT_GROUPS.flatMap((g) => g.items);
      idx.lines.forEach((l) => {
        keys.forEach((k) => { if (catMatch(l, k)) c[k] = (c[k] || 0) + 1; });
      });
    }
    return c;
  }, [idx]);
  // אילו מק"טים עדיין פעילים — כדי להבדיל חלופה מבוטלת מקו שבוטל כולו
  // הטאב אינו חלק מהכתובת, ולכן ריענון או פתיחת קישור ישיר לקו החזירו
  // תמיד ל"קווים" — וכפתור "חזרה" הוציא את המשתמש מקו רכבת אל רשימת
  // האוטובוסים. הטאב נגזר מסוג הקו הפתוח, כך שהחזרה נוחתת במקום שממנו
  // הגיע גם כשהמצב בזיכרון אבד.
  useEffect(() => {
    if (!idx || !rd) return;
    const l = idx.lines.find((x) => x.rd === rd);
    const t = l && l.tt && TABS.find((x) => x.tts.includes(l.tt));
    setTab(t ? t.k : "lines");
  }, [idx, rd]);
  const mktAlive = useMemo(() => {
    const m = {};
    if (idx) idx.lines.forEach((l) => { if (l.lk !== "removed") m[l.rd.split("-")[0]] = true; });
    return m;
  }, [idx]);
  const isLineGone = (l) => l.lk === "removed" && !mktAlive[l.rd.split("-")[0]];
  if (err) return <div className="boot">הנתונים עוד לא נוצרו — הריצה הראשונה של הצינור תיצור אותם. נסו לרענן מאוחר יותר.</div>;
  if (!idx) return <div className="boot">טוען נתונים…</div>;
  const needle = q.trim();
  const inKats = (l) => {
    if (!kats.size) return true;
    for (const k of kats) { if (catMatch(l, k)) return true; }
    return false;
  };
  let list = [], total = 0;
  if (needle || kats.size) {
    // חיפוש רב-מילים: "13 קרית גת" — כל מילה חייבת להתאים לאחד השדות
    const toks = needle.split(/\s+/).filter(Boolean);
    const tokHit = (l, t) => l.line === t || l.line.startsWith(t) || l.rd.startsWith(t) ||
      (l.dest || "").includes(t) || (l.op || "").includes(t);
    // טאב "קווים" הוא אוטובוסים. קווי "שירות לפי דרישה" מופעלים בידי חברות
    // האוטובוס ונשארים גם כאן, ולא רק בטאב סוגי התחבורה (בקשת המשתמש).
    const buses = idx.lines.filter((l) => !l.tt || l.tt === "demand");
    list = buses.filter((l) => inKats(l) && toks.every((t) => tokHit(l, t)));
    const onlyRemoval = kats.size > 0 && [...kats].every((k) => REMOVAL_CATS.has(k));
    // דירוג: קודם מספר הקו המדויק, אחריו קווים שמתחילים בו, ורק בסוף
    // התאמות מק"ט/יעד/מפעיל — ובתוך כל דרגה לפי סדר מספרי
    const numTok = toks.find((t) => /^\d/.test(t)) || toks[0] || "";
    const rank = (l) => !numTok ? 0 : l.line === numTok ? 0 : l.line.startsWith(numTok) ? 1
      : l.rd.startsWith(numTok) ? 2 : ((l.dest || "").includes(numTok) ? 3 : 4);
    const lnum = (l) => parseInt(l.line) || 1e9;
    if (needle) list.sort((a, b) => rank(a) - rank(b) || lnum(a) - lnum(b) || a.line.localeCompare(b.line) || a.rd.localeCompare(b.rd));
    else if (onlyRemoval) list.sort((a, b) => (b.ld || "").localeCompare(a.ld || ""));
    else list.sort((a, b) => lnum(a) - lnum(b) || a.line.localeCompare(b.line) || a.rd.localeCompare(b.rd));
    total = list.length;
    list = list.slice(0, lim);
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
        <button className={"tab" + (tab === "lines" ? " on" : "")} title="חיפוש בכל קווי האוטובוס בארץ והיסטוריית השינויים של כל קו" onClick={() => { setTab("lines"); backToList(); }}>🚌 קווים</button>
        <button className={"tab" + (tab === "stops" ? " on" : "")} title="חיפוש תחנות והיסטוריית השינויים שלהן — שינוי שם, הזזה, ביטול" onClick={() => { setTab("stops"); backToList(); }}>🚏 תחנות</button>
        {TABS.map((t) => (
          <button key={t.k} className={"tab" + (tab === t.k ? " on" : "")} title={t.tip}
            onClick={() => { setTab(t.k); backToList(); }}>{t.icon} {t.label}</button>
        ))}
      </div>
      {tab === "stops" ? <StopsTab /> : (TABS.some((t) => t.k === tab) && !rd) ? (
        <ModesTab idx={idx} openLine={openLine} spec={TABS.find((t) => t.k === tab)} />
      ) : rd ? (
        <LinePage rd={rd} lineGone={!mktAlive[rd.split("-")[0]]}
          sibs={idx.lines.filter((x) => x.rd.split("-")[0] === rd.split("-")[0])}
          onSwitch={switchLine} onBack={backToList} />
      ) : byDay ? (
        <DayFeed idx={idx} openLine={openLine} onBack={() => setByDay(false)}
          init12={H0.startsWith("2012/") ? H0.slice(5) : null} />
      ) : (
        <div className="card">
          <input className="search" type="search" dir="rtl" autoFocus
            placeholder="חיפוש קו: מספר קו, מק״ט, יעד או מפעיל…"
            value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="katbox">
            <button className="kathead" title="פיד כרונולוגי: בחירת שנה וחודש ורואים כל שינוי שקרה, בכל קו בארץ, לפי תאריך" onClick={() => setByDay(true)}>
              🗓️ שינויים לפי יום — מה השתנה בכל תאריך, בכל הקווים
            </button>
          </div>
          <div className="katbox">
            <button className="kathead" onClick={() => setKatOpen(!katOpen)}>
              <span className="katarrow">{katOpen ? "▼" : "◀"}</span>
              🗂️ קטגוריות לבחירה
              {kats.size > 0 && <b className="katn">{kats.size} מסומנות</b>}
            </button>
            {katOpen && (
              <div className="katlist">
                {CAT_GROUPS.map((g) => (
                  <React.Fragment key={g.title}>
                    <div className="katgrp">{g.title}</div>
                    {g.items.map((k) => (
                      <label key={k} className="katrow">
                        <input type="checkbox" checked={kats.has(k)} onChange={() => toggleKat(k)} />
                        <i className="katdot" style={{ background: catColor(k) }} />
                        <span className="katlab">{CAT_LABELS[k]}</span>
                        <b className="katc">{(counts[k] || 0).toLocaleString()}</b>
                      </label>
                    ))}
                  </React.Fragment>
                ))}
                <div className="katnote">
                  🛈 שינויי ציור המסלול מזוהים מהמעקב היומי שהחל ביולי 2026. שינויי תחנות
                  היסטוריים (2023 ואילך) מחושבים מהשוואת רצפי התחנות שבארכיון ומתווספים
                  בהדרגה, ככל שהמילוי הלילי מתקדם.
                </div>
                {kats.size > 0 && (
                  <button className="katclear" onClick={() => setKats(new Set())}>✖ נקה את הבחירה</button>
                )}
              </div>
            )}
          </div>
          {(needle || kats.size > 0) ? (
            <div className="llist">
              {list.map((l) => (
                <a key={l.rd} className="lrow" href={lineHref(l.rd)}
                  onClick={(e) => { if (!plainClick(e)) return; e.preventDefault(); openLine(l.rd); }}>
                  <span className="badge sm">{l.line}</span>
                  {l.lk === "removed" && (isLineGone(l) ? (
                    <span className="k" style={{ background: isRemovedYear(l) ? "#7f1d1d" : "#dc2626" }}>
                      {isRemovedYear(l) ? "הקו בוטל — מעל שנה" : "הקו בוטל"}
                    </span>
                  ) : (
                    <span className="k" style={{ background: isRemovedYear(l) ? "#9a3412" : "#ea580c" }}>
                      {isRemovedYear(l) ? "חלופה בוטלה — מעל שנה" : "חלופה בוטלה"}
                    </span>
                  ))}
                  <span className="ldest">{l.dest}</span>
                  <span className="lmeta">{l.op} · מק״ט {l.rd} · {l.v > 1 ? (l.v - 1) + " שינויים" : "ללא שינויים עדיין"}
                    {l.lk === "removed" && <> · מבוטל מאז {fmtD(l.ld)}</>}</span>
                </a>
              ))}
              {list.length === 0 && (
                <div className="empty">{kats.size > 0 && !needle
                  ? "אין עדיין קווים בקטגוריות שסימנתם — קטגוריות של מסלול ותחנות מצטברות מההשוואות היומיות מכאן והלאה."
                  : "לא נמצא קו תואם."}</div>
              )}
              {total > list.length && (
                <button className="morebtn" onClick={() => setLim(lim + 300)}>
                  ⌄ הצג עוד — מוצגים {list.length.toLocaleString()} מתוך {total.toLocaleString()}
                </button>
              )}
            </div>
          ) : (
            <div className="empty">הקלידו מספר קו, או פתחו את "קטגוריות לבחירה" וסמנו אילו סוגי שינויים להציג.<br />
              <span className="mut">התיעוד המלא מתחיל מהריצה הראשונה של הצינור; היסטוריית הקווים מארכיון אופן באס מתחילה בינואר 2023 (ב-API שלהם אין נתוני 2022 — נבדק מולם), ובטאב התחנות הרישום הושלם אחורה עד ינואר 2022 מקובצי ה-GTFS הגולמיים.</span></div>
          )}
        </div>
      )}
      <footer>
        ניסוי במסגרת <a href="../" target="_blank" rel="noopener">הקו הבוחן</a> · הנתונים: GTFS משרד התחבורה · היסטוריה: אופן באס, הסדנא לידע ציבורי
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
