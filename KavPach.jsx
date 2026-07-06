const { useState, useMemo, useEffect, useCallback, useRef } = React;

// ── Google Fonts - Heebo ──────────────────────────────────────────────────
if (typeof document !== 'undefined' && !document.getElementById('heebo-font')) {
  const fontLink = document.createElement("link");
  fontLink.id = "heebo-font";
  fontLink.href = "https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700;800;900&display=swap";
  fontLink.rel = "stylesheet";
  document.head.appendChild(fontLink);
}

// ── XLSX loader ──────────────────────────────────────────────────────────────
let _xlsxLoaded = false;
const loadXLSX = () => {
  if (_xlsxLoaded) return Promise.resolve();
  return new Promise((res, rej) => {
    const src = "https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js";
    if (typeof window !== 'undefined' && document.querySelector(`script[src="${src}"]`)) { 
      _xlsxLoaded = true; 
      return res(); 
    }
    const s = document.createElement("script");
    s.src = src; s.onload = () => { _xlsxLoaded = true; res(); }; s.onerror = rej;
    document.head.appendChild(s);
  });
};

// yields control to the browser so it can paint / handle input.
// setTimeout(0) is more aggressive than rAF — rAF can pile up when the next chunk
// of JS is already queued, which is exactly when we *want* the UI to breathe.
const yieldFrame = () => new Promise(r => setTimeout(r, 0));

const CitiesDatalist = React.memo(function CitiesDatalist({ cities }) {
  return (
    <datalist id="cities-list">
      {cities.map(c => <option key={`dl-city-${c}`} value={c} />)}
    </datalist>
  );
});

// ── SearchInput ─────────────────────────────────────────────
// אינפוט חיפוש שמופעל בלחיצה / Enter בלבד — בלי דיבאונס, בלי עדכון אוטומטי.
// state פנימי לטקסט; הסינון בהורה רץ רק כשהמשתמש לוחץ "חפש" או Enter,
// או מנקה את השדה (clear -> ריקון מיידי כדי לחזור לתצוגה המלאה).
//
// הערה — לא מצרפים datalist בשלב הזה: על קבצי נתונים עם מאות ערים, הדפדפן
// סורק את כל ה-<option>-ים בכל הקלדה ויוצר לאג מורגש (בעיקר בנייד), אפילו
// ש-state הריאקטי נשאר מקומי. עדיף UX של חיפוש חופשי.
const SearchInput = React.memo(function SearchInput({ value, onSubmit, placeholder, className }) {
  const [local, setLocal] = React.useState(value || '');
  const lastExternal = React.useRef(value);
  React.useEffect(() => {
    if (value !== lastExternal.current) {
      lastExternal.current = value;
      setLocal(value || '');
    }
  }, [value]);
  const submit = (v) => {
    const trimmed = (v ?? local).trim();
    lastExternal.current = trimmed;
    if (React.startTransition) {
      React.startTransition(() => onSubmit(trimmed));
    } else {
      onSubmit(trimmed);
    }
  };
  const clear = () => {
    setLocal('');
    submit('');
  };
  const handleKey = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
    if (e.key === 'Escape') { e.preventDefault(); clear(); }
  };
  const isDirty = local !== (value || '');
  return (
    <div className="relative w-full">
      <input
        type="text"
        value={local}
        onChange={e => setLocal(e.target.value)}
        onKeyDown={handleKey}
        placeholder={placeholder}
        className={className}
      />
      {local && (
        <button
          type="button"
          onClick={clear}
          className="absolute top-1/2 -translate-y-1/2 left-3 w-6 h-6 rounded-full bg-slate-200 hover:bg-slate-300 text-slate-600 font-black text-sm flex items-center justify-center transition-colors"
          title="נקה"
          aria-label="נקה"
        >×</button>
      )}
      {isDirty && (
        <div className="absolute -bottom-5 right-2 text-[10px] font-bold text-slate-400">הקש Enter לחיפוש</div>
      )}
    </div>
  );
});

// ── IndexedDB cache ─────────────────────────────────────────────
// שומרים את התוצאה המעובדת (trips + מאפים + טבלת בנצ'מרק) ב-IndexedDB,
// תחת מפתח משולב מ-last-modified+content-length של כל קבצי המקור. בכניסה
// הבאה, אם אף קובץ לא השתנה, מדלגים על ההורדה ועל הפרסור (~50-80% מזמן הטעינה).
// Maps ו-Sets נשמרים native בזכות structured clone של IDB.
const IDB_NAME = 'kavpach-cache';
const IDB_STORE = 'parsed';
const IDB_KEY = 'data-v3';

const openCacheDB = () => new Promise((resolve, reject) => {
  if (typeof indexedDB === 'undefined') { reject(new Error('no idb')); return; }
  const req = indexedDB.open(IDB_NAME, 1);
  req.onupgradeneeded = () => req.result.createObjectStore(IDB_STORE);
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});

const idbGetCache = async (key) => {
  try {
    const db = await openCacheDB();
    return await new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, 'readonly');
      const req = tx.objectStore(IDB_STORE).get(key);
      req.onsuccess = () => res(req.result);
      req.onerror = () => rej(req.error);
    });
  } catch (e) {
    return null;
  }
};

const idbSetCache = async (key, value) => {
  try {
    const db = await openCacheDB();
    await new Promise((res, rej) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => res();
      tx.onerror = () => rej(tx.error);
    });
  } catch (e) { /* silent — cache is best-effort */ }
};

// מפיק מפתח קאש מהכותרות של תגובת HTTP. last-modified יציב, content-length
// תופס שינוי גם אם השרת מחזיר תאריכי last-modified זהים בטעות.
const fileKeyFromHeaders = (res) => {
  if (!res) return null;
  const lm = res.headers.get('last-modified') || '';
  const cl = res.headers.get('content-length') || '';
  const et = res.headers.get('etag') || '';
  if (!lm && !cl && !et) return null;
  return `${lm}|${cl}|${et}`;
};

// ── DebouncedInput ────────────────────────────────────────────────────────
// אינפוט חיפוש שלא מ-re-render-ר את כל העץ בכל הקלדה.
// state פנימי מקומי לטקסט; הפרנט מקבל את הערך רק אחרי debounce.
// אם value מבחוץ משתנה (e.g. setSearchCity(areaName) מטאב אחר) — מסונכרן.
const DebouncedInput = React.memo(function DebouncedInput({ value, onDebouncedChange, debounceMs = 250, ...rest }) {
  const [local, setLocal] = React.useState(value || '');
  const lastExternal = React.useRef(value);
  const timerRef = React.useRef(null);
  React.useEffect(() => {
    if (value !== lastExternal.current) {
      lastExternal.current = value;
      setLocal(value || '');
    }
  }, [value]);
  const handleChange = (e) => {
    const v = e.target.value;
    setLocal(v);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      lastExternal.current = v;
      // startTransition מסמן את העדכון הזה כעדיפות נמוכה — React רשאי לקטוע
      // אותו אם המשתמש ממשיך להקליד. ככה הסינון הכבד לא חוסם את ה-input.
      if (React.startTransition) {
        React.startTransition(() => onDebouncedChange(v));
      } else {
        onDebouncedChange(v);
      }
    }, debounceMs);
  };
  return <input {...rest} value={local} onChange={handleChange} />;
});

// ── Icons ────────────────────────────────────────────────────────────────────
const ICONS = {
  trash: "M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2M10 11v6M14 11v6",
  upload: "M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12",
  download: "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4",
  search: "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z",
  clock:  "M12 2a10 10 0 100 20A10 10 0 0012 2zm0 5v5l3 3",
  zap:    "M13 10V3L4 14h7v7l9-11h-7z",
  loader: "M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4",
  calendar: "M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z",
  list: "M4 6h16M4 12h16M4 18h16",
  alert: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  info: "M13 16h-1v-4h-1m1-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z",
  chevronUp: "M5 15l7-7 7 7",
  chevronDown: "M19 9l-7 7-7-7",
  settings: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
  moon: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
  chart: "M18 20V10 M12 20V4 M6 20V16",
  mapPin: "M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z M15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  copy: "M8 5H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2 M16 3h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h2",
  star: "M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z",
};

const Ic = ({ n, size = 18, cls = "", animate = false, strokeWidth = "2.5" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={`${cls} ${animate ? "animate-spin" : ""}`}>
    <path d={ICONS[n] || ""} />
  </svg>
);

// ── פונקציות עזר ─────────────────────────────────────────────────────────────
const fmtTime = (v) => {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number") {
    const totalMins = Math.round(v * 1440);
    const h = Math.floor(totalMins / 60) % 24;
    const m = totalMins % 60;
    return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}`;
  }
  const s = String(v).trim();
  if (/^\d{1,2}:\d{2}/.test(s)) return s.slice(0, 5);
  return s;
};

const timeToMins = (t) => {
  if (!t || !t.includes(':')) return null;
  const [h, m] = t.split(':').map(Number);
  if (h > 29 || m > 59) return null;
  return h * 60 + m;
};

const getPeriod = (mins) => {
  if (mins === null) return "לא ידוע";
  if (mins < 360) return "לילה";
  if (mins < 600) return "בוקר";
  if (mins < 960) return "צהריים";
  if (mins < 1140) return "ערב";
  return "לילה";
};

const getLineCategory = (typeStr) => {
  if (!typeStr) return 'urban';
  const t = typeStr.replace(/\s/g, '');
  if (t.includes('אזורי') || t.includes('מועצה')) return 'regional';
  if (t.includes('בין') || t.includes('בינעירוני')) return 'intercity';
  return 'urban';
};

// ── סיווג קווים ל-8 קטגוריות לפי משרד התחבורה ───────────────────────────
// הסיווג מבוסס קודם כל על השדה "קבוצת יעילות תפעולית" (opGroup) אם הוא
// זמין, ואחרת נגזר ממאפיינים: ייחודיות (תלמידים/לילה/מזין), אורך מסלול,
// סוג שירות, ותדירות יומית.
const CATEGORIES = [
  'אזורי',
  'בינעירוני ארוך',
  'בינעירוני קצר',
  'עירוני תדירות גבוהה',
  'עירוני תדירות נמוכה',
  'לילה',
  'קווים מזינים',
  'תלמידים',
];

// ממוצעים ארציים רשמיים — עלות תפעולית לנוסע (ש"ח)
const COST_BENCHMARK = {
  'אזורי': 31.8,
  'בינעירוני ארוך': 34.0,
  'בינעירוני קצר': 23.1,
  'לילה': 46.9,
  'עירוני תדירות גבוהה': 9.4,
  'עירוני תדירות נמוכה': 15.4,
  'קווים מזינים': 17.4,
  'תלמידים': 9.7,
};

// מיפוי שמות מקובץ "מצומצם" → לשמות בטבלת "עלות לנוסע" (הבדלי איות קלים)
const BENCHMARK_DISTRICT_ALIAS = {
  'גולן גליל ועמקים': 'גולן גליל עמקים',
  'מזרח ירושלים': 'מזרח י-ם',
};
const BENCHMARK_GROUP_ALIAS = {
  'קווים מזינים': 'מזינים',
};

// מחזיר בנצ'מרק עלות-לנוסע לפי קטגוריה+מחוז מטבלת "עלות לנוסע" הנטענת.
// נופל ל"כל הארץ" ואז לקבועים הארציים אם אין נתון מחוזי.
const lookupCostBenchmark = (table, category, district) => {
  const cat = BENCHMARK_GROUP_ALIAS[category] || category;
  if (table && table[cat]) {
    const row = table[cat];
    const dist = BENCHMARK_DISTRICT_ALIAS[district] || district;
    if (dist && row[dist] != null) return row[dist];
    if (row['כל הארץ'] != null) return row['כל הארץ'];
  }
  return COST_BENCHMARK[category] || 20;
};

// סף נוסעים לנסיעת שפל לכל קטגוריה
const LOW_RIDER_THRESHOLD = {
  'אזורי': 5,
  'לילה': 5,
  'בינעירוני קצר': 8,
  'קווים מזינים': 8,
  'בינעירוני ארוך': 10,
  'עירוני תדירות נמוכה': 10,
  'עירוני תדירות גבוהה': 15,
  'תלמידים': 15,
};

// מסווג קו לאחת מ-8 הקטגוריות. מקבל אובייקט עם השדות שצריך.
const classifyLine = ({ opGroup, uniqueness, lineType, distance, trips, isNight, isFeeding }) => {
  const og = (opGroup || '').trim();
  const u = (uniqueness || '').trim();

  // 1. הקטגוריות הברורות מ-uniqueness — ייחודיות גוברת
  if (u.includes('תלמיד')) return 'תלמידים';
  if (isNight || u.includes('לילה')) return 'לילה';
  if (isFeeding || u.includes('מזין')) return 'קווים מזינים';

  // 2. opGroup ישיר אם קיים בקטגוריות שלנו
  for (const c of CATEGORIES) {
    if (og === c) return c;
    // התאמה רכה — opGroup לעיתים מכיל את שם הקטגוריה כתת-מחרוזת
    if (og && og.includes(c)) return c;
  }

  // 3. נגזרים מ-lineType
  const lt = (lineType || '').trim();
  if (lt.includes('אזורי') || lt.includes('מועצה') || lt.includes('כפרי')) return 'אזורי';

  // 4. בינעירוני לפי אורך מסלול
  if (lt.includes('בינעירוני') || lt.includes('בין-עירוני') || lt.includes('בין עירוני')) {
    return (distance && distance > 45) ? 'בינעירוני ארוך' : 'בינעירוני קצר';
  }

  // 5. עירוני — תדירות גבוהה/נמוכה לפי נסיעות שבועיות (מקירוב ליום ג')
  //    100 נסיעות ביום ג' ≈ ~600 נסיעות שבועיות (יום-ג' הוא ~17% מהשבוע)
  if (trips && trips >= 600) return 'עירוני תדירות גבוהה';
  return 'עירוני תדירות נמוכה';
};

// תווית סטטוס לפי ציון (5 רמות)
const STATUS_TIERS = [
  { min: 80, label: 'חמור - דורש התערבות', color: 'text-rose-700', bg: 'bg-rose-100 border-rose-300', dot: 'bg-rose-600' },
  { min: 65, label: 'לא יעיל',              color: 'text-rose-600', bg: 'bg-rose-50 border-rose-200',  dot: 'bg-rose-500' },
  { min: 45, label: 'טעון בדיקה',           color: 'text-orange-600', bg: 'bg-orange-50 border-orange-200', dot: 'bg-orange-500' },
  { min: 25, label: 'סטייה קלה',            color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200', dot: 'bg-amber-500' },
  { min: 0,  label: 'תקין',                color: 'text-emerald-700', bg: 'bg-emerald-50 border-emerald-200', dot: 'bg-emerald-500' },
];
const getStatusTier = (score) => STATUS_TIERS.find(t => score >= t.min) || STATUS_TIERS[STATUS_TIERS.length - 1];

const getCapacity = (sizeStr) => {
  if (!sizeStr) return 50;
  const s = String(sizeStr).replace(/\s/g, '');
  if (s.includes("מפרקי")) return 90;
  if (s.includes("מידי")) return 35;
  if (s.includes("מיני")) return 19;
  return 50; 
};

const parseDays = (raw) => {
  if (!raw || String(raw).trim() === "undefined") return { list: [], text: "כללי" };
  let s = String(raw).trim();
  
  if (!/[1-7]/.test(s)) {
    let mapped = "";
    if (s.includes('ראשון') || /(^|\s)א('|\b)/.test(s)) mapped += '1';
    if (s.includes('שני') || /(^|\s)ב('|\b)/.test(s)) mapped += '2';
    if (s.includes('שלישי') || /(^|\s)ג('|\b)/.test(s)) mapped += '3';
    if (s.includes('רביעי') || /(^|\s)ד('|\b)/.test(s)) mapped += '4';
    if (s.includes('חמישי') || /(^|\s)ה('|\b)/.test(s)) mapped += '5';
    if (s.includes('שישי') || /(^|\s)ו('|\b)/.test(s)) mapped += '6';
    if (s.includes('שבת') || s.includes('מוצ')) mapped += '7';
    if (s.includes('חול') || s.includes("ב'-ה'") || s.includes('ב-ה')) mapped += '2345';
    s += mapped;
  }

  const matches = s.match(/[1-7]/g);
  const list = matches ? Array.from(new Set(matches)).sort() : [];
  if (list.length > 0) {
    const joined = list.join('');
    if (joined === '12345') return { list, text: "א'-ה'" };
    if (joined === '123456') return { list, text: "א'-ו'" };
    if (joined === '2345') return { list, text: "ב'-ה'" };
    if (joined === '1234567') return { list, text: "כל השבוע" };
    
    const names = {'1':'ראשון','2':'שני','3':'שלישי','4':'רביעי','5':'חמישי','6':'שישי','7':'שבת'};
    return { list, text: list.map(d => names[d]).join(', ') };
  }
  return { list, text: String(raw).trim() };
};

const parseCity = (stopName) => {
  if (!stopName) return "";
  const s = String(stopName);
  const idx = s.indexOf(' - ');
  return idx > 0 ? s.slice(0, idx).trim() : s.split('/')[0].trim();
};

const cityOnlyStr = (s) => s ? (s.indexOf(' - ') > 0 ? s.slice(0, s.indexOf(' - ')).trim() : s.split('/')[0].trim()) : '';

// רכיב לעיצוב המק"ט, הכיוון והחלופה בתגיות ברורות (Badge style)
const RouteFormat = ({ val }) => {
  if (!val) return null;
  const parts = String(val).split('-');
  const makat = parts[0] || '';
  const dir = parts[1] || '';
  const alt = parts[2] && parts[2] !== '0' && parts[2] !== '#' ? parts[2] : '';
  
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5 whitespace-nowrap text-[11px]" dir="rtl">
      <span className="bg-slate-100 border border-slate-200 px-2 py-0.5 rounded text-slate-600 font-medium shadow-sm">
        מק&quot;ט: <strong className="font-black text-slate-900">{makat}</strong>
      </span>
      {dir && (
        <span className="bg-slate-100 border border-slate-200 px-2 py-0.5 rounded text-slate-600 font-medium shadow-sm">
          כיוון: <strong className="font-black text-slate-900">{dir}</strong>
        </span>
      )}
      {alt && (
        <span className="bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded text-indigo-800 font-medium shadow-sm">
          חלופה: <strong className="font-black">{alt}</strong>
        </span>
      )}
    </div>
  );
};

// ── BusArt — אוטובוס SVG. variant: 'scrap' (לבן, לפח) או 'gold' (מוזהב) ──
const BusArt = ({ variant = 'scrap', className = '' }) => {
  const gold = variant === 'gold';
  const gid = gold ? 'busGold' : 'busScrap';
  const winFill = gold ? '#fffbeb' : '#dbeafe';
  const winStroke = gold ? '#92400e' : '#bfdbfe';
  return (
    <svg viewBox="0 0 170 96" className={className} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          {gold ? (
            <>
              <stop offset="0%" stopColor="#fef3c7" />
              <stop offset="45%" stopColor="#fbbf24" />
              <stop offset="100%" stopColor="#d97706" />
            </>
          ) : (
            <>
              <stop offset="0%" stopColor="#ffffff" />
              <stop offset="100%" stopColor="#eef2f6" />
            </>
          )}
        </linearGradient>
      </defs>
      {/* גוף */}
      <rect x="8" y="20" width="154" height="50" rx="12" fill={`url(#${gid})`} stroke={gold ? '#b45309' : '#cbd5e1'} strokeWidth="3.5" />
      {/* פס צד */}
      <rect x="8" y="47" width="154" height="7" fill={gold ? '#b45309' : '#e2e8f0'} opacity="0.6" />
      {/* חלונות */}
      {[26, 54, 82, 110].map((x, i) => (
        <rect key={i} x={x} y="27" width="22" height="15" rx="3" fill={winFill} stroke={winStroke} strokeWidth="1.5" />
      ))}
      {/* דלת */}
      <rect x="138" y="27" width="16" height="30" rx="3" fill={winFill} stroke={winStroke} strokeWidth="1.5" />
      {/* פנס */}
      <circle cx="158" cy="63" r="3" fill={gold ? '#fde68a' : '#fbbf24'} />
      {/* גלגלים */}
      <circle cx="44" cy="72" r="11" fill="#0f172a" />
      <circle cx="44" cy="72" r="4.5" fill={gold ? '#fbbf24' : '#94a3b8'} />
      <circle cx="124" cy="72" r="11" fill="#0f172a" />
      <circle cx="124" cy="72" r="4.5" fill={gold ? '#fbbf24' : '#94a3b8'} />
      {gold && <circle cx="30" cy="31" r="3" fill="#ffffff" opacity="0.85" />}
    </svg>
  );
};

// ── TrashBin — פח אשפה ────────────────────────────────────────────────
const TrashBin = ({ className = '' }) => (
  <svg viewBox="0 0 120 120" className={className} xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    <rect x="52" y="18" width="16" height="10" rx="2" fill="#1e293b" />
    <rect x="18" y="26" width="84" height="12" rx="3" fill="#334155" />
    <path d="M26 40 L94 40 L86 112 Q85 116 81 116 L39 116 Q35 116 34 112 Z" fill="#475569" />
    <path d="M46 48 L51 108" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />
    <path d="M60 48 L60 108" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />
    <path d="M74 48 L69 108" stroke="#64748b" strokeWidth="4" strokeLinecap="round" />
  </svg>
);

// ── ChoiceScreen — מסך פתיחה: בחירה בין קו פח להקו המוזהב ──────────────
function ChoiceScreen({ onPick }) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 flex items-center justify-center p-4" dir="rtl" style={{ fontFamily: "'Heebo', sans-serif" }}>
      <div className="max-w-7xl w-full">
        <div className="text-center mb-10">
          <h1 className="text-4xl md:text-5xl font-[900] text-slate-900 tracking-tight">הקו הבוחן</h1>
          <p className="text-slate-500 font-bold mt-3 text-base md:text-lg">חמישה כלים לניתוח התחבורה הציבורית — במה לבחור?</p>
        </div>

        <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-6">
          {/* קו פח */}
          <button
            onClick={() => onPick('kavpach')}
            className="group relative overflow-hidden bg-slate-900 rounded-[2.5rem] p-8 text-right shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-300"
          >
            <div className="absolute -left-8 -top-8 w-44 h-44 bg-slate-800 rounded-full opacity-50" />
            <div className="relative">
              <div className="relative h-32 mb-5">
                {/* אוטובוס "גרוטאה" (מאחור) */}
                <BusArt
                  variant="scrap"
                  className="w-32 absolute z-0 drop-shadow-xl transition-transform duration-300 group-hover:translate-y-1.5"
                />
                {/* פח אשפה (מקדימה) */}
                <TrashBin
                  className="w-24 h-24 absolute bottom-0 z-10 drop-shadow-md"
                />
              </div>
              <h2 className="text-3xl font-[900] text-white">קו פח</h2>
              <p className="text-slate-300 font-bold mt-2 text-sm leading-relaxed">קווים ריקים ובזבזניים — מועמדים לביטול או צמצום</p>
              <span className="inline-flex items-center gap-2 mt-5 bg-white text-slate-900 px-5 py-2.5 rounded-2xl font-black text-sm group-hover:gap-3.5 transition-all">כניסה <span>←</span></span>
            </div>
          </button>

          {/* הקו המוזהב */}
          <button
            onClick={() => onPick('golden')}
            className="group relative overflow-hidden rounded-[2.5rem] p-8 text-right shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-300"
            style={{ background: 'linear-gradient(155deg,#1f2937 0%,#3b2f12 52%,#92400e 100%)' }}
          >
            <div className="absolute -left-8 -top-8 w-44 h-44 rounded-full opacity-25" style={{ background: '#fbbf24' }} />
            <div className="relative">
              <div className="flex items-center justify-end mb-6 h-28">
                <BusArt variant="gold" className="w-40 drop-shadow-xl transition-transform duration-300 group-hover:-translate-y-1 group-hover:rotate-2" />
              </div>
              <h2 className="text-3xl font-[900] text-amber-300">הקו המוזהב</h2>
              <p className="text-amber-100/80 font-bold mt-2 text-sm leading-relaxed">הקווים המצטיינים — הסטנדרט שאליו כדאי לשאוף</p>
              <span className="inline-flex items-center gap-2 mt-5 bg-amber-400 text-amber-950 px-5 py-2.5 rounded-2xl font-black text-sm group-hover:gap-3.5 transition-all">כניסה <span>←</span></span>
            </div>
          </button>

          {/* קו באג — פרויקט עצמאי בריפו נפרד (kav-bug); שם הגרסה החיה והמתעדכנת */}
          <a
            href="https://transit-freak.github.io/kav-bug/"
            className="group relative block overflow-hidden rounded-[2.5rem] p-8 text-right shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-300"
            style={{ background: 'linear-gradient(155deg,#1e1b4b 0%,#312e81 55%,#4338ca 100%)' }}
          >
            <div className="absolute -left-8 -top-8 w-44 h-44 rounded-full opacity-25" style={{ background: '#6366f1' }} />
            <div className="relative">
              <div className="flex items-center justify-end mb-6 h-28">
                {/* מוטיב המסלול של "קו באג": קו-ייחוס ירוק וזיגזג הסטייה הכתום */}
                <svg viewBox="0 0 140 90" className="w-40 drop-shadow-xl transition-transform duration-300 group-hover:-translate-y-1" xmlns="http://www.w3.org/2000/svg">
                  <line x1="18" y1="64" x2="122" y2="64" stroke="#1f9d57" strokeWidth="10" strokeLinecap="round" />
                  <polyline points="18,64 44,18 70,64 96,18 122,64" fill="none" stroke="#ef8a17" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
                  <circle cx="18" cy="64" r="9" fill="#fff" />
                  <circle cx="122" cy="64" r="9" fill="#fff" />
                </svg>
              </div>
              <h2 className="text-3xl font-[900] text-indigo-200">קו באג</h2>
              <p className="text-indigo-100/80 font-bold mt-2 text-sm leading-relaxed">תקלות גאומטריות במסלולי הקווים — עיקופים ובליטות מיותרים</p>
              <span className="inline-flex items-center gap-2 mt-5 bg-indigo-400 text-indigo-950 px-5 py-2.5 rounded-2xl font-black text-sm group-hover:gap-3.5 transition-all">כניסה <span>←</span></span>
            </div>
          </a>

          {/* התחנה הבאה — כלי נפרד (אפליקציה עצמאית בתיקיית next-station/) */}
          <a
            href="next-station/"
            className="group relative block overflow-hidden rounded-[2.5rem] p-8 text-right shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-300"
            style={{ background: 'linear-gradient(155deg,#0b2545 0%,#13386e 52%,#2563eb 100%)' }}
          >
            <div className="absolute -left-8 -top-8 w-44 h-44 rounded-full opacity-25" style={{ background: '#60a5fa' }} />
            <div className="relative">
              <div className="flex items-center justify-between mb-6 h-28">
                <span className="bg-sky-400 text-sky-950 px-3 py-1 rounded-full text-[11px] font-black self-start">חדש</span>
                {/* הסמל של "התחנה הבאה" — זהה לאתר עצמו (אמוג'י תחנת אוטובוס 🚏) */}
                <span className="drop-shadow-xl transition-transform duration-300 group-hover:-translate-y-1" style={{ fontSize: '90px', lineHeight: 1 }}>🚏</span>
              </div>
              <h2 className="text-3xl font-[900] text-sky-200">התחנה הבאה</h2>
              <p className="text-sky-100/80 font-bold mt-2 text-sm leading-relaxed">תחנות ששמן אינו תואם לרחוב שבכתובת</p>
              <span className="inline-flex items-center gap-2 mt-5 bg-sky-400 text-sky-950 px-5 py-2.5 rounded-2xl font-black text-sm group-hover:gap-3.5 transition-all">כניסה <span>←</span></span>
            </div>
          </a>

          {/* הקו המדלג — ניסוי חדש (אפליקציה עצמאית בתיקיית skip-stops/) */}
          <a
            href="skip-stops/"
            className="group relative block overflow-hidden rounded-[2.5rem] p-8 text-right shadow-xl hover:shadow-2xl hover:-translate-y-1 transition-all duration-300"
            style={{ background: 'linear-gradient(155deg,#451a03 0%,#7c2d12 52%,#d97706 100%)' }}
          >
            <div className="absolute -left-8 -top-8 w-44 h-44 rounded-full opacity-25" style={{ background: '#f59e0b' }} />
            <div className="relative">
              <div className="flex items-center justify-between mb-6 h-28">
                <span className="bg-amber-400 text-amber-950 px-3 py-1 rounded-full text-[11px] font-black self-start">ניסיוני</span>
                {/* הסמל של "הקו המדלג" — אוטובוס מקפץ מעל תחנה (זהה ל-favicon של הכלי) */}
                <svg viewBox="4 4 26 26" style={{ width: '96px', height: '96px' }} className="drop-shadow-xl transition-transform duration-300 group-hover:-translate-y-1" xmlns="http://www.w3.org/2000/svg">
                  <path d="M4 26 L10 26 Q17 15 24 26 L30 26" stroke="#fde68a" strokeWidth="2" fill="none" strokeDasharray="2.5 2" strokeLinecap="round" />
                  <circle cx="17" cy="26" r="2.6" fill="#7c2d12" stroke="#fff" strokeWidth="1.4" />
                  <circle cx="7" cy="26" r="2.6" fill="#fff" />
                  <circle cx="27" cy="26" r="2.6" fill="#fff" />
                  <rect x="10" y="6" width="14" height="9" rx="2.5" fill="#fff" />
                  <rect x="12" y="8" width="4" height="3.5" rx="1" fill="#d97706" />
                  <rect x="18" y="8" width="4" height="3.5" rx="1" fill="#d97706" />
                  <circle cx="13" cy="15" r="1.6" fill="#7c2d12" />
                  <circle cx="21" cy="15" r="1.6" fill="#7c2d12" />
                </svg>
              </div>
              <h2 className="text-3xl font-[900] text-amber-200">הקו המדלג</h2>
              <p className="text-amber-100/80 font-bold mt-2 text-sm leading-relaxed">קווים שחולפים ליד תחנה פעילה — בלי לעצור בה</p>
              <span className="inline-flex items-center gap-2 mt-5 bg-amber-400 text-amber-950 px-5 py-2.5 rounded-2xl font-black text-sm group-hover:gap-3.5 transition-all">כניסה <span>←</span></span>
            </div>
          </a>
        </div>

        <p className="text-center text-slate-400 font-bold text-xs mt-8">נבנה על ידי שלמה הרטמן</p>
      </div>
    </div>
  );
}

// ── GoldenApp — כלי "הקו המוזהב": קווים מצטיינים ─────────────────────────
function GoldenApp({ onBack, trips, costBenchmarkTable, lineCitiesMap }) {
  const [goldenTab, setGoldenTab] = useState('top');
  const [filterDistrict, setFilterDistrict] = useState('all');
  const [filterCategory, setFilterCategory] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [submittedSearch, setSubmittedSearch] = useState('');
  const [sortBy, setSortBy] = useState('score');
  const [visibleCount, setVisibleCount] = useState(60);
  const [selectedLine, setSelectedLine] = useState(null);
  const [expandSearch, setExpandSearch] = useState('');
  const [expandMatches, setExpandMatches] = useState([]);
  const [areaFilter, setAreaFilter] = useState(null);

  // ניקוד מוזהב (0-100, גבוה יותר = טוב יותר) — ההפך המדויק מניקוד קו פח
  const goldenLines = useMemo(() => {
    if (!trips || trips.length === 0) return [];

    const cityOnlyStr = (s) => s ? (s.indexOf(' - ') > 0 ? s.slice(0, s.indexOf(' - ')).trim() : s.split('/')[0].trim()) : '';
    const groups = {};
    for (let i = 0; i < trips.length; i++) {
      const t = trips[i];
      const o = cityOnlyStr(t.origin);
      const d = cityOnlyStr(t.dest);
      const cityPair = [o, d].sort().join('-');
      const groupKey = `${t.lineNum}_${cityPair}`;
      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(t);
    }

    return Object.entries(groups).map(([groupKey, data]) => {
      const lineNum = data[0].lineNum;
      const totalTrips = data.reduce((s, t) => s + t.tripCount, 0);
      if (totalTrips < 3) return null;

      const totalRiders = data.reduce((s, t) => s + (t.ridership * t.tripCount), 0);
      const avgRiders = totalTrips > 0 ? (totalRiders / totalTrips) : 0;
      const totalPeaks = data.reduce((s, t) => s + (t.peakLoad * t.tripCount), 0);
      const avgPeak = totalTrips > 0 ? (totalPeaks / totalTrips) : 0;

      // דרישת סף לקו מוזהב: גם ממוצע הנוסעים וגם השיא חייבים להיות מעל 30
      if (avgRiders <= 30 || avgPeak <= 30) return null;

      const category = classifyLine({
        opGroup: data[0].opGroup,
        uniqueness: data[0].uniquenessVal,
        lineType: data[0].lineType,
        distance: data[0].distance,
        trips: totalTrips,
        isNight: data[0].isNightLine,
        isFeeding: data[0].isFeedingLine,
      });
      // בקו המוזהב: סף = ממוצע ארצי × 1.5 לפי קטגוריה; לילה נשאר 25 כפי שנקבע
      const isUrban = category === 'עירוני תדירות גבוהה' || category === 'עירוני תדירות נמוכה';
      const GOLDEN_RIDER_THRESHOLD = {
        'עירוני תדירות גבוהה': 44,
        'עירוני תדירות נמוכה': 21,
        'בינעירוני ארוך':       26,
        'בינעירוני קצר':        22,
        'תלמידים':              23,
        'אזורי':                12,
        'קווים מזינים':         12,
        'לילה':                 25,
      };
      const lowRiderTh = GOLDEN_RIDER_THRESHOLD[category] ?? (LOW_RIDER_THRESHOLD[category] || 10);
      const costBenchmark = lookupCostBenchmark(costBenchmarkTable, category, data[0].district);

      const lowTrips = data.filter(t => t.ridership < lowRiderTh);
      const lowCount = lowTrips.reduce((s, t) => s + t.tripCount, 0);
      const percentLow = totalTrips > 0 ? (lowCount / totalTrips) * 100 : 0;

      const avgCapacity = data.reduce((s, t) => s + (t.capacity || 50), 0) / data.length || 50;
      const scale = avgCapacity / 50;

      const wastedKm = Math.round(lowTrips.reduce((s, t) => s + ((t.distance || 0) * t.tripCount), 0));
      const totalKm = Math.round(data.reduce((s, t) => s + ((t.distance || 0) * t.tripCount), 0));
      const wastedRatio = totalKm > 0 ? (wastedKm / totalKm) : 0;

      const validCosts = data.filter(t => t.cost > 0);
      const avgCost = validCosts.length > 0 ? validCosts.reduce((s, t) => s + t.cost, 0) / validCosts.length : 0;
      const costRatio = costBenchmark > 0 && avgCost > 0 ? avgCost / costBenchmark : 0;

      // ── ניקוד מוזהב — הפוך מדויק מניקוד קו פח ──
      // 1. נסיעות ברמה גבוהה (עד 20 נק')
      const highTripsScore = Math.min(20, (100 - percentLow) * 0.20);

      // 2. יעילות ק"מ (עד 15 נק')
      const efficientKmScore = Math.min(15, (1 - wastedRatio) * 15);

      // 3. עלות לנוסע (עד 20 נק')
      const fullCostTh = isUrban ? 0.90 : 0.80;
      let costScore = 0;
      if (costRatio === 0) costScore = 10;
      else if (costRatio <= fullCostTh) costScore = 20;
      else if (costRatio <= 1.0) costScore = 12;
      else if (costRatio <= 1.3) costScore = 6;
      else costScore = 0;

      // 4. עמוס נוסעים (עד 15 נק')
      let avgRidersScore = 0;
      if (avgRiders >= (lowRiderTh * 2 * scale)) avgRidersScore = 15;
      else if (avgRiders >= (lowRiderTh * 1.2 * scale)) avgRidersScore = 8;

      // 5. עמוס שיא (עד 10 נק')
      let peakScore = 0;
      if (avgPeak >= (30 * scale)) peakScore = 10;
      else if (avgPeak >= (20 * scale)) peakScore = 5;

      // 6. נפח שבועי = ממוצע נוסעים × נסיעות שבועיות (עד 20 נק')
      // מתגמל קווים שגם עמוסים וגם תדירים — קו פעם/יום לא יוכל להגיע ל-100
      const weeklyVolume = avgRiders * totalTrips;
      const volHalf = lowRiderTh * 20;  // סף תחתון: סף נוסעים × 20 נסיעות/שבוע
      const volFull = lowRiderTh * 50;  // סף עליון:  סף נוסעים × 50 נסיעות/שבוע
      let volumeScore = 0;
      if (weeklyVolume >= volFull) volumeScore = 20;
      else if (weeklyVolume >= volHalf) volumeScore = 10;

      const rawScore = Math.min(100, Math.round(highTripsScore + efficientKmScore + costScore + avgRidersScore + peakScore + volumeScore));

      // קו מזהב דורש ניקוד 60 ומעלה
      if (rawScore < 60) return null;

      const sortedData = [...data].sort((a, b) => Number(String(a.direction).replace(/\D/g, '')) - Number(String(b.direction).replace(/\D/g, '')));
      return {
        lineNum,
        groupKey,
        score: rawScore,
        category,
        district: sortedData[0].district,
        origin: sortedData[0].origin,
        dest: sortedData[0].dest,
        makat: sortedData[0].makat,
        count: totalTrips,
        avg: avgRiders.toFixed(1),
        avgPeak: Math.round(avgPeak),
        percentLow: Math.round(percentLow),
        wastedKm,
        totalKm,
        nonWastedKm: Math.max(0, totalKm - wastedKm),
        cost: avgCost,
        costRatio: Number(costRatio.toFixed(2)),
        costBenchmark,
        componentScores: {
          highTrips: Math.round(highTripsScore),
          efficientKm: Math.round(efficientKmScore),
          cost: costScore,
          avgRiders: avgRidersScore,
          peak: peakScore,
        },
      };
    }).filter(Boolean).sort((a, b) => b.score - a.score);
  }, [trips, costBenchmarkTable]);

  const allDistricts = useMemo(() => [...new Set(goldenLines.map(l => l.district).filter(Boolean))].sort(), [goldenLines]);
  const allCategories = useMemo(() => [...CATEGORIES], []);

  const filtered = useMemo(() => {
    let r = [...goldenLines];
    if (filterDistrict !== 'all') r = r.filter(l => l.district === filterDistrict);
    if (filterCategory !== 'all') r = r.filter(l => l.category === filterCategory);
    if (submittedSearch) {
      const q = submittedSearch.toLowerCase();
      r = r.filter(l => {
        if (l.origin.toLowerCase().includes(q) || l.dest.toLowerCase().includes(q)) return true;
        if (String(l.lineNum).includes(q)) return true;
        const cleanMakat = String(l.makat || '').replace(/^0+/, '').trim();
        const citiesSet = lineCitiesMap.get(cleanMakat);
        return citiesSet ? Array.from(citiesSet).some(c => c.includes(q)) : false;
      });
    }
    if (sortBy === 'riders') r.sort((a, b) => Number(b.avg) - Number(a.avg));
    else if (sortBy === 'cost') r.sort((a, b) => a.costRatio - b.costRatio);
    else if (sortBy === 'km') r.sort((a, b) => b.totalKm - a.totalKm);
    else r.sort((a, b) => b.score - a.score);
    return r;
  }, [goldenLines, filterDistrict, filterCategory, submittedSearch, sortBy, lineCitiesMap]);

  const areaStats = useMemo(() => {
    const map = new Map();
    goldenLines.forEach(line => {
      if (!line.district) return;
      if (line.score < 80) return;
      if (!map.has(line.district)) map.set(line.district, { key: line.district, count: 0, totalScore: 0, totalRiders: 0, totalTrips: 0, totalKm: 0 });
      const s = map.get(line.district);
      s.count++;
      s.totalScore += line.score;
      s.totalRiders += Number(line.avg);
      s.totalTrips += line.count;
      s.totalKm += line.totalKm;
    });
    return [...map.values()].map(s => ({
      ...s,
      avgScore: Math.round(s.totalScore / s.count),
      avgRiders: (s.totalRiders / s.count).toFixed(1),
    })).sort((a, b) => b.count - a.count);
  }, [goldenLines]);

  const isLoading = !trips || trips.length === 0;

  const scoreColor = (s) => s >= 85 ? '#d97706' : s >= 70 ? '#b45309' : '#92400e';

  const GoldBadge = ({ score }) => (
    <div className="flex items-center justify-center w-14 h-14 rounded-2xl flex-shrink-0 font-black text-xl shadow-inner"
      style={{ background: 'linear-gradient(145deg,#fef3c7,#fbbf24)', color: scoreColor(score), border: '2px solid #f59e0b' }}>
      {score}
    </div>
  );

  const selectCls = "bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full md:w-auto appearance-none cursor-pointer";

  const exportAreaToExcel = async (areaKey) => {
    await loadXLSX();
    const lines = goldenLines.filter(l => l.district === areaKey && l.score >= 80);
    if (!lines.length) return;
    const data = lines.map(l => ({
      'מספר קו': l.lineNum,
      'מק"ט': l.makat || '',
      'מוצא': l.origin || '',
      'יעד': l.dest || '',
      'מחוז': l.district || '',
      'קטגוריה': l.category || '',
      'ניקוד מוזהב': l.score,
      'ממוצע נוסעים לנסיעה': parseFloat(l.avg),
      'עומס שיא ממוצע': l.avgPeak,
      'נסיעות בשבוע': l.count,
      'עלות לנוסע': l.cost > 0 ? `₪${l.cost.toFixed(2)}` : 'לא זמין',
      'ק"מ שבועי כולל': Math.round(l.totalKm || 0),
      'ק"מ סרק': Math.round(l.wastedKm || 0),
    }));
    const ws = window.XLSX.utils.json_to_sheet(data);
    if (!ws['!views']) ws['!views'] = [];
    ws['!views'].push({ rightToLeft: true });
    const wb = window.XLSX.utils.book_new();
    window.XLSX.utils.book_append_sheet(wb, ws, 'קווים_מצטיינים');
    window.XLSX.writeFile(wb, `קו_מוזהב_${areaKey.replace(/\s+/g, '_')}.xlsx`);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 p-4 md:p-6 pb-20" style={{ fontFamily: "'Heebo', sans-serif" }} dir="rtl">
      <div className="max-w-6xl mx-auto">

        <header className="mb-10 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="text-center md:text-right">
            <div className="flex items-center gap-3 justify-center md:justify-end">
              <div className="bg-slate-900 text-white p-2.5 rounded-2xl rotate-3 shadow-lg">
                <Ic n="star" size={28} strokeWidth="2" />
              </div>
              <h1 className="text-4xl font-[900] text-slate-900 tracking-tighter leading-none">הקו המוזהב</h1>
            </div>
            <p className="text-slate-500 text-sm font-bold mt-2 pr-1">מאתרים קווים מצטיינים • יעילות גבוהה, נוסעים רבים</p>
          </div>
          <button
            onClick={onBack}
            className="shrink-0 flex items-center gap-2 bg-white border-2 border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-300 px-4 py-2.5 rounded-2xl font-black text-sm shadow-sm transition-colors"
          >
            <span className="text-base leading-none">⇄</span> החלף כלי
          </button>
        </header>

        <nav className="flex bg-slate-200/50 backdrop-blur p-1.5 rounded-[2rem] mb-12 max-w-4xl mx-auto shadow-inner border border-slate-200 overflow-x-auto">
          {[['top', 'star', 'הקווים המצטיינים', 'bg-white text-amber-600 shadow-md'], ['areas', 'chart', 'ניתוח אזורי', 'bg-white text-amber-600 shadow-md'], ['expand', 'zap', 'הזדמנויות הרחבה', 'bg-white text-emerald-600 shadow-md'], ['about', 'info', 'על המערכת', 'bg-white text-indigo-600 shadow-md']].map(([id, icon, label, activeCls]) => (
            <button key={id} onClick={() => setGoldenTab(id)}
              className={`flex-1 min-w-[120px] py-3.5 rounded-[1.5rem] font-black text-sm transition-all flex items-center justify-center gap-2 ${goldenTab === id ? activeCls : 'text-slate-500 hover:text-slate-700'}`}>
              <Ic n={icon} size={16} /> {label}
            </button>
          ))}
        </nav>

        {/* ── טאב: קווים מצטיינים ── */}
        {goldenTab === 'top' && (
          <div className="space-y-8 transition-opacity duration-300 opacity-100">
            <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm flex flex-col xl:flex-row justify-between items-center gap-4">
              <div>
                <h2 className="text-2xl font-black text-slate-900">הקווים הכי מצטיינים</h2>
                <p className="text-slate-500 font-bold">דירוג המציג את הקווים החזקים ביותר במערכת — ביקוש גבוה, יעילות גבוהה ועלות נמוכה</p>
              </div>
              <div className="flex flex-col md:flex-row gap-3 relative w-full xl:w-auto">
                <select value={sortBy} onChange={e => { setSortBy(e.target.value); setVisibleCount(60); }} className={selectCls}>
                  <option value="score">מיון: לפי ניקוד מוזהב</option>
                  <option value="riders">מיון: ממוצע נוסעים (גבוה לנמוך)</option>
                  <option value="cost">מיון: עלות לנוסע (נמוך לגבוה)</option>
                  <option value="km">מיון: ק"מ שבועי</option>
                </select>
                <select value={filterDistrict} onChange={e => { setFilterDistrict(e.target.value); setVisibleCount(60); }} className={selectCls}>
                  <option value="all">כל המחוזות</option>
                  {allDistricts.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
                <select value={filterCategory} onChange={e => { setFilterCategory(e.target.value); setVisibleCount(60); }} className={selectCls}>
                  <option value="all">כל הקטגוריות</option>
                  {allCategories.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <div className="relative w-full md:w-64">
                  <input
                    type="text"
                    placeholder="הקלד עיר ולחץ Enter..."
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { setSubmittedSearch(searchQuery); setVisibleCount(60); } if (e.key === 'Escape') { setSearchQuery(''); setSubmittedSearch(''); } }}
                    className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-6 py-3 pl-12 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full"
                  />
                  {searchQuery && (
                    <button onClick={() => { setSearchQuery(''); setSubmittedSearch(''); }} className="absolute top-1/2 -translate-y-1/2 left-3 w-6 h-6 rounded-full bg-slate-200 hover:bg-slate-300 text-slate-600 font-black text-sm flex items-center justify-center transition-colors">×</button>
                  )}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filtered.slice(0, visibleCount).map((line, idx) => (
                <div key={line.groupKey} className="vcard bg-white border-2 border-slate-100 rounded-[2.5rem] p-7 shadow-sm hover:border-slate-900 transition-all text-right flex flex-col group relative">
                  <div className="flex items-start justify-between mb-6">
                    <div className="flex flex-col gap-2 items-start text-right">
                      <div className="flex items-center gap-2 flex-wrap">
                        <div className="px-4 py-1.5 rounded-full text-[11px] font-black border bg-emerald-50 text-emerald-700 border-emerald-200">
                          ניקוד {line.score}/100
                        </div>
                        <div className="px-3 py-1.5 rounded-full text-[11px] font-black bg-slate-100 text-slate-700 border border-slate-200">
                          {line.category}
                        </div>
                      </div>
                      <div className="text-[10px] font-bold text-slate-400">מק&quot;ט: {String(line.makat || '').replace(/^0+/, '') || '—'}</div>
                    </div>
                    <div className="bg-slate-900 text-white w-14 h-14 rounded-2xl flex items-center justify-center font-black text-2xl shadow-lg shrink-0">{line.lineNum}</div>
                  </div>

                  <div className="flex-1 mb-5">
                    <div className="flex items-center justify-start gap-3 mb-2 min-w-0">
                      <div className="text-slate-900 font-black text-lg truncate leading-tight">{line.origin}</div>
                      <div className="text-slate-300 text-2xl font-black shrink-0 leading-none">←</div>
                      <div className="text-slate-900 font-black text-lg truncate leading-tight">{line.dest}</div>
                    </div>
                    <span className="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md">{line.district}</span>

                    <div className="text-xs font-bold text-slate-400 mt-4 mb-4 flex items-center gap-2">
                      <span>ניקוד מוזהב:</span>
                      <span className="font-black text-emerald-600">{line.score}/100</span>
                    </div>

                    <div className="space-y-2.5 pt-4 border-t border-slate-100">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-600 font-bold">ממוצע נוסעים לנסיעה</span>
                        <span className="font-black text-slate-900">{line.avg}</span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-600 font-bold">עומס שיא ממוצע</span>
                        <span className="font-black text-slate-900">{line.avgPeak}</span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-600 font-bold">נסיעות בשבוע</span>
                        <span className="font-black text-slate-900">{line.count}</span>
                      </div>
                      <div className="flex items-center justify-between text-sm gap-2">
                        <span className="text-slate-600 font-bold">עלות תפעולית לנוסע</span>
                        <span className="text-right">
                          <span className="font-black text-slate-900">{line.cost > 0 ? `₪${line.cost.toFixed(2)}` : 'לא זמין'}</span>
                          {line.cost > 0 && line.costBenchmark > 0 && (
                            <div className="text-[10px] font-bold text-slate-400">
                              ממוצע {line.category}: ₪{line.costBenchmark}
                              {line.costRatio < 1 && (
                                <span className="text-emerald-500 mr-1">(×{line.costRatio.toFixed(2)})</span>
                              )}
                              {line.costRatio >= 1 && (
                                <span className="text-slate-500 mr-1">(×{line.costRatio.toFixed(2)})</span>
                              )}
                            </div>
                          )}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-600 font-bold">ק&quot;מ לא מבוזבז (שימושי)</span>
                        <span className="font-black text-emerald-600">{(line.nonWastedKm || 0).toLocaleString()} ק&quot;מ</span>
                      </div>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-slate-600 font-bold">ק&quot;מ מבוזבז (נסיעות סרק)</span>
                        <span className="font-black text-rose-600">{line.wastedKm.toLocaleString()} ק&quot;מ</span>
                      </div>
                    </div>

                  </div>

                  <button
                    onClick={() => { setSelectedLine(line); setGoldenTab('expand'); }}
                    className="w-full py-4 bg-slate-900 text-white rounded-2xl text-xs font-black hover:bg-black transition-all shadow-md"
                  >
                    חפש הזדמנויות הרחבה
                  </button>
                </div>
              ))}
              {filtered.length === 0 && (
                <div className="col-span-full text-center py-20 text-slate-400 font-bold">לא נמצאו קווים מצטיינים בסינון הנוכחי.</div>
              )}
            </div>
            {filtered.length > visibleCount && (
              <button onClick={() => setVisibleCount(v => v + 60)} className="w-full py-4 rounded-[2rem] border-2 border-slate-200 text-slate-500 font-black text-sm hover:bg-slate-50 hover:border-slate-300 transition-all shadow-sm">
                טען עוד ({filtered.length - visibleCount} נותרו)
              </button>
            )}
          </div>
        )}

        {/* ── טאב: ניתוח אזורי ── */}
        {goldenTab === 'areas' && (
          <div className="space-y-8 transition-opacity duration-300 opacity-100">
            <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm flex flex-col xl:flex-row justify-between items-center gap-4">
              <div>
                <h2 className="text-2xl font-black text-slate-900">האזורים הכי חזקים</h2>
                <p className="text-slate-500 font-bold">ריכוז הקווים המצטיינים לפי מחוז — לחץ על מחוז לצפייה בקוויו</p>
              </div>
              {areaFilter && (
                <button onClick={() => setAreaFilter(null)} className="shrink-0 bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-2xl font-black text-sm transition-colors">
                  ✕ נקה סינון: {areaFilter}
                </button>
              )}
            </div>

            {!areaFilter && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                {areaStats.map((area, idx) => (
                  <div key={area.key} onClick={() => setAreaFilter(area.key)}
                    className="bg-white border-2 border-slate-100 rounded-[2.5rem] p-7 shadow-sm hover:border-slate-900 transition-all text-right flex flex-col cursor-pointer group">
                    <div className="flex justify-between items-start mb-6">
                      <div className="px-4 py-1.5 rounded-full text-[11px] font-black border bg-emerald-50 border-emerald-200 text-emerald-700">ניקוד ממוצע: {area.avgScore}</div>
                      <button onClick={e => { e.stopPropagation(); exportAreaToExcel(area.key); }} className="bg-emerald-100 hover:bg-emerald-200 text-emerald-700 w-12 h-12 rounded-2xl flex items-center justify-center shadow-sm transition-all shrink-0" title="ייצוא נתוני האזור לאקסל">
                        <Ic n="download" size={20} />
                      </button>
                    </div>
                    <h3 className="text-2xl font-black text-slate-900 mb-4">{area.key}</h3>
                    <div className="space-y-3 pt-4 border-t border-slate-100 text-sm mb-5">
                      <div className="flex justify-between"><span className="text-slate-600 font-bold">קווים מצטיינים</span><span className="font-black text-slate-900">{area.count} קווים</span></div>
                      <div className="flex justify-between"><span className="text-slate-600 font-bold">ממוצע נוסעים</span><span className="font-black text-slate-900">{area.avgRiders}</span></div>
                      <div className="flex justify-between"><span className="text-slate-600 font-bold">סה"כ נסיעות שבועיות</span><span className="font-black text-slate-900">{area.totalTrips.toLocaleString()}</span></div>
                      <div className="flex justify-between"><span className="text-slate-600 font-bold">סה"כ ק"מ שבועיים</span><span className="font-black text-slate-900">{area.totalKm.toLocaleString()} ק"מ</span></div>
                    </div>
                    <button className="mt-auto w-full py-4 bg-slate-900 text-white rounded-2xl text-xs font-black hover:bg-black transition-all shadow-md">צפה בקווים אלו</button>
                  </div>
                ))}
                {areaStats.length === 0 && (
                  <div className="col-span-full text-center py-20 text-slate-400 font-bold">אין נתונים.</div>
                )}
              </div>
            )}

            {areaFilter && (
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {goldenLines.filter(l => l.district === areaFilter && l.score >= 80).map(line => (
                    <div key={line.groupKey} className="bg-white border-2 border-slate-100 rounded-[2.5rem] p-7 shadow-sm hover:border-slate-900 transition-all text-right flex flex-col group">
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex flex-col gap-2 items-start">
                          <div className="px-4 py-1.5 rounded-full text-[11px] font-black border bg-emerald-50 text-emerald-700 border-emerald-200">ניקוד {line.score}/100</div>
                          <div className="px-3 py-1.5 rounded-full text-[11px] font-black bg-slate-100 text-slate-700 border border-slate-200">{line.category}</div>
                        </div>
                        <div className="bg-slate-900 text-white w-14 h-14 rounded-2xl flex items-center justify-center font-black text-2xl shadow-lg shrink-0">{line.lineNum}</div>
                      </div>
                      <div className="flex items-center gap-3 mb-3 min-w-0">
                        <div className="text-slate-900 font-black text-lg truncate leading-tight">{line.origin}</div>
                        <div className="text-slate-300 text-2xl font-black shrink-0">←</div>
                        <div className="text-slate-900 font-black text-lg truncate leading-tight">{line.dest}</div>
                      </div>
                      <div className="space-y-2 text-sm border-t border-slate-100 pt-3 mb-5 flex-1">
                        <div className="flex justify-between"><span className="text-slate-600 font-bold">ממוצע נוסעים</span><span className="font-black">{line.avg}</span></div>
                        <div className="flex justify-between"><span className="text-slate-600 font-bold">עומס שיא</span><span className="font-black">{line.avgPeak}</span></div>
                        <div className="flex justify-between"><span className="text-slate-600 font-bold">עלות לנוסע</span><span className="font-black">{line.cost > 0 ? `₪${line.cost.toFixed(2)}` : '—'}</span></div>
                      </div>
                      <button onClick={() => { setSelectedLine(line); setGoldenTab('expand'); }} className="w-full py-3 bg-slate-900 text-white rounded-2xl text-xs font-black hover:bg-black transition-all shadow-md">חפש הזדמנויות הרחבה</button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── טאב: הזדמנויות הרחבה ── */}
        {goldenTab === 'expand' && (() => {
          if (!selectedLine) {
            const doExpandSearch = () => {
              const q = expandSearch.trim();
              if (!q) return;
              const matches = goldenLines.filter(l => String(l.lineNum) === q || String(l.makat) === q);
              if (matches.length === 1) { setSelectedLine(matches[0]); setExpandMatches([]); }
              else setExpandMatches(matches);
            };
            return (
              <div className="bg-white rounded-[2.5rem] border border-slate-200 shadow-sm p-10 max-w-lg mx-auto">
                <h2 className="text-xl font-black text-slate-900 mb-2 text-right">הזדמנויות הרחבה</h2>
                <p className="text-slate-400 font-bold text-sm mb-6 text-right">הקלד מספר קו לניתוח, או חזור לרשימה לבחירה מהקווים המצטיינים</p>
                <div className="flex gap-3 mb-4">
                  <button onClick={doExpandSearch} className="bg-slate-900 text-white px-6 py-3 rounded-2xl font-black text-sm hover:bg-black transition-colors shrink-0">חפש</button>
                  <input
                    type="text"
                    value={expandSearch}
                    onChange={e => { setExpandSearch(e.target.value); setExpandMatches([]); }}
                    onKeyDown={e => e.key === 'Enter' && doExpandSearch()}
                    placeholder="מספר קו..."
                    className="flex-1 bg-slate-50 border-2 border-slate-200 rounded-2xl px-5 py-3 font-black text-sm outline-none focus:border-slate-900 text-right"
                  />
                </div>
                {expandMatches.length > 1 && (
                  <div className="space-y-2 mb-4">
                    <p className="text-xs font-black text-slate-500 text-right">נמצאו מספר מסלולים — בחר:</p>
                    {expandMatches.map(l => (
                      <button key={l.groupKey} onClick={() => { setSelectedLine(l); setExpandMatches([]); }}
                        className="w-full text-right bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded-2xl px-5 py-3 font-black text-sm transition-colors">
                        קו {l.lineNum} · {l.origin} ← {l.dest} · {l.district}
                      </button>
                    ))}
                  </div>
                )}
                {expandMatches.length === 0 && expandSearch && (
                  <p className="text-xs font-bold text-rose-500 text-right">קו {expandSearch} לא נמצא בקווים המצטיינים</p>
                )}
                <button onClick={() => setGoldenTab('top')} className="mt-4 w-full bg-slate-100 hover:bg-slate-200 text-slate-700 px-8 py-3 rounded-2xl font-black text-sm transition-colors">← חזרה לרשימה</button>
              </div>
            );
          }

          // מסננים לפי אותו groupKey שבו מקובצים הקווים המצטיינים (lineNum + צמד ערים),
          // אחרת "קו 1" יאסוף את כל הקווים שמספרם 1 בכל הארץ וידלל את העומס
          const cityOnly = (s) => s ? (s.indexOf(' - ') > 0 ? s.slice(0, s.indexOf(' - ')).trim() : s.split('/')[0].trim()) : '';
          const lineTrips = trips.filter(t => {
            const pair = [cityOnly(t.origin), cityOnly(t.dest)].sort().join('-');
            return `${t.lineNum}_${pair}` === selectedLine.groupKey;
          });
          const periods = { 'לילה (00-06)': [], 'בוקר שיא (06-09)': [], 'בוקר (09-12)': [], 'צהריים (12-15)': [], 'אחה"צ שיא (15-18)': [], 'ערב (18-22)': [], 'לילה מאוחר (22-24)': [] };
          const periodRange = [[0,360],[360,540],[540,720],[720,900],[900,1080],[1080,1320],[1320,1440]];
          lineTrips.forEach(t => {
            const mins = t.timeMins;
            if (mins == null) return;
            const idx = periodRange.findIndex(([a,b]) => mins >= a && mins < b);
            if (idx >= 0) { const key = Object.keys(periods)[idx]; periods[key].push(t); }
          });
          // יעד עומס נוח = 85% מקיבולת האוטובוס. מעבר לזה — האוטובוס צפוף וצריך נסיעות נוספות.
          // נסיעות להוספה = נסיעות שיביאו את העומס הממוצע חזרה ליעד הנוח.
          const TARGET_LOAD = 0.85;
          const minsToStr = (m) => `${String(Math.floor(m/60)%24).padStart(2,'0')}:${String(Math.round(m)%60).padStart(2,'0')}`;
          // מציע שעות יציאה קונקרטיות להוספה: בכל מרווח שעולה על תדירות מינימלית של
          // 5 דקות, משתל נסיעות נוספות כדי לקרב את המרווח ל-5 דקות (התדר המעשי הצפוף
          // ביותר). מרווח של 5 דקות לא יחולק. מחזיר עד 10 שעות, וגם את הספירה הכוללת.
          const MIN_HEADWAY = 5;
          const suggestTimes = (pts) => {
            const times = [...new Set(pts.map(t => t.timeMins).filter(m => m != null && m > 0))].sort((a,b) => a-b);
            if (times.length < 2) return { times: [], total: 0 };
            const picks = [];
            for (let i=0; i<times.length-1; i++) {
              const start = times[i], gap = times[i+1] - start;
              const inserts = Math.round(gap / MIN_HEADWAY) - 1; // כמה נסיעות לשתול כדי להגיע ל~5 דק'
              for (let k=1; k<=inserts; k++) picks.push(Math.round(start + (gap * k) / (inserts + 1)));
            }
            picks.sort((a,b) => a-b);
            return { times: picks.slice(0, 10).map(minsToStr), total: picks.length };
          };
          const periodStats = Object.entries(periods).map(([label, pts]) => {
            if (pts.length === 0) return { label, count: 0, avgRiders: 0, avgPeak: 0, capacity: 0, occupancy: 0, tripsToAdd: 0, suggestedTimes: [], moreTimes: 0 };
            const totalTrips = pts.reduce((s,t) => s + t.tripCount, 0);
            const avgRiders = totalTrips > 0 ? pts.reduce((s,t) => s + t.ridership * t.tripCount, 0) / totalTrips : 0;
            const avgPeak = totalTrips > 0 ? pts.reduce((s,t) => s + t.peakLoad * t.tripCount, 0) / totalTrips : 0;
            // קיבולת מייצגת לחלון — הקיבולת הגדולה ביותר בין נסיעות החלון
            const capacity = Math.max(...pts.map(t => t.capacity || 50), 50);
            const target = capacity * TARGET_LOAD;
            const occupancy = capacity > 0 ? avgPeak / capacity : 0;
            let tripsToAdd = 0;
            if (avgPeak > target && totalTrips > 0) {
              const needed = Math.ceil(totalTrips * avgPeak / target);
              tripsToAdd = Math.max(0, needed - totalTrips);
            }
            const sug = tripsToAdd > 0 ? suggestTimes(pts) : { times: [], total: 0 };
            return { label, count: totalTrips, avgRiders: avgRiders.toFixed(1), avgPeak: Math.round(avgPeak), capacity, occupancy, tripsToAdd, suggestedTimes: sug.times, moreTimes: Math.max(0, sug.total - sug.times.length) };
          }).filter(p => p.count > 0);
          const maxRiders = Math.max(...periodStats.map(p => Number(p.avgRiders)), 1);
          const totalTripsToAdd = periodStats.reduce((s,p) => s + p.tripsToAdd, 0);
          const crowdedWindows = periodStats.filter(p => p.tripsToAdd > 0).sort((a,b) => b.tripsToAdd - a.tripsToAdd);

          return (
            <div className="space-y-8 transition-opacity duration-300 opacity-100">
              <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm flex flex-col xl:flex-row justify-between items-start gap-4">
                <div>
                  <div className="flex items-center gap-3 mb-2 flex-wrap">
                    <div className="bg-slate-900 text-white w-12 h-12 rounded-xl flex items-center justify-center font-black text-xl shadow-md">{selectedLine.lineNum}</div>
                    <div>
                      <h2 className="text-2xl font-black text-slate-900">הזדמנויות הרחבה — קו {selectedLine.lineNum}</h2>
                      <p className="text-slate-500 font-bold">{selectedLine.origin} ← {selectedLine.dest} · {selectedLine.district}</p>
                    </div>
                  </div>
                  <p className="text-slate-500 font-bold text-sm mt-2">חישוב כמה נסיעות כדאי להוסיף כדי להוריד את העומס לרמה נוחה (עד 85% מקיבולת האוטובוס)</p>
                </div>
                <button onClick={() => setGoldenTab('top')} className="shrink-0 bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2.5 rounded-2xl font-black text-sm transition-colors">← חזרה לרשימה</button>
              </div>

              {/* סיכום: סך נסיעות להוספה */}
              <div className={`rounded-[2.5rem] p-8 shadow-sm border-2 ${totalTripsToAdd > 0 ? 'bg-emerald-50 border-emerald-200' : 'bg-slate-50 border-slate-200'}`}>
                <div className="flex flex-col md:flex-row items-center justify-between gap-4">
                  <div className="text-center md:text-right">
                    <p className={`font-bold text-sm ${totalTripsToAdd > 0 ? 'text-emerald-700' : 'text-slate-500'}`}>סך נסיעות מומלצות להוספה (שבועי)</p>
                    <p className={`text-5xl font-[900] mt-1 ${totalTripsToAdd > 0 ? 'text-emerald-600' : 'text-slate-400'}`}>{totalTripsToAdd > 0 ? `+${totalTripsToAdd}` : '0'}</p>
                  </div>
                  <div className="text-center md:text-left max-w-sm">
                    <p className="text-slate-600 font-bold text-sm leading-relaxed">
                      {totalTripsToAdd > 0
                        ? `הקו עמוס ב-${crowdedWindows.length} חלונות זמן. הוספת ${totalTripsToAdd} נסיעות שבועיות תוריד את העומס הממוצע לרמה נוחה ותקצר המתנה.`
                        : 'בכל חלונות הזמן העומס מתחת ל-85% מהקיבולת — אין צורך בהוספת נסיעות כרגע. הקו פועל ביעילות מיטבית.'}
                    </p>
                  </div>
                </div>
              </div>

              {/* ניתוח עומס לפי שעה */}
              <div className="bg-white rounded-[2.5rem] border border-slate-200 shadow-sm p-7">
                <h3 className="text-lg font-black text-slate-900 mb-5">עומס שיא לפי שעה</h3>
                <div className="space-y-3">
                  {periodStats.map(p => {
                    const occPct = Math.round(p.occupancy * 100);
                    const over = p.tripsToAdd > 0;
                    return (
                      <div key={p.label}>
                        <div className="flex justify-between text-sm font-bold mb-1">
                          <span className="text-slate-700">{p.label}</span>
                          <span className={over ? 'text-emerald-700 font-black' : 'text-slate-900 font-black'}>{occPct}% תפוסה · {p.count} נסיעות</span>
                        </div>
                        <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full transition-all ${over ? 'bg-emerald-500' : 'bg-slate-900'}`} style={{ width: `${Math.min(100, p.occupancy * 100)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                  {periodStats.length === 0 && <p className="text-slate-400 font-bold text-sm">אין נתוני זמן לקו זה</p>}
                </div>
                <p className="text-slate-400 text-xs font-bold mt-4 pt-3 border-t border-slate-100">קו ירוק = העומס עובר 85% מהקיבולת — חלון מועמד להוספת נסיעות</p>
              </div>

              {/* המלצות להוספה — כרטיסים בסגנון קו פח, מראים איפה צריך להוסיף */}
              <div>
                <div className="flex items-center gap-2 mb-4 px-1">
                  <Ic n="zap" size={20} cls="text-emerald-600" />
                  <h3 className="text-lg font-black text-slate-900">
                    {crowdedWindows.length > 0 ? `נמצאו ${crowdedWindows.length} חלונות שמומלץ להוסיף בהם נסיעות` : 'אין חלונות שדורשים הוספת נסיעות'}
                  </h3>
                </div>
                <div className="space-y-4">
                  {crowdedWindows.length === 0 && (
                    <div className="bg-slate-50/50 border-2 border-slate-100 p-6 rounded-[2rem] text-center">
                      <p className="text-slate-500 font-bold">העומס בכל חלונות הזמן מתחת ל-85% מהקיבולת — הקו פועל ביעילות מיטבית.</p>
                    </div>
                  )}
                  {crowdedWindows.map((p, i) => {
                    const occPct = Math.round(p.occupancy * 100);
                    const busLabel = p.capacity >= 90 ? 'מפרקי' : p.capacity >= 50 ? 'אוטובוס' : p.capacity >= 35 ? 'מידי' : 'מיני';
                    return (
                      <div key={p.label} className="bg-white border-2 border-slate-50 p-6 rounded-[2rem] flex flex-col lg:flex-row lg:items-center justify-between gap-6 hover:shadow-lg transition-all border-r-4 border-r-emerald-500">
                        <div className="flex items-start gap-4">
                          <div className="bg-emerald-50 text-emerald-600 p-3.5 rounded-2xl mt-1"><Ic n="zap" size={24} /></div>
                          <div>
                            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                              <span className="font-black text-slate-900 text-lg">קו {selectedLine.lineNum}</span>
                              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-bold">{selectedLine.category}</span>
                            </div>
                            <div className="text-sm font-bold text-slate-500 mb-3">{selectedLine.origin} ← {selectedLine.dest} · {selectedLine.district}</div>
                            <div className="flex flex-wrap gap-2">
                              <span className="text-[11px] font-black bg-emerald-100 text-emerald-700 px-2 py-1 rounded-md">{p.label}</span>
                              <span className="text-[11px] font-black bg-rose-100 text-rose-700 px-2 py-1 rounded-md">{occPct}% תפוסה</span>
                              <span className="text-[11px] font-black bg-slate-100 text-slate-500 px-2 py-1 rounded-md">{p.count} נסיעות כיום</span>
                              <span className="text-[11px] font-black bg-purple-100 text-purple-700 px-2 py-1 rounded-md">{busLabel}</span>
                            </div>
                          </div>
                        </div>
                        <div className="bg-slate-50/80 px-6 py-4 rounded-2xl flex-1 max-w-md w-full">
                          <div className="flex justify-between items-center mb-3 text-sm">
                            <span className="font-bold text-slate-500">עומס שיא ממוצע:</span>
                            <span className="font-black text-slate-700">{p.avgPeak} <span className="text-xs text-slate-400 font-normal">על קיבולת {p.capacity}</span></span>
                          </div>
                          <div className="flex justify-between items-center mb-4 text-sm">
                            <span className="font-bold text-slate-500">נסיעות שבועיות כיום:</span>
                            <span className="font-black text-slate-700">{p.count}</span>
                          </div>
                          <div className="pt-3 border-t border-slate-200 flex justify-between items-center mb-3">
                            <span className="font-black text-emerald-700">מומלץ להוסיף:</span>
                            <span className="font-black text-2xl text-emerald-600 bg-white px-3 py-1 rounded-xl shadow-sm">+{p.tripsToAdd} נסיעות</span>
                          </div>
                          {p.suggestedTimes.length > 0 ? (
                            <div>
                              <div className="text-xs font-bold text-slate-500 mb-2">שעות יציאה מוצעות (קירוב לתדירות של 5 דק'):</div>
                              <div className="flex flex-wrap gap-2">
                                {p.suggestedTimes.map((t, ti) => (
                                  <span key={ti} className="font-black text-sm text-emerald-700 bg-white border border-emerald-200 px-3 py-1.5 rounded-xl shadow-sm">{t}</span>
                                ))}
                                {p.moreTimes > 0 && (
                                  <span className="font-black text-sm text-slate-500 bg-slate-100 px-3 py-1.5 rounded-xl">ועוד {p.moreTimes}</span>
                                )}
                              </div>
                            </div>
                          ) : (
                            <div className="text-xs font-bold text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2">
                              הלוח כבר רץ בתדירות של עד 5 דקות — עדיף לשדרג ל{p.capacity < 90 ? 'אוטובוס מפרקי (90 מקומות)' : 'תוספת קיבולת'} מאשר להוסיף נסיעות.
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* נתוני קו */}
              <div className="bg-white rounded-[2.5rem] border border-slate-200 shadow-sm p-7">
                <h3 className="text-lg font-black text-slate-900 mb-5">נתוני הקו המצטיין</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {[
                    ['ניקוד מוזהב', `${selectedLine.score}/100`],
                    ['ממוצע נוסעים', selectedLine.avg],
                    ['עומס שיא', selectedLine.avgPeak],
                    ['נסיעות בשבוע', selectedLine.count],
                    ['עלות לנוסע', selectedLine.cost > 0 ? `₪${selectedLine.cost.toFixed(2)}` : '—'],
                    ['ק"מ שימושי', `${(selectedLine.nonWastedKm||0).toLocaleString()} ק"מ`],
                    ['קטגוריה', selectedLine.category],
                  ].map(([label, val]) => (
                    <div key={label} className="bg-slate-50 rounded-2xl p-4 text-right">
                      <div className="text-slate-400 text-xs font-bold mb-1">{label}</div>
                      <div className="font-black text-slate-900 text-lg">{val}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          );
        })()}

        {/* ── טאב: אודות ── */}
        {goldenTab === 'about' && (
          <div className="space-y-8">
            <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm">
              <h2 className="text-2xl font-black text-slate-900 mb-4">מה זה הקו המוזהב?</h2>
              <p className="text-slate-600 leading-relaxed font-bold mb-6">הקו המוזהב הוא ההפך המדויק של קו פח — הוא מאתר את הקווים שעושים את העבודה הכי טוב. קווים עם ביקוש גבוה, עלות לנוסע נמוכה, ורוב הנסיעות מלאות.</p>
              <h3 className="font-black text-slate-900 text-lg mb-4">ניקוד מוזהב (0–100)</h3>
              <div className="space-y-3">
                {[
                  ['נסיעות בביקוש גבוה', 'עד 20 נקודות', 'כמה מהנסיעות עוברות את סף הנוסעים לקטגוריה'],
                  ['יעילות ק"מ', 'עד 15 נקודות', 'כמה מהקילומטרים נסועים על נסיעות מאוכלסות'],
                  ['עלות לנוסע', 'עד 20 נקודות', 'עירוני: חייב להיות 10% מתחת לממוצע הקטגוריה — כל השאר: 20% מתחת'],
                  ['עומס נוסעים ממוצע', 'עד 15 נקודות', 'ממוצע הנוסעים לנסיעה ביחס לסף המחמיר של הקטגוריה'],
                  ['עומס שיא', 'עד 10 נקודות', 'כמה אנשים בקטע העמוס ביותר — מתחת ל-20 = לא עמוס, מקבל 0 נקודות'],
                  ['נפח שבועי', 'עד 20 נקודות', 'ממוצע נוסעים × נסיעות שבועיות — מונע מקווי תלמידים וקווי פעם ביום להגיע ל-100'],
                ].map(([title, pts, desc]) => (
                  <div key={title} className="flex items-start justify-between p-5 rounded-2xl bg-slate-50 border border-slate-100">
                    <div>
                      <div className="font-black text-slate-800 text-sm">{title}</div>
                      <div className="text-slate-400 text-xs font-bold mt-1">{desc}</div>
                    </div>
                    <span className="shrink-0 ml-4 px-3 py-1 rounded-full text-[11px] font-black bg-slate-200 text-slate-700">{pts}</span>
                  </div>
                ))}
              </div>
              <div className="mt-6 pt-4 border-t border-slate-100">
                <h4 className="font-black text-slate-700 text-sm mb-3">סף נוסעים מינימלי לקטגוריה (קו מוזהב)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {[['עירוני תדירות גבוהה','44'],['עירוני תדירות נמוכה','21'],['תלמידים','23'],['בינעירוני ארוך','26'],['בינעירוני קצר','22'],['קווים מזינים','12'],['אזורי','12'],['לילה','25']].map(([cat,th]) => (
                    <div key={cat} className="bg-slate-50 rounded-xl p-2.5 text-right border border-slate-100">
                      <div className="text-slate-400 text-[10px] font-bold">{cat}</div>
                      <div className="font-black text-slate-900 text-sm">{th} נוסעים</div>
                    </div>
                  ))}
                </div>
                <p className="text-slate-400 text-xs font-bold mt-4">* מוצגים רק קווים עם ניקוד 60 ומעלה</p>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

function KavPach() {
  // appMode: 'choice' (מסך בחירה) · 'kavpach' (קו פח) · 'golden' (הקו המוזהב)
  // מאותחל מה-hash כדי שלינקים ישירים ורענון דף יישמרו (אותה כתובת בסיס).
  const [appMode, setAppMode] = useState(() => {
    if (typeof window === 'undefined') return 'choice';
    const h = decodeURIComponent((window.location.hash || '').replace('#', '').trim());
    if (h === 'golden' || h === 'מוזהב') return 'golden';
    if (h === 'kavpach' || h === 'פח') return 'kavpach';
    return 'choice';
  });
  const pickMode = useCallback((m) => {
    try { window.location.hash = m === 'choice' ? '' : m; } catch (e) { /* ignore */ }
    setAppMode(m);
  }, []);

  // סנכרון כפתור Back/Forward של הדפדפן עם appMode
  useEffect(() => {
    const onHash = () => {
      const h = decodeURIComponent((window.location.hash || '').replace('#', '').trim());
      if (h === 'golden' || h === 'מוזהב') setAppMode('golden');
      else if (h === 'kavpach' || h === 'פח') setAppMode('kavpach');
      else setAppMode('choice');
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const [trips, setTrips] = useState([]);
  const [lineCitiesMap, setLineCitiesMap] = useState(new Map());
  const [lineStopsMap, setLineStopsMap] = useState(new Map());
  const [lineNormStopsMap, setLineNormStopsMap] = useState(new Map());
  const [costBenchmarkTable, setCostBenchmarkTable] = useState(null);
  const [csvLoadFailed, setCsvLoadFailed] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  const [fileLoad, setFileLoad] = useState({ active: false, progress: 0, message: "מנתח נתונים..." });
  const setFileLoading = (active) => setFileLoad(s => ({ ...s, active }));
  const setFileProgress = (progress) => setFileLoad(s => ({ ...s, progress }));
  const setFileMessage = (message) => setFileLoad(s => ({ ...s, message }));
  const [loadError, setLoadError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  const [tab, setTab] = useState("redundant"); 
  const [searchCity, setSearchCity] = useState("");
  const [filterDistrict, setFilterDistrict] = useState("all");
  const [filterCategory, setFilterCategory] = useState("all");
  const [redundantSortBy, setRedundantSortBy] = useState("score"); 
  const [showCrowded, setShowCrowded] = useState(false);
  const [visibleTripsCount, setVisibleTripsCount] = useState(60);
  const [filterLineType, setFilterLineType] = useState("all");
  
  // ── אזורים חלשים State ──
  const [areaViewMode, setAreaViewMode] = useState("city");
  const [areaSortBy, setAreaSortBy] = useState("wastedKm");

  const [debugLine, setDebugLine] = useState("");
  const [debugResult, setDebugResult] = useState(null);

  const runLineDebug = (line) => {
    const ln = String(line).replace(/^0+/, '').trim();
    if (!ln) { setDebugResult(null); return; }
    const matches = trips.filter(x => String(x.lineNum).replace(/^0+/, '') === ln);
    if (!matches.length) {
      setDebugResult({ line: ln, found: false, msg: 'לא נמצא בנתונים' });
      return;
    }
    // קיבוץ לפי מק"ט — כל מק"ט הוא קו שונה גם אם מספר הקו זהה
    const byMakat = new Map();
    for (const t of matches) {
      const m = String(t.makat || '').replace(/^0+/, '');
      if (!byMakat.has(m)) byMakat.set(m, []);
      byMakat.get(m).push(t);
    }
    const variants = [];
    for (const [m, arr] of byMakat) {
      const stopsSet = lineStopsMap.get(m) || lineStopsMap.get(ln);
      const citiesSet = lineCitiesMap.get(m) || lineCitiesMap.get(ln);
      const normSet = lineNormStopsMap.get(m) || lineNormStopsMap.get(ln);
      const origins = [...new Set(arr.map(x => x.origin))];
      const dests = [...new Set(arr.map(x => x.dest))];
      variants.push({
        makat: m,
        tripCount: arr.length,
        district: arr[0].district,
        origins,
        dests,
        stopCount: stopsSet?.size || 0,
        cityCount: citiesSet?.size || 0,
        normStopCount: normSet?.size || 0,
        cities: citiesSet ? [...citiesSet] : [],
        stopsFirst: stopsSet ? [...stopsSet].slice(0, 10) : [],
      });
    }
    setDebugResult({ line: ln, found: true, variants });
  };
  
  const [optLine, setOptLine] = useState("");
  const [optCity, setOptCity] = useState("all");
  const [optDirection, setOptDirection] = useState("all");
  const [optDays, setOptDays] = useState([]); 
  const [optimizations, setOptimizations] = useState([]);
  const [showAllTripsInSimulator, setShowAllTripsInSimulator] = useState(false);
  const [visibleOptCount, setVisibleOptCount] = useState(50);
  
  const [optMetric, setOptMetric] = useState("ridership");
  const [optCustomGap, setOptCustomGap] = useState("");
  const [optMinTrips, setOptMinTrips] = useState("");
  const [optCancelThreshold, setOptCancelThreshold] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [activeExplainId, setActiveExplainId] = useState(null);
  const [showWhatsNew, setShowWhatsNew] = useState(false);
  const explainRef = useRef(null);

  // ── מצב מפה ──────────────────────────────────────────────────────────────
  const [simLoading, setSimLoading] = useState(false);

  useEffect(() => {
    if (!activeExplainId) return;
    const handler = (e) => {
      if (explainRef.current && !explainRef.current.contains(e.target)) {
        setActiveExplainId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [activeExplainId]);

  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'desc' });
  const [activeTooltip, setActiveTooltip] = useState(null);
  const tooltipRef = useRef(null);

  // searchCity מתעדכן רק אחרי debounce (מתוך DebouncedInput) —
  // לכן ניתן להשתמש בו ישירות לסינון בלי לדחוף עוד מממואיזציה נוספת.

  useEffect(() => {
    setVisibleTripsCount(60);
  }, [searchCity, showCrowded, sortConfig, tab, filterLineType]);

  useEffect(() => {
    if (!activeTooltip) return;
    const handler = (e) => {
      if (tooltipRef.current && !tooltipRef.current.contains(e.target)) {
        setActiveTooltip(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [activeTooltip]);

  const { allDistricts, allCities, allDirections, allLineTypes } = useMemo(() => {
    const dists = new Set();
    const cits = new Set();
    const dirs = new Set();
    const types = new Set();
    
    for (let i = 0; i < trips.length; i++) {
      const t = trips[i];
      if (t.district) dists.add(t.district);
      if (t.origin) cits.add(t.origin);
      if (t.dest) cits.add(t.dest);
      if (t.direction) dirs.add(t.direction);
      if (t.lineType) types.add(t.lineType);
    }
    
    return {
      allDistricts: Array.from(dists).sort(),
      allCities: Array.from(cits).sort(),
      allDirections: Array.from(dirs).sort(),
      allLineTypes: Array.from(types).sort()
    };
  }, [trips]);

const DAYS_FILTER = [
    { id: "1", label: "ראשון" },
    { id: "2", label: "שני" },
    { id: "3", label: "שלישי" },
    { id: "4", label: "רביעי" },
    { id: "5", label: "חמישי" },
    { id: "6", label: "שישי" },
    { id: "7", label: "שבת" }
  ];

  // ── פונקציית טעינה מקובץ CSV מקומי ──────────────────────────────────────────
  const loadFromCSV = useCallback(async () => {
    try {
      setFileLoading(true);
      setFileProgress(5);
      setFileMessage("טוען נתונים מקובץ מקומי...");
      
      const response = await fetch('data.csv');
      if (!response.ok) {
        throw new Error('לא נמצא קובץ CSV');
      }
      
      setFileProgress(15);
      setFileMessage("קורא את הקובץ...");
      
      const csvText = await response.text();
      if (!csvText || csvText.trim().length === 0) {
        throw new Error('קובץ CSV ריק');
      }
      
      setFileProgress(30);
      setFileMessage("מנתח נתונים...");
      await yieldFrame();
      
      // פירוק CSV לשורות
      const lines = csvText.split('\n').filter(line => line.trim());
      if (lines.length < 2) {
        throw new Error('קובץ CSV חייב להכיל לפחות כותרות ושורת נתונים אחת');
      }
      
      // פירוק כותרות
      const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''));
      
      // מיפוי עמודות
      const findCol = (names) => {
        for (const name of names) {
          const idx = headers.findIndex(h => h.includes(name) || h === name);
          if (idx !== -1) return idx;
        }
        return -1;
      };
      
      const cols = {
        lineNum: findCol(["מספר קו", "קו", "line"]),
        makat: findCol(["מק\"ט", "מקט", "Route_Id"]),
        direction: findCol(["כיוון", "direction"]),
        origin: findCol(["מוצא", "יישוב מוצא", "origin"]),
        dest: findCol(["יעד", "יישוב יעד", "dest"]),
        time: findCol(["שעה", "שעת רישוי", "time"]),
        days: findCol(["ימים", "ימי פעילות", "days"]),
        ridership: findCol(["נוסעים", "תיקופים", "ridership"]),
        peakLoad: findCol(["עומס", "שיא", "peak"]),
        district: findCol(["מחוז", "district"]),
        lineType: findCol(["סוג", "סוג שירות", "type"]),
        distance: findCol(["אורך", "מרחק", "distance"]),
        cost: findCol(["עלות", "cost"]),
        tripCount: findCol(["נסיעות", "כמות נסיעות", "trips"]),
        busSize: findCol(["גודל", "רכב", "bus"])
      };
      
      setFileProgress(50);
      setFileMessage("מעבד שורות...");
      await yieldFrame();
      
      const parsed = [];
      const CHUNK = 500;
      
      for (let i = 1; i < lines.length; i += CHUNK) {
        const end = Math.min(i + CHUNK, lines.length);
        
        for (let j = i; j < end; j++) {
          const line = lines[j];
          // פירוק שורה (תומך בערכים עם פסיקים בתוך גרשיים)
          const values = [];
          let current = '';
          let inQuotes = false;
          
          for (let k = 0; k < line.length; k++) {
            const char = line[k];
            if (char === '"') {
              inQuotes = !inQuotes;
            } else if (char === ',' && !inQuotes) {
              values.push(current.trim());
              current = '';
            } else {
              current += char;
            }
          }
          values.push(current.trim());
          
          const getValue = (idx) => idx >= 0 && idx < values.length ? values[idx].replace(/^"|"$/g, '') : '';
          
          const lineNum = getValue(cols.lineNum);
          if (!lineNum) continue;
          
          const ridership = parseFloat(getValue(cols.ridership)) || 0;
          const peakLoad = parseFloat(getValue(cols.peakLoad)) || 0;
          const distance = parseFloat(getValue(cols.distance)) || 0;
          const cost = parseFloat(getValue(cols.cost)) || 0;
          const tripCount = parseInt(getValue(cols.tripCount)) || 1;
          const busSize = getValue(cols.busSize) || "אוטובוס";
          const capacity = getCapacity(busSize);
          
          const timeStr = getValue(cols.time);
          const parsedTime = fmtTime(timeStr);
          const mins = timeToMins(parsedTime);
          const timeMins = mins !== null ? mins : 0;
          
          const daysRaw = getValue(cols.days);
          const daysInfo = parseDays(daysRaw);
          
          const origin = getValue(cols.origin) || "לא ידוע";
          const dest = getValue(cols.dest) || "לא ידוע";
          const lineType = getValue(cols.lineType) || "עירוני";
          const uniqueness = getValue(findCol(["ייחודיות"]));
          
          parsed.push({
            id: j,
            lineNum,
            makat: getValue(cols.makat),
            direction: getValue(cols.direction),
            origin,
            dest,
            time: mins !== null ? parsedTime : "כללי",
            timeMins,
            period: getPeriod(timeMins),
            days: daysInfo.text,
            daysList: daysInfo.list,
            district: getValue(cols.district) || "כללי",
            lineType,
            ridership: Number(ridership.toFixed(2)),
            peakLoad: Number(peakLoad.toFixed(2)),
            busSize,
            capacity,
            efficiency: Number((Math.max(ridership, peakLoad) / capacity).toFixed(2)),
            distance,
            cost,
            weeklyKm: 0,
            isNightLine: uniqueness.includes("לילה"),
            isEilatPrebooked: origin.includes("אילת") || dest.includes("אילת"),
            isFeedingLine: uniqueness.includes("מזין"),
            opGroup: "",
            uniquenessVal: uniqueness || "",
            exclusiveStops: 0,
            tripCount
          });
        }
        
        const pct = 50 + Math.round(((i - 1) / lines.length) * 45);
        setFileProgress(Math.min(pct, 95));
        setFileMessage(`נמצאו ${parsed.length.toLocaleString()} נסיעות...`);
        await yieldFrame();
      }
      
      if (parsed.length === 0) {
        throw new Error('לא נמצאו נתונים תקינים בקובץ');
      }
      
      setTrips(parsed);
      setFileProgress(100);
      setFileMessage(`נטענו ${parsed.length.toLocaleString()} נסיעות ✓`);
      await yieldFrame();
      setFileLoading(false);
      setInitialLoading(false);
      setCsvLoadFailed(false);
      
    } catch (err) {
      console.log("שגיאה בטעינת CSV:", err.message);
      setFileLoading(false);
      setInitialLoading(false);
      setCsvLoadFailed(true);
    }
  }, []);

  // מפתח הקובץ הנוכחי — נשמר ב-ref כדי שלא יגרור re-render, ומועבר לתוך
  // ה-onmessage של ה-worker בלי להיתפס closure ישן.
  const fileKeyRef = useRef(null);

  // ── טעינה אוטומטית בעליית הקומפוננטה ──────────────────────────────────────
  // 4 קבצי מקור: מצומצם(ראשי) · מרחוב(לוז/שעות) · תחנות · עלות לנוסע(בנצ'מרק)
  const loadFromXLSX = useCallback(async () => {
    const FILES = {
      main: 'מצומצם.xlsx',
      schedule: 'מרחוב.xlsx',
      stops: 'תחנות.xlsx',
      benchmark: 'עלות לנוסע.xlsx',
    };
    try {
      // שלב 1: HEAD מקביל לכל הקבצים → מפתח קאש משולב.
      let fileKey = null;
      try {
        const sigs = await Promise.all(
          Object.values(FILES).map(f =>
            // cache: 'no-cache' מאלץ אימות-מחדש מול השרת (304 אם לא השתנה) —
            // כך חתימת הקובץ תמיד עדכנית והקאש המקומי מתעדכן כשהנתונים משתנים.
            fetch(f, { method: 'HEAD', cache: 'no-cache' }).then(r => (r.ok ? (fileKeyFromHeaders(r) || '') : '')).catch(() => '')
          )
        );
        const combined = sigs.filter(Boolean).join('|');
        if (combined) fileKey = combined;
      } catch (e) { /* HEAD נכשל — נמשיך בלי קאש */ }

      // שלב 2: אם יש מפתח, נסה לטעון מ-IndexedDB. אם תואם — שימוש מיידי.
      if (fileKey) {
        const cached = await idbGetCache(IDB_KEY);
        if (cached && cached.fileKey === fileKey && cached.trips && cached.trips.length > 0) {
          setFileLoading(true);
          setFileMessage('טוען מקאש מקומי...');
          setFileProgress(50);
          // yield קצר כדי שה-UI יציג את הודעת הקאש לפני הצפת ה-render הגדול
          await yieldFrame();
          setLineCitiesMap(cached.lineCitiesMap instanceof Map ? cached.lineCitiesMap : new Map());
          setLineStopsMap(cached.lineStopsMap instanceof Map ? cached.lineStopsMap : new Map());
          setLineNormStopsMap(cached.lineNormStopsMap instanceof Map ? cached.lineNormStopsMap : new Map());
          setCostBenchmarkTable(cached.costBenchmark || null);
          // DEBUG: חשיפה ל-window גם בטעינה מהקאש
          if (typeof window !== 'undefined') {
            window.__kp_trips = cached.trips;
            window.__kp_maps = {
              cities: cached.lineCitiesMap || new Map(),
              stops: cached.lineStopsMap || new Map(),
              normStops: cached.lineNormStopsMap || new Map(),
            };
            window.__kp_bench = cached.costBenchmark || null;
          }
          setTrips(cached.trips);
          setFileProgress(100);
          setFileMessage(`נטענו ${cached.trips.length.toLocaleString()} נסיעות (מקאש) ✓`);
          setFileLoading(false);
          setInitialLoading(false);
          fileKeyRef.current = fileKey;
          return true;
        }
      }

      // שלב 3: אין קאש מתאים — הורדה מקבילה + פרסור.
      setFileLoading(true);
      setFileProgress(3);
      setFileMessage('מוריד קבצי נתונים…');
      fileKeyRef.current = fileKey;

      // הורדה עם מעקב progress לכל קובץ
      const grabWithProgress = async (f, required, onBytes) => {
        let res;
        try { res = await fetch(f, { cache: 'no-cache' }); } catch(e) { if (required) throw e; return null; }
        if (!res.ok) { if (required) throw new Error(f + ' missing'); return null; }
        const total = Number(res.headers.get('content-length') || 0);
        const reader = res.body.getReader();
        const chunks = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          if (total > 0 && onBytes) onBytes(received, total);
        }
        const buf = new Uint8Array(received);
        let pos = 0;
        for (const c of chunks) { buf.set(c, pos); pos += c.length; }
        return buf.buffer;
      };

      // ── מסלול מהיר: JSON (אם קיים) ──────────────────────────────────────
      // קבצי JSON נוצרים מראש ע"י convert-to-json.js (~12MB במקום 46MB XLSX).
      // JSON.parse מהיר 50× מ-SheetJS — ~5 שניות במובייל במקום ~2 דקות.
      const jsonProbeCtl = new AbortController();
      const jsonProbeTimer = setTimeout(() => jsonProbeCtl.abort(), 3000);
      const jsonMainRes = await fetch('data-main.json', { cache: 'no-cache', signal: jsonProbeCtl.signal }).catch(() => null);
      clearTimeout(jsonProbeTimer);
      if (jsonMainRes && jsonMainRes.ok) {
        setFileMessage('מוריד נתונים (JSON)…');
        const JSON_EST = { main: 965_000, schedule: 9_840_000, stops: 16_980_000, benchmark: 3_000 };
        const jsonTotalEst = Object.values(JSON_EST).reduce((a, b) => a + b, 0);
        const jsonReceived = { main: 0, schedule: 0, stops: 0, benchmark: 0 };
        const updateJsonProgress = () => {
          const done = Object.entries(jsonReceived).reduce((s, [k, v]) => s + Math.min(v, JSON_EST[k]), 0);
          setFileProgress(Math.min(20, 2 + Math.round((done / jsonTotalEst) * 18)));
        };
        // הקובץ הראשי כבר נטען — נמשוך ממנו את הנתונים
        const jsonMainReader = jsonMainRes.body.getReader();
        const jsonMainChunks = []; let jmRec = 0;
        while (true) {
          const { done, value } = await jsonMainReader.read();
          if (done) break;
          jsonMainChunks.push(value); jmRec += value.length;
          jsonReceived.main = jmRec; updateJsonProgress(); setFileMessage('מוריד נתוני קווים…');
        }
        const jmBuf = new Uint8Array(jmRec); let jmPos = 0;
        for (const c of jsonMainChunks) { jmBuf.set(c, jmPos); jmPos += c.length; }

        const [jsonScheduleBuf, jsonStopsBuf, jsonBenchmarkBuf] = await Promise.all([
          grabWithProgress('data-schedule.json', false, (b) => { jsonReceived.schedule = b; updateJsonProgress(); }),
          grabWithProgress('data-stops.json',    false, (b) => { jsonReceived.stops    = b; updateJsonProgress(); }),
          grabWithProgress('data-benchmark.json',false, (b) => { jsonReceived.benchmark = b; updateJsonProgress(); }),
        ]);

        setFileMessage('מנתח נתונים…');
        await runWorker({ jsonMainBuf: jmBuf.buffer, jsonScheduleBuf, jsonStopsBuf, jsonBenchmarkBuf });
        return true;
      }

      // ── מסלול רגיל: XLSX ─────────────────────────────────────────────────
      // גדלי קבצים משוערים (בבייטים) לחישוב progress כולל
      const EST = { main: 1_200_000, schedule: 24_000_000, stops: 22_000_000, benchmark: 20_000 };
      const totalEst = Object.values(EST).reduce((a, b) => a + b, 0);
      const received = { main: 0, schedule: 0, stops: 0, benchmark: 0 };
      const updateProgress = () => {
        const done = Object.entries(received).reduce((s, [k, v]) => s + Math.min(v, EST[k]), 0);
        const pct = Math.min(20, 2 + Math.round((done / totalEst) * 18));
        const mb = (done / 1_000_000).toFixed(1);
        const totalMb = (totalEst / 1_000_000).toFixed(0);
        setFileProgress(pct);
        setFileMessage(`מוריד נתונים… ${mb} / ${totalMb} MB`);
      };

      const [main, schedule, stops, benchmark] = await Promise.all([
        grabWithProgress(FILES.main,      true,  (b) => { received.main      = b; updateProgress(); }),
        grabWithProgress(FILES.schedule,  false, (b) => { received.schedule  = b; updateProgress(); }),
        grabWithProgress(FILES.stops,     false, (b) => { received.stops     = b; updateProgress(); }),
        grabWithProgress(FILES.benchmark, false, (b) => { received.benchmark = b; updateProgress(); }),
      ]);
      setFileMessage('מנתח נתונים…');
      await runWorker({ main, schedule, stops, benchmark });
      return true;
    } catch (err) {
      console.log('xlsx auto-load failed:', err.message);
      setInitialLoading(false);
      setLoadError(true);
      return false;
    }
  }, []);

  useEffect(() => {
    setLoadError(false);
    setInitialLoading(true);
    setFileProgress(0);
    setFileMessage('טוען נתונים…');
    (async () => {
      const ok = await loadFromXLSX();
      if (!ok) loadFromCSV();
    })();
  }, [loadFromXLSX, loadFromCSV, retryCount]);

  // טוען את ספריית XLSX ברקע (לצרכי ייצוא לאקסל בלבד — הפרסור עצמו רץ ב-worker).
  // קריאה לא חוסמת — אם הפרסור מסתיים לפני שה-XLSX הסתיים, אין בעיה.
  useEffect(() => {
    loadXLSX().catch(() => { /* swallow */ });
  }, []);

  // ── runWorker — שולח payload ל-Web Worker ומטמיע את התוצאה ──────────────
  // payload: { buffer } (קובץ יחיד/ידני) או { main, schedule, stops, benchmark }.
  const runWorker = (payload) => {
    return new Promise((resolve) => {
      let worker;
      try {
        worker = new Worker('xlsx-worker.js?v=20260617u'); // ?v= cache-busting — עדכן בכל פריסה
      } catch (err) {
        console.error('Worker creation failed:', err);
        alert('שגיאה ביצירת thread עיבוד: ' + err.message);
        setFileLoading(false);
        resolve();
        return;
      }

      worker.onmessage = (ev) => {
        const msg = ev.data;
        if (!msg) return;
        if (msg.type === 'progress') {
          // הורדה מסתיימת ב-42%; ממירים את אחוזי ה-Worker (0-100) לטווח 42-100
          // כך שהסרגל ממשיך קדימה ולא קופץ אחורה בעת מעבר משלב הורדה לשלב פרסור
          const remapped = 20 + Math.round((msg.percent / 100) * 79);
          setFileProgress(Math.min(remapped, 99));
          setFileMessage(msg.message);
        } else if (msg.type === 'done') {
          // lineCitiesMap מגיע כ-Map עם Set-ים בזכות structured clone
          const lcm = msg.lineCitiesMap instanceof Map ? msg.lineCitiesMap : new Map();
          const lsm = msg.lineStopsMap instanceof Map ? msg.lineStopsMap : new Map();
          const lnsm = msg.lineNormStopsMap instanceof Map ? msg.lineNormStopsMap : new Map();
          const bench = msg.costBenchmark || null;
          setLineCitiesMap(lcm);
          setLineStopsMap(lsm);
          setLineNormStopsMap(lnsm);
          setCostBenchmarkTable(bench);
          // DEBUG: חשיפה זמנית ל-window לטובת איתור באגים מהקונסול
          if (typeof window !== 'undefined') {
            window.__kp_trips = msg.trips || [];
            window.__kp_maps = { cities: lcm, stops: lsm, normStops: lnsm };
            window.__kp_bench = bench;
          }
          setTrips(msg.trips || []);
          setFileProgress(100);
          setFileMessage(`נטענו ${(msg.trips || []).length.toLocaleString()} נסיעות ✓`);
          setFileLoading(false);
          setInitialLoading(false);
          // שמירה בקאש (best-effort, רץ ברקע) — יעיל לטעינה הבאה
          if (fileKeyRef.current) {
            idbSetCache(IDB_KEY, {
              fileKey: fileKeyRef.current,
              trips: msg.trips || [],
              lineCitiesMap: lcm,
              lineStopsMap: lsm,
              lineNormStopsMap: lnsm,
              costBenchmark: bench,
              savedAt: Date.now(),
            });
          }
          worker.terminate();
          resolve();
        } else if (msg.type === 'error') {
          console.error('Worker error:', msg.message);
          alert('שגיאה: ' + msg.message);
          setFileLoading(false);
          worker.terminate();
          resolve();
        }
      };

      worker.onerror = (err) => {
        console.error('Worker exception:', err);
        alert('שגיאה בעיבוד הקובץ: ' + (err.message || 'unknown'));
        setFileLoading(false);
        worker.terminate();
        resolve();
      };

      // העברה ב-transfer: ה-buffers עוברים למחזיק ה-worker בלי copy.
      const buffers = payload.buffer
        ? [payload.buffer]
        : ['main', 'schedule', 'stops', 'benchmark'].map(k => payload[k]).filter(Boolean);
      try {
        worker.postMessage({ type: 'parse', ...payload }, buffers);
      } catch (err) {
        // fallback אם הדפדפן לא תומך ב-transferable
        worker.postMessage({ type: 'parse', ...payload });
      }
    });
  };

  // העלאה ידנית של קובץ יחיד (זרימת legacy — workbook עם כל הגיליונות).
  const onFile = async (e) => {
    let buffer;
    if (e instanceof ArrayBuffer) {
      buffer = e;
    } else {
      const f = e.target.files[0];
      if (!f) return;
      e.target.value = '';
      setFileLoading(true);
      setFileProgress(2);
      setFileMessage("קורא קובץ...");
      buffer = await f.arrayBuffer();
    }
    setFileLoading(true);
    setFileProgress(2);
    setFileMessage("קורא קובץ...");
    return runWorker({ buffer });
  };

  // ── קווים לא יעילים — ניקוד מבוסס קטגוריה ──────────────────────────────
  // 4 רכיבי ניקוד:
  //   1) נסיעות שפל (עד 30) — סף לפי קטגוריה
  //   2) ק"מ מבוזבז (עד 20)
  //   3) עלות תפעולית (עד 20) — יחס לממוצע הקטגוריה
  //   4) ממוצע נוסעים ועומס שיא (עד 30)
  // הגנות (מופחתות אחרי החיבור):
  //   - תחנות בלעדיות / קו עובר: עד 15 נקודות
  //   - מותאם רכבת (uniqueness מכיל "רכבת"): 10 נקודות
  //   - תלמידים בשעות בית ספר: 10 נקודות
  const redundantLines = useMemo(() => {
    // שלב 1: ספירת כמה קווים מגיעים לכל יעד (לזיהוי "תחנת קצה ייחודית")
    const destLineCount = new Map();
    {
      const seen = new Set();
      for (let i = 0; i < trips.length; i++) {
        const t = trips[i];
        const dKey = String(t.dest || '').trim().toLowerCase();
        if (!dKey || dKey === 'לא ידוע' || dKey === 'כללי') continue;
        const pairKey = `${t.lineNum}__${dKey}`;
        if (seen.has(pairKey)) continue;
        seen.add(pairKey);
        destLineCount.set(dKey, (destLineCount.get(dKey) || 0) + 1);
      }
    }

    const groups = {};
    const cityOnlyStr = (s) => s ? (s.indexOf(' - ') > 0 ? s.slice(0, s.indexOf(' - ')).trim() : s.split('/')[0].trim()) : '';
    for (let i = 0; i < trips.length; i++) {
      const t = trips[i];
      const o = cityOnlyStr(t.origin);
      const d = cityOnlyStr(t.dest);
      const cityPair = [o, d].sort().join('-');
      const groupKey = `${t.lineNum}_${cityPair}`;
      if (!groups[groupKey]) groups[groupKey] = [];
      groups[groupKey].push(t);
    }

    return Object.entries(groups).map(([groupKey, data]) => {
      const lineNum = data[0].lineNum;
      const totalTrips = data.reduce((s, t) => s + t.tripCount, 0);
      const totalRiders = data.reduce((s, t) => s + (t.ridership * t.tripCount), 0);
      const avgRiders = totalTrips > 0 ? (totalRiders / totalTrips) : 0;
      const totalPeaks = data.reduce((s, t) => s + (t.peakLoad * t.tripCount), 0);
      const avgPeak = totalTrips > 0 ? (totalPeaks / totalTrips) : 0;

      // סיווג הקו
      const category = classifyLine({
        opGroup: data[0].opGroup,
        uniqueness: data[0].uniquenessVal,
        lineType: data[0].lineType,
        distance: data[0].distance,
        trips: totalTrips,
        isNight: data[0].isNightLine,
        isFeeding: data[0].isFeedingLine,
      });
      const lowRiderTh = LOW_RIDER_THRESHOLD[category] || 10;
      const costBenchmark = lookupCostBenchmark(costBenchmarkTable, category, data[0].district);

      // נסיעות שפל לפי סף הקטגוריה
      const lowTrips  = data.filter(t => t.ridership < lowRiderTh);
      const lowCount  = lowTrips.reduce((s, t) => s + t.tripCount, 0);
      const percentLow = totalTrips > 0 ? (lowCount / totalTrips) * 100 : 0;

      const deadHoursTrips = data.filter(t => t.timeMins >= 540 && t.timeMins <= 840);
      const avgDeadHours = deadHoursTrips.length > 0 ? deadHoursTrips.reduce((s, t) => s + t.ridership, 0) / deadHoursTrips.length : null;

      const avgCapacity = data.reduce((s,t) => s + (t.capacity || 50), 0) / data.length || 50;
      const scale = avgCapacity / 50;

      const wastedKm = Math.round(
        lowTrips.reduce((s, t) => s + ((t.distance || 0) * t.tripCount), 0)
      );

      const validCosts = data.filter(t => t.cost > 0);
      const avgCost = validCosts.length > 0 ? validCosts.reduce((s, t) => s + t.cost, 0) / validCosts.length : 0;
      const costRatio = costBenchmark > 0 && avgCost > 0 ? avgCost / costBenchmark : 0;

      let totalKm = Math.round(data.reduce((s, t) => s + ((t.distance || 0) * t.tripCount), 0));
      if (data[0].weeklyKm > 0 && totalKm === 0) totalKm = Math.round(data[0].weeklyKm);
      const nonWastedKm = Math.max(0, totalKm - wastedKm);

      // ── ניקוד ──
      let score = 0;
      const componentScores = {};

      // 1. נסיעות שפל (עד 30 נק')
      componentScores.lowTrips = Math.min(30, percentLow * 0.3);
      score += componentScores.lowTrips;

      // 2. ק"מ מבוזבז (עד 20 נק')
      const wastedRatio = totalKm > 0 ? (wastedKm / totalKm) : 0;
      let wastedScore = wastedRatio * 10;
      if (wastedKm > 100) wastedScore += 10;
      componentScores.wastedKm = Math.min(20, wastedScore);
      score += componentScores.wastedKm;

      // 3. עלות תפעולית — יחס לממוצע קטגוריה (עד 20 נק')
      let costScore = 0;
      if (costRatio === 0) costScore = 0;
      else if (costRatio <= 0.7) costScore = 0;
      else if (costRatio <= 1.3) costScore = 5;
      else if (costRatio <= 1.7) costScore = 8;
      else if (costRatio <= 2.5) costScore = 12;
      else if (costRatio <= 4)   costScore = 16;
      else if (costRatio <= 6)   costScore = 18;
      else                       costScore = 20;
      componentScores.cost = costScore;
      score += costScore;

      // 4. נוסעים ועומס שיא (עד 30 נק') — תלוי בקיבולת
      let ridersScore = 0;
      if (avgRiders < (lowRiderTh * 0.6 * scale)) ridersScore += 15;
      else if (avgRiders < (lowRiderTh * 1.2 * scale)) ridersScore += 7;
      if (avgPeak < (15 * scale)) ridersScore += 15;
      componentScores.riders = Math.min(30, ridersScore);
      score += componentScores.riders;

      const rawScore = Math.min(100, Math.round(score));

      // ── הגנות (deductions) ──
      const protections = [];
      let totalDeduction = 0;

      // הגנה 1: תחנות בלעדיות / יעד ייחודי
      const exclusiveStops = data[0].exclusiveStops || 0;
      const destKey = String(data[0].dest || '').trim().toLowerCase();
      const isExclusiveDest = destKey && (destLineCount.get(destKey) || 0) <= 1;
      if (exclusiveStops > 0 || isExclusiveDest) {
        protections.push({ name: 'תחנות ייחודיות', value: 15, detail: exclusiveStops > 0 ? `${exclusiveStops} תחנות בלעדיות` : 'יעד יחיד באזור' });
        totalDeduction += 15;
      }

      // הגנה 2: מותאם רכבת — רק אם השדה "ייחודיות" מכיל במפורש "רכבת".
      // לא לבלבל עם Eilat prebooked — זה מושג שונה לגמרי (הזמנה מראש, לא לוז רכבת).
      const isTrainCoord = (data[0].uniquenessVal || '').includes('רכבת');
      if (isTrainCoord) {
        protections.push({ name: 'מותאם רכבת', value: 10, detail: 'יוצא בתיאום עם לוז רכבת' });
        totalDeduction += 10;
      }

      // הגנה 3: תלמידים בשעות בית ספר
      if (category === 'תלמידים') {
        // בית ספר: 7:00-8:30, 13:00-15:30
        const schoolHourTrips = data.filter(t =>
          (t.timeMins >= 420 && t.timeMins <= 510) ||
          (t.timeMins >= 780 && t.timeMins <= 930)
        ).reduce((s, t) => s + t.tripCount, 0);
        const schoolRatio = totalTrips > 0 ? schoolHourTrips / totalTrips : 0;
        if (schoolRatio >= 0.6) {
          protections.push({ name: 'תלמידים בשעות בי"ס', value: 10, detail: `${Math.round(schoolRatio * 100)}% מהנסיעות` });
          totalDeduction += 10;
        }
      }

      const finalScore = Math.max(0, rawScore - totalDeduction);
      const tier = getStatusTier(finalScore);

      const sortedData = [...data].sort((a, b) => {
        const dirA = String(a.direction).replace(/\D/g, '');
        const dirB = String(b.direction).replace(/\D/g, '');
        return Number(dirA) - Number(dirB);
      });

      return {
        lineNum,
        avg: avgRiders.toFixed(1),
        count: totalTrips,
        totalRiders,
        score: finalScore,
        rawScore,
        componentScores,
        protections,
        totalDeduction,
        category,
        costBenchmark,
        costRatio: Number(costRatio.toFixed(2)),
        lowRiderTh,
        origin: sortedData[0].origin,
        dest: sortedData[0].dest,
        district: sortedData[0].district,
        makat: sortedData[0].makat,
        status: tier.label,
        statusTier: tier,
        percentLow: Math.round(percentLow),
        avgPeak: Math.round(avgPeak),
        wastedKm,
        cost: avgCost,
        totalKm,
        nonWastedKm,
        groupKey,
        isNightLine: sortedData[0].isNightLine,
        isEilatPrebooked: sortedData[0].isEilatPrebooked,
        isFeedingLine: sortedData[0].isFeedingLine,
        exclusiveStops,
      };
    }).filter(l => l.score >= 25).sort((a,b) => b.score - a.score);
  }, [trips, costBenchmarkTable]);

  const filteredRedundant = useMemo(() => {
    let result = [...redundantLines];
    if (filterDistrict !== "all") {
      result = result.filter(r => r.district === filterDistrict);
    }
    if (filterCategory !== "all") {
      result = result.filter(r => r.category === filterCategory);
    }
    if (searchCity) {
      const sCity = searchCity.toLowerCase();
      result = result.filter(r => {
        const isOriginDest = r.origin.toLowerCase().includes(sCity) || r.dest.toLowerCase().includes(sCity);
        if (isOriginDest) return true;
        
        const cleanMakat = String(r.makat || '').replace(/^0+/, '').trim();
        const cleanLine = String(r.lineNum || '').replace(/^0+/, '').trim();
        const citiesSet = lineCitiesMap.get(cleanMakat) || lineCitiesMap.get(cleanLine);
        return citiesSet ? Array.from(citiesSet).some(c => c.includes(sCity)) : false;
      });
    }
    
    result.sort((a, b) => {
      if (redundantSortBy === "wastedKm") return b.wastedKm - a.wastedKm;
      if (redundantSortBy === "cost") return b.cost - a.cost;
      if (redundantSortBy === "count") return b.count - a.count;
      return b.score - a.score;
    });

    return result;
  }, [redundantLines, searchCity, filterDistrict, filterCategory, lineCitiesMap, redundantSortBy]);

  const areaStats = useMemo(() => {
    const map = new Map();
    redundantLines.forEach(line => {
      // כאן הוספנו את הסינון - הניתוח האזורי יתייחס רק לקווים מיותרים לחלוטין (80 ומעלה)
      if (line.score < 80) return;

      const keys = areaViewMode === 'district' 
        ? [line.district] 
        : Array.from(new Set([line.origin, line.dest]));

      keys.forEach(key => {
        if (!key || key === "לא ידוע" || key === "כללי") return;
        if (!map.has(key)) {
          map.set(key, { name: key, totalScore: 0, lineCount: 0, totalWastedKm: 0, totalCost: 0, validCostCount: 0, sumAvgRiders: 0, totalAreaTrips: 0, totalAreaRiders: 0 });
        }
        const entry = map.get(key);
        entry.totalScore += line.score;
        entry.lineCount += 1;
        entry.totalWastedKm += line.wastedKm;
        entry.totalAreaRiders += line.totalRiders;
        entry.totalAreaTrips += line.count;
        entry.sumAvgRiders += parseFloat(line.avg || 0);
        if (line.cost > 0) {
          entry.totalCost += line.cost;
          entry.validCostCount += 1;
        }
      });
    });

    return Array.from(map.values()).map(entry => {
      const baseScore = entry.totalScore / entry.lineCount;
      // קנס חומרה על נפח הבזבוז - כל 15,000 ק"מ סרק מוסיפים נקודה לציון החומרה, עד 40 נקודות תוספת
      const volumePenalty = Math.min(40, entry.totalWastedKm / 15000);
      
      return {
        name: entry.name,
        avgScore: Math.min(100, Math.round(baseScore + volumePenalty)),
        lineCount: entry.lineCount,
        wastedKm: entry.totalWastedKm,
        totalTrips: entry.totalAreaTrips,
        avgCost: entry.validCostCount > 0 ? entry.totalCost / entry.validCostCount : 0,
        avgAreaRiders: entry.totalAreaTrips > 0 ? (entry.totalAreaRiders / entry.totalAreaTrips).toFixed(1) : 0
      };
    }).sort((a, b) => {
      if (areaSortBy === 'wastedKm') return b.wastedKm - a.wastedKm;
      if (areaSortBy === 'lineCount') return b.lineCount - a.lineCount;
      if (areaSortBy === 'avgRiders') return parseFloat(a.avgAreaRiders) - parseFloat(b.avgAreaRiders);
      return b.avgScore - a.avgScore;
    });
  }, [redundantLines, areaViewMode, areaSortBy]);

  const handleViewAreaLines = (areaName) => {
    if (areaViewMode === 'district') {
      setFilterDistrict(areaName);
      setSearchCity("");
    } else {
      setFilterDistrict("all");
      setSearchCity(areaName);
    }
    setTab("redundant");
  };

  const exportAreaToExcel = (areaName, viewMode) => {
    // סינון הקווים הרלוונטיים לאזור שנבחר, ורק אלו שחשודים כמיותרים (ציון 80 ומעלה) כדי שיתאים לתצוגה
    const filteredLines = redundantLines.filter(line => {
      if (line.score < 80) return false;
      if (viewMode === 'district') return line.district === areaName;
      return line.origin === areaName || line.dest === areaName;
    });

    if (filteredLines.length === 0) return;

    // עיצוב הנתונים לקובץ
    const exportData = filteredLines.map(line => ({
      'מספר קו': line.lineNum,
      'מק"ט': line.makat,
      'מוצא': line.origin,
      'יעד': line.dest,
      'מחוז': line.district,
      'ציון אי-יעילות': line.score,
      'ממוצע נוסעים לנסיעה': parseFloat(line.avg),
      'עומס שיא ממוצע': line.avgPeak,
      'כמות נסיעות בשבוע': line.count,
      'עלות תפעולית ממוצעת': line.cost > 0 ? `₪${line.cost.toFixed(2)}` : 'לא זמין',
      'ק"מ מבוזבז': line.wastedKm,
      'ק"מ שימושי (ללא סרק)': line.nonWastedKm,
    }));

    const ws = window.XLSX.utils.json_to_sheet(exportData);
    if(!ws['!views']) ws['!views'] = [];
    ws['!views'].push({ rightToLeft: true }); // הגדרה מימין לשמאל
    const wb = window.XLSX.utils.book_new();
    window.XLSX.utils.book_append_sheet(wb, ws, "קווים_חשודים_כמיותרים");
    
    const fileName = `קווים_חשודים_כמיותרים_${areaName.replace(/\s+/g, '_')}.xlsx`;
    window.XLSX.writeFile(wb, fileName);
  };

  const tableTrips = useMemo(() => {
    const sCity = searchCity.toLowerCase();
    let filtered = trips.filter(t => {
      if (filterLineType !== "all" && t.lineType !== filterLineType) return false;
      if (sCity) {
        const isOriginDest = t.origin.toLowerCase().includes(sCity) || t.dest.toLowerCase().includes(sCity);
        let isTransit = false;
        if (!isOriginDest) {
            const makatKey = String(t.makat || '').replace(/^0+/, '').trim();
            const lineKey = String(t.lineNum || '').replace(/^0+/, '').trim();
            const citiesSet = lineCitiesMap.get(makatKey) || lineCitiesMap.get(lineKey);
            isTransit = citiesSet ? Array.from(citiesSet).some(c => c.includes(sCity)) : false;
        }
        if (!isOriginDest && !isTransit) return false;
      }
      if (showCrowded && t.ridership < 40 && t.peakLoad < 40) return false;
      return true;
    });

    if (sortConfig.key) {
      filtered.sort((a, b) => {
        if (a[sortConfig.key] < b[sortConfig.key]) return sortConfig.direction === 'asc' ? -1 : 1;
        if (a[sortConfig.key] > b[sortConfig.key]) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return filtered;
  }, [trips, searchCity, showCrowded, sortConfig, lineCitiesMap, filterLineType]);

  const runOptimization = async (overrideLine, overrideCity, overrideDirection, overrideDays) => {
    const lineToUse = typeof overrideLine === 'string' ? overrideLine : optLine;
    const cityToUse = typeof overrideCity === 'string' ? overrideCity : optCity;
    const dirToUse = typeof overrideDirection === 'string' ? overrideDirection : optDirection;
    const daysToUse = Array.isArray(overrideDays) ? overrideDays : optDays;
    setSimLoading(true);
    setVisibleOptCount(50);
    await yieldFrame();

    const filteredTrips = trips.filter(t => {
        if (lineToUse) {
          const searchVals = String(lineToUse).split(',').map(s => s.trim()).filter(Boolean);
          if (searchVals.length > 0) {
            const lineStr = String(t.lineNum).trim();
            const makatStr = String(t.makat || '').trim();
            if (!searchVals.includes(lineStr) && !searchVals.includes(makatStr)) return false;
          }
        }
      
      if (cityToUse && cityToUse !== "all") {
        const sCity = cityToUse.toLowerCase();
        const matchesOriginDest = t.origin.toLowerCase().includes(sCity) || t.dest.toLowerCase().includes(sCity);
        const makatKey  = String(t.makat  || '').replace(/^0+/, '').trim();
        const lineKey   = String(t.lineNum || '').replace(/^0+/, '').trim();
        const citiesSet = lineCitiesMap.get(makatKey) || lineCitiesMap.get(lineKey);
        const matchesTransit = citiesSet ? Array.from(citiesSet).some(c => c.includes(sCity)) : false;
        if (!matchesOriginDest && !matchesTransit) return false;
      }    
      
      if (dirToUse && dirToUse !== "all" && !String(t.direction).includes(dirToUse)) return false;
      
      if (daysToUse && daysToUse.length > 0) {
        const hasMatchingDay = daysToUse.some(day => t.daysList.includes(String(day)));
        if (!hasMatchingDay) return false;
      }
      return true;
    });

    if (filteredTrips.length === 0) {
      setOptimizations([]);
      setSimLoading(false);
      return;
    }

    const results = [];
    const grouped = {};
    const lineDayCounts = {};
    const cancelledCountByLineDay = {};

    filteredTrips.forEach(t => {
      const key = `${t.lineNum}|${t.direction}|${t.days}|${t.origin}|${t.dest}`;
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(t);
      const countKey = `${t.lineNum}|${t.daysList.join('')}`;
      lineDayCounts[countKey] = (lineDayCounts[countKey] || 0) + t.tripCount;
    });

    const customGapValue = parseInt(optCustomGap, 10);
    const groupEntries = Object.values(grouped);
    const GSIM_CHUNK = 300; 

    for (let gi = 0; gi < groupEntries.length; gi++) {
      const group = groupEntries[gi];
      group.sort((a,b) => a.timeMins - b.timeMins);
      const usedTrips = new Set(); 
      let cancelledInGroup = 0;
      
      for(let i = 0; i < group.length; i++) {
        const t1 = group[i];
        if (usedTrips.has(t1.id)) continue;

        const t2 = i < group.length - 1 ? group[i+1] : null;
        if (t2 && t1.timeMins === t2.timeMins) continue;

        let merged = false;
        const category = getLineCategory(t1.lineType);
        const totalTripsInDay = lineDayCounts[`${t1.lineNum}|${t1.daysList.join('')}`] || 0;

        const capacity = t1.capacity || 50;
        const scale = capacity / 50;

        let defaultMaxGap, maxRidersEach, maxTotalMerge, cancelGapCheck;

        if (category === 'urban') {
          defaultMaxGap = 30; 
          maxRidersEach = Math.round(10 * scale); 
          maxTotalMerge = Math.round(18 * scale); 
          cancelGapCheck = 15;
        } else if (category === 'regional') {
          defaultMaxGap = 180; 
          maxRidersEach = Math.round(10 * scale); 
          maxTotalMerge = Math.round(18 * scale); 
          cancelGapCheck = 240; 
        } else {
          defaultMaxGap = 60; 
          maxRidersEach = Math.round(10 * scale); 
          maxTotalMerge = Math.round(20 * scale); 
          cancelGapCheck = 60;
        }
        
        const maxGapMerge = !isNaN(customGapValue) && customGapValue > 0 ? customGapValue : defaultMaxGap;
        const isNight = t1.isNightLine || t1.period === 'לילה';
        const hasCustomGap = !isNaN(customGapValue) && customGapValue > 0;

        if (isNight) cancelGapCheck = 60;

        let defaultCancelRiders = category === 'regional' ? Math.max(1, Math.round(3 * scale)) : Math.max(1, Math.round(5 * scale));
        if (t1.isNightLine) defaultCancelRiders = 1;
        const userCancelThreshold = parseFloat(optCancelThreshold);
        const cancelRiders = !isNaN(userCancelThreshold) ? userCancelThreshold : defaultCancelRiders;
        
        let actionTaken = false;
        const getMetricVal = (t) => optMetric === 'peakLoad' && t.peakLoad > 0 ? t.peakLoad : t.ridership;

        if (t2 && !usedTrips.has(t2.id) && totalTripsInDay >= 6) {
          const gap1 = t2.timeMins - t1.timeMins;
          const val1 = getMetricVal(t1);
          const val2 = getMetricVal(t2);
          const totalVal1 = val1 + val2;
          
          const t3 = i < group.length - 2 ? group[i+2] : null;
          let skipForBetterMerge = false;
          
          if (t3 && !usedTrips.has(t3.id)) {
            const gap2 = t3.timeMins - t2.timeMins;
            const val3 = getMetricVal(t3);
            const totalVal2 = val2 + val3;
            if (gap2 > 0 && gap2 < gap1 && gap2 <= maxGapMerge && val2 < maxRidersEach && val3 < maxRidersEach && totalVal2 < maxTotalMerge) {
              skipForBetterMerge = true; 
            }
          }

          if (!skipForBetterMerge && gap1 > 0 && gap1 <= maxGapMerge && val1 < maxRidersEach && val2 < maxRidersEach && totalVal1 < maxTotalMerge && (!isNight || hasCustomGap)) {
            const suggestedMins = Math.floor((t1.timeMins + t2.timeMins) / 2);
            const suggestedTime = `${String(Math.floor(suggestedMins/60)).padStart(2,'0')}:${String(suggestedMins%60).padStart(2,'0')}`;

            results.push({
              type: 'merge',
              isNightLine: t1.isNightLine,
              isEilatPrebooked: t1.isEilatPrebooked,
              isFeedingLine: t1.isFeedingLine,
              categoryLabel: category === 'urban' ? 'עירוני' : category === 'regional' ? 'אזורי' : 'בין-עירוני',
              line: t1.lineNum, origin: t1.origin, dest: t1.dest, direction: t1.direction,
              from: t1.time, to: t2.time, timeMins: t1.timeMins, suggestedTime: suggestedTime,
              days: t1.days, gap: gap1, usedMetric: optMetric, total: Number(totalVal1.toFixed(2)), val1: val1, val2: val2,
              busSize: t1.busSize, capacity: t1.capacity, efficiency: t1.efficiency, metricVal: val1
            });
            usedTrips.add(t1.id); usedTrips.add(t2.id); merged = true; actionTaken = true;
          }
        }

        if (!merged) {
          const valCancel = getMetricVal(t1);

          if (valCancel < cancelRiders) {
            let allowCancel = true;
            const dayKey = `${t1.lineNum}|${t1.daysList.join('')}`;
            const totalTripsBothDirs = lineDayCounts[dayKey] || 0;
            const currentCancelledBoth = cancelledCountByLineDay[dayKey] || 0;

            const userMinTrips = parseInt(optMinTrips, 10);
            const minRequired = !isNaN(userMinTrips) ? userMinTrips : (category === 'regional' ? 3 : 0);

            if ((totalTripsBothDirs - currentCancelledBoth) <= minRequired) { allowCancel = false; }

            // הגנה חדשה: אסור לבטל נסיעה ראשונה או אחרונה ביום של הקו והכיוון.
            // ביטול קצוות יומיים פוגע פגיעה לא פרופורציונלית בנוסעים שתלויים בקו.
            const isFirstOfDay = i === 0;
            const isLastOfDay  = i === group.length - 1;
            if (isFirstOfDay || isLastOfDay) { allowCancel = false; }

            if (allowCancel) {
              let hasAlternative = false; 
              const prev = i > 0 ? group[i-1] : null; const next = t2;
              
              if (prev && (t1.timeMins - prev.timeMins) <= cancelGapCheck) hasAlternative = true;
              if (next && (next.timeMins - t1.timeMins) <= cancelGapCheck) hasAlternative = true;

              if (hasAlternative) {
                results.push({
                  type: 'cancel', isNightLine: t1.isNightLine, isEilatPrebooked: t1.isEilatPrebooked, isFeedingLine: t1.isFeedingLine,
                  categoryLabel: category === 'urban' ? 'עירוני' : category === 'regional' ? 'אזורי' : 'בין-עירוני',
                  line: t1.lineNum, origin: t1.origin, dest: t1.dest, direction: t1.direction,
                  time: t1.time, timeMins: t1.timeMins, days: t1.days, usedMetric: optMetric, metricVal: valCancel, efficiency: t1.efficiency,
                  busSize: t1.busSize, capacity: t1.capacity
                });
                usedTrips.add(t1.id); cancelledInGroup++; cancelledCountByLineDay[dayKey] = (cancelledCountByLineDay[dayKey] || 0) + 1; actionTaken = true;
              }
            }
          }
        }

        if (!actionTaken && !usedTrips.has(t1.id)) {
           results.push({
              type: 'ok', isNightLine: t1.isNightLine, isEilatPrebooked: t1.isEilatPrebooked, isFeedingLine: t1.isFeedingLine,
              categoryLabel: category === 'urban' ? 'עירוני' : category === 'regional' ? 'אזורי' : 'בין-עירוני',
              line: t1.lineNum, origin: t1.origin, dest: t1.dest, direction: t1.direction, time: t1.time, timeMins: t1.timeMins, days: t1.days, usedMetric: optMetric, metricVal: getMetricVal(t1), efficiency: t1.efficiency,
              busSize: t1.busSize, capacity: t1.capacity
           });
           usedTrips.add(t1.id);
        }
      }
      if (gi % GSIM_CHUNK === GSIM_CHUNK - 1) await yieldFrame();
    }
    
    results.sort((a, b) => {
      if (cityToUse && cityToUse !== "all") {
        const getWeight = (lbl) => lbl === 'עירוני' ? 1 : lbl === 'אזורי' ? 2 : 3;
        const wA = getWeight(a.categoryLabel);
        const wB = getWeight(b.categoryLabel);
        if (wA !== wB) return wA - wB;
      }
      const lineComp = String(a.line || "").localeCompare(String(b.line || ""), 'he', {numeric: true});
      if (lineComp !== 0) return lineComp;
      const pairA = [String(a.origin || "").trim(), String(a.dest || "").trim()].sort().join('-');
      const pairB = [String(b.origin || "").trim(), String(b.dest || "").trim()].sort().join('-');
      const pairComp = pairA.localeCompare(pairB, 'he');
      if (pairComp !== 0) return pairComp;
      const dirComp = String(a.direction || "").localeCompare(String(b.direction || ""), 'he', {numeric: true});
      if (dirComp !== 0) return dirComp;
      const getDayVal = (d) => {
        if (!d) return 99;
        if (d.includes("א'-ה'")) return 1;
        if (d.includes("א'-ו'")) return 2;
        if (d.includes("שישי") || d.includes("ו'")) return 6;
        if (d.includes("שבת") || d.includes("מוצ")) return 7;
        return 5;
      };
      const d1 = getDayVal(a.days);
      const d2 = getDayVal(b.days);
      if (d1 !== d2) return d1 - d2;
      return a.timeMins - b.timeMins;
    });

    setOptimizations(results);
    setSimLoading(false);
  };

  const exportOptimizationsToExcel = () => {
    if (optimizations.length === 0) return;
    const dataToExport = showAllTripsInSimulator ? optimizations : optimizations.filter(o => o.type !== 'ok');
    const exportData = dataToExport.map(opt => {
      const metricName = opt.usedMetric === 'peakLoad' ? 'עומס שיא' : 'נוסעים';
      if (opt.type === 'merge') {
        return { 'מספר קו': opt.line, 'סוג קו': opt.categoryLabel, 'סוג רכב': opt.busSize, 'מוצא': opt.origin, 'יעד': opt.dest, 'כיוון': opt.direction, 'ימי פעילות': opt.days, 'פעולה מומלצת': 'איחוד נסיעות', 'שעות מקוריות': `${opt.from}, ${opt.to}`, 'שעה מוצעת (חדשה)': opt.suggestedTime, 'מדד (נוסעים / עומס)': `סה"כ ${metricName}: ${opt.total} (נסיעה 1: ${opt.val1}, נסיעה 2: ${opt.val2})`, 'הערות': `איחוד 2 נסיעות בהפרש של ${opt.gap} דקות` };
      } else if (opt.type === 'cancel') {
        return { 'מספר קו': opt.line, 'סוג קו': opt.categoryLabel, 'סוג רכב': opt.busSize, 'מוצא': opt.origin, 'יעד': opt.dest, 'כיוון': opt.direction, 'ימי פעילות': opt.days, 'פעולה מומלצת': 'ביטול נסיעה', 'שעות מקוריות': opt.time, 'שעה מוצעת (חדשה)': '--', 'מדד (נוסעים / עומס)': `${metricName}: ${opt.metricVal}`, 'הערות': 'חשד לנסיעה מיותרת עם חלופה קרובה בזמן' };
      } else {
         return { 'מספר קו': opt.line, 'סוג קו': opt.categoryLabel, 'סוג רכב': opt.busSize, 'מוצא': opt.origin, 'יעד': opt.dest, 'כיוון': opt.direction, 'ימי פעילות': opt.days, 'פעולה מומלצת': 'ללא שינוי (תקין)', 'שעות מקוריות': opt.time, 'שעה מוצעת (חדשה)': opt.time, 'מדד (נוסעים / עומס)': `${metricName}: ${opt.metricVal}`, 'הערות': 'נסיעה תקינה שעומדת בתנאי' };
      }
    });
    const ws = window.XLSX.utils.json_to_sheet(exportData);
    if(!ws['!views']) ws['!views'] = [];
    ws['!views'].push({ rightToLeft: true });
    const wb = window.XLSX.utils.book_new();
    window.XLSX.utils.book_append_sheet(wb, ws, "המלצות_ייעול");
    
    let fileName = "קופח_המלצות_ייעול_לוז.xlsx";
    if (optimizations.length > 0) {
      if (optLine) {
        const o = optimizations.find(x => String(x.line) === String(optLine)) || optimizations[0];
        fileName = `קו ${o.line} ${o.origin} - ${o.dest}.xlsx`;
      } else if (optCity !== "all") {
        fileName = `ייעול_קווים_${optCity}.xlsx`;
      }
    }
    window.XLSX.writeFile(wb, fileName);
  };

  const handleOptimizeLine = (lineNum, city) => {
    setOptLine(lineNum);
    setOptCity(city || "all");
    setOptDirection("all");
    setOptDays([]); 
    setTab("simulator");
    runOptimization(lineNum, city || "all", "all", []);
  };

  const toggleDay = (dayId) => {
    setOptDays(prev => prev.includes(dayId) ? prev.filter(d => d !== dayId) : [...prev, dayId]);
  };

  const renderTransitChip = (origin, dest) => {
    if (!optCity || optCity === "all") return null;
    const sCity = optCity.toLowerCase();
    const isOriginDest = (origin || "").toLowerCase().includes(sCity) || (dest || "").toLowerCase().includes(sCity);
    if (isOriginDest) return null;
    return (
      <span className="text-[11px] font-black bg-teal-100 text-teal-700 px-2 py-1 rounded-md">
        עובר דרך: {optCity}
      </span>
    );
  };

  const renderPrebookedInfo = (id, isPrebooked) => {
    if (!isPrebooked) return null;
    const showExplain = activeExplainId === id;
    return (
      <div className="relative inline-flex items-center">
        <button
          onClick={(e) => { e.stopPropagation(); setActiveExplainId(showExplain ? null : id); }}
          className="w-5 h-5 rounded-full bg-slate-100 text-slate-600 font-bold text-sm flex items-center justify-center border border-slate-300 hover:bg-slate-200 transition-colors mx-1 outline-none relative z-10"
          title="מידע על נתוני הקו"
        >!</button>
        {showExplain && (
          <div 
             ref={explainRef} 
             className="absolute top-8 right-0 left-auto p-3 sm:p-4 bg-white text-slate-800 text-xs sm:text-sm rounded-xl shadow-2xl z-[9999] leading-relaxed font-normal text-right normal-case border border-slate-200 ring-1 ring-slate-900/5"
             style={{ position: 'absolute', width: 'min(16rem, calc(100vw - 3rem))' }}
          >
            <strong className="block mb-2 text-slate-900 text-base">קו בהזמנה מראש</strong>
            בגלל שנוסעים רוכשים כרטיס מראש, חלקם לא מתקפים שוב בעלייה לאוטובוס. לכן, נתוני התיקופים כאן חלקיים ועלולים להציג עומס נמוך ממה שקורה בפועל.
          </div>
        )}
      </div>
    );
  };

  const renderFeedingLineInfo = (id, isFeeding) => {
    if (!isFeeding) return null;
    const showExplain = activeExplainId === id;
    return (
      <div className="relative inline-flex items-center">
        <button
          onClick={(e) => { e.stopPropagation(); setActiveExplainId(showExplain ? null : id); }}
          className="w-5 h-5 rounded-full bg-sky-100 text-sky-700 font-bold text-sm flex items-center justify-center border border-sky-300 hover:bg-sky-200 transition-colors mx-1 outline-none relative z-10"
          title="מידע על קו מזין רכבת"
        >!</button>
        {showExplain && (
          <div 
             ref={explainRef} 
             className="absolute top-8 right-0 left-auto p-3 sm:p-4 bg-white text-slate-800 text-xs sm:text-sm rounded-xl shadow-2xl z-[9999] leading-relaxed font-normal text-right normal-case border border-slate-200 ring-1 ring-slate-900/5"
             style={{ position: 'absolute', width: 'min(16rem, calc(100vw - 3rem))' }}
          >
            <strong className="block mb-2 text-slate-900 text-base">קו מזין רכבת</strong>
            מטרת קו זה היא לאסוף או לפזר נוסעים מתחנת הרכבת. לכן, לפני קבלת החלטה על ביטול נסיעות או שינוי שעות הפעילות שלו, מומלץ לבדוק ולהצליב את המידע עם לוח הזמנים המעודכן של הרכבת.
          </div>
        )}
      </div>
    );
  };

  const handleOptimizeLineForm = (lineNum, city) => {
    setOptLine(lineNum);
    setOptCity(city || "all");
    setOptDirection("all");
    setOptDays([]); 
    setTab("simulator");
    runOptimization(lineNum, city || "all", "all", []);
  };

  // מסך טעינה מלא — מוצג רק כשנכנסים לכלי לפני שהנתונים מוכנים
  const fullLoadingScreen = (
    <div className="min-h-screen bg-[#F8FAFC] flex flex-col items-center justify-center gap-6 px-6" dir="rtl" style={{ fontFamily: "'Heebo', sans-serif" }}>
      {loadError ? (
        <>
          <div className="w-16 h-16 rounded-full bg-red-100 flex items-center justify-center">
            <span style={{ fontSize: 28 }}>⚠️</span>
          </div>
          <div className="text-center">
            <p className="text-slate-900 font-black text-lg">הטעינה נכשלה</p>
            <p className="text-slate-500 font-bold text-sm mt-1">בדוק חיבור לאינטרנט ונסה שוב</p>
          </div>
          <button
            onClick={() => setRetryCount(c => c + 1)}
            className="bg-slate-900 text-white font-black px-8 py-3.5 rounded-2xl shadow-md hover:bg-slate-700 transition-colors"
          >נסה שוב</button>
        </>
      ) : (
        <>
          <Ic n="loader" size={48} cls="text-slate-900" animate={true} />
          <div className="text-center w-full max-w-xs">
            <p className="text-slate-800 font-black text-lg mb-3">{fileLoad.message || 'טוען נתונים…'}</p>
            <div className="w-full bg-slate-200 rounded-full h-3 overflow-hidden">
              <div className="h-3 rounded-full bg-slate-900 transition-all duration-500" style={{ width: `${fileLoad.progress || 2}%` }} />
            </div>
            <p className="text-slate-500 font-black text-sm mt-2">{fileLoad.progress || 0}%</p>
          </div>
        </>
      )}
    </div>
  );

  // מסך בחירה — תמיד נגיש מיד (לא מחכה לנתונים)
  if (appMode === 'choice') return <ChoiceScreen onPick={pickMode} />;
  // כלים — מחכים לנתונים; מראים טעינה עד שהם מוכנים
  if (initialLoading || trips.length === 0) return fullLoadingScreen;
  if (appMode === 'golden') return <GoldenApp onBack={() => pickMode('choice')} trips={trips} costBenchmarkTable={costBenchmarkTable} lineCitiesMap={lineCitiesMap} />;

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 p-4 md:p-6 pb-20" style={{ fontFamily: "'Heebo', sans-serif" }} dir="rtl">
      <CitiesDatalist cities={allCities} />

      <div className="max-w-6xl mx-auto">
        <header className="mb-10 flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="text-center md:text-right">
            <div className="flex items-center gap-3 justify-center md:justify-end">
              <div className="bg-slate-900 text-white p-2.5 rounded-2xl rotate-3 shadow-lg">
                <Ic n="trash" size={28} />
              </div>
              <h1 className="text-4xl font-[900] text-slate-900 tracking-tighter leading-none">קו פח</h1>
              <div className="relative mr-3 flex items-center gap-3">
                <button
                  onClick={() => setShowWhatsNew(v => !v)}
                  className="bg-indigo-100 text-indigo-800 text-xs font-black px-3 py-1 rounded-full border border-indigo-200 shadow-sm whitespace-nowrap tracking-wide hover:bg-indigo-200 transition-colors cursor-pointer"
                >
                  מה חדש
                </button>
                <span className="text-xs font-bold text-slate-400">נבנה על ידי שלמה הרטמן</span>
              </div>
            </div>
            <p className="text-slate-500 text-sm font-bold mt-2 pr-1">מאתרים קווים ריקים • מייעלים את הלו&quot;ז</p>
          </div>
          <button
            onClick={() => pickMode('choice')}
            className="shrink-0 flex items-center gap-2 bg-white border-2 border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-300 px-4 py-2.5 rounded-2xl font-black text-sm shadow-sm transition-colors"
            title="חזרה למסך הבחירה"
          >
            <span className="text-base leading-none">⇄</span> החלף כלי
          </button>
        </header>

        {showWhatsNew && (
          <div className="fixed inset-0 bg-slate-900/50 flex items-center justify-center z-50 p-4" onClick={() => setShowWhatsNew(false)}>
            <div className="bg-white rounded-2xl shadow-xl p-8 max-w-2xl w-full border border-slate-100 max-h-[90vh] overflow-y-auto text-right" onClick={e => e.stopPropagation()}>
              <div className="flex justify-between items-start mb-6 border-b border-slate-100 pb-4">
                <div>
                  <h3 className="font-black text-2xl text-slate-800">מה חדש</h3>
                  <p className="text-slate-400 font-bold text-xs mt-1">עדכון מידע — נתונים עדכניים ועלות תפעולית מדויקת לפי מחוז</p>
                </div>
                <button onClick={() => setShowWhatsNew(false)} className="text-slate-400 hover:bg-slate-100 hover:text-slate-900 rounded-full w-8 h-8 flex items-center justify-center font-black text-2xl transition-colors leading-none pb-1" title="סגור">
                  &times;
                </button>
              </div>
              <div className="space-y-6 text-slate-700 text-sm leading-relaxed">

                <section>
                  <h4 className="font-black text-slate-900 text-base mb-2 flex items-center gap-2">
                    <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-md text-[10px]">עדכון מידע</span>
                    נתונים עדכניים ממקורות חדשים
                  </h4>
                  <p className="text-slate-600 mb-3">כל הנתונים במערכת עודכנו והוחלפו במקורות החדשים והעדכניים של משרד התחבורה. המידע מאורגן כעת בארבעה קבצים נפרדים — נתוני קווים, לוז נסיעות, תחנות, וטבלת עלויות — לדיוק ועדכון פשוט יותר.</p>
                  <ul className="list-disc list-inside space-y-2 marker:text-emerald-400 pr-2">
                    <li><strong>לוז מורחב:</strong> מעל 205,000 יציאות מתוזמנות עם נתוני נוסעים ועומס מעודכנים.</li>
                    <li><strong>נתוני תחנות מלאים:</strong> כולל שם תחנה, עיר ומיקום לכל קו.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-black text-slate-900 text-base mb-2 flex items-center gap-2">
                    <span className="bg-sky-100 text-sky-700 px-2 py-0.5 rounded-md text-[10px]">שיפור</span>
                    עלות תפעולית מדויקת לפי מחוז
                  </h4>
                  <p className="text-slate-600 mb-3">עד כה כל קו הושווה לממוצע <strong>ארצי</strong> אחד לקטגוריה שלו. כעת ההשוואה מתבצעת מול בנצ'מרק <strong>מחוזי</strong> — כל קו נמדד מול העלות הממוצעת לנוסע בקטגוריה שלו <strong>ובמחוז שלו</strong> בפועל.</p>
                  <ul className="list-disc list-inside space-y-2 marker:text-sky-400 pr-2">
                    <li>זיהוי הוגן יותר של קווים יקרים — קו בפריפריה נמדד מול הפריפריה, לא מול גוש דן.</li>
                    <li>טבלת בנצ'מרק רשמית של 8 קטגוריות × 8 מחוזות.</li>
                  </ul>
                </section>

                <section>
                  <h4 className="font-black text-slate-900 text-base mb-2 flex items-center gap-2">
                    <span className="bg-slate-200 text-slate-700 px-2 py-0.5 rounded-md text-[10px]">תיקון</span>
                    עדכונים מופיעים מיד
                  </h4>
                  <p className="text-slate-600 mb-3">תוקנה בעיה שבה הדפדפן הציג גרסה ישנה מהזיכרון המקומי (cache) ולא את העדכון האחרון. כעת המערכת בודקת מול השרת בכל טעינה ומציגה תמיד את הנתונים והקוד העדכניים ביותר.</p>
                </section>

              </div>
            </div>
          </div>
        )}

        {fileLoad.active || initialLoading ? (
          <div className="flex flex-col items-center justify-center py-40 text-center gap-6">
            {fileLoad.progress < 48 ? (
              <div className="flex flex-col items-center gap-4">
                <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center">
                  <Ic n="loader" size={28} cls="text-white" animate={true} />
                </div>
                <div>
                  <p className="text-xl font-black text-slate-900">{initialLoading && !fileLoad.active ? "טוען נתונים..." : fileLoad.message}</p>
                  <p className="text-slate-400 text-sm font-bold mt-1">יקח כמה שניות</p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-4">
                <div style={{ willChange: 'transform' }}>
                  <Ic n="loader" size={64} cls="text-slate-900" animate={true} />
                </div>
                <p className="text-xl font-black text-slate-800">{fileLoad.message}</p>
                <div className="w-72 bg-slate-200 rounded-full h-3 overflow-hidden">
                  <div className="h-3 rounded-full bg-slate-900" style={{ width: `${fileLoad.progress}%`, transition: 'width 0.3s ease' }} />
                </div>
                <p className="text-slate-400 font-bold text-sm">{fileLoad.progress}%</p>
              </div>
            )}
          </div>
        ) : trips.length === 0 && csvLoadFailed ? (
          <div className="flex flex-col items-center justify-center py-32 px-6 bg-white rounded-[3rem] border-4 border-dashed border-slate-200 shadow-sm text-center">
            <div className="bg-slate-50 p-8 rounded-full mb-8"><Ic n="upload" size={48} cls="text-slate-300" /></div>
            <h2 className="text-3xl font-black text-slate-800 mb-4">מוכנים לזרוק קווים?</h2>
            <h3 className="text-xl font-black text-slate-700 mb-3 bg-indigo-50 text-indigo-800 px-5 py-2 rounded-xl border border-indigo-100 shadow-sm inline-block">המערכת שמוצאת קווים שאפשר לזרוק לפח</h3>
            <p className="text-slate-500 font-medium mb-6 max-w-md">לא נמצא קובץ נתונים מקומי (data.csv).</p>
            <p className="text-slate-400 font-medium mb-12 max-w-md">העלו קובץ אקסל עם נתוני תיקופים כדי להתחיל בניתוח המערכת.</p>
            <label className="bg-slate-900 hover:bg-black text-white px-16 py-5 rounded-[2rem] font-black text-xl cursor-pointer transition-all shadow-xl hover:scale-105 active:scale-95">
              העלאת קובץ נתונים
              <input type="file" className="hidden" accept=".xlsx,.xls" onChange={onFile} />
            </label>
          </div>
        ) : trips.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-40 text-center gap-6">
            <div className="flex flex-col items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center">
                <Ic n="loader" size={28} cls="text-white" animate={true} />
              </div>
              <div>
                <p className="text-xl font-black text-slate-900">טוען נתונים...</p>
                <p className="text-slate-400 text-sm font-bold mt-1">יקח כמה שניות</p>
              </div>
            </div>
          </div>
        ) : (
          <main>
            <nav className="flex bg-slate-200/50 backdrop-blur p-1.5 rounded-[2rem] mb-12 max-w-4xl mx-auto shadow-inner border border-slate-200 overflow-x-auto">
              {["redundant", "areas", "allTrips", "simulator", "about"].map(tabName => {
                const isSelected = tab === tabName;
                let colorClass = "text-slate-500";
                let iconName = "";
                let label = "";
                if (tabName === "redundant") { colorClass = isSelected ? "bg-white text-rose-600 shadow-md" : "text-slate-500 hover:text-slate-700"; iconName = "trash"; label = "קווים לא יעילים"; }
                if (tabName === "areas") { colorClass = isSelected ? "bg-white text-amber-600 shadow-md" : "text-slate-500 hover:text-slate-700"; iconName = "chart"; label = "ניתוח אזורי"; }
                if (tabName === "allTrips") { colorClass = isSelected ? "bg-white text-indigo-600 shadow-md" : "text-slate-500 hover:text-slate-700"; iconName = "list"; label = "כל הנסיעות"; }
                if (tabName === "simulator") { colorClass = isSelected ? "bg-white text-slate-900 shadow-md" : "text-slate-500 hover:text-slate-700"; iconName = "zap"; label = "אלגוריתם ייעול"; }
                if (tabName === "about") { colorClass = isSelected ? "bg-white text-indigo-600 shadow-md" : "text-slate-500 hover:text-slate-700"; iconName = "info"; label = "על המערכת"; }

                return (
                  <button key={`nav-${tabName}`} onClick={() => {
                    setTab(tabName);
                  }} className={`flex-1 min-w-[120px] py-3.5 rounded-[1.5rem] font-black text-sm transition-all flex items-center justify-center gap-2 ${colorClass}`}>
                    <Ic n={iconName} size={16} /> {label}
                  </button>
                )
              })}
            </nav>

            {tab === "redundant" && (
              <div className="space-y-8 transition-opacity duration-300 opacity-100">
                <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm flex flex-col xl:flex-row justify-between items-center gap-4">
                  <div>
                    <h2 className="text-2xl font-black text-slate-900">הקווים הכי לא יעילים</h2>
                    <p className="text-slate-500 font-bold">דירוג המציג את הקווים החלשים ביותר במערכת, לצורך בחינה וייעול</p>
                  </div>
                  <div className="flex flex-col md:flex-row gap-3 relative w-full xl:w-auto">
                    <select 
                      value={redundantSortBy} 
                      onChange={e => setRedundantSortBy(e.target.value)} 
                      className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full md:w-56 appearance-none cursor-pointer"
                    >
                      <option value="score">מיון: לפי אי-יעילות</option>
                      <option value="wastedKm">מיון: ק&quot;מ מבוזבז (גבוה לנמוך)</option>
                      <option value="cost">מיון: עלות לנוסע (גבוהה לנמוכה)</option>
                      <option value="count">מיון: כמות נסיעות בשבוע</option>
                    </select>
                    <select 
                      value={filterDistrict} 
                      onChange={e => setFilterDistrict(e.target.value)} 
                      className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full md:w-48 appearance-none cursor-pointer"
                    >
                      <option value="all">כל המחוזות</option>
                      {allDistricts.map(d => <option key={`dist-${d}`} value={d}>{d}</option>)}
                    </select>
                    <select
                      value={filterCategory}
                      onChange={e => setFilterCategory(e.target.value)}
                      className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full md:w-56 appearance-none cursor-pointer"
                    >
                      <option value="all">כל הקטגוריות</option>
                      {CATEGORIES.map(c => <option key={`cat-${c}`} value={c}>{c}</option>)}
                    </select>
                    <div className="flex relative w-full xl:w-64">
                      <SearchInput
                        value={searchCity} 
                        onSubmit={setSearchCity} 
                        placeholder="הקלד עיר ולחץ Enter..."
                        className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-6 py-3 pl-12 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full"
                      />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {filteredRedundant.length > 0 ? filteredRedundant.map((res, i) => (
                    <div key={`red-${res.groupKey}-${i}`} className="vcard bg-white border-2 border-slate-100 rounded-[2.5rem] p-7 shadow-sm hover:border-slate-900 transition-all text-right flex flex-col group relative">
                      <div className="flex items-start justify-between mb-6">
                        <div className="flex flex-col gap-2 items-start text-right">
                          <div className="flex items-center gap-2 flex-wrap">
                            <div className={`px-4 py-1.5 rounded-full text-[11px] font-black border ${res.statusTier.bg} ${res.statusTier.color}`}>
                              {res.status}
                            </div>
                            <div className="px-3 py-1.5 rounded-full text-[11px] font-black bg-slate-100 text-slate-700 border border-slate-200">
                              {res.category}
                            </div>
                            {res.isNightLine && (
                              <span className="text-indigo-400 bg-indigo-50 p-1 rounded-full" title="קו לילה">
                                <Ic n="moon" size={14} />
                              </span>
                            )}
                            {renderPrebookedInfo('red-'+i, res.isEilatPrebooked)}
                            {renderFeedingLineInfo('red-'+i, res.isFeedingLine)}
                          </div>
                          <div className="mt-1">
                            <RouteFormat val={res.makat} />
                          </div>
                        </div>
                        <div className="bg-slate-900 text-white w-14 h-14 rounded-2xl flex items-center justify-center font-black text-2xl shadow-lg shrink-0">{res.lineNum}</div>
                      </div>
                      <div className="flex-1 mb-5">
                        
                        <div className="flex items-center justify-start gap-3 mb-2 min-w-0">
                          <div className="text-slate-900 font-black text-lg truncate leading-tight" title={res.origin}>{res.origin}</div>
                          <div className="text-slate-300 text-2xl font-black shrink-0 leading-none">←</div>
                          <div className="text-slate-900 font-black text-lg truncate leading-tight" title={res.dest}>{res.dest}</div>
                        </div>
                        
                        <div className="flex flex-wrap items-center gap-2 mb-4">
                          <span className="text-[10px] font-bold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md shrink-0">{res.district}</span>
                          {(() => {
                            if (!searchCity) return null;
                            const sCity = searchCity.toLowerCase();
                            const isOriginDest = res.origin.toLowerCase().includes(sCity) || res.dest.toLowerCase().includes(sCity);
                            if (isOriginDest) return null;

                            const cleanMakat = String(res.makat || '').replace(/^0+/, '').trim();
                            const cleanLine = String(res.lineNum || '').replace(/^0+/, '').trim();
                            const citiesSet = lineCitiesMap.get(cleanMakat) || lineCitiesMap.get(cleanLine);
                            
                            if (!citiesSet) return null;
                            
                            const matchedCity = Array.from(citiesSet).find(c => c.includes(sCity));

                            if (!matchedCity) return null;

                            return (
                              <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 whitespace-nowrap shrink-0">
                                עובר דרך: {matchedCity}
                              </span>
                            );
                          })()}
                        </div>

                        <div className="text-xs font-bold text-slate-400 mb-4 flex items-center gap-2 flex-wrap">
                          <span>ציון אי-יעילות:</span>
                          <span className={`font-black ${res.statusTier.color}`}>{res.score}/100</span>
                          {res.totalDeduction > 0 && (
                            <span className="text-slate-400 font-bold">
                              (גולמי {res.rawScore}, הופחתו {res.totalDeduction} בגין הגנות)
                            </span>
                          )}
                        </div>

                        {res.protections.length > 0 && (
                          <div className="mb-4 bg-emerald-50 border border-emerald-200 rounded-2xl px-3 py-2">
                            <div className="text-[10px] font-black text-emerald-700 mb-1">הגנות פעילות</div>
                            <div className="flex flex-wrap gap-1.5">
                              {res.protections.map((p, k) => (
                                <span key={`prot-${i}-${k}`} className="bg-white border border-emerald-200 text-emerald-700 px-2 py-0.5 rounded-full text-[10px] font-bold" title={p.detail}>
                                  {p.name} −{p.value}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="space-y-2.5 pt-4 border-t border-slate-100">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-600 font-bold">ממוצע נוסעים לנסיעה</span>
                            <span className="font-black text-slate-900">{res.avg}</span>
                          </div>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-600 font-bold">עומס שיא ממוצע</span>
                            <span className="font-black text-slate-900">{res.avgPeak}</span>
                          </div>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-600 font-bold">נסיעות בשבוע</span>
                            <span className="font-black text-slate-900">{res.count}</span>
                          </div>
                          <div className="flex items-center justify-between text-sm gap-2">
                            <span className="text-slate-600 font-bold">עלות תפעולית לנוסע</span>
                            <span className="text-right">
                              <span className="font-black text-slate-900">{res.cost > 0 ? `₪${res.cost.toFixed(2)}` : 'לא זמין'}</span>
                              {res.cost > 0 && res.costBenchmark > 0 && (
                                <div className="text-[10px] font-bold text-slate-400">
                                  ממוצע {res.category}: ₪{res.costBenchmark}
                                  {res.costRatio > 1 && (
                                    <span className="text-rose-500 mr-1">(×{res.costRatio.toFixed(2)})</span>
                                  )}
                                </div>
                              )}
                            </span>
                          </div>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-600 font-bold">ק&quot;מ לא מבוזבז (שימושי)</span>
                            <span className="font-black text-emerald-600">{res.nonWastedKm.toLocaleString()} ק&quot;מ</span>
                          </div>
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-slate-600 font-bold">ק&quot;מ מבוזבז (נסיעות סרק)</span>
                            <span className="font-black text-rose-600">{res.wastedKm.toLocaleString()} ק&quot;מ</span>
                          </div>
                        </div>
                      </div>
                      <button onClick={() => handleOptimizeLineForm(res.lineNum, res.origin)} className="w-full py-4 bg-slate-900 text-white rounded-2xl text-xs font-black hover:bg-black transition-all shadow-md">חפש הזדמנויות התייעלות</button>
                    </div>
                  )) : (
                    <div className="col-span-full text-center py-20 text-slate-400 font-bold">לא נמצאו קווים לסינון המבוקש.</div>
                  )}
                </div>
              </div>
            )}

            {tab === "areas" && (
              <div className="space-y-8 transition-opacity duration-300 opacity-100">
                <div className="bg-white p-8 rounded-[2.5rem] border border-slate-200 shadow-sm flex flex-col xl:flex-row justify-between items-center gap-4">
                  <div>
                    <h2 className="text-2xl font-black text-slate-900">האזורים הכי לא יעילים</h2>
                    <p className="text-slate-500 font-bold">ריכוז של הקווים המיותרים לחלוטין ונסיעות הסרק לפי ערים או מחוזות</p>
                  </div>
                  <div className="flex flex-col md:flex-row gap-3 relative w-full xl:w-auto">
                    <div className="flex bg-slate-100 p-1 rounded-2xl shadow-inner">
                       <button onClick={() => setAreaViewMode('city')} className={`px-6 py-2.5 rounded-xl font-black text-sm transition-all ${areaViewMode === 'city' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>לפי עיר</button>
                       <button onClick={() => setAreaViewMode('district')} className={`px-6 py-2.5 rounded-xl font-black text-sm transition-all ${areaViewMode === 'district' ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>לפי מחוז</button>
                    </div>
                    <select
                      value={areaSortBy}
                      onChange={e => setAreaSortBy(e.target.value)}
                      className="bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 font-black outline-none focus:border-slate-900 text-right shadow-sm w-full md:w-48 appearance-none cursor-pointer"
                    >
                      <option value="wastedKm">מיון: ק&quot;מ מבוזבז (מומלץ)</option>
                      <option value="score">מיון: מדד חומרה אזורי</option>
                      <option value="lineCount">מיון: כמות קווים מיותרים</option>
                      <option value="avgRiders">מיון: ממוצע נוסעים (נמוך לגבוה)</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {areaStats.map((area, i) => (
                     <div key={i} className="bg-white border-2 border-slate-100 rounded-[2.5rem] p-7 shadow-sm hover:border-amber-400 transition-all text-right flex flex-col group relative">
                        <div className="flex justify-between items-start mb-6">
                           <div className={`px-4 py-1.5 rounded-full text-[11px] font-black border ${area.avgScore >= 80 ? 'bg-rose-50 border-rose-200 text-rose-600' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>מדד חומרה: {area.avgScore}</div>
                           <div className="flex gap-2">
                             <button 
                               onClick={(e) => { e.stopPropagation(); exportAreaToExcel(area.name, areaViewMode); }}
                               className="bg-emerald-100 hover:bg-emerald-200 text-emerald-700 w-12 h-12 rounded-2xl flex items-center justify-center shadow-sm transition-all"
                               title="ייצוא נתוני האזור לאקסל"
                             >
                               <Ic n="download" size={20} />
                             </button>
                           </div>
                        </div>
                        <h3 className="text-2xl font-black text-slate-900 mb-4">{area.name}</h3>
                        <div className="space-y-3 pt-4 border-t border-slate-100 text-sm mb-5">
                           <div className="flex justify-between"><span className="text-slate-600 font-bold">קווים מיותרים באזור</span><span className="font-black text-slate-900">{area.lineCount} קווים</span></div>
                           <div className="flex justify-between"><span className="text-slate-600 font-bold">סה&quot;כ נסיעות בשבוע</span><span className="font-black text-slate-900">{area.totalTrips.toLocaleString()}</span></div>
                           <div className="flex justify-between"><span className="text-slate-600 font-bold">ממוצע נוסעים בנסיעה</span><span className="font-black text-slate-900">{area.avgAreaRiders}</span></div>
                           <div className="flex justify-between"><span className="text-slate-600 font-bold">ק&quot;מ מבוזבז (סה&quot;כ)</span><span className="font-black text-rose-600">{area.wastedKm.toLocaleString()} ק&quot;מ</span></div>
                           <div className="flex justify-between"><span className="text-slate-600 font-bold">עלות תפעולית ממוצעת</span><span className="font-black text-slate-900">{area.avgCost > 0 ? `₪${area.avgCost.toFixed(2)}` : 'לא זמין'}</span></div>
                        </div>
                        <button onClick={() => handleViewAreaLines(area.name)} className="mt-auto w-full py-4 bg-slate-900 text-white rounded-2xl text-xs font-black hover:bg-black transition-all shadow-md">צפה בקווים אלו</button>
                     </div>
                  ))}
                  {areaStats.length === 0 && (
                     <div className="col-span-full text-center py-20 text-slate-400 font-bold">לא נמצאו אזורים תואמים לסינון.</div>
                  )}
                </div>
              </div>
            )}

            {tab === "allTrips" && (
              <div className="bg-white p-6 md:p-8 rounded-[3rem] border border-slate-200 shadow-sm transition-opacity duration-300 opacity-100">
                <header className="mb-8 flex flex-col md:flex-row justify-between items-center gap-6">
                  <div>
                    <h2 className="text-2xl font-black text-slate-900 mb-2">כל הנסיעות במערכת</h2>
                    <p className="text-slate-500 font-bold text-sm">סנן לפי עיר ומצא נסיעות עמוסות.</p>
                  </div>
                  <div className="flex flex-col md:flex-row items-center gap-4 w-full md:w-auto">
                    <label className="flex items-center gap-3 bg-rose-50/50 border-2 border-rose-100 text-rose-800 px-4 py-3 rounded-2xl cursor-pointer hover:bg-rose-50 transition-colors w-full md:w-auto font-black text-sm">
                      <input type="checkbox" checked={showCrowded} onChange={e => setShowCrowded(e.target.checked)} className="w-5 h-5 accent-rose-600 rounded" />
                      הצג רק נסיעות עמוסות
                    </label>
                    <div className="flex relative w-full md:w-auto">
                      <SearchInput
                        value={searchCity} 
                        onSubmit={setSearchCity} 
                        placeholder="חיפוש עיר (מוצא או יעד) — Enter"
                        className="w-full bg-slate-50 border-2 border-slate-200 rounded-2xl px-4 py-3 pl-12 font-black outline-none focus:border-slate-900 text-right shadow-sm"
                      />
                    </div>
                  </div>
                </header>
                
                <div className="overflow-x-auto rounded-[2rem] border-2 border-slate-100 max-h-[60vh] pb-32">
                  <table className="w-full text-right border-collapse">
                    <thead className="sticky top-0 bg-slate-50 shadow-sm z-20" ref={tooltipRef}>
                      <tr className="text-slate-400 text-xs font-black uppercase">
                        <th className="p-5">מס&apos; קו</th>
                        <th className="p-5">מוצא</th>
                        <th className="p-5">יעד</th>
                        <th className="p-5">שעה</th>
                        <th className="p-5 relative">
                          <div className="flex items-center gap-1.5">
                            <span>נוסעים (יעילות)</span>
                            <button onClick={() => setActiveTooltip(activeTooltip === 'ridership' ? null : 'ridership')} className="text-slate-400 hover:text-indigo-600 transition-colors">
                              <Ic n="info" size={14} />
                            </button>
                            <div className="flex flex-col -space-y-1.5 mr-2">
                              <button onClick={() => setSortConfig({key: 'ridership', direction: 'desc'})} className={`${sortConfig.key === 'ridership' && sortConfig.direction === 'desc' ? 'text-indigo-600' : 'text-slate-300 hover:text-slate-500'}`}><Ic n="chevronUp" size={12} strokeWidth="3" /></button>
                              <button onClick={() => setSortConfig({key: 'ridership', direction: 'asc'})} className={`${sortConfig.key === 'ridership' && sortConfig.direction === 'asc' ? 'text-indigo-600' : 'text-slate-300 hover:text-slate-500'}`}><Ic n="chevronDown" size={12} strokeWidth="3" /></button>
                            </div>
                          </div>
                          {activeTooltip === 'ridership' && (
                            <div className="absolute z-30 top-full right-0 mt-2 w-64 p-3 bg-slate-800 text-white text-xs rounded-xl shadow-xl font-normal normal-case text-right leading-relaxed border border-slate-700">
                              <strong className="block mb-1 text-indigo-300">נוסעים (יעילות):</strong> סך כל האנשים שעלו על האוטובוס לאורך כל המסלול. מדד היעילות בסוגריים מחושב ביחס לקיבולת האוטובוס הספציפי שהוגדר (מיניבוס, מידיבוס, אוטובוס רגיל או מפרקי).
                            </div>
                          )}
                        </th>
                        <th className="p-5 relative">
                          <div className="flex items-center gap-1.5">
                            <span>עומס שיא</span>
                            <button onClick={() => setActiveTooltip(activeTooltip === 'peakLoad' ? null : 'peakLoad')} className="text-slate-400 hover:text-indigo-600 transition-colors">
                              <Ic n="info" size={14} />
                            </button>
                            <div className="flex flex-col -space-y-1.5 mr-2">
                              <button onClick={() => setSortConfig({key: 'peakLoad', direction: 'desc'})} className={`${sortConfig.key === 'peakLoad' && sortConfig.direction === 'desc' ? 'text-indigo-600' : 'text-slate-300 hover:text-slate-500'}`}><Ic n="chevronUp" size={12} strokeWidth="3" /></button>
                              <button onClick={() => setSortConfig({key: 'peakLoad', direction: 'asc'})} className={`${sortConfig.key === 'peakLoad' && sortConfig.direction === 'asc' ? 'text-indigo-600' : 'text-slate-300 hover:text-slate-500'}`}><Ic n="chevronDown" size={12} strokeWidth="3" /></button>
                            </div>
                          </div>
                          {activeTooltip === 'peakLoad' && (
                            <div className="absolute z-30 top-full left-0 mt-2 w-64 p-3 bg-slate-800 text-white text-xs rounded-xl shadow-xl font-normal normal-case text-right leading-relaxed border border-slate-700">
                              <strong className="block mb-1 text-indigo-300">עומס שיא:</strong> המספר המקסימלי של נוסעים שהיו בתוך האוטובוס בו-זמנית בנקודה העמוסה ביותר במסלול שלו.
                            </div>
                          )}
                        </th>
                        <th className="p-5 relative">
                          <div className="flex items-center gap-2">
                            <span>סוג</span>
                            <div className="relative inline-block">
                              <select
                                value={filterLineType}
                                onChange={e => setFilterLineType(e.target.value)}
                                className="appearance-none bg-slate-100 border border-slate-200 text-slate-600 rounded-md pl-6 pr-2 py-1 text-[10px] font-black outline-none focus:ring-2 focus:ring-indigo-500 cursor-pointer hover:bg-slate-200 transition-colors"
                              >
                                <option value="all">הכל</option>
                                {allLineTypes.map(t => <option key={`type-${t}`} value={t}>{t}</option>)}
                              </select>
                              <div className="absolute left-1.5 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                                <Ic n="chevronDown" size={10} strokeWidth="3" />
                              </div>
                            </div>
                          </div>
                        </th>
                      </tr>
                    </thead>
                    <tbody className="text-sm font-bold text-slate-700">
                      {tableTrips.slice(0, visibleTripsCount).map((t, i) => (
                        <tr key={`trip-${t.id || i}`} className="vrow border-t border-slate-100 hover:bg-slate-50 transition-colors">
                          <td className="p-5 font-black">
                            <div className="flex flex-col items-start gap-1 relative">
                              <div className="flex items-center gap-2 justify-start">
                                {t.isNightLine && (
                                  <span className="text-indigo-400 bg-indigo-50 p-1 rounded-full" title="קו לילה">
                                    <Ic n="moon" size={16} />
                                  </span>
                                )}
                                {renderPrebookedInfo('trip-'+i, t.isEilatPrebooked)}
                                {renderFeedingLineInfo('trip-'+i, t.isFeedingLine)}
                                <span className="bg-slate-900 text-white px-3 py-1.5 rounded-xl">{t.lineNum}</span>
                              </div>
                              {(() => {
                                if (!searchCity) return null;
                                const sCity = searchCity.toLowerCase();
                                const isOriginDest = t.origin.toLowerCase().includes(sCity) || t.dest.toLowerCase().includes(sCity);
                                if (isOriginDest) return null;

                                const cleanMakat = String(t.makat || '').replace(/^0+/, '').trim();
                                const cleanLine = String(t.lineNum || '').replace(/^0+/, '').trim();
                                const citiesSet = lineCitiesMap.get(cleanMakat) || lineCitiesMap.get(cleanLine);
                                
                                if (!citiesSet) return null;
                                
                                const matchedCity = Array.from(citiesSet).find(c => c.includes(sCity));
                                if (!matchedCity) return null;

                                return (
                                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 whitespace-nowrap shrink-0">
                                    עובר דרך: {matchedCity}
                                  </span>
                                );
                              })()}
                            </div>
                          </td>
                          <td className="p-5">{t.origin}</td>
                          <td className="p-5">{t.dest}</td>
                          <td className="p-5 font-black">{t.time}</td>
                          <td className={`p-5 flex items-center gap-2 ${t.ridership >= (t.capacity * 0.8) ? 'text-rose-600 font-black' : ''}`}>
                            {t.ridership} 
                            <span className={`text-[10px] px-2 py-0.5 rounded-full ${t.efficiency > 0.5 ? 'bg-emerald-100 text-emerald-700' : t.efficiency > 0.2 ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700'}`} title={`רכב: ${t.busSize} (קיבולת: ${t.capacity})`}>
                              {t.efficiency}
                            </span>
                          </td>
                          <td className={`p-5 ${t.peakLoad >= (t.capacity * 0.8) ? 'text-rose-600 font-black' : ''}`}>{t.peakLoad}</td>
                          <td className="p-5 text-slate-500 text-xs">{t.lineType}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {tableTrips.length > visibleTripsCount && (
                    <div className="text-center py-6 bg-slate-50 border-t border-slate-100">
                      <button
                        onClick={() => setVisibleTripsCount(prev => prev + 300)}
                        className="bg-indigo-100 hover:bg-indigo-200 text-indigo-700 font-black py-2.5 px-6 rounded-xl transition-all shadow-sm text-sm"
                      >
                        הצג עוד תוצאות ({visibleTripsCount} מתוך {tableTrips.length.toLocaleString()})
                      </button>
                    </div>
                  )}
                  {tableTrips.length <= visibleTripsCount && tableTrips.length > 0 && (
                    <div className="text-center py-4 text-xs font-bold text-slate-400 bg-slate-50 border-t border-slate-100">
                      הוצגו כל {tableTrips.length.toLocaleString()} התוצאות.
                    </div>
                  )}
                </div>
              </div>
            )}

            {tab === "simulator" && (
              <div className="bg-white p-8 rounded-[3rem] border border-slate-200 shadow-sm max-w-4xl mx-auto transition-opacity duration-300 opacity-100">
                <header className="mb-8">
                  <h2 className="text-2xl font-black text-slate-900 mb-2">אלגוריתם ייעול ושיפור לוחות זמנים</h2>
                  <p className="text-slate-500 font-bold text-sm leading-relaxed">
                    המערכת מזהה אוטומטית את סוג השירות (עירוני/אזורי/בינעירוני) ואת <strong>גודל הרכב</strong> (מפרקי, מיניבוס וכו&apos;), ומתאימה את רף הביטול וחוקי האיחוד באופן דינמי לכל נסיעה.
                  </p>
                </header>
                
                <div className="bg-slate-50 p-6 rounded-[2rem] border-2 border-slate-100 mb-8 shadow-inner">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
                    <div>
                      <label className="block text-xs font-[900] text-slate-400 mb-3 pr-2 uppercase tracking-wider">מספר קו / מק&quot;ט</label>
                      <input
                        type="text"
                        value={optLine}
                        onChange={e => setOptLine(e.target.value)}
                        onKeyDown={e => {
                          if (e.key === 'Enter' && optLine.trim() !== '' && !optLine.trim().endsWith(',')) {
                            e.preventDefault();
                            setOptLine(prev => prev.trim() + ', ');
                          }
                        }}
                        placeholder="למשל 1, 150..."
                        className="w-full bg-white border-2 border-slate-200 rounded-2xl px-5 py-3 font-black text-sm outline-none focus:border-slate-900 shadow-sm transition-all"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-[900] text-slate-400 mb-3 pr-2 uppercase tracking-wider">עיר (מוצא או יעד)</label>
                      <input 
                        type="text" 
                        list="cities-list"
                        value={optCity === "all" ? "" : optCity} 
                        onChange={e => setOptCity(e.target.value || "all")} 
                        placeholder="הקלד שם עיר..."
                        className="w-full bg-white border-2 border-slate-200 rounded-2xl px-5 py-3 font-black outline-none focus:border-slate-900 text-right transition-all shadow-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-[900] text-slate-400 mb-3 pr-2 uppercase tracking-wider">כיוון נסיעה</label>
                      <select value={optDirection} onChange={e => setOptDirection(e.target.value)} className="w-full bg-white border-2 border-slate-200 rounded-2xl px-5 py-3 font-black outline-none focus:border-slate-900 cursor-pointer text-right shadow-sm appearance-none">
                        <option value="all">כל הכיוונים</option>
                        {allDirections.map(d => <option key={`dir-${d}`} value={d}>{d}</option>)}
                      </select>
                    </div>
                  </div>

                  <div className="mb-8">
                    <label className="block text-xs font-[900] text-slate-400 mb-4 pr-2 uppercase tracking-wider">ימי פעילות (סינון מרובה)</label>
                    <div className="flex flex-wrap gap-3">
                      <button 
                        onClick={() => setOptDays([])} 
                        className={`px-5 py-2.5 rounded-2xl text-sm font-black transition-all border-2 ${optDays.length === 0 ? 'bg-slate-900 text-white border-slate-900 shadow-md' : 'bg-white border-slate-200 text-slate-500 hover:border-slate-400'}`}
                      >
                        כל הימים
                      </button>
                      {DAYS_FILTER.map(d => (
                        <button 
                          key={`day-${d.id}`} 
                          onClick={() => toggleDay(d.id)} 
                          className={`px-5 py-2.5 rounded-2xl text-sm font-black transition-all border-2 ${optDays.includes(d.id) ? 'bg-teal-600 text-white border-teal-600 shadow-md' : 'bg-white border-slate-200 text-slate-500 hover:border-teal-600'}`}
                        >
                          {d.label}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="border-t border-slate-200 pt-6 mb-2">
                    <button
                      onClick={() => setShowAdvanced(prev => !prev)}
                      className="flex items-center gap-2 text-xs font-black text-slate-500 hover:text-slate-900 transition-colors bg-slate-200/50 px-4 py-2 rounded-xl"
                    >
                      <Ic n="settings" size={14} />
                      הגדרות אלגוריתם מתקדמות
                      <Ic n={showAdvanced ? "chevronUp" : "chevronDown"} size={14} />
                    </button>

                    {showAdvanced && (
                      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 mt-6 p-6 bg-white rounded-3xl border border-slate-200 shadow-sm animate-in fade-in slide-in-from-top-2 duration-300">
                        <div className="space-y-2">
                          <label className="block text-[11px] font-black text-slate-400 uppercase pr-1">מדד לניתוח</label>
                          <select value={optMetric} onChange={e => setOptMetric(e.target.value)} className="w-full bg-slate-50 border-2 border-slate-100 rounded-xl px-4 py-2.5 font-black text-sm outline-none focus:border-teal-600 cursor-pointer text-right transition-all">
                            <option value="ridership">נוסעים בפועל</option>
                            <option value="peakLoad">עומס שיא</option>
                          </select>
                        </div>
                        <div className="space-y-2">
                          <label className="block text-[11px] font-black text-slate-400 uppercase pr-1">מרווח איחוד (דק&apos;)</label>
                          <input
                            type="number"
                            value={optCustomGap}
                            onChange={e => setOptCustomGap(e.target.value)}
                            placeholder="לפי סוג קו"
                            className="w-full bg-slate-50 border-2 border-slate-100 rounded-xl px-4 py-2.5 font-black text-sm outline-none focus:border-slate-900 text-right transition-all"
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="block text-[11px] font-black text-slate-400 uppercase pr-1">מינימום נסיעות ביום</label>
                          <input
                            type="number"
                            value={optMinTrips}
                            onChange={e => setOptMinTrips(e.target.value)}
                            placeholder="3 נסיעות"
                            className="w-full bg-slate-50 border-2 border-slate-100 rounded-xl px-4 py-2.5 font-black text-sm outline-none focus:border-slate-900 text-right transition-all"
                          />
                        </div>
                        <div className="space-y-2">
                          <label className="block text-[11px] font-black text-slate-400 uppercase pr-1">רף נוסעים לביטול</label>
                          <input
                            type="number"
                            value={optCancelThreshold}
                            onChange={e => setOptCancelThreshold(e.target.value)}
                            placeholder="מתחת ל-5"
                            className="w-full bg-slate-50 border-2 border-slate-100 rounded-xl px-4 py-2.5 font-black text-sm outline-none focus:border-slate-900 text-right transition-all"
                          />
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center gap-4 pt-8 border-t border-slate-200 mt-6">
                    <button
                      onClick={() => runOptimization()}
                      className="bg-slate-900 hover:bg-black text-white px-10 py-4 rounded-2xl font-black transition-all shadow-lg active:scale-95 flex items-center gap-3 disabled:opacity-60"
                    >
                      {simLoading ? <Ic n="loader" size={20} animate /> : <Ic n="zap" size={20} />}
                      הרץ אלגוריתם
                    </button>

                    {optimizations.length > 0 && (
                      <button onClick={exportOptimizationsToExcel} className="bg-emerald-600 hover:bg-emerald-700 text-white px-8 py-4 rounded-2xl font-black text-sm transition-all shadow-lg flex items-center gap-3">
                        <Ic n="download" size={18} />
                        ייצוא לאקסל
                      </button>
                    )}
                  </div>
                </div>

                {optimizations.length > 0 && (
                  <div className="flex flex-col md:flex-row justify-between items-start md:items-end mb-6 gap-4 border-b border-slate-200 pb-4">
                    <div>
                      <h3 className="text-xl font-black text-slate-900">תוצאות הייעול</h3>
                      <p className="text-slate-500 text-sm font-bold">
                        נמצאו {optimizations.filter(o => o.type !== 'ok').length} המלצות לשינויים בלוח הזמנים
                      </p>
                    </div>
                    <label className="flex items-center gap-2 bg-slate-100 px-4 py-2.5 rounded-xl cursor-pointer hover:bg-slate-200 transition-colors">
                      <input 
                        type="checkbox" 
                        checked={showAllTripsInSimulator} 
                        onChange={(e) => setShowAllTripsInSimulator(e.target.checked)}
                        className="w-4 h-4 accent-indigo-600 rounded"
                      />
                      <span className="text-sm font-bold text-slate-700">הצג את כל נסיעות הקו (כולל תקינות)</span>
                    </label>
                  </div>
                )}

                <div className="space-y-4">
                  {!simLoading && optimizations.length > 0 ? (() => {
                    const optsToRender = showAllTripsInSimulator
                      ? optimizations
                      : optimizations.filter(o => o.type !== 'ok');
                    return (
                      <>
                        {optsToRender.slice(0, visibleOptCount).map((opt, i) => (
                    opt.type === 'merge' ? (
                      <div key={`opt-${i}`} className="bg-white border-2 border-slate-50 p-6 rounded-[2rem] flex flex-col lg:flex-row lg:items-center justify-between gap-6 hover:shadow-lg transition-all border-r-4 border-r-indigo-500">
                        <div className="flex items-start gap-4">
                          <div className="bg-indigo-50 text-indigo-600 p-3.5 rounded-2xl mt-1"><Ic n="calendar" size={24} /></div>
                          <div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="font-black text-slate-900 text-lg">קו {opt.line}</span>
                                {opt.isNightLine && (
                                  <span className="text-indigo-400 bg-indigo-50 p-1 rounded-full" title="קו לילה">
                                    <Ic n="moon" size={16} />
                                  </span>
                                )}
                                {renderPrebookedInfo('sim-'+i, opt.isEilatPrebooked)}
                                {renderFeedingLineInfo('feed-'+i, opt.isFeedingLine)}
                              </div>
                              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-bold">{opt.categoryLabel}</span>
                            </div>
                            <div className="text-sm font-bold text-slate-500 mb-3">{opt.origin} ← {opt.dest}</div>
                            <div className="flex flex-wrap gap-2">
                              <span className="text-[11px] font-black bg-slate-100 text-slate-500 px-2 py-1 rounded-md">יום {opt.days}</span>
                              {renderTransitChip(opt.origin, opt.dest)}
                              <span className="text-[11px] font-black bg-indigo-100 text-indigo-700 px-2 py-1 rounded-md">מומלצת לאיחוד</span>
                              <span className="text-[11px] font-black bg-sky-100 text-sky-700 px-2 py-1 rounded-md">כיוון {opt.direction}</span>
                              <span className="text-[11px] font-black bg-purple-100 text-purple-700 px-2 py-1 rounded-md">{opt.busSize}</span>
                            </div>
                          </div>
                        </div>
                        <div className="bg-slate-50/80 px-6 py-4 rounded-2xl flex-1 max-w-md w-full">
                          <div className="flex justify-between items-center mb-3 text-sm">
                            <span className="font-bold text-slate-500">נסיעות נוכחיות:</span>
                            <span className="font-black text-slate-700">{opt.from} ו-{opt.to} <span className="text-xs text-slate-400 font-normal">({opt.gap} דק&apos; הפרש)</span></span>
                          </div>
                          <div className="flex justify-between items-center mb-4 text-sm">
                            <span className="font-bold text-slate-500">{opt.usedMetric === 'peakLoad' ? 'עומס שיא מצטבר:' : 'נוסעים מצטבר:'}</span>
                            <span className="font-black text-slate-700">
                              {opt.total} <span className="text-xs text-slate-400 font-normal mr-1">({opt.val1} בנסיעה ה-1, {opt.val2} בנסיעה ה-2)</span>
                            </span>
                          </div>
                          <div className="pt-3 border-t border-slate-200 flex justify-between items-center">
                            <span className="font-black text-indigo-700">שעה מומלצת לאיחוד:</span>
                            <span className="font-black text-2xl text-indigo-600 bg-white px-3 py-1 rounded-xl shadow-sm">{opt.suggestedTime}</span>
                          </div>
                        </div>
                      </div>
                    ) : opt.type === 'cancel' ? (
                      <div key={`opt-${i}`} className={`bg-white border-2 border-slate-50 p-6 rounded-[2rem] flex flex-col lg:flex-row lg:items-center justify-between gap-6 hover:shadow-lg transition-all border-r-4 border-r-rose-500`}>
                        <div className="flex items-start gap-4">
                          <div className={`bg-rose-50 text-rose-600 p-3.5 rounded-2xl mt-1`}><Ic n="alert" size={24} /></div>
                          <div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="font-black text-slate-900 text-lg">קו {opt.line}</span>
                                {opt.isNightLine && (
                                  <span className="text-indigo-400 bg-indigo-50 p-1 rounded-full" title="קו לילה">
                                    <Ic n="moon" size={16} />
                                  </span>
                                )}
                                {renderPrebookedInfo('sim-'+i, opt.isEilatPrebooked)}
                                {renderFeedingLineInfo('feed-'+i, opt.isFeedingLine)}
                              </div>
                              <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded font-bold">{opt.categoryLabel}</span>
                            </div>
                            <div className="text-sm font-bold text-slate-500 mb-3">{opt.origin} ← {opt.dest}</div>
                            <div className="flex flex-wrap gap-2">
                              <span className="text-[11px] font-black bg-slate-100 text-slate-500 px-2 py-1 rounded-md">יום {opt.days}</span>
                              {renderTransitChip(opt.origin, opt.dest)}
                              <span className={`text-[11px] font-black px-2 py-1 rounded-md bg-rose-100 text-rose-700`}>
                                חשד לנסיעה מיותרת
                              </span>
                              <span className="text-[11px] font-black bg-sky-100 text-sky-700 px-2 py-1 rounded-md">כיוון {opt.direction}</span>
                              <span className="text-[11px] font-black bg-purple-100 text-purple-700 px-2 py-1 rounded-md">{opt.busSize}</span>
                            </div>
                          </div>
                        </div>
                        <div className="bg-slate-50/80 px-6 py-4 rounded-2xl flex-1 max-w-md w-full">
                          <div className="flex justify-between items-center mb-3 text-sm">
                            <span className="font-bold text-slate-500">שעת הנסיעה:</span>
                            <span className={`font-black text-2xl text-rose-600`}>{opt.time}</span>
                          </div>
                          <div className="flex justify-between items-center mb-3 text-sm">
                            <span className="font-bold text-slate-500">{opt.usedMetric === 'peakLoad' ? 'עומס שיא:' : 'נוסעים בפועל:'}</span>
                            <span className="font-black text-slate-700">{opt.metricVal}</span>
                          </div>
                          <div className="flex justify-between items-center text-sm pt-3 border-t border-slate-200">
                            <span className="font-bold text-slate-500">ציון יעילות:</span>
                            <span className={`font-black text-rose-600`}>{opt.efficiency}</span>
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div key={`opt-${i}`} className="bg-slate-50/50 border-2 border-slate-100 p-6 rounded-[2rem] flex flex-col lg:flex-row lg:items-center justify-between gap-6 opacity-70 hover:opacity-100 transition-all">
                        <div className="flex items-start gap-4">
                          <div className="bg-slate-200 text-slate-500 p-3.5 rounded-2xl mt-1"><Ic n="list" size={24} /></div>
                          <div>
                            <div className="flex items-center gap-2 mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="font-black text-slate-700 text-lg">קו {opt.line}</span>
                                {opt.isNightLine && (
                                  <span className="text-indigo-400 bg-indigo-50 p-1 rounded-full" title="קו לילה">
                                    <Ic n="moon" size={16} />
                                  </span>
                                )}
                                {renderPrebookedInfo('sim-ok-'+i, opt.isEilatPrebooked)}
                                {renderFeedingLineInfo('feed-ok-'+i, opt.isFeedingLine)}
                              </div>
                              <span className="text-xs bg-slate-200 text-slate-600 px-2 py-0.5 rounded font-bold">{opt.categoryLabel}</span>
                            </div>
                            <div className="text-sm font-bold text-slate-500 mb-3">{opt.origin} ← {opt.dest}</div>
                            <div className="flex flex-wrap gap-2">
                              <span className="text-[11px] font-black bg-slate-200 text-slate-600 px-2 py-1 rounded-md">יום {opt.days}</span>
                              {renderTransitChip(opt.origin, opt.dest)}
                              <span className="text-[11px] font-black bg-emerald-100 text-emerald-700 px-2 py-1 rounded-md">נסיעה תקינה (ללא שינוי)</span>
                              <span className="text-[11px] font-black bg-sky-100 text-sky-700 px-2 py-1 rounded-md">כיוון {opt.direction}</span>
                              <span className="text-[11px] font-black bg-purple-100 text-purple-700 px-2 py-1 rounded-md">{opt.busSize}</span>
                            </div>
                          </div>
                        </div>
                        <div className="bg-white border border-slate-200 px-6 py-4 rounded-2xl flex-1 max-w-md w-full">
                           <div className="flex justify-between items-center mb-3 text-sm">
                            <span className="font-bold text-slate-500">שעת הנסיעה:</span>
                            <span className="font-black text-xl text-slate-700">{opt.time}</span>
                          </div>
                          <div className="flex justify-between items-center mb-1 text-sm">
                            <span className="font-bold text-slate-500">{opt.usedMetric === 'peakLoad' ? 'עומס שיא:' : 'נוסעים בפועל:'}</span>
                            <span className="font-black text-slate-700">{opt.metricVal}</span>
                          </div>
                        </div>
                      </div>
                    )
                  ))}
                        {optsToRender.length > visibleOptCount && (
                          <div className="pt-4 text-center">
                            <button
                              onClick={() => setVisibleOptCount(prev => prev + 50)}
                              className="w-full py-4 bg-indigo-600 hover:bg-indigo-700 text-white rounded-2xl font-black text-sm transition-all shadow-md flex items-center justify-center gap-2"
                            >
                              <Ic n="chevronDown" size={18} />
                              הצג עוד תוצאות
                              <span className="bg-indigo-500 text-white text-xs px-2.5 py-1 rounded-full font-black">
                                {visibleOptCount} / {optsToRender.length.toLocaleString()}
                              </span>
                            </button>
                          </div>
                        )}
                      </>
                    );
                  })() : !simLoading ? (
                    <div className="py-20 text-center bg-slate-50 rounded-[2rem] border-2 border-dashed border-slate-200">
                      <div className="text-slate-300 font-black italic text-lg mb-2">לא נמצאו הזדמנויות ייעול לסינון המבוקש</div>
                      <p className="text-slate-400 text-sm font-bold px-10">נסה לשנות את הסינון או לבחור קו/עיר אחרים.</p>
                    </div>
                  ) : null}
                </div>
              </div>
            )}

            {tab === "about" && (
              <div className="bg-white p-8 md:p-12 rounded-[3rem] border border-slate-200 shadow-sm max-w-4xl mx-auto transition-opacity duration-300 opacity-100">
                <header className="mb-10 text-center border-b border-slate-100 pb-8">
                  <h2 className="text-3xl font-black text-slate-900 mb-4">על המערכת ושיטות החישוב</h2>
                  <p className="text-slate-500 font-bold text-lg max-w-2xl mx-auto leading-relaxed">
                    מערכת &quot;קו פח&quot; פותחה ככלי עזר למתכנני תחבורה, במטרה לנתח נתוני אמת, לאתר חוסר יעילות ולשפר את לוחות הזמנים של האוטובוסים.
                  </p>
                </header>

                <div className="space-y-6">

                  {/* מה חדש בגרסה הנוכחית — תמיד בהתחלה */}
                  <section className="bg-gradient-to-bl from-indigo-50 to-white rounded-[2rem] p-6 border-2 border-indigo-200 shadow-sm">
                    <div className="flex items-center gap-3 mb-4">
                      <h3 className="text-xl font-black text-indigo-700">מה חדש בעדכון הנוכחי</h3>
                    </div>
                    <div className="space-y-4 text-sm text-slate-700 leading-relaxed">

                      <div className="bg-white rounded-2xl p-4 border border-indigo-100">
                        <h4 className="font-black text-slate-900 mb-1.5 flex items-center gap-2">
                          <span className="bg-emerald-100 text-emerald-700 px-2 py-0.5 rounded-md text-[10px]">עדכון מידע</span>
                          נתונים עדכניים ממקורות חדשים
                        </h4>
                        <p className="text-slate-600 mb-2">כל הנתונים במערכת עודכנו והוחלפו במקורות החדשים והעדכניים של משרד התחבורה. המידע מאורגן כעת בארבעה קבצים נפרדים — נתוני קווים, לוז נסיעות, תחנות, וטבלת עלויות.</p>
                        <ul className="list-disc list-inside space-y-1 marker:text-emerald-400 pr-2 text-xs">
                          <li>לוז מורחב: מעל 205,000 יציאות מתוזמנות עם נתוני נוסעים ועומס מעודכנים.</li>
                          <li>נתוני תחנות מלאים: שם תחנה, עיר ומיקום לכל קו.</li>
                        </ul>
                      </div>

                      <div className="bg-white rounded-2xl p-4 border border-indigo-100">
                        <h4 className="font-black text-slate-900 mb-1.5 flex items-center gap-2">
                          <span className="bg-sky-100 text-sky-700 px-2 py-0.5 rounded-md text-[10px]">שיפור</span>
                          עלות תפעולית מדויקת לפי מחוז
                        </h4>
                        <p className="text-slate-600 mb-2">עד כה כל קו הושווה לממוצע <strong>ארצי</strong> אחד לקטגוריה שלו. כעת ההשוואה מתבצעת מול בנצ'מרק <strong>מחוזי</strong> — כל קו נמדד מול העלות הממוצעת לנוסע בקטגוריה שלו ובמחוז שלו בפועל.</p>
                        <ul className="list-disc list-inside space-y-1 marker:text-sky-400 pr-2 text-xs">
                          <li>זיהוי הוגן יותר — קו בפריפריה נמדד מול הפריפריה, לא מול גוש דן.</li>
                          <li>טבלת בנצ'מרק רשמית של 8 קטגוריות × 8 מחוזות.</li>
                        </ul>
                      </div>

                      <div className="bg-white rounded-2xl p-4 border border-indigo-100">
                        <h4 className="font-black text-slate-900 mb-1.5 flex items-center gap-2">
                          <span className="bg-slate-200 text-slate-700 px-2 py-0.5 rounded-md text-[10px]">תיקון</span>
                          עדכונים מופיעים מיד
                        </h4>
                        <p className="text-slate-600">תוקנה בעיה שבה הדפדפן הציג גרסה ישנה מהזיכרון המקומי (cache) ולא את העדכון האחרון. כעת המערכת בודקת מול השרת בכל טעינה ומציגה תמיד את הנתונים והקוד העדכניים ביותר.</p>
                      </div>

                    </div>
                  </section>

                  <div className="border-t border-slate-100 pt-2">
                    <h3 className="text-2xl font-black text-slate-900 mb-2">איך המערכת עובדת</h3>
                    <p className="text-slate-500 font-medium text-sm">הסבר על כל אחד מהכלים: מה הוא מציג, איך החישוב עובד, ומתי כדאי להשתמש בו.</p>
                  </div>

                  {/* טאב: קווים מיותרים */}
                  <section className="bg-rose-50/40 rounded-[2rem] p-6 border border-rose-100">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="bg-rose-600 text-white p-2 rounded-xl"><Ic n="trash" size={18} /></div>
                      <h3 className="text-xl font-black text-rose-700">קווים לא יעילים</h3>
                    </div>
                    <p className="text-slate-700 font-medium text-sm mb-4 leading-relaxed">
                      <strong>מה הוא עושה:</strong> מדרג כל קו בסולם 0–100 לפי רמת אי-היעילות שלו, ומציג רק קווים עם ציון 25+. כל קו מקבל גם תווית סטטוס בולטת (חמור / לא יעיל / טעון בדיקה / סטייה קלה / תקין) וצבע מתאים.
                    </p>

                    <div className="bg-white rounded-2xl border border-rose-100 p-4 mb-3">
                      <h4 className="font-black text-slate-800 text-sm mb-2">שלב 1: סיווג ל-8 קטגוריות</h4>
                      <p className="text-slate-600 text-sm leading-relaxed mb-2">לפני שמחשבים ציון, הקו מסווג לאחת מ-8 הקטגוריות הרשמיות של משרד התחבורה — לפי שדה "ייחודיות", "קבוצת יעילות תפעולית", סוג שירות, אורך מסלול (סף 45 ק"מ) ותדירות שבועית (סף 600).</p>
                      <div className="flex flex-wrap gap-1.5 text-[11px] font-black">
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">אזורי</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">בינעירוני ארוך</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">בינעירוני קצר</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">עירוני תדירות גבוהה</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">עירוני תדירות נמוכה</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">לילה</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">קווים מזינים</span>
                        <span className="bg-slate-100 text-slate-700 px-2 py-1 rounded-md">תלמידים</span>
                      </div>
                    </div>

                    <div className="bg-white rounded-2xl border border-rose-100 p-4 mb-3">
                      <h4 className="font-black text-slate-800 text-sm mb-2">שלב 2: ניקוד (0–100)</h4>
                      <p className="text-slate-600 text-sm leading-relaxed mb-2">ארבעה רכיבים, סף הנוסעים בכל אחד מהם מותאם לקטגוריה (5 לאזורי/לילה, 8 לקצר/מזין, 10 לארוך/תדירות נמוכה, 15 לתדירות גבוהה/תלמידים):</p>
                      <ul className="list-disc list-inside text-slate-600 text-sm space-y-1.5 pr-2">
                        <li><strong>נסיעות שפל (עד 30 נק&apos;):</strong> אחוז הנסיעות עם פחות נוסעים מסף הקטגוריה.</li>
                        <li><strong>קילומטר מבוזבז (עד 20 נק&apos;):</strong> משקלל אחוז ק&quot;מ סרק וכמות מוחלטת.</li>
                        <li><strong>עלות תפעולית לנוסע (עד 20 נק&apos;):</strong> יחס לבנצ&apos;מרק הקטגוריה (₪31.8 לאזורי, ₪9.4 לעירוני תדירות גבוהה, וכו&apos;).</li>
                        <li><strong>ממוצע נוסעים ועומס שיא (עד 30 נק&apos;):</strong> ביחס לקיבולת הרכב — מיניבוס (19), מידי (35), רגיל (50), מפרקי (90).</li>
                      </ul>
                    </div>

                    <div className="bg-emerald-50 rounded-2xl border border-emerald-100 p-4 mb-3">
                      <h4 className="font-black text-emerald-800 text-sm mb-2">שלב 3: הגנות (מופחתות מהציון)</h4>
                      <ul className="list-disc list-inside text-emerald-700 text-sm font-medium space-y-1 pr-2">
                        <li><strong>תחנות בלעדיות / יעד ייחודי (−15):</strong> הקו משרת תחנות שאין אליהן קו אחר.</li>
                        <li><strong>מותאם רכבת (−10):</strong> עמודת "ייחודיות" מציינת זאת במפורש.</li>
                        <li><strong>תלמידים בשעות בי&quot;ס (−10):</strong> 60%+ מהנסיעות ב-7:00–8:30 או 13:00–15:30.</li>
                      </ul>
                    </div>

                    <div className="bg-white rounded-2xl border border-rose-100 p-4">
                      <h4 className="font-black text-slate-800 text-sm mb-2">שלב 4: תיוג סטטוס</h4>
                      <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-[11px] font-black">
                        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-xl p-2 text-center">0–24 תקין</div>
                        <div className="bg-amber-50 border border-amber-200 text-amber-600 rounded-xl p-2 text-center">25–44 סטייה קלה</div>
                        <div className="bg-orange-50 border border-orange-200 text-orange-600 rounded-xl p-2 text-center">45–64 טעון בדיקה</div>
                        <div className="bg-rose-50 border border-rose-200 text-rose-600 rounded-xl p-2 text-center">65–79 לא יעיל</div>
                        <div className="bg-rose-100 border border-rose-300 text-rose-700 rounded-xl p-2 text-center">80+ חמור</div>
                      </div>
                    </div>
                  </section>

                  {/* טאב: ניתוח אזורי */}
                  <section className="bg-amber-50/40 rounded-[2rem] p-6 border border-amber-100">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="bg-amber-600 text-white p-2 rounded-xl"><Ic n="chart" size={18} /></div>
                      <h3 className="text-xl font-black text-amber-700">ניתוח אזורי</h3>
                    </div>
                    <p className="text-slate-700 font-medium text-sm mb-4 leading-relaxed">
                      <strong>מה הוא עושה:</strong> מציג מפת חום אזורית של בעיות יעילות — לפי עיר או לפי מחוז. עוזר לזהות אזורים גיאוגרפיים עם ריכוז גבוה של קווים בעייתיים.
                    </p>
                    <div className="bg-white rounded-2xl border border-amber-100 p-4">
                      <h4 className="font-black text-slate-800 text-sm mb-2">איך החישוב עובד</h4>
                      <ul className="list-disc list-inside text-slate-600 text-sm space-y-1.5 pr-2">
                        <li>הניתוח מתייחס <strong>רק לקווים עם ציון 80+</strong> (סטטוס "חמור — דורש התערבות"), כדי לזקק את התמונה.</li>
                        <li>לכל עיר/מחוז נסכמים: מספר הקווים החמורים, סך הנסיעות, סך ק"מ מבוזבז, וממוצע עלות תפעולית.</li>
                        <li>לחיצה על אזור מעבירה ישירות לטאב "קווים לא יעילים" עם פילטר מתאים.</li>
                      </ul>
                    </div>
                  </section>

                  {/* טאב: כל הנסיעות */}
                  <section className="bg-indigo-50/40 rounded-[2rem] p-6 border border-indigo-100">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="bg-indigo-600 text-white p-2 rounded-xl"><Ic n="list" size={18} /></div>
                      <h3 className="text-xl font-black text-indigo-700">כל הנסיעות במערכת</h3>
                    </div>
                    <p className="text-slate-700 font-medium text-sm mb-4 leading-relaxed">
                      <strong>מה הוא עושה:</strong> טבלה מלאה של כל הנסיעות במערכת, עם אפשרות לסינון, חיפוש ומיון. שימושי לאיתור נקודתי של נסיעה ספציפית או לבחינת עומס בעיר מסוימת.
                    </p>
                    <div className="bg-white rounded-2xl border border-indigo-100 p-4">
                      <h4 className="font-black text-slate-800 text-sm mb-2">פילטרים זמינים</h4>
                      <ul className="list-disc list-inside text-slate-600 text-sm space-y-1.5 pr-2">
                        <li><strong>חיפוש עיר:</strong> מסנן נסיעות שעוברות דרך עיר מסוימת (מוצא, יעד, או דרך). הסינון מתבצע בהקשת Enter.</li>
                        <li><strong>נסיעות עמוסות:</strong> טוגל שמסנן רק נסיעות עם ניצולת מעל 80% מקיבולת הרכב.</li>
                        <li><strong>סוג קו:</strong> סינון לפי קטגוריית הקו (עירוני / בינעירוני / אזורי וכו&apos;).</li>
                        <li><strong>מיון:</strong> לפי נוסעים או עומס שיא — עולה או יורד.</li>
                      </ul>
                    </div>
                  </section>

                  {/* טאב: סימולטור */}
                  <section className="bg-slate-50 rounded-[2rem] p-6 border border-slate-200">
                    <div className="flex items-center gap-3 mb-3">
                      <div className="bg-slate-900 text-white p-2 rounded-xl"><Ic n="zap" size={18} /></div>
                      <h3 className="text-xl font-black text-slate-900">אלגוריתם ייעול (סימולטור)</h3>
                    </div>
                    <p className="text-slate-700 font-medium text-sm mb-4 leading-relaxed">
                      <strong>מה הוא עושה:</strong> מקבל קו מסוים ומציג המלצות פעולה לכל נסיעה: <strong>איחוד</strong> שתי נסיעות צמודות, <strong>ביטול</strong> נסיעת סרק, או <strong>השארה</strong>. כל המלצה כוללת נימוק והשפעה צפויה.
                    </p>

                    <div className="bg-white rounded-2xl border border-slate-200 p-4 mb-3">
                      <h4 className="font-black text-slate-800 text-sm mb-2">תנאי איחוד</h4>
                      <p className="text-slate-600 text-sm leading-relaxed mb-2">המערכת מחפשת נסיעות צמודות שניתן לאחד בלי לגרום לעומס. הסף הזמני:</p>
                      <ul className="list-disc list-inside text-slate-600 text-sm space-y-1 pr-2 mb-3">
                        <li><strong>עירוני:</strong> עד 30 דקות פער.</li>
                        <li><strong>בין-עירוני:</strong> עד שעה.</li>
                        <li><strong>אזורי:</strong> עד 3 שעות (או לפי זמן המתנה ידני).</li>
                      </ul>
                      <p className="text-slate-700 font-bold text-sm mb-1">סף סך נוסעים לאיחוד (מתאים לקיבולת הרכב):</p>
                      <ul className="list-none text-slate-600 text-sm space-y-1 pr-2">
                        <li>• <strong>מיניבוס (19):</strong> עד ~7 נוסעים יחד.</li>
                        <li>• <strong>מידיבוס (35):</strong> עד ~13.</li>
                        <li>• <strong>רגיל (50):</strong> עד ~18–20.</li>
                        <li>• <strong>מפרקי (90):</strong> עד ~32–36.</li>
                      </ul>
                    </div>

                    <div className="bg-white rounded-2xl border border-slate-200 p-4">
                      <h4 className="font-black text-slate-800 text-sm mb-2">תנאי ביטול</h4>
                      <ul className="list-disc list-inside text-slate-600 text-sm space-y-2 pr-2">
                        <li><strong>רף נוסעים נמוך:</strong> ~5 נוסעים באוטובוס רגיל לעירוני, ~3 לאזורי. ברכבים קטנים הרף יורד, במפרקי הוא עולה.</li>
                        <li><strong>חלופה זמינה חובה:</strong> עד 15 דק&apos; בעירוני, שעה בבין-עירוני, או עד 4 שעות באזורי.</li>
                        <li><strong>הגנת רשת (אזוריים):</strong> אלגוריתם הביטול נעצר אם תרד מתחת ל-3 נסיעות ביום — לשמור על קו חיים בסיסי.</li>
                        <li><strong>הגנה על נסיעה ראשונה/אחרונה ביום:</strong> לעולם לא תוצע לביטול, גם אם ריקה.</li>
                      </ul>
                    </div>
                  </section>

                </div>

                <div className="mt-12 bg-indigo-50/50 p-6 md:p-8 rounded-[2rem] border border-indigo-100 flex flex-col items-center text-center">
                  <h3 className="font-black text-slate-900 text-lg mb-2">אודות הפרויקט</h3>
                  <p className="text-slate-600 text-sm font-medium leading-relaxed max-w-lg mb-5">
                    הפרויקט הוקם בהתנדבות וללא כוונות רווח.<br />
                    נבנה על ידי <strong className="text-slate-900">שלמה הרטמן</strong> בשילוב מודל הבינה המלאכותית <strong className="text-slate-900">Gemini</strong>.
                  </p>
                  <div className="bg-white border-2 border-indigo-100 text-slate-700 px-6 py-3 rounded-xl font-black shadow-sm flex flex-col md:flex-row items-center gap-2">
                    <span>להצעות ולשיפורים:</span>
                    <span className="text-indigo-600" dir="ltr">ahlomihartman@gmail.com</span>
                  </div>
                </div>
              </div>
            )}
          </main>
        )}
      </div>
    </div>
  );
}
