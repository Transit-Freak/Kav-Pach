// בדיקת עשן ל"הקו בזמן" — נולדה עם תיקוני פאנל שלב ב.
//
// בודקת: הדף עולה בלי חריגות · "מה השתנה לאחרונה" מוצג · האינדקס הכבד
// לא חוסם את המסך (סעיף 12) · "שינויים לפי יום" נפתח על החודש הנוכחי
// ולא על מרץ 2017 (סעיף 1) · חיפוש עם גרשיים מוצא תוצאות (סעיף 3) ·
// טאב התחנות עולה. הכל מוגש מקומית: React מ-vendor, לפלט בסטאב Proxy.
import fs from 'fs';
import http from 'http';
import path from 'path';
import { createRequire } from 'module';

const ROOT = process.cwd();
const require_ = createRequire(path.join(process.env.PW_MODULES || ROOT, 'noop.js'));
const { chromium } = require_('playwright-core');
const fail = (msg) => { console.error('❌', msg); process.exit(1); };

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.jsx': 'text/javascript',
  '.css': 'text/css', '.json': 'application/json' };
const srv = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
  try {
    const p = path.join(ROOT, rel.startsWith('line-history') || rel.startsWith('magihim') || rel.startsWith('vendor') ? '' : 'line-history', rel);
    let body = fs.readFileSync(p);
    if (p.endsWith('index.html')) body = Buffer.from(body.toString().replace(/\s(integrity|crossorigin)="[^"]*"/g, ''));
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
page.on('pageerror', (e) => errs.push(e.message.slice(0, 140)));
await page.route('**://unpkg.com/**', (r) => {
  const u = r.request().url();
  if (u.endsWith('.css')) return r.fulfill({ contentType: 'text/css', body: '' });
  if (u.includes('react-dom')) return r.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, 'vendor/react-dom.development.js')) });
  if (u.includes('react')) return r.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, 'vendor/react.development.js')) });
  if (u.includes('babel')) return r.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, 'vendor/babel.min.js')) });
  return r.fulfill({ contentType: 'text/javascript', body: `(function(){var P=new Proxy(function(){},{get:function(t,k){if(k===Symbol.toPrimitive||k==='toString')return function(){return ''};return P;},apply:function(){return P;},construct:function(){return P;}});window.L=P;})();` });
});
await page.route('**://fonts.g**/**', (r) => r.fulfill({ contentType: 'text/css', body: '' }));
await page.route('**://*.tile.openstreetmap.org/**', (r) => r.fulfill({ body: Buffer.from([]) }));

await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
// המסך חייב להופיע גם לפני שהאינדקס הכבד הגיע — ואחריו הפיד האחרון
await page.waitForSelector('.tabs', { timeout: 120000 }).catch(() => fail('הטאבים לא הופיעו — האתר עדיין חסום על האינדקס'));
await page.waitForSelector('.recent .dayhead', { timeout: 120000 }).catch(() => fail('"מה השתנה לאחרונה" לא נטען'));
const firstDay = await page.locator('.recent .dayhead').first().textContent();
console.log('✓ מסך הבית עלה · היום הראשון בפיד:', firstDay.split('·')[0].trim());

// חיפוש עם גרשיים (סעיף 3): בנתונים כתוב רשל''צ בשני גרשים
await page.locator('.search').first().fill('רשל"צ');
await page.waitForTimeout(1200);
const hits = await page.locator('.llist .lrow').count();
console.log('✓ חיפוש רשל"צ (גרשיים):', hits, 'תוצאות');
if (!hits) fail('נירמול הגרשיים לא עובד — אפס תוצאות על רשל"צ');
await page.locator('.search').first().fill('');
await page.waitForTimeout(600);

// "שינויים לפי יום" נפתח על החודש הנוכחי ולא על מרץ 2017 (סעיף 1)
await page.locator('button:has-text("שינויים לפי יום")').first().click();
await page.waitForSelector('.dayhead', { timeout: 60000 }).catch(() => fail('הפיד היומי לא נטען'));
const onChip = await page.locator('.months .mchip.on').first().textContent();
if (onChip.includes('2017')) fail('הפיד היומי עדיין נפתח על 2017 (צ׳יפ פעיל: ' + onChip + ')');
console.log('✓ הפיד היומי נפתח על:', onChip.trim());
await page.locator('button:has-text("חזרה לחיפוש הקווים")').click();

// טאב תחנות
await page.locator('button.tab:has-text("תחנות")').click();
await page.waitForSelector('.slist .srow, .slist .sgroup', { timeout: 60000 }).catch(() => fail('טאב התחנות לא נטען'));
const srows = await page.locator('.slist .srow').count();
console.log('✓ טאב התחנות:', srows, 'שורות');

if (errs.length) fail('חריגות JS: ' + errs.slice(0, 3).join(' | '));
console.log('✅ בדיקת הקו בזמן עברה');
await browser.close();
srv.close();
process.exit(0);
