// סריקת כל עמודי הקווים באתר — איתור עמוד שקורס.
//
// נולדה מבאג אמיתי (08.2026): codeOf שמר על הגבול התחתון של אינדקס
// הגרסאות אבל לא על העליון, וקו שקיבל תחנות בגרסה האחרונה הפיל את כל
// העמוד. הקריסה נראתה כאילו "חסר לקו מפצל חלופות" — בפועל הרינדור נעצר
// באמצע וכל מה שאחריו לא נוצר. בדיקת האתר הרגילה פותחת עמוד קו אחד
// מכל קטגוריה, ולכן היא יכולה לפספס קו יחיד מתוך 13,000.
//
// הבדיקה עוברת קו-קו דרך ה-hash בתוך אותו עמוד. טעינה מחדש עולה ~25
// שניות (פענוח האינדקס וכל הנתונים בכל פעם), וניווט פנימי עשיריות
// שנייה — 13,189 עמודים ב-13 דקות במקום ימים.
//
// כישלון = חריגת JS בעמוד, או שהעמוד לא הציג את הקו המבוקש.
//
// ONLY=rd1,rd2   בדיקת קווים מסוימים בלבד
// LIMIT=n        n הקווים הראשונים
// יציאה 1 אם נמצאה תקלה.
import fs from 'fs';
import http from 'http';
import path from 'path';
import { createRequire } from 'module';

const ROOT = process.cwd();
const LH = path.join(ROOT, 'line-history');
const require_ = createRequire(path.join(process.env.PW_MODULES || ROOT, 'noop.js'));
const { chromium } = require_('playwright-core');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.jsx': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };

const srv = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
  const p = fs.existsSync(path.join(LH, rel)) ? path.join(LH, rel) : path.join(ROOT, rel);
  try {
    let body = fs.readFileSync(p);
    // בלי רשת: מסירים חתימות SRI כדי שאפשר יהיה להגיש את הספריות מקומית
    if (p.endsWith('index.html')) body = body.toString().replace(/\s(integrity|crossorigin)="[^"]*"/g, '');
    res.writeHead(200, { 'content-type': MIME[path.extname(p)] || 'application/octet-stream' });
    res.end(body);
  } catch { res.writeHead(404); res.end(); }
});
await new Promise((ok) => srv.listen(0, '127.0.0.1', ok));
const port = srv.address().port;

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/opt/pw-browsers/chromium',
  args: ['--no-sandbox'],
});
const page = await browser.newPage();
// ספריות ה-CDN מ-vendor/ המקומי; לאפלט סטאב, כי הבדיקה רצה בלי רשת
await page.route('**://unpkg.com/**', (route) => {
  const u = route.request().url();
  const local = u.includes('react-dom') ? 'vendor/react-dom.development.js'
    : u.includes('react') ? 'vendor/react.development.js'
    : u.includes('babel') ? 'vendor/babel.min.js' : null;
  if (local) return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, local)) });
  if (u.endsWith('.css')) return route.fulfill({ contentType: 'text/css', body: '' });
  return route.fulfill({ contentType: 'text/javascript', body: `
    (function(){ var chain=function(){return obj;},
      obj={addTo:chain,bindPopup:chain,fitBounds:chain,remove:chain,setView:chain,on:chain,
           addLayer:chain,removeLayer:chain,invalidateSize:chain,extend:chain,pad:chain,
           getBounds:chain,setLatLng:chain,openPopup:chain,bindTooltip:chain,
           isValid:function(){return true;}};
      window.L={map:chain,tileLayer:chain,polyline:chain,circleMarker:chain,latLngBounds:chain,
                marker:chain,layerGroup:chain,divIcon:chain,control:{scale:chain}};})();` });
});
await page.route('**://fonts.googleapis.com/**', (r) => r.fulfill({ contentType: 'text/css', body: '' }));
await page.route('**://fonts.gstatic.com/**', (r) => r.fulfill({ body: '' }));

const all = JSON.parse(fs.readFileSync(path.join(LH, 'data/lines.json'), 'utf8')).lines.map((l) => l.rd);
const ONLY = (process.env.ONLY || '').split(',').filter(Boolean);
const LIMIT = Number(process.env.LIMIT || 0);
const list = ONLY.length ? ONLY : (LIMIT ? all.slice(0, LIMIT) : all);
console.log(`עמודי קווים לבדיקה: ${list.length.toLocaleString()}`);

const bad = new Map();
let cur = null;
page.on('pageerror', (e) => { if (cur && !bad.has(cur)) bad.set(cur, e.message.slice(0, 90)); });

const ready = () => page.waitForFunction(
  () => document.body.innerText.includes('וריאנטים'), { timeout: 60000 }).catch(() => {});
await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
await ready();

const START = Date.now();
for (let i = 0; i < list.length; i++) {
  cur = list[i];
  await page.evaluate((h) => { location.hash = h; }, encodeURIComponent(cur));
  // שורת הפרטים חייבת לשאת את המק"ט של הקו המבוקש — כך "נפתח" אינו
  // מסתפק בעמוד הקודם שנשאר על המסך.
  // הסתמכות על .empty כאישור הייתה מרוקנת את הבדיקה: מסך הפתיחה מציג
  // .empty בזמן טעינת השינויים האחרונים, ולכן כל קו "עבר" מיד. רק
  // הודעת "לא נמצאו נתונים לוריאנט הזה" נחשבת — והיא תקלה בפני עצמה.
  const res = await page.waitForFunction((rd) => {
    const f = document.querySelector('.facts');
    if (f && f.textContent.includes(rd)) return 'ok';
    const e = [...document.querySelectorAll('.empty')]
      .find((x) => x.textContent.includes('לא נמצאו נתונים לוריאנט'));
    return e ? 'missing' : false;
  }, cur, { timeout: 15000 }).then((h) => h.jsonValue()).catch(() => null);
  if (res === null) { if (!bad.has(cur)) bad.set(cur, 'העמוד לא נפתח (timeout)'); }
  else if (res === 'missing') { if (!bad.has(cur)) bad.set(cur, 'אין נתונים לוריאנט'); }
  if (bad.has(cur)) {   // אחרי חריגה עץ ה-React שבור — טוענים מחדש
    await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
    await ready();
  }
  if ((i + 1) % 2000 === 0)
    console.log(`  ${i + 1}/${list.length} · תקלות: ${bad.size} · ${((Date.now() - START) / 6e4).toFixed(1)} דק'`);
}

const mins = ((Date.now() - START) / 6e4).toFixed(1);
if (bad.size) {
  console.error(`❌ ${bad.size} מתוך ${list.length} עמודי קווים נכשלו (${mins} דק')`);
  for (const [rd, msg] of bad) console.error(`   ${rd}: ${msg}`);
} else {
  console.log(`✅ כל ${list.length.toLocaleString()} עמודי הקווים נפתחים (${mins} דק')`);
}
await browser.close();
srv.close();
process.exit(bad.size ? 1 : 0);
