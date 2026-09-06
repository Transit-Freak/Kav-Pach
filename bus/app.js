// מדד דיוק האוטובוסים — הלוגיקה של העמוד. הנתונים: data/index.json (סיכום ארצי
// לכל יום), data/days/YYYY-MM-DD.json (מסלולים, מפעילים, ערים, שעות, המאחרות),
// data/days/YYYY-MM-DD.stops.json (פרופיל איחור לאורך כל קו — נטען כשפותחים קו),
// data/stops.json (שמות תחנות לפי מק"ט). העיצוב: כמו מדד אמינות הרכבת.
(function(){
'use strict';

const CATS = ['מוקדם (יותר מ-2 דק׳)', 'בזמן (עד 5 דק׳)', 'איחור 5–10 דק׳', 'איחור 10–20 דק׳', 'איחור מעל 20 דק׳'];
const C = {early: '#7C3AED', ok: '#00A65A', warn: '#F4B400', late: '#F26B1D', bad: '#D7263D', grid: '#E5E7EB', axis: '#8A94A3', bg: '#FFFFFF', line: '#1E5BC6', accent: '#101418'};
const BCOL = [C.early, C.ok, C.warn, C.late, C.bad];
const GRID = C.grid, AXIS = C.axis, BG = C.bg;
const DAYNAMES = ['ראשון', 'שני', 'שלישי', 'רביעי', 'חמישי', 'שישי', 'שבת'];
const DATA = 'data/';
const MIN_RIDES = 10;   // דירוג קווים: לפחות כך וכך נסיעות שנצפו, אחרת קו של נסיעה אחת מוביל
let IDX = null, DAYS = [], CAT = {}, NAMES = null, period = 'day', dayD = null, dayCache = {}, stopCache = {};
let sortA = {k: 'meas', dir: -1}, sortC = {k: 'meas', dir: -1}, sortL = {k: 'meas', dir: -1}, lq = '', agency = '', rank = '', openLine = null, showAllL = false;
const $ = (s, el) => (el || document).querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const pct = (a, b) => b ? Math.round(100 * a / b) + '%' : '—';
const fmt1 = v => v == null ? '—' : (Math.round(v * 10) / 10).toLocaleString('he-IL', {minimumFractionDigits: 1, maximumFractionDigits: 1});
const num = v => v == null ? '—' : Number(v).toLocaleString('he-IL');
const heDate = d => { const [y, m, dd] = d.split('-'); return `${DAYNAMES[new Date(+y, m - 1, +dd).getDay()]}, ${+dd}.${+m}.${y}`; };
const shortDate = d => { const [, m, dd] = d.split('-'); return `${+dd}.${+m}`; };
const hhmm = s => s == null ? '—' : `${String(Math.floor(s / 3600) % 24).padStart(2, '0')}:${String(Math.floor(s / 60) % 60).padStart(2, '0')}`;
const dcls = v => v == null ? 'dn' : v < -2 ? 'd0' : v <= 5 ? 'd1' : v <= 10 ? 'd2' : v <= 20 ? 'd3' : 'd4';
const catOf = v => v == null ? -1 : v < -2 ? 0 : v <= 5 ? 1 : v <= 10 ? 2 : v <= 20 ? 3 : 4;
const delayTxt = m => m == null ? '—' : (m > 0 ? '+' : '') + fmt1(m);
function load(url) { return fetch(url + '?v=' + Date.now()).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); }); }
const stopName = code => (NAMES && NAMES[code]) || code;
// יום שבו נצפו פחות מ-30% מהנסיעות המתוכננות — שידור חלקי, מוצג בנפרד
const partial = d => d.sched > 0 && d.obs < d.sched * 0.3;

// ---------------------------------------------------------------- צבירה (כמה ימים)
function emptyAgg() { return {sched: 0, obs: 0, meas: 0, c: [0, 0, 0, 0, 0], o: [0, 0, 0, 0, 0], sum: 0, s: null, far: 0, extra: 0, vt: [0, 0, 0]}; }
// גודל הרכב במילים של האתר: "אוטובוס" אצל המשרד הוא קטגוריית גודל (לא מיניבוס,
// לא מידיבוס, לא מפרקי) — אותו ניסוח כמו ב"הקו בזמן" (שלמה 06.09)
const VNAMES = {'מיניבוס': 'מיניבוס', 'מידיבוס': 'מידיבוס', 'אוטובוס': 'אוטובוס בגודל מלא', 'מפרקי': 'אוטובוס מפרקי'};
const vname = v => VNAMES[v] || v || '';
function addAgg(t, x) {
  const sched = x.sched != null ? x.sched : x[0], obs = x.obs != null ? x.obs : x[1], meas = x.meas != null ? x.meas : x[2], c = x.c || x[3], s = x.s || x[4];
  t.sched += sched || 0; t.obs += obs || 0; t.meas += meas || 0;
  (c || []).forEach((v, i) => t.c[i] += v);
  if (s && s[0] != null) t.sum += s[0] * (meas || 0);
}
function finish(t) { t.avg = t.meas ? t.sum / t.meas : null; t.on = t.meas ? t.c[1] / t.meas : null; return t; }

// ---------------------------------------------------------------- תרשימים
function lineChart(el, pts, o) {
  const W = o.w || 720, H = o.h || 200, L = 36, R = 8, T = 12, B = 26;
  const vals = pts.map(p => p.y).filter(v => v != null);
  if (!vals.length) { el.innerHTML = '<div class="empty">אין נתונים</div>'; return; }
  let mn = o.min != null ? o.min : Math.min(...vals), mx = o.max != null ? o.max : Math.max(...vals);
  if (mx === mn) { mx += 1; mn -= 1; }
  const px = i => L + (W - L - R) * (pts.length > 1 ? i / (pts.length - 1) : 0.5);
  const py = v => T + (H - T - B) * (1 - (v - mn) / (mx - mn));
  const ticks = 4; let grid = '';
  for (let i = 0; i <= ticks; i++) { const v = mn + (mx - mn) * i / ticks, y = py(v); grid += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${GRID}"/><text x="${L - 6}" y="${y + 4}" font-size="10" fill="${AXIS}" text-anchor="end">${Math.round(v)}${o.unit || ''}</text>`; }
  let path = '', area = '', dots = '', started = false;
  pts.forEach((p, i) => {
    if (p.y == null) { started = false; return; }
    const x = px(i), y = py(p.y);
    path += (started ? 'L' : 'M') + x + ' ' + y;
    if (!started) area += `M${x} ${py(mn)}L${x} ${y}`; else area += `L${x} ${y}`;
    started = true;
    if (pts.length <= 60 || i === pts.length - 1) dots += `<circle cx="${x}" cy="${y}" r="${i === pts.length - 1 ? 4.5 : 2.5}" fill="${i === pts.length - 1 ? C.accent : o.color}" stroke="${BG}" stroke-width="1.5"/>`;
    if ((i + 1 < pts.length && pts[i + 1].y == null) || i === pts.length - 1) area += `L${x} ${py(mn)}Z`;
  });
  const step = Math.max(1, Math.ceil(pts.length / 8)); let xl = '';
  pts.forEach((p, i) => { if (i % step === 0 || i === pts.length - 1) xl += `<text x="${px(i)}" y="${H - 8}" font-size="10" fill="${AXIS}" text-anchor="middle">${esc(p.x)}</text>`; });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="aspect-ratio:${W}/${H}">${grid}${xl}<path d="${area}" fill="${o.color}" opacity=".10"/><path d="${path}" fill="none" stroke="${o.color}" stroke-width="2" stroke-linejoin="round"/><line id="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="${C.accent}" stroke-dasharray="3 3" opacity="0" /><rect x="${L}" y="0" width="${W - L - R}" height="${H}" fill="transparent"/>${dots}</svg><div class="tip"></div>`;
  const svg = $('svg', el), tip = $('.tip', el), cross = $('#cross', el);
  const move = ev => {
    const r = svg.getBoundingClientRect(); const fx = (ev.clientX - r.left) / r.width * W;
    let best = 0, bd = 1e9; pts.forEach((p, i) => { const d = Math.abs(px(i) - fx); if (d < bd) { bd = d; best = i; } });
    const p = pts[best]; cross.setAttribute('x1', px(best)); cross.setAttribute('x2', px(best)); cross.setAttribute('opacity', '1');
    tip.innerHTML = p.tip; tip.style.display = 'block';
    const leftPct = px(best) / W * 100; tip.style.right = `${100 - leftPct}%`; tip.style.top = `${Math.max(0, py(p.y == null ? mn : p.y) / H * r.height - 60)}px`;
  };
  el.onmousemove = move; el.ontouchstart = ev => move(ev.touches[0]); el.ontouchmove = ev => move(ev.touches[0]);
  el.onmouseleave = () => { tip.style.display = 'none'; cross.setAttribute('opacity', '0'); };
}
function barChart(el, bars, o) {
  const W = o.w || 720, H = o.h || 180, L = 36, R = 8, T = 12, B = 26, mx = o.max || 100;
  const n = bars.length, bw = (W - L - R) / n, gap = Math.min(4, bw * .25);
  const py = v => T + (H - T - B) * (1 - v / mx);
  let grid = ''; for (let i = 0; i <= 4; i++) { const v = mx * i / 4, y = py(v); grid += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="${GRID}"/><text x="${L - 6}" y="${y + 4}" font-size="10" fill="${AXIS}" text-anchor="end">${Math.round(v)}${o.unit || ''}</text>`; }
  let rects = '', xl = '';
  bars.forEach((b, i) => {
    const x = L + i * bw + gap / 2;
    if (b.y != null) rects += `<rect x="${x}" y="${py(Math.min(b.y, mx))}" width="${bw - gap}" height="${py(0) - py(Math.min(b.y, mx))}" rx="2" fill="${b.color || o.color}"/>`;
    else rects += `<rect x="${x}" y="${py(0) - 2}" width="${bw - gap}" height="2" rx="1" fill="${GRID}"/>`;
    if (n <= 26 || i % Math.ceil(n / 26) === 0) xl += `<text x="${x + (bw - gap) / 2}" y="${H - 8}" font-size="10" fill="${AXIS}" text-anchor="middle">${esc(b.x)}</text>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="aspect-ratio:${W}/${H}">${grid}${rects}${xl}</svg><div class="tip"></div>`;
  const tip = $('.tip', el), svg = $('svg', el);
  el.onmousemove = ev => {
    const r = svg.getBoundingClientRect(); const fx = (ev.clientX - r.left) / r.width * W; const i = Math.min(n - 1, Math.max(0, Math.floor((fx - L) / bw)));
    const b = bars[i]; if (!b) return; tip.innerHTML = b.tip; tip.style.display = 'block';
    tip.style.right = `${100 - (L + (i + .5) * bw) / W * 100}%`; tip.style.top = `${Math.max(0, py(Math.min(b.y || 0, mx)) / H * r.height - 60)}px`;
  };
  el.onmouseleave = () => { tip.style.display = 'none'; };
}
const hourColor = share => share == null ? GRID : share >= .8 ? C.ok : share >= .65 ? C.warn : share >= .5 ? C.late : C.bad;

// ---------------------------------------------------------------- לוח שנה ותקופות
const HEMONTHS = ['ינואר', 'פברואר', 'מרץ', 'אפריל', 'מאי', 'יוני', 'יולי', 'אוגוסט', 'ספטמבר', 'אוקטובר', 'נובמבר', 'דצמבר'];
let calOpen = false, calYM = null;
function calHtml() {
  const [y, m] = calYM;
  const nDays = new Date(y, m + 1, 0).getDate(), startDow = new Date(y, m, 1).getDay();
  const byD = new Map(DAYS.map(d => [d.d, d]));
  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push('<span></span>');
  for (let day = 1; day <= nDays; day++) {
    const iso = `${y}-${String(m + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
    const d = byD.get(iso);
    if (!d) { cells.push(`<span class="cd off">${day}</span>`); continue; }
    const cls = ['cd', partial(d) ? 'part' : '', iso === dayD && period === 'day' ? 'on' : ''].filter(Boolean).join(' ');
    const tip = d.meas ? `${pct(d.c[1], d.meas)} בזמן · ${num(d.obs)} נסיעות נצפו` : 'אין מדידות';
    cells.push(`<button class="${cls}" data-d="${iso}" title="${tip}">${day}</button>`);
  }
  const mm = String(m + 1).padStart(2, '0');
  const canPrev = DAYS[0].d < `${y}-${mm}-01`, canNext = DAYS[DAYS.length - 1].d > `${y}-${mm}-${nDays}`;
  return `<div class="calhead"><button class="cnav" data-nav="-1" title="חודש קודם" ${canPrev ? '' : 'disabled'}>‹</button><b>${HEMONTHS[m]} ${y}</b><button class="cnav" data-nav="1" title="חודש הבא" ${canNext ? '' : 'disabled'}>›</button></div>
    <div class="calgrid">${['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'].map(w => `<i>${w}׳</i>`).join('')}${cells.join('')}</div>
    <div class="calnote">אפור בהיר: אין נתונים · נקודה: שידור חלקי באותו יום</div>`;
}
function renderCal() {
  const cal = $('#cal'); if (!cal) return;
  cal.hidden = !calOpen; if (!calOpen) return;
  cal.innerHTML = calHtml();
  cal.querySelectorAll('.cnav').forEach(b => b.onclick = e => { e.stopPropagation(); let [y, m] = calYM; m += Number(b.dataset.nav); if (m < 0) { m = 11; y--; } if (m > 11) { m = 0; y++; } calYM = [y, m]; renderCal(); });
  cal.querySelectorAll('button.cd').forEach(b => b.onclick = e => { e.stopPropagation(); calOpen = false; dayD = b.dataset.d; period = 'day'; render(); });
}
document.addEventListener('click', e => { if (calOpen && !e.target.closest('.dwrap')) { calOpen = false; renderCal(); } });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && calOpen) { calOpen = false; renderCal(); } });
function renderPeriods() {
  const el = $('#periods');
  const chips = [['day', 'יום'], ['7', '7 ימים'], ['30', '30 ימים']].filter(([k]) => k === 'day' || DAYS.length >= 3 && (k === '7' || DAYS.length > 7));
  const curD = dayD || DAYS[DAYS.length - 1].d;
  if (!calYM) calYM = [Number(curD.slice(0, 4)), Number(curD.slice(5, 7)) - 1];
  el.innerHTML = `<div class="seg">${chips.map(([k, t]) => `<button class="pchip${period === k ? ' on' : ''}" data-p="${k}">${t}</button>`).join('')}</div>` +
    `<div class="daynav${period === 'day' ? ' on' : ''}"><button id="dprev" title="יום קודם">‹</button><div class="dwrap"><button id="dpick" class="dbtn" title="בחירת יום">${period === 'day' ? heDate(curD) : 'בחירת יום ▾'}</button><div id="cal" class="cal" hidden></div></div><button id="dnext" title="יום הבא">›</button></div>`;
  el.querySelectorAll('.pchip').forEach(b => b.onclick = () => { period = b.dataset.p; render(); });
  const setDay = d => { if (!DAYS.some(x => x.d === d)) return; dayD = d; period = 'day'; render(); };
  $('#dpick').onclick = e => { e.stopPropagation(); calOpen = !calOpen; if (calOpen) calYM = [Number(curD.slice(0, 4)), Number(curD.slice(5, 7)) - 1]; renderCal(); };
  const cur = () => DAYS.findIndex(x => x.d === curD);
  $('#dprev').onclick = () => { const i = cur(); if (period !== 'day') setDay(DAYS[DAYS.length - 1].d); else if (i > 0) setDay(DAYS[i - 1].d); };
  $('#dnext').onclick = () => { const i = cur(); if (period !== 'day') setDay(DAYS[DAYS.length - 1].d); else if (i < DAYS.length - 1) setDay(DAYS[i + 1].d); };
  renderCal();
}
function windowDays() {
  if (period === 'day') return DAYS.filter(d => d.d === dayD);
  return DAYS.slice(-Number(period)).filter(d => !partial(d));
}

// ---------------------------------------------------------------- תצוגה
function heroHtml(a, days) {
  const title = days.length === 1 ? heDate(days[0].d) : days.length ? `${shortDate(days[0].d)} – ${shortDate(days[days.length - 1].d)}.${days[days.length - 1].d.slice(0, 4)} · ${days.length} ימים` : '';
  const on = a.meas ? pct(a.c[1], a.meas) : '—';
  const oT = a.o.reduce((x, y) => x + y, 0);
  // כל נתון מסביר את עצמו במקום, במשפט פשוט (שלמה 06.09: "לא מובן מה כל דבר אומר")
  const items = [
    ['יציאה בזמן מהמוצא', oT ? pct(a.o[1], oT) : '—', '', oT ? `מכל הנסיעות, ${pct(a.o[1], oT)} יצאו מהתחנה הראשונה בזמן. ${pct(a.o[0], oT)} יצאו מוקדם (יותר מ-2 דקות לפני השעה שבלו״ז) ו-${pct(a.o[2] + a.o[3] + a.o[4], oT)} יצאו באיחור (יותר מ-5 דקות אחריה).` : 'אין מדידה בתחנת המוצא'],
    ['איחור ממוצע בתחנה', a.avg == null ? '—' : fmt1(a.avg), 'דק׳', `בממוצע, אוטובוס מגיע לתחנה ${a.avg == null ? '—' : fmt1(a.avg)} דקות אחרי השעה שבלו״ז.${a.s && a.s[1] != null ? ` חצי מההגעות עד ${fmt1(a.s[1])} דקות, ו-90% עד ${fmt1(a.s[2])} דקות.` : ''}`],
    ['מעל 20 דקות', a.meas ? pct(a.c[4], a.meas) : '—', '', `${a.meas ? pct(a.c[4], a.meas) : '—'} מההגעות לתחנות היו באיחור של יותר מ-20 דקות (${a.meas ? pct(a.c[3] + a.c[4], a.meas) : '—'} יותר מ-10 דקות). ${a.meas ? pct(a.c[0], a.meas) : '—'} מההגעות היו מוקדמות מדי.`],
    ['נסיעות שנצפו', num(a.obs), '', `מתוך ${num(a.sched)} נסיעות בלוח הזמנים, ${num(a.obs)} (${pct(a.obs, a.sched)}) שידרו מיקום ונמדדו.${a.extra ? ` עוד ${num(a.extra)} נסיעות שודרו אבל לא מופיעות בלו״ז (תגבורים).` : ''}`],
  ];
  const cap = `${title}. נמדדו ${num(a.meas)} הגעות של אוטובוסים לתחנות ברחבי הארץ. הגעה נחשבת "בזמן" כשהאוטובוס מגיע לא יותר מ-5 דקות אחרי השעה שבלוח הזמנים, ולא יותר מ-2 דקות לפניה.`;
  const r = 54, circ = 2 * Math.PI * r, share = a.meas ? a.c[1] / a.meas : 0;
  const segs = a.meas ? a.c.map(v => v / a.meas) : [0, 0, 0, 0, 0];
  let off = 0, arcs = '';
  segs.forEach((s, i) => { if (s > 0) arcs += `<circle r="${r}" cx="70" cy="70" fill="none" stroke="${BCOL[i]}" stroke-width="14" stroke-dasharray="${(s * circ).toFixed(1)} ${circ.toFixed(1)}" stroke-dashoffset="${(-off * circ).toFixed(1)}" transform="rotate(-90 70 70)"/>`; off += s; });
  return `<div class="ringwrap"><div class="ring"><svg viewBox="0 0 140 140"><circle r="${r}" cx="70" cy="70" fill="none" stroke="var(--line)" stroke-width="14"/>${arcs}</svg><div class="rv"><b>${on}</b><span>בזמן</span></div></div>
    <div class="rtext"><h2>${Math.round(share * 100) || 0}% מההגעות לתחנות היו בזמן</h2><p>${esc(cap)}</p><div class="rstats">${items.map(([l, v, u, c]) => `<div><b>${v}${u ? `<i>${u}</i>` : ''}</b><span>${l}</span><small>${c}</small></div>`).join('')}</div></div></div>`;
}
function distHtml(a) {
  if (!a.meas) return '';
  return `<div class="dist">${a.c.map((v, i) => v ? `<i class="s${i}" style="flex:${v}" title="${CATS[i]}: ${num(v)}"></i>` : '').join('')}</div>
    <div class="legend">${a.c.map((v, i) => `<span><i style="background:${BCOL[i]}"></i>${CATS[i]} · ${pct(v, a.meas)} (${num(v)})</span>`).join('')}</div>`;
}
function sortRows(rows, s) { return rows.sort((x, y) => { const a = x[s.k], b = y[s.k]; if (a == null && b == null) return 0; if (a == null) return 1; if (b == null) return -1; return (a < b ? -1 : a > b ? 1 : 0) * s.dir; }); }
function th(label, k, s) { return `<th data-k="${k}" class="${s.k === k ? 'on' : ''}">${label}${s.k === k ? (s.dir < 0 ? ' ▼' : ' ▲') : ''}</th>`; }
const onCell = on => `${on == null ? '—' : Math.round(on * 100) + '%'}<span class="bar"><i style="width:${Math.round((on || 0) * 100)}%"></i></span>`;

function mergeDays(days) {
  const tot = emptyAgg(), A = {}, Cc = {}, H = {}, Rr = {}, worst = [];
  for (const d of days) {
    addAgg(tot, d.tot);
    tot.far += d.tot.far || 0; tot.extra += d.tot.extra || 0;
    if (days.length === 1) tot.s = d.tot.s;
    for (const [nm, sched, obs, meas, c, s, o, va] of d.agencies) { const x = A[nm] || (A[nm] = emptyAgg()); addAgg(x, {sched, obs, meas, c, s}); (o || []).forEach((v, i) => x.o[i] += v); (va || []).forEach((v, i) => x.vt[i] += v); }
    (d.tot.vt || []).forEach((v, i) => tot.vt[i] += v);
    for (const [nm, meas, c, s] of d.cities) addAgg(Cc[nm] || (Cc[nm] = emptyAgg()), {meas, c, s});
    for (const [h, n, on] of d.hours) { const x = H[h] || (H[h] = [0, 0]); x[0] += n; x[1] += on; }
    for (const r of d.routes) {
      const [rid, sched, obs, meas, c, s, o, hours, ws, vt] = r;
      const x = Rr[rid] || (Rr[rid] = Object.assign(emptyAgg(), {rid, hours: {}, ws: [], vplan: '', vact: {}}));
      addAgg(x, {sched, obs, meas, c, s}); o.forEach((v, i) => { x.o[i] += v; tot.o[i] += v; });
      for (const [h, n, on] of hours) { const y = x.hours[h] || (x.hours[h] = [0, 0]); y[0] += n; y[1] += on; }
      if (vt) { x.vplan = vt[0]; x.vt[0] += vt[1]; x.vt[1] += vt[2]; x.vt[2] += vt[3]; x.vact[vt[4]] = (x.vact[vt[4]] || 0) + vt[1]; }
      if (days.length === 1) { x.s = s; x.ws = ws; }
    }
    for (const w of d.worst) worst.push([d.d, ...w]);
  }
  finish(tot); Object.values(A).forEach(finish); Object.values(Cc).forEach(finish); Object.values(Rr).forEach(finish);
  worst.sort((a, b) => b[3] - a[3]);
  return {tot, A, Cc, H, Rr, worst, days: days.map(d => d.d)};
}

function lineLabel(rid) {
  const c = CAT[rid] || [];
  // route_long_name מסתיים בקוד כיוון+חלופה ("…-כרמיאל-10") — לא לתצוגה
  return {short: c[1] || rid, long: (c[2] || '').replace(/-\d[\d#א-ת]?$/, '').replace('<->', ' ← '), agency: c[3] || '', dir: c[4] || '', alt: c[5] || '', aid: c[7] || ''};
}
let M = null;
function render() {
  renderPeriods();
  const days = windowDays();
  const app = $('#app');
  const need = days.filter(d => !dayCache[d.d]);
  if (need.length) {
    app.innerHTML = '<div class="msg">טוען את נתוני הימים…</div>';
    Promise.all(need.map(d => load(DATA + 'days/' + d.d + '.json').then(j => { dayCache[d.d] = j; }))).then(render).catch(e => { app.innerHTML = `<div class="msg">הנתונים לא נטענו (${esc(e.message)})</div>`; });
    return;
  }
  const loaded = days.map(d => dayCache[d.d]);
  if (!loaded.length) { app.innerHTML = '<div class="msg">אין נתונים לתקופה</div>'; return; }
  M = mergeDays(loaded);
  $('#sub').textContent = `${num(DAYS.length)} ימים · מעודכן ${IDX.updated ? IDX.updated.replace('T', ' ').replace('Z', ' UTC') : ''} · המקור: שידורי המיקום של משרד התחבורה (SIRI) דרך דאטאבוס, לוח הזמנים (GTFS) של משרד התחבורה`;
  const trend = DAYS.map(d => ({x: shortDate(d.d), y: partial(d) || !d.meas ? null : Math.round(100 * d.c[1] / d.meas), tip: `<b>${heDate(d.d)}</b><br>${d.meas ? pct(d.c[1], d.meas) + ' בזמן' : 'אין מדידות'}${partial(d) ? '<br>שידור חלקי' : ''}<br>${num(d.obs)} נסיעות נצפו מתוך ${num(d.sched)}`}));
  const hours = Array.from({length: 24}, (_, h) => { const v = M.H[h]; const sh = v && v[0] >= 30 ? v[1] / v[0] : null; return {x: String(h).padStart(2, '0'), y: sh == null ? null : Math.round(sh * 100), color: hourColor(sh), tip: `<b>${String(h).padStart(2, '0')}:00–${String(h).padStart(2, '0')}:59</b><br>${v && v[0] ? pct(v[1], v[0]) + ' בזמן · ' + num(v[0]) + ' הגעות' : 'אין נתונים'}`}; });
  app.innerHTML = `
    ${heroHtml(M.tot, loaded)}
    <div class="panel"><div class="ptitle">התפלגות ההגעות לתחנות</div><p class="pdesc">כל הגעה של אוטובוס לתחנה נספרת פעם אחת, לפי הפער בינה לבין השעה שבלוח הזמנים: כמה הגיעו מוקדם, כמה בזמן, וכמה איחרו ובכמה.</p>${distHtml(M.tot)}</div>
    <div class="cols2">
      <div class="panel"><div class="ptitle">אחוז בזמן, יום אחרי יום</div><p class="pdesc">כמה מההגעות לתחנות היו בזמן בכל יום שנמדד. לחיצה על יום בלוח השנה למעלה פותחת אותו.</p><div class="chart" id="c-trend"></div></div>
      <div class="panel"><div class="ptitle">אחוז בזמן לפי השעה ביום</div><p class="pdesc">לפי השעה שבה האוטובוס היה אמור להגיע לתחנה. ירוק: 80% ומעלה בזמן, צהוב: 65%–80%, כתום: 50%–65%, אדום: פחות מ-50%.</p><div class="chart" id="c-hours"></div></div>
    </div>
    <div class="panel"><div class="ptitle">לפי מפעיל</div><p class="pdesc">אותם מדדים לכל חברת אוטובוסים. לחיצה על כותרת עמודה ממיינת, לחיצה על שם המפעיל מציגה את הקווים שלו.</p><div id="t-ag"></div></div>
    <div class="panel"><div class="ptitle">לפי קו</div><p class="pdesc">כל כיוון של כל קו בנפרד. אפשר לבחור מפעיל, לדרג ("הכי לא מדייקים") או לחפש מספר קו. לחיצה על מספר הקו פותחת פירוט: באיזה קטע לאורך הקו נצבר האיחור.</p>
      <div class="filters" id="lfilters"></div>
      <div id="line-detail"></div><div id="t-lines"></div></div>
    <div class="panel"><div class="ptitle">סוג הרכב מול מה שנקבע לקו</div><p class="pdesc">לכל קו משרד התחבורה קובע גודל רכב: מיניבוס, מידיבוס, אוטובוס בגודל מלא או מפרקי. כאן משווים אותו לרכב שהגיע בפועל בכל נסיעה, לפי מספר הרכב בשידור ומאגר ציי הרכב של המשרד. "רכב קטן יותר" הוא למשל מיניבוס בקו שנקבע לו אוטובוס בגודל מלא.</p><div id="vt-sum"></div><div class="filters" id="vt-filters"></div><div id="t-vt"></div></div>
    <div class="panel"><div class="ptitle">הנסיעות שאיחרו הכי הרבה</div><p class="pdesc">נסיעות בודדות שבאחת התחנות איחרו 20 דקות ומעלה, מהגרועה ביותר. לחיצה על נסיעה מציגה אותה תחנה אחרי תחנה: מתוכנן, בפועל והפער.</p><ul class="worst" id="worst"></ul></div>
    <div class="panel"><div class="ptitle">לפי עיר</div><p class="pdesc">כל ההגעות לתחנות שנמצאות בעיר, מכל הקווים שעוברים בה.</p><div id="t-city"></div></div>`;
  lineChart($('#c-trend'), trend, {color: C.line, min: 0, max: 100, unit: '%'});
  barChart($('#c-hours'), hours, {color: C.line, max: 100, unit: '%'});
  renderAgencies(); renderCities(); renderFilters(); renderLines(); renderWorst(); renderVehicles();
}
let vsort = 'small', vAll = false, vAgency = '';
function renderVehicles() {
  const box = $('#t-vt'); if (!box) return;
  const T = M.tot.vt;
  if (!T[0]) { $('#vt-sum').innerHTML = '<div class="empty">אין עדיין נתוני רכב לתקופה הזו (מחושב מהריצה הבאה)</div>'; $('#vt-filters').innerHTML = ''; box.innerHTML = ''; return; }
  const ags = Object.entries(M.A).filter(([, s]) => s.vt[0]).sort((a, b) => b[1].vt[0] - a[1].vt[0]);
  $('#vt-sum').innerHTML = `<div class="stat-row">
      <div><b>${pct(T[1], T[0])}</b><span>מהנסיעות הגיע רכב קטן ממה שנקבע לקו</span></div>
      <div><b>${pct(T[2], T[0])}</b><span>רכב גדול ממה שנקבע</span></div>
      <div><b>${num(T[0])}</b><span>נסיעות שבהן גם הרכב וגם סוג הקו ידועים (${pct(T[0], M.tot.obs)} מהנסיעות שנצפו)</span></div></div>
    <div class="tblbox"><table><thead><tr><th>מפעיל</th><th>נסיעות עם רכב מזוהה</th><th>רכב קטן יותר</th><th>רכב גדול יותר</th></tr></thead><tbody>${ags.sort((a, b) => b[1].vt[1] / b[1].vt[0] - a[1].vt[1] / a[1].vt[0]).map(([nm, s]) => `<tr><td class="nm">${esc(nm)}</td><td>${num(s.vt[0])}</td><td class="${s.vt[1] / s.vt[0] > .2 ? 'd4' : s.vt[1] / s.vt[0] > .05 ? 'd2' : ''}">${pct(s.vt[1], s.vt[0])}</td><td>${pct(s.vt[2], s.vt[0])}</td></tr>`).join('')}</tbody></table></div>`;
  $('#vt-filters').innerHTML = `<select id="vt-ag"><option value="">כל המפעילים</option>${ags.map(([a]) => `<option value="${esc(a)}"${a === vAgency ? ' selected' : ''}>${esc(a)}</option>`).join('')}</select>` +
    [['small', 'הכי הרבה רכב קטן יותר'], ['large', 'הכי הרבה רכב גדול יותר']].map(([k, t]) => `<button class="fchip${vsort === k ? ' on' : ''}" data-v="${k}">${t}</button>`).join('');
  $('#vt-ag').onchange = e => { vAgency = e.target.value; vAll = false; renderVehicles(); };
  $('#vt-filters').querySelectorAll('.fchip').forEach(b => b.onclick = () => { vsort = b.dataset.v; vAll = false; renderVehicles(); });
  let rows = Object.values(M.Rr).filter(s => s.vt[0] >= 5).map(s => { const l = lineLabel(s.rid); const act = Object.entries(s.vact).sort((a, b) => b[1] - a[1])[0]; return {rid: s.rid, short: l.short, long: l.long, agency: l.agency, plan: s.vplan, act: act ? act[0] : '', n: s.vt[0], small: s.vt[1] / s.vt[0], large: s.vt[2] / s.vt[0]}; });
  if (vAgency) rows = rows.filter(r => r.agency === vAgency);
  const k = vsort === 'small' ? 'small' : 'large';
  rows.sort((a, b) => b[k] - a[k] || b.n - a.n);
  rows = rows.filter(r => r[k] > 0);
  const total = rows.length;
  if (!vAll) rows = rows.slice(0, 40);
  box.innerHTML = rows.length ? `<div class="tblbox" style="margin-top:10px"><table><thead><tr><th>קו</th><th>מסלול</th><th>מפעיל</th><th>נקבע לקו</th><th>הגיע בפועל (הנפוץ)</th><th>נסיעות עם רכב מזוהה</th><th>רכב קטן יותר</th><th>רכב גדול יותר</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td class="nm"><button class="linebtn" data-rid="${esc(r.rid)}">${esc(r.short)}</button></td><td style="font-size:12px;color:var(--mut)">${esc(r.long)}</td><td style="font-size:12px">${esc(r.agency)}</td><td>${esc(vname(r.plan))}</td><td><b>${esc(vname(r.act))}</b></td><td>${num(r.n)}</td><td class="${r.small > .5 ? 'd4' : r.small > .2 ? 'd3' : ''}">${Math.round(r.small * 100)}%</td><td>${Math.round(r.large * 100)}%</td></tr>`).join('') + '</tbody></table></div>' +
    (total > rows.length ? `<button class="more" id="more-v">הצגת כל ${num(total)} הקווים</button>` : '') +
    `<div class="mut" style="margin-top:6px">${num(total)} מסלולים${vAgency ? ' של ' + esc(vAgency) : ''} · רק קווים עם 5 נסיעות לפחות שבהן הרכב מזוהה · רכבי קבלן ורכבים שאינם במאגר המשרד לא נספרים</div>` :
    '<div class="empty">אין קווים כאלה</div>';
  box.querySelectorAll('.linebtn').forEach(b => b.onclick = () => { openLine = b.dataset.rid; renderLineDetail(); $('#line-detail').scrollIntoView({behavior: 'smooth', block: 'start'}); });
  const mb = $('#more-v'); if (mb) mb.onclick = () => { vAll = true; renderVehicles(); };
}
function renderAgencies() {
  const rows = Object.entries(M.A).map(([nm, s]) => { const oT = s.o.reduce((x, y) => x + y, 0); return {nm, sched: s.sched, obs: s.obs, meas: s.meas, on: s.on, oon: oT ? s.o[1] / oT : null, oearly: oT ? s.o[0] / oT : null, avg: s.avg, b4: s.meas ? s.c[4] / s.meas : null}; });
  sortRows(rows, sortA);
  $('#t-ag').innerHTML = `<div class="tblbox"><table id="ta"><thead><tr>${th('מפעיל', 'nm', sortA)}${th('נסיעות בלו״ז', 'sched', sortA)}${th('נצפו', 'obs', sortA)}${th('הגעות נמדדו', 'meas', sortA)}${th('בזמן בתחנות', 'on', sortA)}${th('יציאה בזמן מהמוצא', 'oon', sortA)}${th('יצאו מוקדם', 'oearly', sortA)}${th('איחור ממוצע', 'avg', sortA)}${th('מעל 20 דק׳', 'b4', sortA)}</tr></thead><tbody>` +
    rows.map(r => `<tr><td class="nm"><button class="linebtn" data-ag="${esc(r.nm)}" title="סינון הקווים למפעיל הזה">${esc(r.nm)}</button></td><td>${num(r.sched)}</td><td>${num(r.obs)} <small style="color:var(--dim)">(${pct(r.obs, r.sched)})</small></td><td>${num(r.meas)}</td><td>${onCell(r.on)}</td><td>${r.oon == null ? '—' : Math.round(r.oon * 100) + '%'}</td><td>${r.oearly == null ? '—' : Math.round(r.oearly * 100) + '%'}</td><td class="${dcls(r.avg)}">${r.avg == null ? '—' : fmt1(r.avg) + ' דק׳'}</td><td>${r.b4 == null ? '—' : Math.round(r.b4 * 100) + '%'}</td></tr>`).join('') + '</tbody></table></div>';
  $('#ta thead').onclick = e => { const k = e.target.closest('th') && e.target.closest('th').dataset.k; if (!k) return; sortA = {k, dir: sortA.k === k ? -sortA.dir : (k === 'nm' ? 1 : -1)}; renderAgencies(); };
  $('#t-ag').querySelectorAll('.linebtn').forEach(b => b.onclick = () => { agency = b.dataset.ag; rank = rank || 'worst'; showAllL = false; renderFilters(); renderLines(); renderWorst(); $('#lfilters').scrollIntoView({behavior: 'smooth', block: 'start'}); });
}
function renderCities() {
  const rows = Object.entries(M.Cc).map(([nm, s]) => ({nm, meas: s.meas, on: s.on, early: s.meas ? s.c[0] / s.meas : null, avg: s.avg, b4: s.meas ? s.c[4] / s.meas : null}));
  sortRows(rows, sortC);
  $('#t-city').innerHTML = `<div class="tblbox"><table id="tc"><thead><tr>${th('עיר', 'nm', sortC)}${th('הגעות נמדדו', 'meas', sortC)}${th('בזמן', 'on', sortC)}${th('מוקדם', 'early', sortC)}${th('איחור ממוצע', 'avg', sortC)}${th('מעל 20 דק׳', 'b4', sortC)}</tr></thead><tbody>` +
    rows.map(r => `<tr><td class="nm">${esc(r.nm)}</td><td>${num(r.meas)}</td><td>${onCell(r.on)}</td><td>${r.early == null ? '—' : Math.round(r.early * 100) + '%'}</td><td class="${dcls(r.avg)}">${r.avg == null ? '—' : fmt1(r.avg) + ' דק׳'}</td><td>${r.b4 == null ? '—' : Math.round(r.b4 * 100) + '%'}</td></tr>`).join('') + '</tbody></table></div>';
  $('#tc thead').onclick = e => { const k = e.target.closest('th') && e.target.closest('th').dataset.k; if (!k) return; sortC = {k, dir: sortC.k === k ? -sortC.dir : (k === 'nm' ? 1 : -1)}; renderCities(); };
}
function renderFilters() {
  const ags = Object.keys(M.A).sort((a, b) => M.A[b].meas - M.A[a].meas);
  const chips = [['worst', 'הכי לא מדייקים'], ['best', 'הכי מדייקים'], ['early', 'הכי הרבה יציאות מוקדמות'], ['', 'הכי הרבה נסיעות']];
  $('#lfilters').innerHTML = `<select id="agsel" title="מפעיל"><option value="">כל המפעילים</option>${ags.map(a => `<option value="${esc(a)}"${a === agency ? ' selected' : ''}>${esc(a)}</option>`).join('')}</select>` +
    chips.map(([k, t]) => `<button class="fchip${rank === k ? ' on' : ''}" data-r="${k}">${t}</button>`).join('') +
    `<input class="search" id="lq" placeholder="חיפוש קו: מספר, יעד…" value="${esc(lq)}">`;
  $('#agsel').onchange = e => { agency = e.target.value; showAllL = false; renderLines(); renderWorst(); };
  $('#lfilters').querySelectorAll('.fchip').forEach(b => b.onclick = () => { rank = b.dataset.r; showAllL = false; sortL = rank === 'worst' ? {k: 'on', dir: 1} : rank === 'best' ? {k: 'on', dir: -1} : rank === 'early' ? {k: 'oearly', dir: -1} : {k: 'meas', dir: -1}; renderFilters(); renderLines(); });
  $('#lq').oninput = e => { lq = e.target.value; showAllL = false; renderLines(); };
}
function renderLines() {
  const q = lq.trim();
  let rows = Object.values(M.Rr).map(s => { const l = lineLabel(s.rid); const oT = s.o.reduce((x, y) => x + y, 0); return Object.assign({short: l.short, long: l.long, agency: l.agency, dir: l.dir, on: s.on, early: s.meas ? s.c[0] / s.meas : null, oearly: oT ? s.o[0] / oT : null, avg: s.avg, b4: s.meas ? s.c[4] / s.meas : null}, s); });
  if (agency) rows = rows.filter(r => r.agency === agency);
  if (rank) rows = rows.filter(r => r.obs >= MIN_RIDES);
  if (q) {
    const tok = q.split(/\s+/);
    const numTok = tok.find(t => /^\d/.test(t)), txt = tok.filter(t => t !== numTok).join(' ');
    rows = rows.filter(r => (!numTok || r.short === numTok || (!txt && r.short.startsWith(numTok))) && (!txt || (r.long + ' ' + r.agency).includes(txt)));
  }
  sortRows(rows, sortL);
  const total = rows.length;
  if (!showAllL) rows = rows.slice(0, q ? 60 : 40);
  $('#t-lines').innerHTML = `<div class="tblbox"><table id="tlines"><thead><tr>${th('קו', 'short', sortL)}${th('מסלול', 'long', sortL)}${th('מפעיל', 'agency', sortL)}${th('נסיעות', 'sched', sortL)}${th('נצפו', 'obs', sortL)}${th('הגעות', 'meas', sortL)}${th('בזמן', 'on', sortL)}${th('יצאו מוקדם', 'oearly', sortL)}${th('איחור ממוצע', 'avg', sortL)}${th('מעל 20 דק׳', 'b4', sortL)}</tr></thead><tbody>` +
    rows.map(r => `<tr><td class="nm"><button class="linebtn" data-rid="${esc(r.rid)}">${esc(r.short)}</button></td><td style="font-size:12px;color:var(--mut)">${esc(r.long)}</td><td style="font-size:12px">${esc(r.agency)}</td><td>${num(r.sched)}</td><td>${num(r.obs)}</td><td>${num(r.meas)}</td><td>${onCell(r.on)}</td><td>${r.oearly == null ? '—' : Math.round(r.oearly * 100) + '%'}</td><td class="${dcls(r.avg)}">${r.avg == null ? '—' : fmt1(r.avg) + ' דק׳'}</td><td>${r.b4 == null ? '—' : Math.round(r.b4 * 100) + '%'}</td></tr>`).join('') + '</tbody></table></div>' +
    (total > rows.length ? `<button class="more" id="more-l">הצגת כל ${num(total)} הקווים</button>` : '') +
    `<div class="mut" style="margin-top:6px">${num(total)} מסלולים${agency ? ' של ' + esc(agency) : ''} (כיוון וחלופה נספרים בנפרד)${rank ? ` · בדירוג רק קווים עם לפחות ${MIN_RIDES} נסיעות שנצפו` : ''}</div>`;
  $('#tlines thead').onclick = e => { const k = e.target.closest('th') && e.target.closest('th').dataset.k; if (!k) return; sortL = {k, dir: sortL.k === k ? -sortL.dir : (['short', 'long', 'agency'].includes(k) ? 1 : -1)}; renderLines(); };
  $('#t-lines').querySelectorAll('.linebtn').forEach(b => b.onclick = () => { openLine = b.dataset.rid; renderLineDetail(); $('#line-detail').scrollIntoView({behavior: 'smooth', block: 'start'}); });
  const mb = $('#more-l'); if (mb) mb.onclick = () => { showAllL = true; renderLines(); };
  renderLineDetail();
}
// פרופיל לאורך הקו: מהקבצים היומיים של התחנות (נטענים בפעם הראשונה), מאוחד על פני התקופה
function loadProfiles(days) {
  const need = days.filter(d => !stopCache[d]);
  const p = [];
  if (!NAMES) p.push(load(DATA + 'stops.json').then(j => { NAMES = j; }).catch(() => { NAMES = {}; }));
  need.forEach(d => p.push(load(DATA + 'days/' + d + '.stops.json').then(j => { stopCache[d] = j; }).catch(() => { stopCache[d] = {}; })));
  return Promise.all(p);
}
function profileOf(rid, days) {
  const acc = new Map();
  for (const d of days) {
    const rows = (stopCache[d] || {})[rid];
    if (!rows) continue;
    rows.forEach(([code, n, avg10, on], i) => { const x = acc.get(code) || {code, n: 0, sum: 0, on: 0, i}; x.n += n; x.sum += avg10 / 10 * n; x.on += on; acc.set(code, x); });
  }
  return [...acc.values()].sort((a, b) => a.i - b.i).map(x => ({code: x.code, n: x.n, avg: x.sum / x.n, on: x.on / x.n}));
}
function renderLineDetail() {
  const el = $('#line-detail'); if (!el) return;
  const s = openLine && M.Rr[openLine];
  if (!s) { el.innerHTML = ''; return; }
  const l = lineLabel(openLine);
  const hours = Array.from({length: 24}, (_, h) => { const v = s.hours[h]; const sh = v && v[0] >= 5 ? v[1] / v[0] : null; return {x: String(h).padStart(2, '0'), y: sh == null ? null : Math.round(sh * 100), color: hourColor(sh), tip: `<b>${String(h).padStart(2, '0')}:00</b><br>${v && v[0] ? pct(v[1], v[0]) + ' בזמן · ' + num(v[0]) + ' הגעות' : 'אין נתונים'}`}; });
  const oT = s.o.reduce((a, b) => a + b, 0);
  el.innerHTML = `<div class="ldetail">
    <div class="lhead"><span class="badge">${esc(l.short)}</span><span class="ldest">${esc(l.long)} · ${esc(l.agency)}${l.dir ? ' · כיוון ' + esc(l.dir) : ''}${l.alt && l.alt !== '#' && l.alt !== '0' ? ' · חלופה ' + esc(l.alt) : ''}</span><button class="closebtn" id="close-l">✕ סגירה</button></div>
    <div class="stat-row">
      <div><b>${s.meas ? pct(s.c[1], s.meas) : '—'}</b><span>בזמן, בכל התחנות</span></div>
      <div><b>${oT ? pct(s.o[1], oT) : '—'}</b><span>יציאה בזמן מהמוצא</span></div>
      <div><b>${oT ? pct(s.o[0], oT) : '—'}</b><span>יציאה מוקדמת מהמוצא</span></div>
      <div><b>${s.avg == null ? '—' : fmt1(s.avg)}<i>דק׳</i></b><span>איחור ממוצע${s.s && s.s[2] != null ? ` · 90% עד ${fmt1(s.s[2])}` : ''}</span></div>
      <div><b>${num(s.obs)}</b><span>נסיעות נצפו מתוך ${num(s.sched)}</span></div>
    </div>
    ${s.vt[0] ? `<p class="pdesc">גודל הרכב: נקבע לקו <b>${esc(vname(s.vplan))}</b>. ב-${num(s.vt[0])} נסיעות הרכב מזוהה: ${Object.entries(s.vact).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${esc(vname(t))} ${pct(n, s.vt[0])}`).join(', ')}${s.vt[1] ? ` · <b class="d4">רכב קטן ממה שנקבע ב-${pct(s.vt[1], s.vt[0])}</b>` : ''}${s.vt[2] ? ` · רכב גדול ממה שנקבע ב-${pct(s.vt[2], s.vt[0])}` : ''}.</p>` : ''}
    ${distHtml(s)}
    <div class="cols2" style="margin-top:10px"><div><div class="ptitle">אחוז בזמן לפי השעה ביום</div><p class="pdesc">לפי השעה שבה האוטובוס היה אמור להגיע לתחנה.</p><div class="chart" id="c-lh"></div></div>
    <div><div class="ptitle">האיחור הממוצע לאורך הקו</div><p class="pdesc">עמודה לכל תחנה, מהמוצא (ימין) ליעד. איפה שהעמודות קופצות, שם הקו מאבד זמן.</p><div class="chart" id="c-lp"><div class="empty">טוען…</div></div></div></div>
    <div class="ptitle" style="margin-top:12px">תחנה אחרי תחנה</div><p class="pdesc">לכל תחנה בקו: כמה הגעות נמדדו, האיחור הממוצע, ואיזה חלק מההגעות היה בזמן.</p><div id="lprof"><div class="empty">טוען…</div></div>
  </div>`;
  barChart($('#c-lh'), hours, {color: C.line, max: 100, unit: '%', h: 160});
  $('#close-l').onclick = () => { openLine = null; el.innerHTML = ''; };
  const rid = openLine, days = M.days;
  loadProfiles(days).then(() => {
    if (openLine !== rid) return;
    const prof = profileOf(rid, days);
    const box = $('#lprof'), ch = $('#c-lp');
    if (!box) return;
    if (!prof.length) { box.innerHTML = '<div class="empty">אין עדיין פירוט לתחנות ליום הזה (מחושב מהריצה הבאה)</div>'; ch.innerHTML = '<div class="empty">אין נתונים</div>'; return; }
    const mx = Math.max(10, Math.ceil(Math.max(...prof.map(p => p.avg)) / 5) * 5);
    barChart(ch, prof.map((p, i) => ({x: String(i + 1), y: Math.max(0, p.avg), color: BCOL[catOf(p.avg)], tip: `<b>${esc(stopName(p.code))}</b><br>איחור ממוצע ${delayTxt(p.avg)} דק׳ · ${pct(p.on * p.n, p.n)} בזמן · ${num(p.n)} הגעות`})), {color: C.line, max: mx, unit: '׳', h: 160});
    box.innerHTML = `<div class="prof"><div class="ps h"><span></span><span>תחנה</span><span>הגעות</span><span>איחור ממוצע</span><span>בזמן</span></div>` +
      prof.map((p, i) => `<div class="ps"><span class="dot s${catOf(p.avg)}"></span><span class="rn">${esc(stopName(p.code))} <small>${esc(p.code)}${i === 0 ? ' · מוצא' : i === prof.length - 1 ? ' · יעד' : ''}</small></span><span class="num">${num(p.n)}</span><span class="num ${dcls(p.avg)}">${delayTxt(p.avg)} דק׳</span><span class="num">${Math.round(p.on * 100)}%</span></div>`).join('') + '</div>' +
      '<div class="mut" style="margin-top:6px">בתחנת המוצא: יציאה מול השעה שבלו״ז. בשאר התחנות: הגעה. קפיצה חדה בין שתי תחנות סמוכות היא הקטע שבו הקו מאבד זמן.</div>';
  });
}
function renderWorst() {
  let rows = M.worst;
  if (agency) rows = rows.filter(w => lineLabel(w[1]).agency === agency);
  rows = rows.slice(0, 40);
  $('#worst').innerHTML = rows.length ? rows.map((w, i) => { const [d, rid, , dl, stop, sched, ps] = w; const l = lineLabel(rid); return `<li data-i="${i}" tabindex="0"><span class="badge">${esc(l.short)}</span><span class="dl">+${num(dl)} דק׳</span><span>${esc(l.long)}</span><small style="color:var(--dim)">${esc(l.agency)} · יציאה מתוכננת ${hhmm(sched)}${period !== 'day' ? ' · ' + shortDate(d) : ''} · האיחור הגדול נמדד ב${esc(stop)}${ps && ps.length ? '' : ' · אין פירוט תחנות'}</small></li>`; }).join('') : `<li>אין נסיעות עם איחור מעל 20 דקות${agency ? ' אצל ' + esc(agency) : ''}</li>`;
  $('#worst').querySelectorAll('li[data-i]').forEach(li => { const open = () => openRide(rows[+li.dataset.i]); li.onclick = open; li.onkeydown = e => { if (e.key === 'Enter') open(); }; });
}
function openRide(w) {
  const [d, rid, trip, dl, stop, sched, ps] = w;
  const l = lineLabel(rid);
  const ovl = document.createElement('div'); ovl.className = 'ovl';
  const body = () => !ps || !ps.length ? '<div class="empty">אין פירוט תחנות לנסיעה הזו</div>' :
    `<div class="route"><div class="rs h"><span></span><span>תחנה</span><span>מתוכנן</span><span>בפועל</span><span>איחור</span></div>` +
    ps.map((x, i) => { const [code, sc, act] = x; const dm = (act - sc) / 60; const b = catOf(dm); const first = i === 0;
      return `<div class="rs"><span class="dot s${b}"></span><span class="rn">${esc(stopName(code))}${first ? ' <small>מוצא · יציאה</small>' : i === ps.length - 1 ? ' <small>אחרונה שנמדדה</small>' : ''}</span><span class="rt">${hhmm(sc)}</span><span class="ra">${hhmm(act)}</span><span class="rd ${dcls(dm)}">${delayTxt(dm)} דק׳</span></div>`; }).join('') + '</div>';
  // קישור לציר הזמן של דאטאבוס: מפעיל + מספר קו + זמן היציאה (שם בוחרים כיוון ונסיעה).
  // מזהה הנסיעה של משרד התחבורה לא מוכר להם (שלמה 06.09: "Route with id … not found").
  const [dy, dm, dd] = d.split('-').map(Number);
  const ts = new Date(dy, dm - 1, dd, 0, 0, sched || 0).getTime();
  const dbLink = `https://open-bus-map-search.hasadna.org.il/timeline?${l.aid ? `operatorId=${encodeURIComponent(l.aid)}&` : ''}lineNumber=${encodeURIComponent(l.short)}&timestamp=${ts}`;
  ovl.innerHTML = `<div class="modal" role="dialog" aria-modal="true"><div class="mhead"><h2>קו ${esc(l.short)}</h2><span class="st s4">+${num(dl)} דק׳ לכל היותר</span><button class="x" aria-label="סגירה">✕</button></div>
    <div class="msub">${esc(l.long)} · ${esc(l.agency)} · ${heDate(d)} · יציאה מתוכננת ${hhmm(sched)} · <a href="${dbLink}" target="_blank" rel="noopener">הקו בדאטאבוס ↗</a> <small style="color:var(--dim)">(שם בוחרים את הכיוון ואת הנסיעה של ${hhmm(sched)})</small></div>
    <div id="ride-body">${NAMES ? body() : '<div class="empty">טוען שמות תחנות…</div>'}</div>
    <div class="note">"בפועל" בתחנת המוצא הוא רגע היציאה, ובשאר התחנות רגע ההגעה (דיוק של כחצי דקה). תחנות שהאוטובוס לא שידר לידן לא מופיעות.</div></div>`;
  document.body.appendChild(ovl);
  const close = () => { ovl.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  $('.x', ovl).onclick = close; ovl.onclick = e => { if (e.target === ovl) close(); };
  if (!NAMES) loadProfiles([]).then(() => { const b = $('#ride-body', ovl); if (b) b.innerHTML = body(); });
}

const METHOD = `<div class="ptitle">איך זה נמדד</div>
<p><b>בקצרה:</b> משרד התחבורה משדר כל דקה את המיקום של כל אוטובוס בארץ, ולצידו את התחנה הבאה שלו ואת המרחק אליה. דאטאבוס (הסדנא לידע ציבורי) שומרים את השידורים האלה, ואנחנו מורידים את השמירה של כל יום, מצמידים כל נסיעה ללוח הזמנים שמשרד התחבורה פרסם לאותו יום, ובודקים בכל תחנה: מתי האוטובוס היה אמור להגיע, ומתי הגיע.</p>
<ul>
<li><b>מתי "הגיע":</b> כשהמרחק לתחנה הבאה יורד לאפס, או כשהתחנה הבאה מתחלפת בזו שאחריה. בין שתי דגימות (דקה) הזמן משוערך לפי המרחק, כך שהדיוק הוא כחצי דקה. התחנה עצמה נקבעת לפי המק״ט ששודר, לא לפי המספר הסידורי.</li>
<li><b>תחנת המוצא:</b> שם נמדדת היציאה, לא ההגעה. משרד התחבורה מציג את הרכב "בתחנה" חמש דקות לפני היציאה גם כשהוא עומד ברציף, ולכן היציאה נקבעת רק אחרי שראינו אותו עומד באמת (שתי דגימות לפחות) ואז זז. אם השידור נקטע בין העמידה לנסיעה, היציאה משוערכת מהמיקום הראשון בדרך לפי מהירות הלו״ז. "יצא מוקדם" הוא אוטובוס שעזב את המוצא יותר מ-2 דקות לפני השעה שבלו״ז.</li>
<li><b>ההצמדה ללו״ז:</b> לפי מספר המסלול ושעת היציאה המתוכננת שהאוטובוס עצמו משדר, מול קובץ ה-GTFS של אותו יום. כשכמה רכבים משדרים את אותה נסיעה (תגבור), נמדד השידור הארוך.</li>
<li><b>קטגוריות:</b> מוקדם = יותר מ-2 דקות לפני הלו״ז (בעיה לנוסע שמגיע בזמן); בזמן = עד 5 דקות איחור; ואז 5–10, 10–20, ומעל 20 דקות. "בזמן" נספר לכל הגעה לתחנה, לא לנסיעה.</li>
<li><b>מה לא נספר:</b> נסיעות שלא שידרו בכלל (מופיעות כ"לא נצפו"); נסיעה ששודרה יותר משעה וחצי רחוק מהלו״ז שלה (כנראה רכב שהוסב לנסיעה אחרת); מדידה בודדת שקופצת ב-20 דקות משתי שכנותיה (תקלת שיערוך); רכבת ורכבת קלה; ויום שבו נצפו פחות מ-30% מהנסיעות (שידור חלקי, מוצג בנפרד). נסיעות ששודרו ואין להן נסיעה בלו״ז (תגבורים) נספרות בנפרד.</li>
<li><b>העומס על דאטאבוס:</b> אפס קריאות ל-API. הקבצים היומיים יורדים מאחסון S3 שנועד לזה, פעם אחת בלילה.</li>
</ul>`;

function init() {
  $('#method').innerHTML = METHOD;
  Promise.all([load(DATA + 'index.json'), load(DATA + 'routes.json').catch(() => ({}))]).then(([idx, cat]) => {
    IDX = idx; CAT = cat || {};
    DAYS = (idx.days || []).map(d => typeof d === 'string' ? {d} : d).filter(d => d.d);
    if (!DAYS.length) { $('#app').innerHTML = '<div class="msg">עדיין אין ימים מחושבים.</div>'; $('#sub').textContent = ''; return; }
    const h = decodeURIComponent((location.hash || '').slice(1));
    dayD = DAYS.some(d => d.d === h) ? h : DAYS[DAYS.length - 1].d;
    period = 'day';
    render();
  }).catch(e => { $('#app').innerHTML = `<div class="msg">הנתונים לא נטענו (${esc(e.message)})</div>`; });
}
init();
})();
