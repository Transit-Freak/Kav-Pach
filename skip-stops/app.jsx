/* הקו המדלג — ניסוי: קווים עירוניים שחולפים ליד תחנה פעילה בלי לעצור בה.
   הנתונים: skip-stops/data.json, נוצר ע"י tools/skiplines.py ב-GitHub Actions. */
const { useState, useEffect, useMemo, useRef, useDeferredValue } = React;
const BUILD = window.SK_BUILD || "0";
const PAGE = 100;

function fmtM(m) { return m >= 1000 ? (m / 1000).toFixed(1) + ' ק"מ' : Math.round(m) + " מ'"; }

/* ---------- מפה ---------- */
function SkipMap({ it, route }) {
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
  }, [it, route]);

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
function Detail({ it, shapes }) {
  const nSkip = (it.skippers || []).length;
  return (
    <div className="detail">
      <SkipMap it={it} route={shapes && it.shp ? shapes[it.shp] : null} />
      <div className="legend">
        <span><i className="dot red" /> התחנה המדולגת</span>
        <span><i className="dot green" /> תחנות שהקו כן עוצר בהן</span>
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
          {(it.others || []).map((o) => <span key={o} className="chip">{o}</span>)}
          {it.onum > (it.others || []).length ? " ועוד…" : ""}
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
        <p className="mut">
          ייתכן שיש סיבה מוצדקת — נתיב נסיעה שממנו אי-אפשר לעצור, עומס במפרץ, או החלטת תכנון מכוונת.
          הממצא מבוסס על השוואת מסלול הקו (GTFS) לרצף התחנות שלו בלבד.
        </p>
      </div>
    </div>
  );
}

/* ---------- שורה ---------- */
const Row = React.memo(function Row({ it, open, onToggle, shapes }) {
  return (
    <div className={"it" + (open ? " open" : "")}>
      <button className="it-head" onClick={onToggle}>
        <span className="line-badge">{it.line}</span>
        <span className="it-main">
          <span className="it-title">מדלג על: {it.stop} <span className="code">({it.code})</span></span>
          <span className="it-sub">{it.city} · עוצר {fmtM(it.before)} לפני ו-{fmtM(it.after)} אחרי · {it.onum} קווים כן עוצרים{it._sys ? <span className="tag-sys">שיטתי</span> : null}</span>
        </span>
        <span className="arrow">{open ? "▲" : "▼"}</span>
      </button>
      {open && <Detail it={it} shapes={shapes} />}
    </div>
  );
});

/* ---------- אפליקציה ---------- */
function App() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [city, setCity] = useState("");
  const [q, setQ] = useState("");
  const [openKey, setOpenKey] = useState(null);
  const [page, setPage] = useState(1);
  const [showSys, setShowSys] = useState(false);
  const dq = useDeferredValue(q);

  useEffect(() => {
    fetch("data.json?v=" + BUILD)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(setData)
      .catch((e) => setErr(e));
  }, []);

  const items = useMemo(() => {
    if (!data) return [];
    const raw = (data.items || []).map((it, i) => ({ ...it, _k: it.line + "@" + it.sid, _i: i,
      _q: (it.line + " " + it.stop + " " + it.code + " " + it.city).toLowerCase() }));
    // "דילוג שיטתי" — כשכמה קווים מדלגים על אותה תחנה (תכנון ציר, כמו דרך בגין
    // בת"א) זה כנראה מכוון ולא טעות. קו בודד שמדלג על הרבה תחנות רק מסומן בהערה.
    const perLine = {};
    raw.forEach((it) => { const k = it.line + "@" + it.city; perLine[k] = (perLine[k] || 0) + 1; });
    raw.forEach((it) => {
      it._lt = perLine[it.line + "@" + it.city];
      it._sys = (it.skippers || []).length >= 3;
    });
    return raw;
  }, [data]);

  const filtered = useMemo(() => {
    const needle = dq.trim().toLowerCase();
    return items.filter((it) => {
      if (!showSys && it._sys) return false;
      if (city && it.city !== city) return false;
      if (!needle) return true;
      if (it.line === needle) return true;
      return it._q.includes(needle);
    });
  }, [items, city, dq, showSys]);

  useEffect(() => { setPage(1); }, [city, dq, showSys]);

  if (err) return <div className="boot">שגיאה בטעינת הנתונים — ייתכן שההרצה הראשונה עוד לא הסתיימה. נסו לרענן מאוחר יותר.</div>;
  if (!data) return <div className="boot">טוען נתונים…</div>;

  const cities = data.cities || [];
  const byCity = {};
  items.forEach((it) => { byCity[it.city] = (byCity[it.city] || 0) + 1; });
  const sysN = items.filter((it) => it._sys).length;
  const shown = filtered.slice(0, page * PAGE);

  return (
    <div className="wrap">
      <header>
        <h1>🚌 הקו המדלג <span className="beta">ניסיוני</span></h1>
        <p className="tag">
          קווים עירוניים שעוברים ממש ליד תחנה פעילה, עוצרים בתחנה שלפניה ובתחנה שאחריה — אבל עליה מדלגים.
        </p>
        <div className="stats">
          <span className="stat"><b>{data.total}</b> ממצאים בכל הארץ</span>
          {cities.slice(0, 4).map((c) => <span key={c} className="stat">{c}: <b>{byCity[c] || 0}</b></span>)}
          <span className="stat mut">עודכן: {data.gen}</span>
        </div>
      </header>

      <div className="explain">
        <b>איך זה עובד?</b> משווים את מסלול הנסיעה של כל קו עירוני (GTFS של משרד התחבורה) לרצף התחנות
        שהוא עוצר בהן. תחנה נחשבת "מדולגת" רק אם הקו עובר עד 25 מ' ממנה, בצד הנכון של הכביש, נוסע לאורך
        הרחוב (לא רק חוצה אותו), ועוצר בתחנות משני צדדיה במרחק סביר. קווי תלמידים, שאטלים (חנה וסע),
        קווים בין-עירוניים ואזוריים לא נבדקים — להם מותר לדלג. בנוסף, המערכת בודקת אם עוד קווים עושים
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

      <div className="count">{filtered.length === items.length ? "" : filtered.length + " תוצאות"}</div>

      <div className="list">
        {shown.map((it) => (
          <Row key={it._k} it={it} open={openKey === it._k} shapes={data.shapes}
            onToggle={() => setOpenKey(openKey === it._k ? null : it._k)} />
        ))}
        {shown.length === 0 && <div className="empty">לא נמצאו תוצאות.</div>}
        {filtered.length > shown.length && (
          <button className="more-btn" onClick={() => setPage(page + 1)}>
            הצגת עוד ({filtered.length - shown.length} נוספים)
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
