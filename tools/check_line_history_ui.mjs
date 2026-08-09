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
const listedL = new Set(months.months || []);
const onDiskL = new Set(fs.readdirSync(path.join(LH, 'data/changes'))
  .filter((f) => /^\d{4}-\d{2}\.json$/.test(f)).map((f) => f.slice(0, 7)));
for (const m of onDiskL) if (!listedL.has(m)) fail(`חודש קווים ${m} קיים על הדיסק אבל חסר ב-months.json`);
for (const m of listedL) if (!onDiskL.has(m)) fail(`חודש קווים ${m} רשום ב-months.json אבל אין לו קובץ`);
const oldestL = [...listedL].sort()[0];
console.log(`✓ נתונים: ${listed.size} חודשי תחנות (מ-${oldest}) + ${listedL.size} חודשי קווים (מ-${oldestL})`);

// ---- שלב א2': הטקסטים על האתר תואמים לטווח שבנתונים ----
// התיאור שמופיע כשמשתפים קישור אמר "מ-2022" עוד חודשים אחרי שהמילוי הגיע
// למרץ 2017. טקסט שמתאר את הנתונים חייב להיבדק מול הנתונים.
{
  const yr = oldest.slice(0, 4);
  const html = fs.readFileSync(path.join(LH, 'index.html'), 'utf8');
  for (const tag of ['name="description"', 'property="og:description"']) {
    const m = html.match(new RegExp(`<meta ${tag} content="([^"]*)"`));
    if (!m) fail(`חסר תג ${tag} בעמוד — כך נראה הקישור כשמשתפים אותו`);
    if (!m[1].includes(yr)) fail(`${tag} לא מזכיר את ${yr}, השנה שבה הנתונים מתחילים: "${m[1]}"`);
  }
  const app = fs.readFileSync(path.join(LH, 'app.jsx'), 'utf8');
  const nsrc = (app.match(/SOURCES = \[([\s\S]*?)\n\];/) || ['', ''])[1]
    .split('{ t:').length - 1;
  if (nsrc < 4) fail(`רשימת המקורות באתר מונה ${nsrc} מקורות — פחות ממה שבשימוש`);
  console.log(`✓ טקסטים: התיאור לשיתוף מזכיר ${yr} · ${nsrc} מקורות רשומים באתר`);
}

// ---- שלב ב': הממשק באמת מציג את החודש הכי ישן ----
const require_ = createRequire(path.join(process.env.PW_MODULES || ROOT, 'noop.js'));
const { chromium } = require_('playwright-core');

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.jsx': 'text/javascript', '.css': 'text/css', '.json': 'application/json' };
const srv = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]).replace(/^\/+/, '') || 'index.html';
  // האתר קורא גם לנתוני 2012 שיושבים מחוץ לתיקייה שלו (‎../magihim-2012‎).
  // בלי זה הבדיקה מחזירה 404 על מה שבדפדפן עובד.
  const p = fs.existsSync(path.join(LH, rel)) ? path.join(LH, rel) : path.join(ROOT, rel);
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
  // סטאב לאפלט: הבדיקה רצה בלי רשת, אבל דף הקו כן מצייר מפה. הסטאב חייב
  // לכסות את כל מה שהאפליקציה קוראת לו — אחרת נפילת הסטאב מתחזה לבאג באתר.
  return route.fulfill({ contentType: 'text/javascript', body: `
    (function(){
      var chain = function(){ return obj; },
          obj = { addTo: chain, bindPopup: chain, fitBounds: chain, remove: chain,
                  setView: chain, on: chain, addLayer: chain, removeLayer: chain,
                  invalidateSize: chain, extend: chain, pad: chain, getBounds: chain,
                  setLatLng: chain, openPopup: chain, bindTooltip: chain,
                  isValid: function(){ return true; } };
      window.L = { map: chain, tileLayer: chain, polyline: chain,
                   circleMarker: chain, latLngBounds: chain, marker: chain,
                   layerGroup: chain, divIcon: chain, control: { scale: chain } };
    })();` });
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

// תצוגת חודש בודד אינה זקוקה לקורות החיים של כל התחנות (4.5 מגה), ולכן
// הקובץ הזה לא אמור להיטען לפני שבוחרים "כל התקופה". בלי הבדיקה הזו
// הטעינה הכבדה תחזור בהיסח הדעת בפעם הבאה שמישהו נוגע ב-useEffect.
{
  const heavy = [];
  page.on('request', (r) => { if (r.url().includes('stops-hist.json')) heavy.push(r.url()); });
  await page.locator('.months .mchip', { hasText: `${om}.${oy}` }).first().click();
  await page.waitForTimeout(1500);
  if (heavy.length) fail('תצוגת חודש הורידה את כל קורות החיים של התחנות');
  await page.click('.months .mchip:has-text("כל התקופה")');
  await page.waitForTimeout(3000);
  if (!heavy.length) fail('"כל התקופה" לא טענה את קורות החיים');
  console.log('✓ משקל: תצוגת חודש נטענת בלי 4.5 המגה, ו"כל התקופה" טוענת אותם');
  await page.locator('.months .mchip', { hasText: new RegExp(`^${oy}$`) }).first().click();
  await page.locator('.months .mchip', { hasText: `${om}.${oy}` }).first().click();
  await page.waitForSelector('.slist .srow', { timeout: 30000 });
}

// ---- שלב ב2': אירועי הזזה — "מ־" ו"אל" מלאים משני הצדדים ----
// הסורק הארכיוני רשם רק את המיקום החדש, והשורה יצאה "הוזזה מ׳ · (, ) ← (…)":
// מרחק ריק וסוגריים ריקים. תקלה שקטה — הכל מוצג, פשוט בלי תוכן.
{
  const moved = fs.readdirSync(path.join(LH, 'data/changes'))
    .filter((f) => f.startsWith('stops-') && f.endsWith('.json'))
    .map((f) => {
      const j = JSON.parse(fs.readFileSync(path.join(LH, 'data/changes', f), 'utf8'));
      return { mo: j.month, n: j.changes.filter((c) => c.k === 'moved').length };
    }).sort((a, b) => b.n - a.n)[0];
  if (moved && moved.n) {
    const [my, mm] = moved.mo.split('-');
    await page.locator('.months .mchip', { hasText: new RegExp(`^${my}$`) }).first().click();
    await page.locator('.months .mchip', { hasText: `${mm}.${my}` }).first().click();
    await page.waitForSelector('.slist .srow', { timeout: 30000 })
      .catch(() => fail(`הזזות: נבחר ${mm}.${my} ולא הופיעה אף שורה`));
    const txt = await page.locator('.slist').innerText();
    if (/הוזזה\s+מ׳/.test(txt)) fail(`הזזות ב-${moved.mo}: "הוזזה מ׳" בלי מרחק`);
    if (/\(\s*,\s*\)/.test(txt)) fail(`הזזות ב-${moved.mo}: מיקום קודם ריק — "(, )"`);
    console.log(`✓ הזזות: ${moved.n} ב-${moved.mo}, המרחק והמיקום הקודם מוצגים`);
  }
}

// ---- שלב ב3': רשימת המקורות נפתחת ומציגה את המקורות ----
{
  const box = page.locator('.srcbox');
  if (!(await box.count())) fail('רשימת המקורות לא הופיעה בעמוד');
  await box.locator('summary').click();
  const n = await page.locator('.srcbox .srcitem').count();
  if (n < 4) fail(`רשימת המקורות נפתחה עם ${n} מקורות בלבד`);
  console.log(`✓ מקורות: הרשימה נפתחת ומציגה ${n} מקורות`);
}

// ---- שלב ב3.5': קישור ישיר לתחנה ----
// לקו הייתה כתובת ולתחנה לא, ולכן אי אפשר היה לשלוח למישהו שינוי בתחנה
// מסוימת. הבדיקה נכנסת דרך הכתובת עצמה, כמו מי שקיבל אותה בהודעה.
{
  const hist = JSON.parse(fs.readFileSync(path.join(LH, 'data/stops-hist.json'), 'utf8'));
  const code = Object.keys(hist).find((c) => (hist[c] || []).length >= 3);
  await page.goto(`http://127.0.0.1:${port}/index.html#stop=${code}`,
    { waitUntil: 'domcontentloaded' });
  await page.reload({ waitUntil: 'domcontentloaded' });   // hash בלבד אינו טוען מחדש
  await page.waitForSelector('.slist .srow', { timeout: 30000 })
    .catch(() => fail(`הכתובת #stop=${code} לא פתחה את התחנה`));
  const txt = await page.locator('.slist').innerText();
  if (!txt.includes(code)) fail(`הכתובת #stop=${code} נפתחה על תחנה אחרת`);
  const nrow = await page.locator('.slist .srow').count();
  console.log(`✓ קישור לתחנה: #stop=${code} נפתח עם ${nrow} שורות`);
  await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tabs', { timeout: 30000 });
}

// ---- שלב ב3.7': חיפוש קו מציג גם את הגרסה של 2012 ----
// חיפוש "548" החזיר את הקו כפי שהוא היום בלבד. הגרסה של 2012 — קו אחר
// לגמרי, מקרית מלאכי לבני ברק — קיימת בנתונים ולא הופיעה בתוצאות.
{
  await page.click('button.tab:has-text("קווים")');
  await page.fill('input.search', '548');
  await page.waitForSelector('.r12 .lrow', { timeout: 30000 })
    .catch(() => fail('חיפוש 548 לא הציג את קווי 2012'));
  const t12 = await page.locator('.r12').innerText();
  if (!t12.includes('ברק')) fail('חיפוש 548: הגרסה של 2012 לבני ברק לא הופיעה');
  const n12 = await page.locator('.r12 .lrow').count();
  await page.locator('.r12 .lrow').first().click();
  await page.waitForSelector('.s12 li, .dayhead', { timeout: 30000 })
    .catch(() => fail('לחיצה על קו 2012 לא פתחה את רצף התחנות'));
  console.log(`✓ חיפוש: 548 מציג גם ${n12} קווים מצילום 2012, ולחיצה פותחת אותם`);
  await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tabs', { timeout: 30000 });
}

// ---- שלב ב4': ביטולים — קטגוריה אחת, מקובצת לפי שנה ----
// הביטולים חיים בקטגוריה ולא במסך נפרד, ולכן הבדיקה נכנסת מאותה דרך שבה
// נכנס משתמש: פותחת את רשימת הקטגוריות ומסמנת את התיבה.
{
  await page.click('button.tab:has-text("קווים")');
  // החיפוש נשמר בין ביקורים, ותצוגת הביטולים המקובצת היא ללא חיפוש חופשי
  await page.fill('input.search', '');
  await page.click('button.kathead:has-text("קטגוריות לבחירה")', { timeout: 30000 });
  await page.locator('.katrow', { hasText: 'מבוטל' }).first().locator('input').check();
  await page.waitForSelector('.gonehead', { timeout: 30000 })
    .catch(() => fail('סימון קטגוריית ביטול לא הציג את הרשימה המקובצת'));
  const n = await page.locator('.llist .lrow').count();
  if (!n) fail('קטגוריית הביטולים נפתחה ריקה');
  const head = await page.locator('.gonehead').innerText();
  if (!/\d/.test(head)) fail('ביטולים: אין מספר קווים בכותרת');
  const chips = await page.locator('.months .mchip').count();
  if (chips < 2) fail('ביטולים: אין חלוקה לשנים');
  await page.locator('.llist .lrow').first().click();
  await page.waitForSelector('.linehead', { timeout: 30000 })
    .catch(() => fail('לחיצה על קו שבוטל לא פתחה את עמוד הקו'));
  console.log(`✓ ביטולים: ${n} שורות מקובצות ב-${chips - 1} שנים, ולחיצה מגיעה לעמוד הקו`);
  await page.goto(`http://127.0.0.1:${port}/index.html`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.tabs', { timeout: 30000 });
}

// ---- שלב ג': פיד "שינויים לפי יום" של הקווים — החודש הכי ישן נגיש ----
if (oldestL) {
  await page.click('button.tab:has-text("קווים")');
  await page.click('button.kathead:has-text("שינויים לפי יום")', { timeout: 30000 });
  await page.waitForSelector('.months .mchip', { timeout: 30000 })
    .catch(() => fail('פיד הקווים: בוחר החודשים לא הופיע'));
  const [ly, lm] = oldestL.split('-');
  const yChip = page.locator('.months .mchip', { hasText: new RegExp(`^${ly}$`) }).first();
  if (!(await yChip.count())) fail(`פיד הקווים: אין כפתור לשנה ${ly} — ${oldestL} לא נגיש`);
  await yChip.click();
  const mChip = page.locator('.months .mchip', { hasText: `${lm}.${ly}` }).first();
  if (!(await mChip.count())) fail(`פיד הקווים: אין כפתור לחודש ${lm}.${ly}`);
  await mChip.click();
  await page.waitForSelector('.dayhead', { timeout: 30000 })
    .catch(() => fail(`פיד הקווים: נבחר ${lm}.${ly} ולא הופיע אף יום`));
  console.log(`✓ פיד קווים: החודש הכי ישן (${lm}.${ly}) נגיש ומציג ימים`);
}

// ---- שלב ד': טאב סוגי התחבורה — רכבת, מוניות שירות, רכבת קלה ----
// עד יולי 2026 הסורק סינן כל route_type שאינו אוטובוס. אחרי שהוסר הסינון,
// הבדיקה מוודאת שהקווים האלה באמת מגיעים למסך ושדף הקו שלהם נפתח: לרכבת
// אין מספר קו ב-GTFS, ותג ריק הוא בדיוק סוג התקלה שנעלמת מהעין.
const idxLines = JSON.parse(fs.readFileSync(path.join(LH, 'data/lines.json'), 'utf8')).lines;
// רכבת ומוניות שירות הן קטגוריות נפרדות זו מזו — כל אחת נבדקת בפני עצמה
const MODE_TABS = [
  { label: 'רכבת', tts: ['rail', 'lightrail', 'cable'] },
  { label: 'מוניות שירות', tts: ['taxi'] },
];
for (const t of MODE_TABS) {
  const n = idxLines.filter((l) => t.tts.includes(l.tt)).length;
  if (!n) { console.log(`· ${t.label}: אין עדיין קווים כאלה באינדקס — מדלגים`); continue; }
  await page.click(`button.tab:has-text("${t.label}")`, { timeout: 30000 });
  await page.waitForSelector('.llist .lrow', { timeout: 30000 })
    .catch(() => fail(`${t.label}: לא הופיעה אף שורת קו למרות ${n} באינדקס`));
  const shown = await page.locator('.llist .lrow').count();
  // תג ריק: קו רכבת בלי מספר חייב להציג סמל במקומו
  const blank = await page.locator('.llist .lrow .badge').evaluateAll(
    (els) => els.filter((e) => !e.textContent.trim()).length);
  if (blank) fail(`${t.label}: ${blank} תגים ריקים — סמל הסוג לא מוצג`);
  await page.locator('.llist .lrow').first().click();
  await page.waitForSelector('.linehead .badge', { timeout: 30000 })
    .catch(() => fail(`${t.label}: דף הקו לא נפתח`));
  // סוג התחבורה חייב להופיע בתוך עמוד הקו, לא רק ברשימה
  const facts = await page.locator('.facts').first().textContent();
  if (!/רכבת|מונית שירות|רכבל|כרמלית|לפי דרישה/.test(facts || ''))
    fail(`${t.label}: סוג התחבורה לא מופיע בעמוד הקו — "${(facts || '').slice(0, 60)}"`);
  // "חזרה לחיפוש" מקו רכבת/מונית חייבת לנחות באותה קטגוריה ולא ב"קווים":
  // הטאב אינו בכתובת, וללא גזירה מסוג הקו המשתמש הועף לרשימת האוטובוסים
  await page.click('button.back');
  await page.waitForSelector('.llist .lrow', { timeout: 30000 })
    .catch(() => fail(`${t.label}: חזרה מעמוד הקו לא הציגה רשימה`));
  const onTab = await page.locator('button.tab.on').textContent();
  if (!(onTab || '').includes(t.label))
    fail(`${t.label}: חזרה מעמוד הקו נחתה בטאב "${(onTab || '').trim()}" במקום "${t.label}"`);
  console.log(`✓ ${t.label}: ${n} באינדקס, ${shown} מוצגים, הסוג מוצג, חזרה נשארת בקטגוריה`);
}
// "שירות לפי דרישה" נשאר תחת קווים ולא כקטגוריה נפרדת — אבל חייב להיות
// מסומן ככזה בתוך עמוד הקו, אחרת אי אפשר לדעת שזו לא נסיעה רגילה
const dem = idxLines.find((l) => l.tt === 'demand');
if (dem) {
  // שינוי שמשנה רק את ה-hash אינו טוען את הדף מחדש, ולכן React לא קורא
  // אותו שוב — חובה reload מפורש, אחרת נבדק המסך הקודם
  await page.goto(`http://127.0.0.1:${port}/index.html#${encodeURIComponent(dem.rd)}`,
    { waitUntil: 'domcontentloaded' });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.facts', { timeout: 30000 })
    .catch(() => fail(`שירות לפי דרישה: עמוד הקו ${dem.rd} לא נטען`));
  const f = await page.locator('.facts').first().textContent();
  if (!/לפי דרישה/.test(f || '')) fail(`שירות לפי דרישה: הקו ${dem.rd} אינו מסומן ככזה`);
  console.log('✓ שירות לפי דרישה: נשאר תחת קווים ומסומן בעמוד הקו');
}

await browser.close();
srv.close();
console.log('✅ הבדיקה עברה');
