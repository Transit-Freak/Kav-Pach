/* הקו המדלג — ניסוי: קווים עירוניים שחולפים ליד תחנה פעילה בלי לעצור בה.
   הנתונים: skip-stops/data.json, נוצר ע"י tools/skiplines.py ב-GitHub Actions. */
const { useState, useEffect, useMemo, useRef, useDeferredValue } = React;
const BUILD = window.SK_BUILD || "0";
const PAGE = 100;

function fmtM(m) { return m >= 1000 ? (m / 1000).toFixed(1) + ' ק"מ' : Math.round(m) + " מ'"; }

/* ---------- מפה ---------- */
function SkipMap({ it, route, lineStops }) {
  const ref = useRef(null);
  const mapRef = useRef(null);
  const [full, setFull] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    const map = L.map(ref.current, {
      scrollWheelZoom: false,
      gestureHandling: coarse,
      gestureHandlingOptions: {
        text: { touch: "להזזת המפה גללו בשתי אצבעות", scroll: "לזום: Ctrl + גלילה", scrollMac: "לזום: ⌘ + גלילה" },
      },
    });
    mapRef.current = map;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      maxZoom: 19,
    }).addTo(map);

    // המסלול המלא של הקו — קו דק ובהיר מתחת לקטע המודגש
    const rt = (route || []).filter((p) => p.length === 2);
    if (rt.length > 1) {
      L.polyline(rt, { color: "#f59e0b", weight: 3, opacity: 0.5, dashArray: "1 6" }).addTo(map);
    }
    const seg = (it.seg || []).filter((p) => p.length === 2);
    if (seg.length > 1) {
      L.polyline(seg, { color: "#d97706", weight: 5, opacity: 0.85 }).addTo(map);
    }
    // כל תחנות העצירה של הקו — נקודות קטנות עם שם בריחוף
    (lineStops || []).forEach((st) => {
      if (!st[2] && !st[3]) return;
      L.circleMarker([st[2], st[3]], {
        radius: 4, color: "#b45309", weight: 2, fillColor: "#fde68a", fillOpacity: 1,
      }).addTo(map).bindTooltip(st[0], { direction: "top", className: "sk-tip" });
    });
    const mk = (la, lo, color, label, dir) => {
      if (!la && !lo) return null;
      const m = L.circleMarker([la, lo], {
        radius: 8, color, weight: 3, fillColor: "#fff", fillOpacity: 1,
      }).addTo(map);
      m.bindTooltip(label, { permanent: true, direction: dir, offset: [0, dir === "top" ? -8 : 8], className: "sk-tip" });
      return m;
    };
    mk(it.la, it.lo, "#dc2626", "מדולגת: " + it.stop, "top");
    if (it.bstop && it.bstop.la) mk(it.bstop.la, it.bstop.lo, "#16a34a", "עוצר: " + it.bstop.n, "bottom");
    if (it.astop && it.astop.la) mk(it.astop.la, it.astop.lo, "#16a34a", "עוצר: " + it.astop.n, "bottom");

    const pts = seg.length > 1 ? seg : [[it.la, it.lo]];
    map.fitBounds(L.latLngBounds(pts).pad(0.25));
    setFull(false);
    return () => { mapRef.current = null; map.remove(); };
  }, [it, route, lineStops]);

  const toggleFull = () => {
    const map = mapRef.current;
    if (!map) return;
    const rt = (route || []).filter((p) => p.length === 2);
    const seg = (it.seg || []).filter((p) => p.length === 2);
    const tgt = !full && rt.length > 1 ? rt : (seg.length > 1 ? seg : [[it.la, it.lo]]);
    map.fitBounds(L.latLngBounds(tgt).pad(0.15));
    setFull(!full);
  };

  return (
    <div className="map-wrap">
      <div className="map" ref={ref} />
      {(route || []).length > 1 && (
        <button className="full-btn" onClick={toggleFull}>
          {full ? "התמקדות בתחנה" : "כל המסלול"}
        </button>
      )}
    </div>
  );
}

/* ---------- פירוט ממצא ---------- */
function Detail({ it, db, onLine }) {
  const nSkip = (it.skippers || []).length;
  const [allOthers, setAllOthers] = useState(false);
  const others = it.others || [];
  const shownOthers = allOthers ? others : others.slice(0, 12);
  // רשימת תחנות הקו לפי הסדר + מיקום התחנה המדולגת בתוכה
  const sids = (db.shapestops && it.skey ? db.shapestops[it.skey] : null) || [];
  const sd = db.stopsd || {};
  const lineStops = sids.map((x) => sd[x]).filter(Boolean);
  const listing = [];
  sids.forEach((x) => {
    if (x === it.asid) listing.push({ skip: true, n: it.stop, c: it.code });
    const r = sd[x];
    if (r) listing.push({ n: r[0], c: r[1], b: x === it.bsid || x === it.asid });
  });
  return (
    <div className="detail">
      <SkipMap it={it} route={db.shapes && it.shp ? db.shapes[it.shp] : null} lineStops={lineStops} />
      <div className="legend">
        <span><i className="dot red" /> התחנה המדולגת</span>
        <span><i className="dot green" /> העצירות שלפני ואחרי</span>
        <span><i className="dot small" /> שאר תחנות הקו</span>
        <span><i className="ln" /> הקטע סביב התחנה</span>
        <span><i className="ln lt" /> שאר מסלול קו {it.line}</span>
      </div>
      <div className="facts">
        <p>
          קו <b>{it.line}</b> עובר <b>{it.dist} מ'</b> מתחנת <b>{it.stop}</b> (מק"ט {it.code}) —
          עוצר ב"<b>{it.bstop && it.bstop.n}</b>" כ-<b>{fmtM(it.before)}</b> לפניה
          וב"<b>{it.astop && it.astop.n}</b>" כ-<b>{fmtM(it.after)}</b> אחריה,
          אבל בה עצמה לא עוצר.
        </p>
        <p>
          בתחנה עוצרים <b>{it.onum}</b> קווים אחרים:{" "}
          {shownOthers.map((o) => (
            <button key={o} className="chip clk" title={"הצגת הממצאים של קו " + o}
              onClick={() => onLine && onLine(o)}>{o}</button>
          ))}
          {others.length > 12 && (
            <button className="chip more" onClick={() => setAllOthers(!allOthers)}>
              {allOthers ? "פחות ▲" : "עוד " + (others.length - 12) + " ▼"}
            </button>
          )}
          {it.onum > others.length && !allOthers ? " (הרשימה המלאה תופיע ברענון הבא)" : ""}
        </p>
        {nSkip > 1 && (
          <p>מדלגים על התחנה הזו גם: {(it.skippers || []).filter((x) => x !== it.line).map((o) => <span key={o} className="chip warn">{o}</span>)}</p>
        )}
        {nSkip >= 3 && (
          <p className="sysnote">
            ⚠️ <b>{nSkip} קווים שונים</b> מדלגים על התחנה הזו — כנראה דילוג מכוון
            (תכנון הציר, למשל תחנות ייעודיות לחלק מהקווים) ולא טעות.
          </p>
        )}
        {it._lt >= 8 && (
          <p className="sysnote">
            ⚠️ קו {it.line} מדלג על <b>{it._lt} תחנות</b> ב{it.city} — ייתכן שזה מסלול
            עם מקטע מהיר מכוון, לא דילוג נקודתי.
          </p>
        )}
        {listing.length > 0 && (
          <details className="stoplist">
            <summary>רשימת התחנות של קו {it.line} במסלול הזה ({listing.filter((x) => !x.skip).length})</summary>
            <ol>
              {listing.map((x, i) => (
                <li key={i} className={x.skip ? "skip" : (x.b ? "adj" : "")}>
                  {x.skip ? "⛔ " : ""}{x.n} <span className="code">({x.c})</span>{x.skip ? " — מדולגת" : ""}
                </li>
              ))}
            </ol>
          </details>
        )}
        <p className="mut">
          ייתכן שיש סיבה מוצדקת — נתיב נסיעה שממנו אי-אפשר לעצור, עומס במפרץ, או החלטת תכנון מכוונת.
          הממצא מבוסס על השוואת מסלול הקו (GTFS) לרצף התחנות שלו בלבד.
        </p>
      </div>
    </div>
  );
}

/* ---------- שורה ---------- */
const Row = React.memo(function Row({ it, open, onToggle, db, inner, onLine }) {
  return (
    <div className={"it" + (open ? " open" : "") + (inner ? " inner" : "")}>
      <button className="it-head" onClick={onToggle}>
        {!inner && <span className="line-badge">{it.line}</span>}
        <span className="it-main">
          <span className="it-title">מדלג על: {it.stop} <span className="code">({it.code})</span></span>
          <span className="it-sub">{it.city} · עוצר {fmtM(it.before)} לפני ו-{fmtM(it.after)} אחרי · {it.onum} קווים כן עוצרים{it.ty && it.ty !== "עירוני" ? <span className="tag-sys ty">{it.ty}</span> : null}{it._sys ? <span className="tag-sys">שיטתי</span> : null}</span>
        </span>
        <span className="arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && <Detail it={it} db={db} onLine={onLine} />}
    </div>
  );
});

/* ---------- קבוצה: כל הדילוגים של אותו קו באותה עיר תחת כרטיס אחד ---------- */
const LineGroup = React.memo(function LineGroup({ items, open, onToggle, openSub, setOpenSub, db, onLine }) {
  const it = items[0];
  return (
    <div className={"it grp" + (open ? " open" : "")}>
      <button className="it-head" onClick={onToggle}>
        <span className="line-badge">{it.line}</span>
        <span className="it-main">
          <span className="it-title">מדלג על {items.length} תחנות</span>
          <span className="it-sub">{it.city} · {items.slice(0, 3).map((x) => x.stop).join(" · ")}{items.length > 3 ? " · …" : ""}</span>
        </span>
        <span className="arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="grp-list">
          {items.map((x) => (
            <Row key={x._k} it={x} inner open={openSub === x._k} db={db} onLine={onLine}
              onToggle={() => setOpenSub(openSub === x._k ? null : x._k)} />
          ))}
        </div>
      )}
    </div>
  );
});

/* ---------- אפליקציה ---------- */
function App() {
  const [data, setData] = useState(null);
  const [interD, setInterD] = useState(null);   // קווים לא-עירוניים — נטען רק כשמבקשים
  const [interBusy, setInterBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [city, setCity] = useState("");
  const [q, setQ] = useState("");
  const [openKey, setOpenKey] = useState(null);
  const [openSub, setOpenSub] = useState(null);
  const [page, setPage] = useState(1);
  const [showSys, setShowSys] = useState(false);
  const [fOp, setFOp] = useState("");       // מפעיל
  const [fMahoz, setFMahoz] = useState(""); // מחוז (מהקובץ המצומצם)
  const [fUniq, setFUniq] = useState(""); // ייחודיות הקו (סדיר/לילה/מזינים)
  const [fType, setFType] = useState("עירוני"); // סוג קו — עירוני כברירת מחדל
  const [fGap, setFGap] = useState(0);      // מרחק מזערי מהעצירה הקרובה
  const [fSkips, setFSkips] = useState(0); // כמה תחנות הקו מדלג (לפחות)
  const dq = useDeferredValue(q);
  const goLine = (ln) => { setQ(ln); setOpenKey(null); setOpenSub(null); window.scrollTo({ top: 0, behavior: "smooth" }); };

  useEffect(() => {
    fetch("data.json?v=" + BUILD)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setData)
      .catch((e) => setErr(e));
  }, []);

  // הקובץ הלא-עירוני כבד — נטען פעם אחת, רק כשבוחרים סוג קו שאינו עירוני
  useEffect(() => {
    if (fType === "עירוני" || interD || interBusy) return;
    setInterBusy(true);
    fetch("data-inter.json?v=" + BUILD)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { setInterD(d || { items: [] }); setInterBusy(false); })
      .catch(() => { setInterD({ items: [] }); setInterBusy(false); });
  }, [fType, interD, interBusy]);

  // מאחדים את שתי החבילות לעבודה אחידה בהמשך
  const db = useMemo(() => {
    if (!data) return null;
    if (!interD || !interD.items || !interD.items.length) return data;
    return {
      ...data,
      items: data.items.concat(interD.items),
      shapes: { ...data.shapes, ...(interD.shapes || {}) },
      shapestops: { ...data.shapestops, ...(interD.shapestops || {}) },
      stopsd: { ...data.stopsd, ...(interD.stopsd || {}) },
    };
  }, [data, interD]);

  const items = useMemo(() => {
    if (!db) return [];
    const raw = (db.items || []).map((it, i) => ({ ...it, _k: it.line + "@" + it.sid + "@" + (it.ty || ""), _i: i,
      _q: (it.line + " " + it.stop + " " + it.code + " " + it.city).toLowerCase() }));
    // "דילוג שיטתי" — כשכמה קווים מדלגים על אותה תחנה (תכנון ציר, כמו דרך בגין
    // בת"א) זה כנראה מכוון ולא טעות. קו בודד שמדלג על הרבה תחנות רק מסומן בהערה.
    const perLine = {};
    raw.forEach((it) => { const k = it.line + "@" + it.city + "@" + (it.ty || ""); perLine[k] = (perLine[k] || 0) + 1; });
    raw.forEach((it) => {
      it._lt = perLine[it.line + "@" + it.city + "@" + (it.ty || "")];
      it._sys = (it.skippers || []).length >= 3;
    });
    return raw;
  }, [db]);

  const filtered = useMemo(() => {
    const needle = dq.trim().toLowerCase();
    return items.filter((it) => {
      if (!showSys && it._sys) return false;
      if (fType !== "all" && (it.ty || "עירוני") !== fType) return false;
      if (city && it.city !== city) return false;
      if (fOp && it.op !== fOp) return false;
      if (fMahoz && it.mahoz !== fMahoz) return false;
      if (fUniq && (it.uniq || "סדיר") !== fUniq) return false;
      if (fGap && Math.min(it.before, it.after) < fGap) return false;
      if (fSkips > 0 && it._lt >= fSkips) return false;
      if (!needle) return true;
      if (it.line === needle) return true;
      return it._q.includes(needle);
    });
  }, [items, city, dq, showSys, fOp, fMahoz, fUniq, fGap, fSkips, fType]);

  useEffect(() => { setPage(1); }, [city, dq, showSys, fOp, fMahoz, fUniq, fGap, fSkips, fType]);

  if (err) return <div className="boot">שגיאה בטעינת הנתונים — ייתכן שההרצה הראשונה עוד לא הסתיימה. נסו לרענן מאוחר יותר.</div>;
  if (!data) return <div className="boot">טוען נתונים…</div>;

  const byCity = {};
  items.forEach((it) => { if (it.city) byCity[it.city] = (byCity[it.city] || 0) + 1; });
  const cities = Object.keys(byCity).sort((a, b) => byCity[b] - byCity[a]);
  const sysN = items.filter((it) => it._sys).length;
  // קיבוץ: כל הדילוגים של אותו קו באותה עיר — כרטיס אחד (הסדר לפי הממצא המדורג הכי גבוה)
  const groups = [];
  {
    const gm = new Map();
    filtered.forEach((it) => {
      const k = it.line + "@" + it.city + "@" + (it.ty || "");
      if (!gm.has(k)) { gm.set(k, []); groups.push(gm.get(k)); }
      gm.get(k).push(it);
    });
  }
  const shown = groups.slice(0, page * PAGE);

  return (
    <div className="wrap">
      <header>
        <h1>🚌 הקו המדלג <span className="beta">ניסיוני</span></h1>
        <p className="tag">
          קווים עירוניים שעוברים ממש ליד תחנה פעילה, עוצרים בתחנה שלפניה ובתחנה שאחריה — אבל עליה מדלגים.
        </p>
        <div className="stats">
          <span className="stat"><b>{items.length.toLocaleString()}</b> ממצאים</span>
          {cities.slice(0, 4).map((c) => <span key={c} className="stat">{c}: <b>{byCity[c] || 0}</b></span>)}
          <span className="stat mut">עודכן: {data.gen}</span>
        </div>
      </header>

      <div className="explain">
        <b>איך זה עובד?</b> משווים את מסלול הנסיעה של כל קו עירוני (GTFS של משרד התחבורה) לרצף התחנות
        שהוא עוצר בהן. תחנה נחשבת "מדולגת" רק אם הקו עובר עד 10 מ' ממנה, בצד הנכון של הכביש, נוסע לאורך
        הרחוב (לא רק חוצה אותו), ועוצר בתחנות משני צדדיה במרחק סביר. קווי תלמידים ושאטלים (חנה וסע)
        לא נבדקים, וכך גם רציפי מסופים ותחנות מרכזיות — אוטובוס עוצר רק ברציף שלו וזה תקין. כברירת מחדל מוצגים קווים עירוניים — קווים בין-עירוניים ואזוריים (שלהם מותר
        לדלג יותר) נבדקים גם, ואפשר לבחור אותם במסנן סוג הקו. בנוסף, המערכת בודקת אם עוד קווים עושים
        את אותו הדבר: כשכמה קווים מדלגים על אותה תחנה, או שקו מדלג על תחנות רבות ברצף (כמו ציר דרך בגין
        בת"א) — זה מסומן "דילוג שיטתי", כנראה מכוון, ומוסתר כברירת מחדל. הרשימה ממוינת מהחשוד ביותר:
        תחנות שקו בודד מדלג עליהן בזמן שהרבה קווים אחרים עוצרים.
      </div>

      <div className="controls">
        <div className="chips">
          <select className="city-sel" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="">כל הארץ ({items.length})</option>
            {cities.map((c) => (
              <option key={c} value={c}>{c} ({byCity[c] || 0})</option>
            ))}
          </select>
          <button className={"chipf sys" + (showSys ? " on" : "")} onClick={() => setShowSys(!showSys)}
            title="דילוג ששייך כנראה לתכנון: כמה קווים מדלגים על אותה תחנה, או קו שמדלג על תחנות רבות">
            {showSys ? "מציג" : "מוסתרים"} {sysN} דילוגים שיטתיים
          </button>
        </div>
        <input
          className="search" type="search" dir="rtl"
          placeholder="חיפוש: מספר קו, שם תחנה, עיר או מק״ט…"
          value={q} onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {(() => {
        const uniqVals = (arr) => [...new Set(arr.filter(Boolean))].sort((a, b) => a.localeCompare(b, "he"));
        const ops = uniqVals(items.map((it) => it.op));
        const mahozs = uniqVals(items.map((it) => it.mahoz));
        const uniqs = uniqVals(items.map((it) => it.uniq || "סדיר"));
        return (
          <div className="controls2">
            <select className="fsel" value={fType} onChange={(e) => setFType(e.target.value)}>
              <option value="עירוני">קווים עירוניים</option>
              <option value="בינעירוני">קווים בין-עירוניים</option>
              <option value="אזורי">קווים אזוריים</option>
              <option value="all">כל סוגי הקווים</option>
            </select>
            {ops.length > 0 && (
              <select className="fsel" value={fOp} onChange={(e) => setFOp(e.target.value)}>
                <option value="">מפעיל: הכול</option>
                {ops.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {mahozs.length > 0 && (
              <select className="fsel" value={fMahoz} onChange={(e) => setFMahoz(e.target.value)}>
                <option value="">מחוז: הכול</option>
                {mahozs.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            {uniqs.length > 1 && (
              <select className="fsel" value={fUniq} onChange={(e) => setFUniq(e.target.value)}>
                <option value="">סוג קו: הכול</option>
                {uniqs.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            )}
            <label className="fnum">
              מרחק מהעצירות לפחות
              <input type="number" min="0" step="50" inputMode="numeric" placeholder="0"
                value={fGap || ""} onChange={(e) => setFGap(Math.max(0, +e.target.value || 0))} />
              מ'
            </label>
            <label className="fnum">
              הקו מדלג על פחות מ-
              <input type="number" min="0" step="1" inputMode="numeric" placeholder="∞"
                value={fSkips || ""} onChange={(e) => setFSkips(Math.max(0, +e.target.value || 0))} />
              תחנות
            </label>
          </div>
        );
      })()}

      <div className="count">
        {interBusy ? "טוען קווים לא-עירוניים… " : ""}
        {filtered.length === items.length ? "" : filtered.length + " תוצאות (" + groups.length + " קווים)"}
      </div>

      <div className="list">
        {shown.map((g) => {
          const gk = "g:" + g[0].line + "@" + g[0].city + "@" + (g[0].ty || "");
          return g.length === 1 ? (
            <Row key={g[0]._k} it={g[0]} open={openKey === g[0]._k} db={db} onLine={goLine}
              onToggle={() => setOpenKey(openKey === g[0]._k ? null : g[0]._k)} />
          ) : (
            <LineGroup key={gk} items={g} open={openKey === gk} db={db} onLine={goLine}
              openSub={openSub} setOpenSub={setOpenSub}
              onToggle={() => setOpenKey(openKey === gk ? null : gk)} />
          );
        })}
        {shown.length === 0 && <div className="empty">לא נמצאו תוצאות.</div>}
        {groups.length > shown.length && (
          <button className="more-btn" onClick={() => setPage(page + 1)}>
            הצגת עוד ({groups.length - shown.length} קווים נוספים)
          </button>
        )}
      </div>

      <footer>
        ניסוי במסגרת <a href="../">הקו הבוחן</a> · הנתונים: GTFS + הקובץ המצומצם של משרד התחבורה ·
        הבדיקה מכסה את כל הקווים העירוניים בארץ
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
