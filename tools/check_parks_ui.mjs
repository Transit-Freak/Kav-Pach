// בדיקת עשן לאתר נגישות אזורי תעשייה — נועדה לרוץ אחרי כל שינוי עיצוב.
//
// נכתבה כשה-CSS הופרד ל-style.css כדי שמעצב גרפי יוכל לעבוד על המראה
// בלי לגעת בלוגיקה (ראו parks/DESIGN.md). הבדיקה עונה על השאלה האחת
// שמעניינת אחרי שינוי עיצוב: הפונקציונליות עדיין חיה?
//
// בודקת: הדף עולה בלי חריגות · הטבלה מתמלאת · מיון בלחיצת כותרת ·
// חיפוש מסנן · לחיצה על שורה פותחת אזור · חזרה · פאנל שכבות נפתח.
import fs from 'fs';
import http from 'http';
import path from 'path';
import { createRequire } from 'module';

const ROOT = process.cwd();
const require_ = createRequire(path.join(process.env.PW_MODULES || ROOT, 'noop.js'));
const { chromium } = require_('playwright-core');
const fail = (msg) => { console.error('❌', msg); process.exit(1); };

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.png': 'image/png' };
const srv = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
  try {
    const p = path.join(ROOT, 'parks', rel);
    const body = fs.readFileSync(p);
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
const errs = [];
page.on('pageerror', (e) => errs.push(e.message.slice(0, 120)));
// בלי רשת חיצונית: ללפלט סטאב מלא, לגופנים תשובה ריקה
await page.route('**://unpkg.com/**', (r) => {
  if (r.request().url().endsWith('.css')) return r.fulfill({ contentType: 'text/css', body: '' });
  return r.fulfill({ contentType: 'text/javascript', body: `
    (function(){
      // סטאב Proxy: כל שרשרת קריאות/גישות מחזירה את עצמה — עמיד לכל API
      var P = new Proxy(function(){}, {
        get: function(t, k){
          if (k === Symbol.toPrimitive || k === 'toString') return function(){ return ''; };
          if (k === 'isValid') return function(){ return true; };
          if (k === 'getCenter') return function(){ return { lat: 32, lng: 35 }; };
          if (k === 'getZoom') return function(){ return 8; };
          return P;
        },
        apply: function(){ return P; },
        construct: function(){ return P; }
      });
      window.L = P;
    })();` });
});
await page.route('**://fonts.g**/**', (r) => r.fulfill({ contentType: 'text/css', body: '' }));

page.on('console', (m) => { if (m.type() === 'error' && !m.text().includes('integrity') && !m.text().includes('status of 404')) errs.push('console: ' + m.text().slice(0, 120)); });
// socio*.json הם קבצים אופציונליים (הקוד עוטף אותם ב-catch); חתימות
// SRI נכשלות בכוונה כשהסטאב מחליף את קובצי ה-CDN — שניהם אינם תקלה
page.on('response', (r) => { if (r.status() >= 400 && !/socio[^/]*\.json/.test(r.url())) errs.push('HTTP ' + r.status() + ': ' + r.url().slice(-70)); });
await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
// מסך הפתיחה הוא מפת החום — הטבלה מתמלאת ברקע ומוסתרת, לכן ההמתנה
// היא ל-attached ולא ל-visible, ואז עוברים לרשימה בכפתור החזרה
await page.waitForSelector('#tbl tbody tr', { state: 'attached', timeout: 30000 })
  .catch(async () => { console.log('שגיאות:', errs.slice(0,5)); fail('הטבלה לא התמלאה — הדף לא עלה כמו שצריך'); });
// מסך הפתיחה (מפת החום) תלוי בציור מפה אמיתי — בסביבת הבדיקה עוברים
// ישירות לתצוגת הטבלה דרך אותה פונקציה שכפתור החזרה מפעיל
await page.evaluate(() => showTable());
await page.waitForSelector('#tblview', { state: 'visible', timeout: 10000 })
  .catch(() => fail('המעבר לתצוגת הרשימה לא עבד'));
const rows = await page.locator('#tbl tbody tr').count();

// מיון: לחיצה על כותרת משנה את סדר השורות
const firstBefore = await page.locator('#tbl tbody tr').first().textContent();
await page.locator('#tbl th').nth(2).click();
await page.waitForTimeout(400);
await page.locator('#tbl th').nth(2).click();
await page.waitForTimeout(400);
const firstAfter = await page.locator('#tbl tbody tr').first().textContent();
const sortOk = firstBefore !== firstAfter;

// חיפוש מסנן
const q = await page.locator('#q');
await q.fill('חולון');
await page.waitForTimeout(500);
const filtered = await page.locator('#tbl tbody tr').count();
await q.fill('');
await page.waitForTimeout(400);

// פתיחת אזור: לחיצה על שורה מציגה את הפאנל, וכפתור חזרה מחזיר
await page.locator('#tbl tbody tr').first().click();
await page.waitForSelector('#wrap', { state: 'visible', timeout: 15000 })
  .catch(() => fail('לחיצה על שורה לא פתחה את תצוגת האזור'));
await page.locator('#backbtn').click();
await page.waitForSelector('#tblview', { state: 'visible', timeout: 10000 })
  .catch(() => fail('כפתור החזרה לא החזיר לטבלה'));

// פאנל שכבות
await page.locator('#layersbtn').click();
const panelOpen = await page.locator('#layerspanel').isVisible().catch(() => false);

console.log(`✓ טבלה: ${rows} שורות · מיון: ${sortOk ? 'עובד' : 'לא שינה סדר!'} · חיפוש "חולון": ${filtered} שורות · אזור נפתח ונסגר · פאנל שכבות: ${panelOpen ? 'נפתח' : 'לא נפתח!'}`);
if (!sortOk) fail('המיון לא שינה את סדר השורות');
if (!(filtered > 0 && filtered < rows)) fail(`החיפוש לא סינן (לפני: ${rows}, אחרי: ${filtered})`);
if (!panelOpen) fail('פאנל השכבות לא נפתח');
if (errs.length) fail('חריגות JS: ' + errs.slice(0, 3).join(' | '));
console.log('✅ בדיקת אתר אזורי התעשייה עברה — הפונקציונליות שלמה');
await browser.close();
srv.close();
process.exit(0);
