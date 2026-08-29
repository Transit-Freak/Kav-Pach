// הצייד — סיור יומי באתר החי של הקו בזמן, כמו משתמש אמיתי.
//
// דרישת שלמה: "אני לא אמור לדווח לך על כל תקלה — אתה אמור לצוד כל דבר".
// בכל ריצה: מדגם אקראי של קווים מהאתר המפורסם (לא מקומי — מה שהגולשים
// באמת מקבלים), ובכל קו: טעינת העמוד, שגיאות JS, מפה שלא מציירת כלום,
// רשומות ➕/➖ בלי מק"ט, וכפתור "השווה" שלא נפתח. הממצאים נכתבים
// ל-data/ui-hunt.json ומוצגים בפאנל התקלות.
import fs from 'fs';
import { chromium } from 'playwright';

const BASE = process.env.HUNT_BASE || 'https://transit-freak.github.io/kav-bochan/line-history/';
const N = parseInt(process.env.HUNT_N || '30', 10);

const idx = await (await fetch(BASE + 'data/lines.json?cb=' + Date.now())).json();
const lines = idx.lines || [];
const withChanges = lines.filter((l) => (l.ks || []).length > 1);
const pick = (arr, n) => {
  const out = [];
  const used = new Set();
  while (out.length < Math.min(n, arr.length)) {
    const i = Math.floor(Math.random() * arr.length);
    if (!used.has(i)) { used.add(i); out.push(arr[i]); }
  }
  return out;
};
const sample = [...pick(withChanges, N - 5), ...pick(lines, 5)];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 950 } });
const issues = [];
let errs = [];
page.on('pageerror', (e) => errs.push(String(e.message || e).slice(0, 160)));

let checked = 0;
for (const l of sample) {
  const rd = l.rd;
  errs = [];
  try {
    await page.goto(BASE + '#' + encodeURIComponent(rd), { waitUntil: 'domcontentloaded', timeout: 45000 });
    const ok = await page.waitForSelector('.evsrc, .timeline, .tl', { timeout: 30000 }).catch(() => null);
    if (!ok) { issues.push({ rd, type: 'page_load', detail: 'ציר הזמן לא נטען תוך 30 שניות' }); continue; }
    await page.waitForTimeout(3500);
    checked++;
    if (errs.length) issues.push({ rd, type: 'js_error', detail: errs[0] });
    const r = await page.evaluate(() => {
      const paths = document.querySelectorAll('.leaflet-overlay-pane path').length;
      const markers = document.querySelectorAll('.leaflet-overlay-pane path, .leaflet-marker-pane *').length;
      const hasMap = !!document.querySelector('.map');
      // רשומות ➕/➖ בלי מק"ט: פריט ברשימה שאין בו סוגריים עם מספר
      let noCode = 0;
      let sampleTxt = '';
      document.querySelectorAll('.sub div').forEach((d) => {
        const t = d.textContent || '';
        if (!t.startsWith('➕') && !t.startsWith('➖')) return;
        t.replace(/^[➕➖][^:]*:/, '').split(',').forEach((item) => {
          const s = item.trim();
          if (s && !/\(\d{2,}\)/.test(s) && !/×\d+$/.test(s)) { noCode++; if (!sampleTxt) sampleTxt = s.slice(0, 40); }
        });
      });
      return { paths, markers, hasMap, noCode, sampleTxt };
    });
    if (r.hasMap && r.paths === 0 && r.markers === 0) {
      issues.push({ rd, type: 'empty_map', detail: 'המפה לא מציירת מסלול ולא תחנות' });
    }
    if (r.noCode > 0) {
      issues.push({ rd, type: 'no_code', detail: `${r.noCode} רשומות בלי מק"ט (למשל: ${r.sampleTxt})` });
    }
    // "השווה" על כרטיס אקראי — חייב לפתוח את מצב ההשוואה
    const btns = page.locator('text=השווה');
    const cnt = await btns.count();
    if (cnt > 1) {
      errs = [];
      await btns.nth(1 + Math.floor(Math.random() * (cnt - 1))).click().catch(() => {});
      await page.waitForTimeout(2200);
      const cmpOpen = await page.evaluate(() => document.body.innerText.includes('השוואה שביקשת'));
      if (!cmpOpen) issues.push({ rd, type: 'compare_broken', detail: 'לחיצה על "השווה" לא פתחה השוואה' });
      if (errs.length) issues.push({ rd, type: 'js_error_compare', detail: errs[0] });
    }
  } catch (e) {
    issues.push({ rd, type: 'crash', detail: String(e.message || e).slice(0, 160) });
  }
}
await browser.close();

const out = {
  generated: new Date().toISOString().slice(0, 16).replace('T', ' '),
  base: BASE, checked, sampled: sample.length,
  issues,
};
fs.writeFileSync('line-history/data/ui-hunt.json', JSON.stringify(out));
console.log(`הצייד סיים: ${checked} עמודים נבדקו · ${issues.length} ממצאים`);
for (const i of issues) console.log(` · ${i.rd} — ${i.type}: ${i.detail}`);
process.exit(0);
