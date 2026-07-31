// בדיקת שמירה ל"הקו בזמן": כל חודש שקיים בנתונים חייב להיות נגיש מהממשק.
//
// נולדה מבאג אמיתי (07.2026): slice(0,18) בבוחר החודשים הסתיר בשקט את כל
// האירועים שלפני 02.2025 — הדאטה היה שם, כפתור לא היה. הבדיקה נכשלת ברעש
// אם זה יקרה שוב, מכל סיבה שהיא.
//
// שלב א' (מהיר, בלי דפדפן): כל קובץ changes/stops-*.json מופיע ב-months.json
//   ולהפך, והחודש הכי ישן ברשימה תואם את הקובץ הכי ישן על הדיסק.
// שלב ב' (דפדפן ללא-ראש): פותחים את האתר, עוברים לטאב התחנות, לוחצים על
//   השנה הכי ישנה ואז על החודש הכי ישן — ומוודאים שמופיעות שורות אירועים.
//   הרצה הרמטית: ספריות ה-CDN מוגשות מ-vendor/ המקומי, בלי רשת חיצונית.
//
// הרצה: node tools/check_line_history_ui.mjs   (מריצים משורש הריפו)
// דורש: npm i --no-save playwright-core, ודפדפן כרום — ברירת מחדל
//   /opt/pw-browsers/chromium, או CHROMIUM_PATH (ב-CI: which google-chrome).
import fs from 'fs';
import http from 'http';
import path from 'path';
import { createRequire } from 'module';

const ROOT = process.cwd();
const LH = path.join(ROOT, 'line-history');
const fail = (msg) => { console.error('❌', msg); process.exit(1); };

// ---- שלב א': עקביות הנתונים ----
const months = JSON.parse(fs.readFileSync(path.join(LH, 'data/months.json'), 'utf8'));
const listed = new Set(months.stopMonths || []);
const onDisk = new Set(fs.readdirSync(path.join(LH, 'data/changes'))
  .filter((f) => /^stops-\d{4}-\d{2}\.json$/.test(f)).map((f) => f.slice(6, 13)));
for (const m of onDisk) if (!listed.has(m)) fail(`חודש ${m} קיים על הדיסק אבל חסר ב-months.json`);
for (const m of listed) if (!onDisk.has(m)) fail(`חודש ${m} רשום ב-months.json אבל אין לו קובץ`);
const oldest = [...listed].sort()[0];
if (!oldest) fail('אין חודשי תחנות בכלל');
console.log(`✓ נתונים: ${listed.size} חודשים, מ-${oldest} עד ${[...listed].sort().at(-1)}`);

// ---- שלב ב': הממשק באמת מציג את החודש הכי ישן ----
const require_ = createRequire(path.join(process.env.PW_MODULES || ROOT, 'noop.js'));
const { chromium } = require_('playwright-core');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.jsx': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const srv = http.createServer((req, res) => {
  const p = path.join(LH, decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html');
  try {
    let body = fs.readFileSync(p);
    if (p.endsWith('index.html')) {
      // בלי רשת: מסירים חתימות SRI כדי שאפשר יהיה להגיש את הספריות מקומית
      body = body.toString().replace(/\s(integrity|crossorigin)="[^"]*"/g, '');
    }
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
page.on('pageerror', (e) => fail('שגיאת דף: ' + e.message));
// ספריות ה-CDN מ-vendor/ המקומי; לאפלט וגופנים — סטאבים ריקים
await page.route('**://unpkg.com/**', (route) => {
  const u = route.request().url();
  const local = u.includes('react-dom') ? 'vendor/react-dom.development.js'
    : u.includes('react') ? 'vendor/react.development.js'
    : u.includes('babel') ? 'vendor/babel.min.js' : null;
  if (local) return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, local)) });
  if (u.endsWith('.css')) return route.fulfill({ contentType: 'text/css', body: '' });
  return route.fulfill({ contentType: 'text/javascript', body: 'window.L=window.L||{map:()=>({})};' });
});
await page.route('**://fonts.googleapis.com/**', (r) => r.fulfill({ contentType: 'text/css', body: '' }));
await page.route('**://fonts.gstatic.com/**', (r) => r.fulfill({ body: '' }));

await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
await page.click('button.tab:has-text("תחנות")', { timeout: 30000 });
// הצ'יפים מצוירים רק אחרי ש-months.json נטען — חובה לחכות להם
await page.waitForSelector('.months .mchip', { timeout: 30000 })
  .catch(() => fail('בוחר החודשים לא הופיע בכלל בטאב התחנות'));

const [oy, om] = oldest.split('-');
const yearChip = page.locator('.months .mchip', { hasText: new RegExp(`^${oy}$`) }).first();
if (!(await yearChip.count())) fail(`אין כפתור לשנה ${oy} — הדאטה של ${oldest} לא נגיש מהממשק`);
await yearChip.click();
const monChip = page.locator('.months .mchip', { hasText: `${om}.${oy}` }).first();
if (!(await monChip.count())) fail(`אין כפתור לחודש ${om}.${oy} אחרי בחירת השנה`);
await monChip.click();
await page.waitForSelector('.slist .srow', { timeout: 30000 })
  .catch(() => fail(`נבחר ${om}.${oy} ולא הופיעה אף שורת אירוע`));
const rows = await page.locator('.slist .srow').count();
console.log(`✓ ממשק: החודש הכי ישן (${om}.${oy}) נגיש ומציג ${rows} שורות`);

await browser.close();
srv.close();
console.log('✅ הבדיקה עברה');
