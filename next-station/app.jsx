const { useState, useEffect, useRef, useMemo, useCallback, useDeferredValue } = React;

// קטגוריות הזיהוי — צבע, תווית והסבר
const CATS = {
  mismatch: { label: "אי-התאמה מלאה", color: "#dc2626", desc: "הרחוב לא מופיע בשם כלל" },
  reversal: { label: "היפוך / ציון-דרך", color: "#7c3aed", desc: "הרחוב האמיתי מופיע שני בשם" },
  spelling: { label: "טעות כתיב", color: "#d97706", desc: "אותו רחוב, אות שונה — כנראה שגיאה" },
  streetvar: { label: "אי-התאמה ברחוב", color: "#0891b2", desc: "הרחוב נכתב כאן אחרת מרוב התחנות באותו רחוב" },
  uncertain: { label: "ספק / כתיב חלופי", color: "#64748b", desc: "כנראה לא טעות — הבדל כתיב, או שם על-שם מוסד/ציון-דרך (בית ספר, מרפאה, ישיבה…)" },
  closer: { label: "הצעות כלליות", color: "#16a34a", desc: "הרחוב המצטלב בשם רחוק מהתחנה — יש רחוב אחר קרוב יותר שכדאי שיופיע בשם" },
};

// אייקון לסוג נקודת העניין (POI) מ-OpenStreetMap
const POI_ICON = {
  school: "🏫", academia: "🎓", health: "🏥", mall: "🛒", train: "🚉",
  worship: "🕍", police: "🚓", fire: "🚒", library: "📚", community: "🏘️",
  gov: "🏛️", culture: "🎭", busstation: "🚌", park: "🌳", sport: "⚽",
  shop: "🏪", fuel: "⛽", bank: "🏦", junction: "🛣️", post: "📮", cemetery: "🪦", hood: "🏙️", care: "🧓", checkpoint: "🛂",
};

// מציגים ב"ליד התחנה" רק מקומות עד ~5–6 דק׳ הליכה אמיתית
const NEARBY_MAX_MIN = 6;
// זמן הליכה אפקטיבי לסינון: חי (אם הגיע) > צרוב מראש > הערכה אווירית.
// אותו זמן שמוצג הוא גם זה שמסנן — אחרת מקום "קרוב אווירית" אך עם הליכה
// ארוכה (למשל מעבר לכביש מהיר) היה נשאר ברשימת "עד ~5 דק'" עם 18 דק'.
function effWalkMin(x, live) {
  const rt = live || x.rt;
  if (rt && rt.d != null && rt.d <= 4 * x.d + 300) return rt.min;
  return x.d < 80 ? 1 : Math.round(x.d / 80);
}
// החלק בשם התחנה שאמור להיות הרחוב (לפני ה-/)
function primName(n) { return String(n || "").split(/[\\/]/)[0].trim(); }
// נורמליזציה לחיפוש: מתעלם מגרשיים/גרש/מקפים ורווחים כפולים ("בן-גוריון" ≡ "בן גוריון", קק"ל ≡ קקל)
function nq(s) { return String(s || "").replace(/["'׳״]/g, "").replace(/[-–]/g, " ").replace(/\s+/g, " ").trim(); }
// "הצעה מופרכת בהליכה": לפי OSRM הרחוב המצטלב שבשם דווקא קרוב יותר מהמוצע — מסתירים
function walkBad(s) { const w = s.rw; return !!(w && w.cur && w.sug && w.sug.d > w.cur.d); }

// משווה שתי מחרוזות ברמת התו ומסמן בצבע את האותיות השונות (LCS).
function lcsMark(a, b, which) {
  a = String(a || ""); b = String(b || "");
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--) for (let j = n - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) { out.push([a[i], false, i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { if (which === "a") out.push([a[i], true, i]); i++; }
    else { if (which === "b") out.push([b[j], true, j]); j++; }
  }
  while (i < m) { if (which === "a") out.push([a[i], true, i]); i++; }
  while (j < n) { if (which === "b") out.push([b[j], true, j]); j++; }
  return out.map(([ch, d, k]) => d ? <span className="d-hl" key={k}>{ch}</span> : <span key={k}>{ch}</span>);
}

// כפתור העתקה כללי — מעתיק טקסט ללוח עם משוב "הועתק"
function CopyBtn({ label, make }) {
  const [ok, setOk] = useState(false);
  function copy(e) {
    e.stopPropagation();
    const done = () => { setOk(true); setTimeout(() => setOk(false), 1600); };
    if (navigator.clipboard) navigator.clipboard.writeText(make()).then(done).catch(done);
  }
  return <button className="share-btn" onClick={copy}>{ok ? "✓ הועתק!" : label}</button>;
}
function ShareLink({ code }) {
  return <CopyBtn label="🔗 העתקת קישור לתחנה" make={() => window.location.origin + window.location.pathname + "#stop=" + code} />;
}
// טקסט מסכם של התחנה — להדבקה בוואטסאפ/מייל/פנייה
function stopText(s) {
  return [
    s.n,
    "מס׳ תחנה: " + s.c,
    s.t ? "עיר: " + s.t : null,
    "רחוב בכתובת: " + s.s,
    s.ms ? "רחוב לפי המפה: " + s.ms + " (" + s.md + " מ׳)" : null,
    "סוג: " + ((CATS[s.k] && CATS[s.k].label) || s.k),
    s.sug ? "שם מוצע: " + s.sug : null,
    s.la != null ? "מפה: https://www.google.com/maps?q=" + s.la + "," + s.lo : null,
    "קישור לתחנה: " + window.location.origin + window.location.pathname + "#stop=" + s.c,
  ].filter(Boolean).join("\n");
}

// שורה ברשימה — ממורשת (React.memo): נבנית מחדש רק כשהתחנה/הבחירה שלה משתנות,
// ולא בכל הקלדה בחיפוש או בחירת תחנה אחרת. זה מה שמונע קיפאון בטלפון.
const Row = React.memo(function Row({ s, on, times, onSel, onRoute, routeBusy, onReport }) {
  return (
    <div className={"item" + (on ? " on" : "")}>
      <button className="it-head" onClick={() => onSel(s)}>
        <div className="it-top">
          <span className="badge" style={{ background: CATS[s.k].color }}>{CATS[s.k].label}</span>
          <span className="code">{s.c}</span>
        </div>
        <div className="it-name">{s.n}</div>
        <div className="it-street">
          רחוב בכתובת: <b>{s.s}</b>
          {s.t ? " · " + s.t : ""}
        </div>
      </button>
      <div className="it-detail">
        <StopDetails s={s} inList onRoute={onRoute} routeBusy={routeBusy} times={times} onReport={onReport} />
      </div>
    </div>
  );
});

// כל פרטי התחנה — משותף לפאנל שעל המפה ולשורה ברשימה.
// inList=true: מדלג על שדות שכבר מוצגים בכותרת השורה (מספר, רחוב, עיר)
function StopDetails({ s, inList, onRoute, routeBusy, times, onReport }) {
  const nearPois = (s.p || []).map((x, i) => ({ x, i })).filter((o) => effWalkMin(o.x, times && times[o.i]) <= NEARBY_MAX_MIN);
  return (
    <>
      {!inList && <div className="d-row">מס׳ תחנה: <b>{s.c}</b></div>}
      {!inList && <div className="d-row">רחוב בכתובת: <b>{s.s}</b></div>}
      {s.ms && (
        <div className="d-row">🗺️ רחוב לפי המפה: <b>{s.ms}</b> <span className="d-poi-d">{s.md} מ׳</span></div>
      )}
      {!inList && s.t && <div className="d-row">עיר: {s.t}</div>}
      <div className="d-cat" style={{ color: CATS[s.k].color }}>
        {CATS[s.k].label} — {CATS[s.k].desc}
      </div>
      {s.lm ? (
        <div className="d-diff">🏛️ התחנה קרויה על-שם מוסד או מקום (לא על-שם רחוב) — ככל הנראה שם תקין.</div>
      ) : (s.k === "spelling" || s.k === "uncertain") && (
        <div className="d-diff">💬 בשם התחנה: «<b>{lcsMark(primName(s.n), s.s, "a")}</b>» · בכתובת: «<b>{lcsMark(primName(s.n), s.s, "b")}</b>»</div>
      )}
      {s.sv && (
        <div className="d-sv">
          🛣️ ברחוב זה <b>{s.sv.n}</b> תחנות כותבות «<b>{s.sv.maj}</b>» — וכאן כתוב «<b>{s.sv.use}</b>»
        </div>
      )}
      {s.k === "closer" && (
        <div className="d-sug">
          {s.cur
            ? <>📍 הרחוב המצטלב שבשם («<b>{s.cur}</b>»{s.curd != null ? " — כ-" + s.curd + " מ׳ מהתחנה" : " — אינו ליד התחנה"}) רחוק יותר מהרחוב <b>{s.ms}</b> (<b>{s.md}</b> מ׳), שעובר ממש לידה.</>
            : <>📍 הרחוב <b>{s.ms}</b> עובר ממש ליד התחנה (<b>{s.md}</b> מ׳) ואינו מופיע בשם.</>}
          <div className="d-sug-name">💡 שם מוצע: <b>{s.sug}</b></div>
          {s.rw && (s.rw.cur || s.rw.sug) && (
            <div className="d-walk-cmp">
              🚶 הליכה אמיתית מהתחנה:
              {s.rw.cur && <> <span className="lg cur">{s.cur}</span> <b>{s.rw.cur.d} מ׳</b> ({s.rw.cur.min} דק׳)</>}
              {s.rw.cur && s.rw.sug && " · "}
              {s.rw.sug && <> <span className="lg sug">{s.ms}</span> <b>{s.rw.sug.d} מ׳</b> ({s.rw.sug.min} דק׳)</>}
              {s.rw.cur && s.rw.sug && (
                <div className="d-walk-verdict">{s.rw.sug.d <= s.rw.cur.d ? "✓ הרחוב המוצע אכן קרוב יותר גם בהליכה" : "↺ דווקא הרחוב שבשם קרוב יותר בהליכה"}</div>
              )}
            </div>
          )}
          <div className="d-map-legend"><span className="lg cur">● בשם כיום</span> <span className="lg sug">● מוצע</span> — מסומנים על המפה</div>
        </div>
      )}
      {s.sug && s.k !== "closer" && (
        <div className="d-sug">💡 שם מוצע (לפי הרחובות במפה): <b>{s.sug}</b></div>
      )}
      {s.psug && (
        <div className="d-sug">🏛️ מוקד מרכזי סמוך (עד 100 מ׳): <b>{s.psug}</b> <span className="d-poi-d">{s.psugd} מ׳</span></div>
      )}
      {nearPois.length > 0 && (
        <div className="d-poi">
          <div className="d-poi-h">📍 ליד התחנה (OSM) — עד ~5 דק׳ הליכה:</div>
          {nearPois.map(({ x, i }) => {
            let rt = (times && times[i]) || x.rt; // חי בבחירה > צרוב מראש > הערכה
            // אם המסלול ארוך בצורה לא-סבירה מהמרחק האווירי (מחסום/חוסר שביל ב-OSM) — חזרה להערכה
            if (rt && rt.d != null && rt.d > 4 * x.d + 300) rt = null;
            return (
              <div className="d-poi-row" key={i}>
                <span className="d-poi-n">{POI_ICON[x.k] || "•"} {x.n}</span>
                <span className="d-poi-d">
                  {rt
                    ? <span className="d-walk-real">🚶 {rt.min} דק׳{rt.d != null ? " · " + rt.d + " מ׳" : ""}</span>
                    : <span>{x.d} מ׳ · {walkMin(x.d)} 🚶</span>}
                </span>
                {onRoute && x.la != null && (
                  <button className="d-route-btn" disabled={routeBusy} onClick={() => onRoute(s, x)} title="הצג מסלול הליכה על המפה">
                    {routeBusy ? "…" : "מסלול ›"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
      {s.la != null && (
        <a className="gmap" href={"https://www.google.com/maps?q=" + s.la + "," + s.lo} target="_blank" rel="noopener noreferrer">
          פתח במפות Google ↗
        </a>
      )}
      <ShareLink code={s.c} />
      <CopyBtn label="📋 העתקת פרטי התחנה" make={() => stopText(s)} />
      {onReport && (
        <button className="rep-trigger" onClick={(e) => { e.stopPropagation(); onReport(s); }}>🚩 דווח על תחנה זו</button>
      )}
    </>
  );
}

function App() {
  const [data, setData] = useState(null);
  const [cat, setCat] = useState("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);
  const [activeOnly, setActiveOnly] = useState(false);
  const [route, setRoute] = useState(null); // {loading|err|ok, to, d, min}
  const [poiTimes, setPoiTimes] = useState(null); // זמני הליכה אמיתיים לנקודות, מיושרים ל-sel.p
  const [reportStop, setReportStop] = useState(null); // תחנה שמדווחים עליה
  const [hist, setHist] = useState(null); // היסטוריית ספירות למגמות
  const [chg, setChg] = useState(null); // יומן "תוקן!" — תחנות שתוקנו במקור
  const [showFixed, setShowFixed] = useState(false);
  const [letterCity, setLetterCity] = useState(null); // מחולל מכתב לרשות (null=סגור)
  // כמה שורות מציגים בפועל — מתחילים קטן (מהיר בטלפון) ומרחיבים בכפתור "הצגת עוד"
  const PAGE = 120;
  const [cap, setCap] = useState(PAGE);
  const mapRef = useRef(null);
  const markRef = useRef(null);
  const routeRef = useRef(null);
  const poiLayerRef = useRef(null);
  const roadsLayerRef = useRef(null);
  const OSRM = "https://routing.openstreetmap.de/routed-foot";

  // מסלול הליכה אמיתי מהתחנה לנקודת העניין — ניתוב חי בדפדפן (OSRM foot, FOSSGIS)
  // useCallback: פונקציה יציבה, כדי ששורות הרשימה הממורשות (React.memo) לא ייבנו מחדש לחינם
  const showRoute = useCallback(function (from, poi) {
    const m = mapRef.current;
    if (!m || from.la == null || poi.la == null) return;
    setSel(from);
    setRoute({ loading: true, to: poi.n });
    const url =
      "https://routing.openstreetmap.de/routed-foot/route/v1/foot/" +
      from.lo + "," + from.la + ";" + poi.lo + "," + poi.la +
      "?overview=full&geometries=geojson";
    fetch(url)
      .then((r) => r.json())
      .then((j) => {
        if (!j.routes || !j.routes[0]) throw new Error("no route");
        const rt = j.routes[0];
        if (routeRef.current) routeRef.current.remove();
        routeRef.current = L.geoJSON(rt.geometry, { style: { color: "#0891b2", weight: 5, opacity: 0.85, dashArray: "1 8", lineCap: "round" } }).addTo(m);
        m.fitBounds(routeRef.current.getBounds(), { padding: [50, 50], maxZoom: 17 });
        setRoute({ ok: true, to: poi.n, d: Math.round(rt.distance), min: Math.max(1, Math.round(rt.duration / 60)) });
      })
      .catch(() => setRoute({ err: true, to: poi.n }));
  }, []);
  function clearRoute() {
    if (routeRef.current) { routeRef.current.remove(); routeRef.current = null; }
    setRoute(null);
  }

  useEffect(() => {
    // טוקן יומי כדי שעדכוני-הנתונים האוטומטיים יגיעו למשתמשים תוך יום (ולא יישארו ב-cache)
    fetch("data.json?v=" + window.NS_BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => r.json())
      .then((d) => {
        // מחרוזת-חיפוש מנורמלת אחת לכל תחנה, מחושבת פעם אחת בטעינה —
        // כך שכל הקלדה בחיפוש לא מנרמלת מחדש 4 שדות לכל תחנה (איטי מאוד בטלפון)
        (d.stops || []).forEach((s) => { s._q = nq([s.t, s.n, s.c, s.s].join("|")); });
        setData(d);
      })
      .catch(() => setData({ counts: {}, stops: [] }));
    // היסטוריית ספירות (רשומה ליום) — להצגת מגמה מאז הריצה הקודמת
    fetch("history.json?v=" + window.NS_BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => (r.ok ? r.json() : null))
      .then(setHist)
      .catch(() => {});
    // יומן תיקונים במקור — תחנות ששמן/כתובתן שונו ב-GTFS ויצאו מרשימת השגיאות
    fetch("changes.json?v=" + window.NS_BUILD + "-" + new Date().toISOString().slice(0, 10))
      .then((r) => (r.ok ? r.json() : null))
      .then(setChg)
      .catch(() => {});
  }, []);

  // קישור ישיר לתחנה: פתיחה עם #stop=<מספר> בוחרת אותה אוטומטית
  useEffect(() => {
    if (!data) return;
    const m = /#stop=(\d+)/.exec(window.location.hash || "");
    if (m) { const s = data.stops.find((x) => x.c === m[1]); if (s) setSel(s); }
  }, [data]);
  // שומר את התחנה הנבחרת בכתובת — כך שאפשר להעתיק/לשתף את הקישור מסרגל הדפדפן.
  // רק אחרי שהנתונים נטענו — אחרת ה-# של קישור עמוק נמחק לפני שהספקנו לקרוא אותו
  useEffect(() => {
    if (!data) return;
    if (sel) history.replaceState(null, "", "#stop=" + sel.c);
    else if (window.location.hash) history.replaceState(null, "", window.location.pathname + window.location.search);
  }, [sel, data]);

  // אתחול מפה
  useEffect(() => {
    if (mapRef.current || !document.getElementById("map")) return;
    // מסך מגע: אצבע אחת גוללת את הדף, שתי אצבעות מזיזות את המפה —
    // אחרת המפה "חוטפת" כל גרירה והדף נראה תקוע (התוסף מציג הסבר קצר על המפה)
    const coarse = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
    const m = L.map("map", {
      center: [31.6, 34.9], zoom: 8, zoomControl: true,
      gestureHandling: coarse, // אם התוסף לא נטען — האפשרות פשוט מתעלמת
      gestureHandlingOptions: { duration: 1500, text: { touch: "להזזת המפה — שתי אצבעות (אצבע אחת גוללת את הדף)", scroll: "להגדלה — Ctrl + גלגלת", scrollMac: "להגדלה — ⌘ + גלגלת" } },
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "© OpenStreetMap", maxZoom: 19,
    }).addTo(m);
    mapRef.current = m;
  }, [data]);

  // מעבר לתחנה הנבחרת — מסמן את התחנה ואת המקומות הסמוכים, ומחשב זמני הליכה אמיתיים
  useEffect(() => {
    const m = mapRef.current;
    if (!m) return;
    // ניקוי כל השכבות הקודמות — תמיד, גם במעבר בין תחנות וגם בביטול בחירה (מונע "שאריות")
    if (routeRef.current) { routeRef.current.remove(); routeRef.current = null; }
    if (poiLayerRef.current) { poiLayerRef.current.remove(); poiLayerRef.current = null; }
    if (roadsLayerRef.current) { roadsLayerRef.current.remove(); roadsLayerRef.current = null; }
    if (markRef.current) { markRef.current.remove(); markRef.current = null; }
    setRoute(null);
    setPoiTimes(null);
    if (!sel || sel.la == null) return;
    // סמן התחנה
    markRef.current = L.marker([sel.la, sel.lo])
      .addTo(m)
      .bindPopup("<b>" + esc(sel.n) + "</b><br>רחוב בכתובת: " + esc(sel.s) + "<br>" + esc(sel.t));
    // "הצעות כלליות": נקודה מדויקת על כל רחוב, עם השם ממש על הנקודה (לא מרחף)
    if (sel.k === "closer" && sel.roads) {
      const rg = L.layerGroup();
      const draw = (road, color, cls) => {
        if (!road || !road.pt) return;
        L.circleMarker(road.pt, { radius: 7, color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 })
          .addTo(rg)
          .bindTooltip(esc(road.n), { permanent: true, direction: "center", className: "road-lbl " + cls });
      };
      draw(sel.roads.prim, "#64748b", "prim");  // אפור — הרחוב הראשי
      draw(sel.roads.cur, "#dc2626", "cur");     // אדום — המצטלב שבשם כיום
      draw(sel.roads.sug, "#16a34a", "sug");     // ירוק — הרחוב המוצע
      rg.addTo(m);
      roadsLayerRef.current = rg;
    }
    // סמן רק את נקודות העניין הקרובות (עד ~5 דק׳ הליכה)
    const withC = (sel.p || []).map((x, idx) => ({ x, idx })).filter((o) => o.x.la != null && effWalkMin(o.x) <= NEARBY_MAX_MIN);
    if (withC.length) {
      const grp = L.layerGroup();
      withC.forEach(({ x }) => {
        L.marker([x.la, x.lo], {
          icon: L.divIcon({ className: "poi-pin", html: "<div class='poi-pin-i'>" + (POI_ICON[x.k] || "📍") + "</div>", iconSize: [28, 28], iconAnchor: [14, 14] }),
        }).addTo(grp).bindPopup("<b>" + esc(x.n) + "</b><br>" + x.d + " מ׳ (קו אווירי)");
      });
      grp.addTo(m);
      poiLayerRef.current = grp;
      const b = L.latLngBounds([[sel.la, sel.lo], ...withC.map(({ x }) => [x.la, x.lo])]);
      m.fitBounds(b, { padding: [60, 60], maxZoom: 17 });
      // זמני הליכה אמיתיים בבת-אחת (OSRM table) — מרענן את הזמן הצרוב
      const pts = [[sel.lo, sel.la], ...withC.map(({ x }) => [x.lo, x.la])];
      fetch(OSRM + "/table/v1/foot/" + pts.map((c) => c.join(",")).join(";") + "?sources=0&annotations=duration,distance")
        .then((r) => r.json())
        .then((j) => {
          if (!j.durations || !j.durations[0]) return;
          const dur = j.durations[0], dis = (j.distances && j.distances[0]) || [];
          const res = (sel.p || []).map(() => null);
          withC.forEach(({ idx }, k0) => {
            const k = k0 + 1;
            if (dur[k] != null) res[idx] = { min: Math.max(1, Math.round(dur[k] / 60)), d: dis[k] != null ? Math.round(dis[k]) : null };
          });
          setPoiTimes(res);
        })
        .catch(() => {});
    } else {
      m.flyTo([sel.la, sel.lo], 17, { duration: 0.6 });
    }
    markRef.current.openPopup();
  }, [sel]);

  // סדר חומרה לקטגוריות — "ספק" תמיד אחרון
  const RANK = { mismatch: 0, reversal: 1, spelling: 2, streetvar: 3, uncertain: 4, closer: 5 };

  // useDeferredValue: תיבת החיפוש מגיבה מיד לכל הקלדה, והסינון הכבד רץ ברקע
  // (בלי זה כל אות "תוקעת" את המקלדת בטלפון עד שהסינון מסתיים)
  const dq = useDeferredValue(q);
  // סינון חדש (חיפוש/קטגוריה/פעילות) — חוזרים לעמוד הראשון
  useEffect(() => { setCap(PAGE); }, [cat, dq, activeOnly]);
  // החלפת קטגוריה — הרשימה הפנימית חוזרת לראשה (שלא ניתקע עמוק ברשימה שהתקצרה)
  useEffect(() => {
    const el = document.querySelector(".list");
    if (el && el.scrollTop) el.scrollTop = 0;
  }, [cat]);
  const filtered = useMemo(() => {
    if (!data) return [];
    const qn = nq(dq);
    const farness = (s) => (s.curd == null ? 1e9 : s.curd); // מצטלב לא-נמצא = הכי רחוק
    return data.stops
      .filter(
        (s) =>
          // "הכל" מציג רק קטגוריות-שגיאה; "הצעות כלליות" נפרדות ונבחרות בצ'יפ שלהן
          (cat === "all" ? s.k !== "closer" : s.k === cat) &&
          !(s.k === "closer" && walkBad(s)) && // מסתירים הצעות שההליכה הפריכה
          (!activeOnly || s.act !== false) &&
          (!qn || (s._q || "").indexOf(qn) >= 0)
      )
      .sort((a, b) =>
        (RANK[a.k] - RANK[b.k]) ||
        // בהצעות כלליות: מהרחוב המצטלב הרחוק ביותר אל הקרוב
        (a.k === "closer" ? farness(b) - farness(a) : Number(a.c) - Number(b.c))
      );
  }, [data, cat, dq, activeOnly]);

  const hasActiveInfo = !!(data && data.stops.some((s) => s.act === false));

  // הורדת התצוגה הנוכחית כקובץ אקסל (CSV עם BOM כדי שעברית תיפתח נכון ב-Excel)
  function downloadCSV() {
    const cols = ["מס׳ תחנה", "שם התחנה", "רחוב בכתובת", "עיר", "סוג", "רחוב לפי המפה", "מרחק (מ׳)", "שם מוצע"];
    const esc = (v) => '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
    const rows = filtered.map((s) => [s.c, s.n, s.s, s.t || "", (CATS[s.k] && CATS[s.k].label) || s.k, s.ms || "", s.md == null ? "" : s.md, s.sug || ""].map(esc).join(","));
    const csv = "﻿" + cols.map(esc).join(",") + "\n" + rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "תחנות-" + (cat === "all" ? "הכל" : (CATS[cat] ? CATS[cat].label : cat)) + ".csv";
    a.click();
  }

  if (!data) return <div className="boot">טוען נתונים…</div>;
  const shown = filtered.slice(0, cap);
  // מספר "הצעות כלליות" שמוצגות בפועל = אלה שההליכה לא הפריכה
  const closerValid = data.stops.reduce((a, s) => a + (s.k === "closer" && !walkBad(s) ? 1 : 0), 0);

  return (
    <div className="app">
      <header className="hdr">
        <div className="brand">
          <div className="logo">🚏</div>
          <div className="brand-txt">
            <h1>התחנה הבאה</h1>
            <p>תחנות אוטובוס ששמן אינו תואם לרחוב שבכתובת הרשמית</p>
          </div>
        </div>
        <div className="src">
          נתונים: משרד התחבורה (GTFS){data.generated ? " · עודכן לאחרונה: " + data.generated.split("-").reverse().join(".") : ""}
          {(() => {
            // תאריך עדכון נתוני המפה (OSM) — מציגים את הישן מבין POI/כבישים (הערבות הזהירה)
            const o = data.osm; if (!o) return "";
            const ds = [o.poi, o.roads].filter(Boolean).sort();
            return ds.length ? " · מפה (OpenStreetMap): עודכנה " + ds[0].split("-").reverse().join(".") : "";
          })()}
          {" "}· נבנה ע"י שלמה הרטמן
        </div>
        {(() => {
          if (!hist || hist.length < 2) return null;
          const cur = hist[hist.length - 1];
          // תיקוני-מקור מאומתים (שינוי טקסט ב-GTFS) — מוצגים תמיד, גם כשהכללים השתנו
          const lastChg = chg && chg.length ? chg[chg.length - 1] : null;
          const fixedN = lastChg && lastChg.d === cur.d ? (lastChg.fixed || []).length : 0;
          // השוואת ספירות-קטגוריה — רק מול ריצה קודמת עם אותה גרסת-כללים (v),
          // כדי ששינויי סיווג שלנו לא יוצגו כאילו משרד התחבורה תיקן/קלקל.
          const prev = hist.slice(0, -1).reverse().find((e) => e.v && cur.v && e.v === cur.v);
          const diffs = prev
            ? Object.keys(CATS).map((k) => ({ k, d: (cur.c[k] || 0) - (prev.c[k] || 0) })).filter((x) => x.d !== 0)
            : null;
          const prevRun = hist[hist.length - 2]; // הריצה שמולה נמדדו התיקונים — להצגת התאריך
          return (
            <div className="trend">
              📈 מאז הריצה הקודמת{prevRun ? " (" + prevRun.d.split("-").reverse().join(".") + ")" : ""}: <b>{fixedN.toLocaleString()}</b> תחנות תוקנו במקור (מאומת מול הטקסט ב-GTFS)
              {!prev && <span> · השוואת הקטגוריות תתחדש בריצה הבאה (כללי הזיהוי עודכנו)</span>}
              {prev && (diffs.length === 0
                ? " · ללא שינוי בקטגוריות"
                : diffs.map((x, i) => (
                    <span key={x.k}>
                      {" · "}
                      {CATS[x.k].label}{" "}
                      <b className={x.d < 0 ? "down" : "up"}>{x.d < 0 ? "▼" : "▲"}{Math.abs(x.d).toLocaleString()}</b>
                    </span>
                  )))}
            </div>
          );
        })()}
      </header>

      <div className="stats">
        <button className={"stat" + (cat === "all" ? " on" : "")} onClick={() => setCat("all")}>
          <b>{(data.stops.length - (data.counts.closer || 0)).toLocaleString()}</b>
          <span>סה"כ חשודות</span>
        </button>
        {Object.keys(CATS).map((k) => (
          <button
            key={k}
            className={"stat" + (cat === k ? " on" : "")}
            style={{ "--c": CATS[k].color }}
            onClick={() => setCat(cat === k ? "all" : k)}
            title={CATS[k].desc}
          >
            <b style={{ color: CATS[k].color }}>{((k === "closer" ? closerValid : data.counts[k]) || 0).toLocaleString()}</b>
            <span>{CATS[k].label}</span>
          </button>
        ))}
      </div>

      {chg && chg.length > 0 && (() => {
        const total = chg.reduce((a, e) => a + (e.fixed || []).length, 0);
        if (!total) return null;
        return (
          <div className="fixedbar">
            <button className="fixedbar-h" onClick={() => setShowFixed(!showFixed)}>
              🔧 <b>{total.toLocaleString()}</b> תחנות תוקנו במקור (שם/כתובת שונו ב-GTFS) מאז {chg[0].d.split("-").reverse().join(".")} {showFixed ? "▲" : "▼"}
            </button>
            {showFixed && (
              <div className="fixed-list">
                {chg.slice().reverse().map((e) => (
                  <div key={e.d}>
                    <div className="fixed-date">{e.d.split("-").reverse().join(".")} — {e.fixed.length} תיקונים</div>
                    {e.fixed.map((f, i) => (
                      <div className="fixed-row" key={f.c + "_" + i}>
                        <span className="code">{f.c}</span> {f.t} · <s>{f.on}</s> ← <b>{f.nn}</b>
                        {f.os !== f.ns && <span className="fixed-street"> (כתובת: {f.os} ← {f.ns})</span>}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })()}

      <div className="body">
        <div className="panel">
          <input
            className="search"
            placeholder="חיפוש: עיר / שם תחנה / מספר…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {hasActiveInfo && (
            <label className="toggle">
              <input type="checkbox" checked={activeOnly} onChange={(e) => setActiveOnly(e.target.checked)} />
              <span>הסתר תחנות לא פעילות (שאינן בקו פעיל)</span>
            </label>
          )}
          <div className="count">
            מציג {shown.length.toLocaleString()} מתוך {filtered.length.toLocaleString()}
            <button className="dl-btn" onClick={downloadCSV} disabled={!filtered.length} title="הורדת התצוגה הנוכחית כקובץ אקסל">⬇ אקסל ({filtered.length.toLocaleString()})</button>
            <button className="dl-btn letter-btn" onClick={() => setLetterCity("")} title="יצירת מכתב פנייה לעירייה/משרד התחבורה עם רשימת הליקויים בעיר">📨 מכתב לרשות</button>
          </div>
          <div className="list">
            {shown.map((s) => (
              <Row
                key={s.c}
                s={s}
                on={!!(sel && sel.c === s.c)}
                times={sel && sel.c === s.c ? poiTimes : null}
                onSel={setSel}
                onRoute={showRoute}
                routeBusy={!!(route && route.loading)}
                onReport={setReportStop}
              />
            ))}
            {filtered.length > shown.length && (
              <button className="more-btn" onClick={() => setCap(cap + PAGE)}>
                הצגת עוד {Math.min(PAGE, filtered.length - shown.length).toLocaleString()} תחנות ({(filtered.length - shown.length).toLocaleString()} נוספות בסינון הנוכחי)
              </button>
            )}
            {shown.length === 0 && <div className="empty">לא נמצאו תחנות בסינון הנוכחי.</div>}
          </div>
        </div>

        <div className="map-wrap">
          <div id="map"></div>
          {route && (
            <div className={"route-info" + (route.err ? " err" : "")}>
              <button className="d-x" onClick={clearRoute}>×</button>
              {route.loading && <span>🚶 מחשב מסלול הליכה ל«{route.to}»…</span>}
              {route.ok && <span>🚶 מסלול הליכה ל«<b>{route.to}</b>»: <b>{route.d} מ׳</b> · <b>{route.min} דק׳</b> (לאורך הרחובות)</span>}
              {route.err && <span>לא נמצא מסלול הליכה ל«{route.to}» (שירות הניתוב לא זמין כרגע)</span>}
            </div>
          )}
          {sel && (
            <div className="detail">
              <button className="d-x" onClick={() => setSel(null)}>×</button>
              <div className="d-name">{sel.n}</div>
              <StopDetails s={sel} onRoute={showRoute} routeBusy={route && route.loading} times={poiTimes} onReport={setReportStop} />
            </div>
          )}
        </div>
      </div>
      {reportStop && <ReportModal s={reportStop} onClose={() => setReportStop(null)} />}
      {letterCity !== null && <LetterModal data={data} initial={q.trim()} onClose={() => setLetterCity(null)} />}
    </div>
  );
}

// מחולל מכתב פנייה לרשות — רשימת הליקויים בעיר, מוכן להעתקה/הורדה
function LetterModal({ data, initial, onClose }) {
  const ERR = ["mismatch", "reversal", "spelling", "streetvar"];
  const cities = useMemo(() => {
    const m = new Map();
    data.stops.forEach((s) => { if (ERR.includes(s.k) && s.t) m.set(s.t, (m.get(s.t) || 0) + 1); });
    return Array.from(m.entries()).sort((a, b) => b[1] - a[1]);
  }, [data]);
  const [city, setCity] = useState(() => (cities.some(([t]) => t === initial) ? initial : ""));
  const rows = city ? data.stops.filter((s) => ERR.includes(s.k) && s.t === city) : [];
  const MAX = 30;
  const letter = city ? [
    "לכבוד: עיריית/מועצת " + city + " · משרד התחבורה",
    "הנדון: ליקויים בשמות תחנות אוטובוס ב" + city,
    "",
    "שלום רב,",
    "בבדיקה שנערכה באמצעות האתר \"התחנה הבאה\" נמצאו ב" + city + " " + rows.length +
      " תחנות שבהן שם התחנה אינו תואם את הרחוב שבכתובת הרשמית (מקור: נתוני GTFS של משרד התחבורה" +
      (data.generated ? ", עדכון " + data.generated.split("-").reverse().join(".") : "") + "):",
    "",
    ...rows.slice(0, MAX).map((s) =>
      "• תחנה " + s.c + " — \"" + s.n + "\" (רחוב בכתובת: " + s.s + ", " + ((CATS[s.k] && CATS[s.k].label) || s.k) + ")" +
      (s.sug ? " — שם מוצע: " + s.sug : "")),
    ...(rows.length > MAX ? ["…ועוד " + (rows.length - MAX) + " תחנות. הרשימה המלאה זמינה באתר."] : []),
    "",
    "שמות תחנות מדויקים חיוניים להתמצאות הנוסעים. נודה לבדיקת הליקויים ולתיקונם מול מפעילי התחבורה הציבורית.",
    "",
    "נוצר באמצעות \"התחנה הבאה\": https://transit-freak.github.io/kav-bochan/next-station/",
    "בברכה,",
  ].join("\n") : "";
  function copyLetter() { navigator.clipboard && navigator.clipboard.writeText(letter); }
  function downloadLetter() {
    const blob = new Blob(["﻿" + letter], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "מכתב-תחנות-" + city + ".txt";
    a.click();
  }
  return (
    <div className="rep-overlay" onClick={onClose}>
      <div className="rep-modal" onClick={(e) => e.stopPropagation()}>
        <button className="d-x" onClick={onClose}>×</button>
        <div className="rep-h">📨 מכתב לרשות</div>
        <label className="rep-l">בחרו עיר:</label>
        <select className="rep-sel" value={city} onChange={(e) => setCity(e.target.value)}>
          <option value="">— בחרו עיר —</option>
          {cities.map(([t, n]) => <option key={t} value={t}>{t} ({n})</option>)}
        </select>
        {city && (
          <>
            <label className="rep-l">המכתב ({rows.length} תחנות):</label>
            <textarea className="rep-txt letter-txt" readOnly value={letter} />
            <div className="letter-actions">
              <button className="rep-btn" onClick={copyLetter}>📋 העתקה</button>
              <button className="rep-btn" onClick={downloadLetter}>⬇ הורדה</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// הערכת זמן הליכה ממרחק אווירי (~80 מ׳ לדקה ≈ 4.8 קמ"ש, כמו kavnav)
function walkMin(m) {
  if (m == null) return "";
  if (m < 80) return "פחות מדקה";
  return "~" + Math.round(m / 80) + " דק׳";
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

// ===== דיווח משתמשים =====
const REPORT_TO = "shlomihartman@gmail.com"; // יעד ברירת-מחדל (mailto). אפשר לשדרג לטופס ע"י window.NS_REPORT_ENDPOINT

// "בדיקה אוטומטית" — הערכת המערכת את עצמה, להצגה למדווח ולצירוף לדיווח
function autoCheck(s) {
  if (s.k === "closer") {
    const w = s.rw;
    if (w && w.cur && w.sug) {
      if (w.sug.d <= w.cur.d)
        return { tone: "ok", text: "בדיקה אוטומטית: גם בהליכה אמיתית הרחוב המוצע («" + s.ms + "» " + w.sug.d + " מ׳) קרוב יותר מהרחוב שבשם («" + s.cur + "» " + w.cur.d + " מ׳) — ההצעה כנראה מוצדקת." };
      return { tone: "warn", text: "בדיקה אוטומטית: בהליכה אמיתית דווקא הרחוב שבשם קרוב יותר — ייתכן שאין כאן צורך בשינוי." };
    }
    return { tone: "neutral", text: "בדיקה אוטומטית: ההצעה מבוססת על מרחק אווירי (אין נתוני הליכה לרחוב זה)." };
  }
  if (s.lm)
    return { tone: "ok", text: "בדיקה אוטומטית: התחנה קרויה על-שם מוסד או מקום (לא על-שם רחוב) — ככל הנראה שם תקין." };
  if (s.k === "spelling" || s.k === "uncertain")
    return { tone: "warn", text: "בדיקה אוטומטית: ההבדל בין השם לכתובת הוא ברמת אות/כתיב — ייתכן שזו אותה מילה." };
  if (s.ms) return { tone: "neutral", text: "בדיקה אוטומטית: לפי המפה הרחוב הקרוב לתחנה הוא «" + s.ms + "» (" + s.md + " מ׳); בכתובת רשום «" + s.s + "»." };
  return { tone: "neutral", text: "בדיקה אוטומטית: הרחוב בכתובת («" + s.s + "») אינו מופיע בשם התחנה." };
}

function reportText(s, reason, note) {
  const cat = (CATS[s.k] && CATS[s.k].label) || s.k;
  return [
    "דיווח על תחנה — התחנה הבאה",
    "מספר תחנה: " + s.c,
    "שם: " + s.n,
    "עיר: " + (s.t || ""),
    "קטגוריה: " + cat,
    "רחוב בכתובת: " + s.s,
    s.ms ? "רחוב לפי המפה: " + s.ms + " (" + s.md + " מ׳)" : null,
    s.k === "closer" && s.sug ? "שם מוצע: " + s.sug : null,
    "",
    "סיבת הדיווח: " + reason,
    note ? "הערה: " + note : null,
    "",
    autoCheck(s).text,
    s.la != null ? "\nמפה: https://www.google.com/maps?q=" + s.la + "," + s.lo : null,
  ].filter((x) => x != null).join("\n");
}

function mailtoUrl(subject, body) {
  return "mailto:" + REPORT_TO + "?subject=" + encodeURIComponent(subject) + "&body=" + encodeURIComponent(body);
}

// קישור אישור מהמייל: פותח Issue מוכן-מראש ב-GitHub; שליחתו (ע"י בעל המאגר בלבד)
// מוסיפה את התחנה ל-overrides.json אוטומטית דרך ה-Action approve-report.
function approveIssueUrl(s, reason, note) {
  const title = "[אישור] תחנה " + s.c;
  const body =
    "code: " + s.c + "\n" +
    "name: " + s.n + "\n" +
    "note: " + reason + (note ? " — " + note : "") + "\n\n" +
    "לחיצה על Submit new issue תאשר את התחנה כ'לא תקלה' (האישור אוטומטי, תקף כל עוד שם התחנה לא השתנה).";
  return "https://github.com/Transit-Freak/kav-bochan/issues/new?title=" + encodeURIComponent(title) + "&body=" + encodeURIComponent(body);
}

function ReportModal({ s, onClose }) {
  const [reason, setReason] = useState("זו לא תקלה — השם/הרחוב תקין");
  const [note, setNote] = useState("");
  const [done, setDone] = useState(false);
  const ac = autoCheck(s);
  function submit() {
    const body = reportText(s, reason, note);
    const subject = "דיווח: תחנה " + s.c + " — " + s.n;
    const endpoint = typeof window !== "undefined" && window.NS_REPORT_ENDPOINT;
    if (endpoint) {
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ subject, code: s.c, name: s.n, city: s.t, category: s.k, addr: s.s, mapStreet: s.ms, suggested: s.sug, reason, note, autoCheck: ac.text, message: body, approveLink: approveIssueUrl(s, reason, note) }),
      })
        .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); setDone("sent"); })
        .catch(() => { window.location.href = mailtoUrl(subject, body); setDone("mail"); });
    } else {
      window.location.href = mailtoUrl(subject, body);
      setDone("mail");
    }
  }
  return (
    <div className="rep-overlay" onClick={onClose}>
      <div className="rep-modal" onClick={(e) => e.stopPropagation()}>
        <button className="d-x" onClick={onClose}>×</button>
        {done ? (
          <div className="rep-done">
            <div className="rep-done-h">תודה! הדיווח נשלח 🙏</div>
            <div className="rep-sub">
              {done === "sent"
                ? "הדיווח הגיע למנהל האתר וייבדק בהקדם."
                : "אם נפתחה תוכנת המייל — יש לשלוח את ההודעה כדי להשלים את הדיווח."}
            </div>
            <button className="rep-btn" onClick={onClose}>סגירה</button>
          </div>
        ) : (
          <>
            <div className="rep-h">דיווח על התחנה</div>
            <div className="rep-stop"><b>{s.n}</b> · {s.t} · מס׳ {s.c}</div>
            <div className={"rep-auto " + ac.tone}>🤖 {ac.text}</div>
            <label className="rep-l">מה הבעיה?</label>
            <select className="rep-sel" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option>זו לא תקלה — השם/הרחוב תקין</option>
              <option>ההצעה שגויה / השם המוצע לא מתאים</option>
              <option>טעות אחרת בפרטי התחנה</option>
              <option>אחר</option>
            </select>
            <label className="rep-l">פרטים (לא חובה):</label>
            <textarea className="rep-txt" value={note} onChange={(e) => setNote(e.target.value)} placeholder="כל מה שיעזור לי לבדוק…" />
            <button className="rep-btn" onClick={submit}>שליחת הדיווח</button>
            <div className="rep-foot">הדיווח נשלח לבדיקה ידנית של מנהל האתר.</div>
          </>
        )}
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
