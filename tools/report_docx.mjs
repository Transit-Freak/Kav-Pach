// דו"ח נגישות אזורי התעשייה — מסמך Word לפי המפרט של איריס (parks/REPORT-SPEC.md).
// כל המספרים מ-parks/report/data.json (tools/report_data.py); אין מספר מוקלד כאן.
//   node tools/report_docx.mjs   →  parks/report/נגישות-אזורי-תעשייה.docx
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const D = require(process.env.DOCX_MODULE || 'docx');
const { Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell,
        WidthType, ShadingType, BorderStyle, ImageRun, PageBreak, Footer, PageNumber, TableOfContents,
        LevelFormat, VerticalAlign } = D;

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const REP = path.join(ROOT, 'parks', 'report');
const data = JSON.parse(fs.readFileSync(path.join(REP, 'data.json'), 'utf8'));
const IMG = p => path.join(REP, 'img', p);

// ── עיצוב ─────────────────────────────────────────────────────────────────
const FONT = 'Arial';
const INK = '0F172A', MUT = '475569', BRAND = '32318E', DEEP = '043E7E', TINT = 'EEF2FB', TBRD = 'C7D2F0';
const PAGE_W = 11906, PAGE_H = 16838, MARGIN = 1134;            // A4 לאורך, שוליים 2 ס"מ (DXA)
const TEXT_W = PAGE_W - 2 * MARGIN;                            // 9638 DXA
const fmt = (v, unit = '') => v == null ? '—' : `${v}${unit}`;
const scaleColor = s => { if (s == null) return '94A3B8'; for (const [t, c] of data.formula.scale) if (s >= t) return c.replace('#', '').toUpperCase(); return '050505'; };
const inkOn = hex => ['14B03D','C00D18','8E0B1E','3F0A18','050505','E63C14','EE7A16'].includes(hex) ? 'FFFFFF' : INK;

const run = (text, o = {}) => new TextRun({ text: String(text), font: FONT, rightToLeft: true, size: o.size || 22, bold: !!o.bold, color: o.color || INK, italics: !!o.italics });
const P = (text, o = {}) => new Paragraph({ bidirectional: true, alignment: o.align || AlignmentType.RIGHT, spacing: { after: o.after ?? 120, line: 300 },
  children: Array.isArray(text) ? text : [run(text, o)] });
// מעבר עמוד על הכותרת עצמה (pageBreakBefore), לא כפסקה נפרדת: פסקת מעבר-עמוד
// שנופלת בראש עמוד שכבר התמלא מייצרת עמוד ריק (איריס 02.09). H1 שובר כברירת מחדל.
const H1 = (t, o = {}) => new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: o.pb !== false, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 240, after: 160 }, children: [run(t, { size: 34, bold: true, color: DEEP })] });
const H2 = (t, o = {}) => new Paragraph({ heading: HeadingLevel.HEADING_2, pageBreakBefore: !!o.pb, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 200, after: 100 }, children: [run(t, { size: 26, bold: true, color: BRAND })] });
const Note = t => P([run(t, { size: 19, color: MUT, italics: true })], { after: 160 });
const Bullet = t => new Paragraph({ bidirectional: true, alignment: AlignmentType.RIGHT, numbering: { reference: 'bul', level: 0 }, spacing: { after: 60, line: 300 }, children: Array.isArray(t) ? t : [run(t)] });
const Break = () => new Paragraph({ children: [new PageBreak()] });
const Img = (file, w = 560) => {
  const p = IMG(file); if (!fs.existsSync(p)) return Note(`[תרשים ${file} לא נוצר בבנייה הזו]`);
  const b = fs.readFileSync(p); let h = Math.round(w * 0.78);
  try { const { width, height } = pngSize(b); h = Math.round(w * height / width); } catch {}
  return new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new ImageRun({ type: 'png', data: b, transformation: { width: w, height: h } })] });
};
function pngSize(b) { return { width: b.readUInt32BE(16), height: b.readUInt32BE(20) }; }

// טבלה RTL: העמודה הראשונה ברשימה מופיעה מימין. רוחבים ב-DXA, סכומם = TEXT_W.
function T(headers, rows, widths, o = {}) {
  const ws = widths.map(w => Math.round(TEXT_W * w));
  const cell = (txt, i, hdr, fill, fg) => new TableCell({
    width: { size: ws[i], type: WidthType.DXA }, verticalAlign: VerticalAlign.CENTER,
    shading: fill ? { type: ShadingType.CLEAR, fill, color: 'auto' } : (hdr ? { type: ShadingType.CLEAR, fill: TINT, color: 'auto' } : undefined),
    margins: o.tight ? { top: 30, bottom: 30, left: 60, right: 60 } : { top: 60, bottom: 60, left: 80, right: 80 },
    children: [new Paragraph({ bidirectional: true, alignment: o.center && i > 0 ? AlignmentType.CENTER : AlignmentType.RIGHT, spacing: { after: 0 },
      children: [run(txt, { size: o.size || 19, bold: hdr || !!fill, color: fg || (hdr ? DEEP : INK) })] })] });
  return new Table({ visuallyRightToLeft: true, columnWidths: ws, width: { size: TEXT_W, type: WidthType.DXA },
    borders: { top: { style: BorderStyle.SINGLE, size: 4, color: TBRD }, bottom: { style: BorderStyle.SINGLE, size: 4, color: TBRD },
               left: { style: BorderStyle.SINGLE, size: 4, color: TBRD }, right: { style: BorderStyle.SINGLE, size: 4, color: TBRD },
               insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: TBRD }, insideVertical: { style: BorderStyle.SINGLE, size: 4, color: TBRD } },
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, i, true)) }),
           ...rows.map(r => new TableRow({ children: r.map((c, i) => {
             const [txt, fill, fg] = Array.isArray(c) ? c : [c, undefined, undefined]; return cell(txt, i, false, fill, fg); }) }))] });
}
const sp = (t, o = {}) => new Paragraph({ bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { after: o.after ?? 60 }, children: [] });

// ── תוכן ──────────────────────────────────────────────────────────────────
const N = data.national, F = data.formula, R = data.regions;
const kids = [];

// שער
kids.push(new Paragraph({ spacing: { before: 2600, after: 200 }, alignment: AlignmentType.RIGHT, bidirectional: true, children: [run('נגישות אזורי התעשייה בישראל לתחבורה ציבורית', { size: 52, bold: true, color: DEEP })] }));
kids.push(P([run(`תמונת מצב ארצית · ${N.n} אזורי תעשייה ותעסוקה`, { size: 28, color: BRAND })], { after: 400 }));
kids.push(P([run(`נתוני משרד התחבורה (GTFS) מיום ${data.gtfs_date} · הדו"ח חושב מהנתונים החיים ב-${data.generated} (שעון ישראל)`, { size: 20, color: MUT })]));
kids.push(P([run('הקו הבוחן · אתר "נגישות אזורי תעשייה" · transit-freak.github.io/kav-bochan/parks', { size: 20, color: MUT })]));
kids.push(P([run('[מקום להקדמה של איריס]', { size: 22, color: 'B45309', italics: true })], { after: 0 }));

// תוכן עניינים
// כותרת התוכן בלי רמת כותרת — כדי שלא תופיע בתוך התוכן עצמו; מעבר העמוד עליה
kids.push(new Paragraph({ pageBreakBefore: true, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 240, after: 160 }, children: [run('תוכן העניינים', { size: 34, bold: true, color: DEEP })] }));
kids.push(new TableOfContents('תוכן', { hyperlink: true, headingStyleRange: '1-2' }));

// 2. מקורות
kids.push(H1('1. מקורות הנתונים'));
kids.push(P('כל נתון בדו"ח ובאתר נשאב ממקור ציבורי מזוהה. הטבלה מפרטת מאיזה מאגר הגיע כל רכיב, ומתי.'));
kids.push(T(['הנתון', 'המאגר', 'תאריך', 'הערה'], data.sources.map(s => [s.what, s.src, fmt(s.date), s.note || '']), [0.24, 0.40, 0.12, 0.24]));
kids.push(Note('הדו"ח נבנה מחדש מהנתונים החיים בכל הרצה, כמו האתר עצמו. אין בו מספר מוקלד.'));
kids.push(sp());

// 3. שיטת החישוב
kids.push(H1('2. שיטת החישוב', { pb: false }));
kids.push(H2('הציון המשוקלל של האתר'));
kids.push(P(`לכל אזור מחושב ציון 0–100 מארבעה רכיבים. כל רכיב מקבל ציון לפי טבלת מדרגות, והציונים משוקללים לפי המשקלים שנקבעו ב-${F.version}.`));
const W = F.weights;
kids.push(T(['הרכיב', 'מה נמדד', 'משקל'], [
  ['הקו החזק בשיא הבוקר', 'הקו עם הכי הרבה יציאות בין 06:00 ל-09:00 בכיוון האזור, בכיוון בודד: כל כמה דקות הוא יוצא', `${Math.round(W.bl * 100)}%`],
  ['הנקודה הרחוקה', 'כמה דקות הולך ברגל העובד במפעל המרוחק ביותר באזור עד התחנה הקרובה אליו, במסלול אמיתי על רשת הרחובות', `${Math.round(W.far * 100)}%`],
  ['התדירות הממוצעת בשיא', 'כל יציאות האוטובוס השימושיות ב-7 שעות השיא, לכיוון: בבוקר אל האזור, אחר הצהריים ממנו', `${Math.round(W.uf * 100)}%`],
  ['הליכה ממרכז האזור', 'דקות הליכה ממרכז הפוליגון לתחנה הקרובה ביותר', `${Math.round(W.near * 100)}%`],
], [0.26, 0.60, 0.14], { center: true }));
kids.push(sp());
kids.push(H2('טבלת התדירות (לשני רכיבי התדירות)'));
const hb = F.headway_bands;
kids.push(T(['מרווח בין אוטובוסים', 'ציון'], [...hb.map(([t, s], i) => [i === 0 ? `עד ${t} דק׳` : `${hb[i - 1][0]}–${t} דק׳`, [`${s}`, scaleColor(s), inkOn(scaleColor(s))]]), [`מעל ${hb[hb.length - 1][0]} דק׳`, ['0', scaleColor(0), 'FFFFFF']]], [0.5, 0.5], { center: true }));
kids.push(Note('הגבול שייך למדרגה הטובה: בדיוק 10 דקות = 90, בדיוק 15 = 80. קווי תלמידים וקווי לילה אינם נספרים. הספירה כיוונית: רק קווים שנכנסים לאזור בבוקר ויוצאים ממנו אחר הצהריים.'));
kids.push(H2('טבלת ההליכה (לשני רכיבי ההליכה)'));
const wb = F.walk_bands;
kids.push(T(['דקות הליכה', 'ציון'], [...wb.map(([t, s], i) => [i === 0 ? `עד ${t} דק׳` : `${wb[i - 1][0]}–${t} דק׳`, [`${s}`, scaleColor(s), inkOn(scaleColor(s))]]), [`מעל ${wb[wb.length - 1][0]} דק׳`, ['0', scaleColor(0), 'FFFFFF']]], [0.5, 0.5], { center: true }));
kids.push(Note('ההליכה נמדדת בניתוב אמיתי על רשת OpenStreetMap במהירות 5 קמ"ש, בפרופיל שמתיר כבישי שירות פרטיים ורמפות של כבישים ראשיים, כי שם עוברים העובדים בפועל. תחנה במרחק של יותר מ-20 דקות הליכה אינה נספרת כלל.'));
kids.push(H2('סרגל הצבעים'));
// גם טקסט בצבע המילוי: אם צופה מסוים מפיל את הצללת התאים, הגוון עדיין נראה
kids.push(T(['ציון', ...F.scale.slice().reverse().map(([t]) => `${t}`)], [['גוון', ...F.scale.slice().reverse().map(([t, c]) => { const h = c.replace('#', '').toUpperCase(); return ['■', h, h]; })]], [0.12, ...Array(11).fill(0.08)], { center: true, size: 16 }));
kids.push(Note('ירוק רק מ-90. 70–89 צהוב, 50–69 כתום, ומתחת לזה מאדום ועד שחור.'));
kids.push(H2('שכבות המבחנים במפה'));
kids.push(P('שלוש שכבות מפה מציגות כל רכיב תדירות והליכה בנפרד, על אותן מדרגות של הרכיב המקביל בציון, כדי שהשכבה והציון לא יסתרו זה את זה. שכבת "תחנות" מונה תחנות פעילות בתוך הפוליגון בלבד, ושכבת "תדירות" את כל יציאות היום.'));
kids.push(sp());

// 4. השוואה בינלאומית
kids.push(H1('3. השוואה לתקנים בינלאומיים', { pb: false }));
kids.push(P('שני סולמות מקובלים מודדים דברים קרובים למה שהדו"ח מודד. שניהם מאששים את מיקום המדרגות, ושניהם שונים מהדו"ח בקצה התחתון.'));
kids.push(H2('PTAL — לונדון (Transport for London)'));
kids.push(P('מדד הנגישות של לונדון משקלל לכל נקודה את זמן ההליכה לתחנה ואת תדירות הקווים בה. זמן ההמתנה מחושב כמחצית המרווח בין אוטובוסים ועוד 2 דקות אמינות, ומתווסף לזמן ההליכה. הקו הטוב ביותר נספר במשקל מלא, כל קו נוסף בחצי. התוצאה מדורגת 1a (הנמוך) עד 6b (הגבוה). PTAL אינו מכיר צוק תדירות: קו של 90 דקות עדיין נספר, רק פחות. הצוק שלו נמצא בהליכה: תחנת אוטובוס במרחק של יותר מ-640 מטר אינה נספרת כלל, בדומה לסף 20 הדקות בדו"ח.'));
kids.push(H2('TCQSM — ארצות הברית (Transit Capacity and Quality of Service Manual)'));
kids.push(T(['רמת שירות', 'מרווח בין אוטובוסים', 'תיאור המדריך', 'המדרגה בדו"ח'], [
  ['A', 'עד 10 דק׳', 'הנוסע אינו צריך לוח זמנים', '90–100'], ['B', '10–14', 'שירות תדיר, הנוסע מתייעץ בלוח', '80'],
  ['C', '15–20', 'זמן ההמתנה המקסימלי הסביר אם מחמיצים אוטובוס', '70'], ['D', '21–30', 'שירות לא אטרקטיבי לנוסע שיש לו רכב', '65'],
  ['E', '31–60', 'שירות זמין במהלך השעה', '55–40'], ['F', 'מעל 60', 'שירות לא אטרקטיבי לכל הנוסעים', '15–0'],
], [0.14, 0.22, 0.42, 0.22], { center: true }));
kids.push(Note('החפיפה למדרגות הדו"ח קרובה לאחד-לאחד. הבדל אחד: ב-TCQSM המעבר מ-E ל-F הוא צעד של דרגה אחת, בעוד שבדו"ח קו של יותר משעה וחצי מקבל 0. המהדורה השלישית של המדריך (2013) המירה את האותיות לתיאור מילולי אך שמרה על הספים.'));
kids.push(sp());

// 5. מדריך שימוש באתר
kids.push(H1('4. מדריך שימוש באתר', { pb: false }));
kids.push(P('האתר מציג את כל הנתונים שבדו"ח, מעודכנים בכל שבוע. הדו"ח הוא תמונת מצב; האתר הוא המקור החי.'));
kids.push(H2('מה רואים בעמוד הראשי'));
kids.push(Bullet('מפה ארצית: כל אזור הוא עיגול שצבעו וגודלו לפי הציון המשוקלל, על סרגל הצבעים שלמעלה. אזור תעסוקה מסומן בטבעת סגולה, אזור תשתית בטבעת כהה.'));
kids.push(Bullet('כפתור "רשימה": כל האזורים בטבלה, עם הציון, ציון משרד התחבורה, מספר הקווים והתחנות. אפשר למיין בלחיצה על כותרת עמודה.'));
kids.push(Bullet('כפתור "ייצוא לאקסל" מעל הטבלה מוריד את כל הרשימה כקובץ CSV.'));
kids.push(Bullet('כפתור "שכבות": בחירת שכבת המפה. ברירת המחדל היא הציון המשוקלל. שכבות נוספות: תחנות בתוך האזור (משולשים), יציאות ביום חול (עיגולים), ציון משרד התחבורה (כוכבים), ושלוש שכבות מבחן לרכיבי הציון. לכל שכבה מקרא משלה עם הסבר מה היא מודדת.'));
kids.push(Bullet('תיבת "פער מרכז–פריפריה" מתחת למפה מתבססת על ציוני משרד התחבורה בלבד, מדד חיצוני.'));
kids.push(H2('עמוד אזור'));
kids.push(Bullet('לחיצה על אזור במפה או ברשימה פותחת את עמודו: בראשו הציון המשוקלל וארבעת רכיביו, עם הנתון הגולמי מאחורי כל רכיב.'));
kids.push(Bullet('מתחת: ציוני משרד התחבורה של האזור הסטטיסטי, ורשימת כל הקווים שמגיעים לאזור. צבע מספר הקו הוא תדירותו בשיא הבוקר על אותו סרגל.'));
kids.push(Bullet('לחיצה על קו מציגה את מסלולו על המפה. בטלפון מופיע כפתור "חזרה לרשימת הקווים".'));
kids.push(Bullet('המחוון "מציג תחנות עד X דקות הליכה" מסנן את התחנות במפה. כפתור "מדידה" מחליף בין מדידה עד מרכז האזור ועד גבולו.'));
// 6. תמונת מצב ארצית
kids.push(H1('5. תמונת המצב הארצית'));
kids.push(P([run(`${N.n} אזורי תעשייה ותעסוקה בנויים. הציון החציוני: `), run(`${N.median}`, { bold: true }), run(`. הממוצע: ${N.mean}.`)]));
kids.push(Img('pie-national.png', 520));
kids.push(T(['הקבוצה', 'אזורים', 'אחוז'], N.traffic.map(t => [[t.label, t.color.replace('#', '').toUpperCase(), inkOn(t.color.replace('#', '').toUpperCase())], `${t.n}`, `${t.pct}%`]), [0.5, 0.25, 0.25], { center: true }));
kids.push(sp());
kids.push(H2('עובדות משלימות'));
kids.push(Bullet(`${N.no_line_n} אזורים (${N.no_line_pct}%) בלי אף קו אוטובוס בטווח 20 דקות הליכה.`));
kids.push(Bullet(`${N.no_peak_n} אזורים בלי אף יציאה שימושית בשעות השיא.`));
kids.push(Bullet(`ריכוזיות השירות: 10% מהאזורים (המשורתים ביותר) מקבלים ${N.top10_share}% מכל יציאות האוטובוס בשעות השיא בארץ, ו-5% המובילים מקבלים ${N.top5_share}%. האזור החציוני מקבל ${N.median_peak_departures} יציאות שימושיות בשיא.`));
kids.push(Bullet(`הליכת העובד המרוחק — חציון ארצי ${fmt(N.stats.far_median, ' דק׳')}; ב-${N.stats.pct_far_over20}% מהאזורים היא מעל 20 דקות או שאין תחנה כלל.`));
kids.push(Bullet(`הקו החזק — חציון ארצי: אוטובוס כל ${fmt(N.stats.bl_headway_median, ' דק׳')} בשיא הבוקר. ב-${N.stats.pct_bl_le15}% מהאזורים הוא כל רבע שעה או פחות, וב-${N.stats.pct_bl_ge60}% פעם בשעה או יותר.`));
kids.push(Note('הרשימות המלאות — האזורים בלי תחנה בטווח, האזורים בלי יציאה בשיא, והאזורים שהוצאו מהדירוג — בנספח ב.'));
kids.push(H2('אותן עובדות, בתרשימים', { pb: true }));
kids.push(Img('bar-noservice.png', 500));
kids.push(Img('bar-far-dist.png', 500));
kids.push(Img('bar-bl-dist.png', 500));
kids.push(Img('bar-concentration.png', 500));
kids.push(Note('ריכוזיות: האזורים מסודרים לפי מספר יציאות השיא ומחולקים לעשרה עשירונים שווים; העמודה היא חלקו של כל עשירון בסך היציאות הארצי.'));
// 7. פערים
kids.push(H1('6. הפערים'));
kids.push(P([run(`הציון החציוני הארצי הוא `), run(`${N.median}`, { bold: true }), run(`. כל קבוצה שלמטה נמדדת מולו ובשלושת המדדים שהוגדרו לדו"ח: נגישות כלל האזור (הליכה מהנקודה הרחוקה), התדירות הממוצעת בשיא לכיוון, ותדירות הקו החזק בשיא.`)]));
const grpTable = G => T(['קבוצה', 'אזורים', 'ציון ממוצע', 'ציון 70+', 'ציון <50', 'הליכה מהנקודה הרחוקה (חציון)', 'מרווח ממוצע בשיא (חציון)', 'הקו החזק (חציון)', 'ציון משרד התחבורה'],
  Object.entries(G).map(([k, s]) => [k, `${s.n}`, [`${fmt(s.score_mean)}`, scaleColor(s.score_mean), inkOn(scaleColor(s.score_mean))], `${s.pct_ge70}%`, `${s.pct_lt50}%`, fmt(s.far_median, ' דק׳'), fmt(s.uf_headway_median, ' דק׳'), fmt(s.bl_headway_median, ' דק׳'), fmt(s.mot_mean)]),
  [0.16, 0.08, 0.10, 0.09, 0.09, 0.14, 0.12, 0.11, 0.11], { center: true, size: 17 });
kids.push(H2('מרכז מול פריפריה'));
kids.push(P(`"מרכז" = עד ${R.defs.center_km} ק"מ מתל אביב (${R.center_periphery['מרכז'].n} אזורים) · "פריפריה" = כל השאר (${R.center_periphery['פריפריה'].n}).`));
kids.push(grpTable(R.center_periphery));
kids.push(sp());
kids.push(Img('bar-cp-score.png', 500)); kids.push(Img('bar-cp-far.png', 500)); kids.push(Img('bar-cp-bl.png', 500));
kids.push(H2('צפון, מרכז, ירושלים ויהודה ושומרון, דרום', { pb: true }));
kids.push(P(`החלוקה לפי ${R.defs.district_source} (${R.defs.district_matched} מתוך ${N.n} אזורים; לשאר לפי קו רוחב). ${R.defs.groups}.`));
kids.push(grpTable(R.north_center_south));
kids.push(sp());
kids.push(Img('bar-ncs-score.png', 500)); kids.push(Img('bar-ncs-bl.png', 500)); kids.push(Img('bar-ncs-far.png', 500));
if (R.periphery_by_region && Object.keys(R.periphery_by_region).length >= 2) {
  kids.push(H2('הפריפריה בצפון מול הפריפריה בדרום'));
  kids.push(P('אותם אזורים שמחוץ ל-45 הק"מ מתל אביב, מפוצלים לפי מחוז:'));
  kids.push(grpTable(R.periphery_by_region));
}
kids.push(H2('החברה היהודית מול החברה הערבית והבדואית', { pb: true }));
if (data.sector) {
  kids.push(P(`התיוג הרשמי: השדה ${data.sector.source_field}. ${data.sector.minority.n} אזורים מתויגים כמגזר מיעוטים, מול ${data.sector.other.n} שאינם מתויגים.`));
  kids.push(grpTable({ 'מגזר מיעוטים (תיוג רשמי)': data.sector.minority, 'כל שאר האזורים': data.sector.other }));
  kids.push(sp());
  kids.push(P('בתוך המגזר המתויג, לפי תת-הקבוצה שבשכבה:'));
  kids.push(grpTable(data.sector.subgroups));
  kids.push(Note('הקבוצה המתויגת כמכלול אינה נמוכה משאר הארץ בציון המשוקלל; הפער נמצא בתוכה: האזורים הבדואיים הם הקבוצה החלשה, ורוב האזורים המתויגים האחרים קטנים, עם תחנות בתוך האזור, ולכן רכיבי ההליכה שלהם גבוהים. ציון משרד התחבורה מספר סיפור דומה. הנתונים כפי שהם; הפרשנות לדו"ח.'));
  kids.push(Img('bar-sector-score.png', 500)); kids.push(Img('bar-sector-bl.png', 500));
} else {
  kids.push(P([run('בבנייה הזו לא היה זמין שדה תיוג מגזרי בנתונים: המאגרים שהדו"ח נשען עליהם כרגע (שכבת אזורי התעשייה של משרד התחבורה ורשימת משרד הכלכלה) אינם מכילים אותו. ', { color: 'B45309' }), run('הסעיף יושלם כשהשדה יתווסף לצינור הנתונים, בלי שינוי בשאר הדו"ח.', { color: 'B45309', italics: true })]));
}
if (data.socio && data.socio.groups) {
  kids.push(H2('לפי האשכול החברתי-כלכלי של הרשות המקומית'));
  kids.push(P(`אשכול הלמ"ס (${data.socio.year}) של הרשות שבה נמצא האזור. ${data.socio.unmatched} אזורים ללא רשות מזוהה אינם בטבלה.`));
  kids.push(grpTable(data.socio.groups));
  kids.push(Img('bar-socio-score.png', 500));
  kids.push(Note('האשכול לבדו מטעה: רשויות באשכול נמוך במרכז הארץ (בני ברק, למשל) משורתות היטב בזכות המיקום, ולכן הפער החברתי-כלכלי נראה כאן קטן מהפער הגאוגרפי.'));
}
// למה הפערים קטנים ממה שמצפים — פירוק לרכיבים (שאלת איריס 02.09, נקודה 3)
if (data.decomposition) {
  kids.push(H2('למה הפערים קטנים ממה שמצפים — פירוק הציון לרכיבים', { pb: true }));
  kids.push(P('הציון הוא סכום משוקלל של ארבעה רכיבים (0–100 כל אחד): הקו החזק 40%, הנקודה הרחוקה 30%, התדירות הממוצעת 20%, ההליכה ממרכז האזור 10%. הטבלה מציגה לכל קבוצה את ממוצע כל רכיב, ואת תרומתו לציון אחרי השקלול.'));
  const DK = ['bl', 'far', 'uf', 'near'], DN = { bl: 'הקו החזק (40%)', far: 'הנקודה הרחוקה (30%)', uf: 'תדירות ממוצעת (20%)', near: 'ממרכז האזור (10%)' };
  kids.push(T(['קבוצה', 'אזורים', 'ציון', ...DK.map(k => DN[k]), 'שטח חציוני', 'עד 0.3 קמ"ר', 'הקו החזק (חציון)'],
    Object.entries(data.decomposition).filter(([, d]) => d).map(([k, d]) => [k, `${d.n}`, [`${fmt(d.score_mean)}`, scaleColor(d.score_mean), inkOn(scaleColor(d.score_mean))],
      ...DK.map(c => `${fmt(d.comp[c])} (${fmt(d.weighted[c])})`), `${fmt(d.area_median, ' קמ"ר')}`, `${d.pct_small}%`, fmt(d.bl_headway_median, ' דק׳')]),
    [0.16, 0.07, 0.08, 0.12, 0.12, 0.12, 0.11, 0.09, 0.07, 0.06], { center: true, size: 16, tight: true }));
  kids.push(Note('בכל תא של רכיב: ממוצע הרכיב, ובסוגריים תרומתו לציון אחרי השקלול.'));
  kids.push(P('מה רואים: כמעט כל הפער בין הקבוצות נמצא בשני רכיבי התדירות (הקו החזק והתדירות הממוצעת). שני רכיבי ההליכה, שהם 40% מהציון, כמעט זהים בכל הקבוצות — כי רוב אזורי התעשייה בישראל קטנים, ובאזור קטן כל תחנה קרובה לכל נקודה. אזור של 0.2 קמ"ר עם תחנה אחת מקבל 80–100 בשני רכיבי ההליכה בלי קשר לשירות בתחנה. ולכן שתי קבוצות שנבדלות מאוד בתדירות נבדלות בציון פחות ממה שנראה בשטח.'));
  kids.push(P('בחתך המגזרי מצטרף גורם שני: השוואה בין אזורים, לא בין אוכלוסיות. אזורי התעשייה ביישובים הבדואיים הם קבוצה קטנה, ורובם יושבים על כביש ראשי שעובר בו קו בין-עירוני; מה שאין ביישוב עצמו לא נמדד כאן. הפער האמיתי בין הקבוצות נראה בעמודות התדירות הגולמיות (הקו החזק, חציון בדקות) ולא רק בציון.'));
  kids.push(Note('הפרשנות של הצוות; המספרים כפי שהם. מי שרוצה פערים חדים יותר יכול לשקול משקל גבוה יותר לתדירות — זו החלטה של הדו"ח, לא של הנתונים.'));
}
// 8. עשירייה כפולה
kids.push(H1('7. עשרת המשורתים ביותר מול עשרת הפחות משורתים'));
kids.push(P(`לפי הציון המשוקלל. נכללים אזורים בשטח ${data.min_area_for_top} קמ"ר ומעלה, כי אזור זעיר מקבל את רכיבי ההליכה כמעט אוטומטית.`));
const tenTable = rows => T(['#', 'האזור', 'הרשות המקומית', 'הציון שלנו', 'ציון משרד התחבורה', 'הקו החזק בשיא', 'הנקודה הרחוקה'],
  rows.map((r, i) => [`${i + 1}`, r.name, r.city, [`${r.score}`, scaleColor(r.score), inkOn(scaleColor(r.score))], fmt(r.mot), r.bl_headway ? `כל ~${r.bl_headway} דק׳` : 'אין קו בשיא', r.far != null ? `${r.far} דק׳ הליכה` : 'אין תחנות בטווח']),
  [0.05, 0.27, 0.17, 0.10, 0.12, 0.15, 0.14], { center: true, size: 16, tight: true });
kids.push(H2('המשורתים ביותר')); kids.push(tenTable(data.top10));
kids.push(H2('הפחות משורתים')); kids.push(tenTable(data.bottom10));
// 9. פערים בתוך רשות
kids.push(H1('8. פערים בתוך אותה רשות מקומית'));
kids.push(P('רשויות שבהן אזור אחד משורת היטב ואזור אחר באותה רשות כמעט לא. העמודה האחרונה מזהה את הרכיב שפותח את רוב הפער.'));
kids.push(T(['הרשות', 'האזור המשורת', 'ציון', 'האזור המנותק', 'ציון', 'פער', 'מה פותח את הפער'],
  data.gaps_within_city.map(g => [g.city, g.hi.name, [`${g.hi.score}`, scaleColor(g.hi.score), inkOn(scaleColor(g.hi.score))], g.lo.name, [`${g.lo.score}`, scaleColor(g.lo.score), inkOn(scaleColor(g.lo.score))], `${g.gap}`, g.why]),
  [0.12, 0.18, 0.07, 0.18, 0.07, 0.07, 0.31], { center: true, size: 16 }));
// 9. פערים מול ציון משרד התחבורה (איריס 02.09, נקודה 12)
if (data.mot_gaps) {
  const MG = data.mot_gaps;
  kids.push(H1('9. כשהציון שלנו וציון משרד התחבורה חולקים'));
  kids.push(P(`ציון משרד התחבורה אינו מודד את אותו הדבר. הוא ניתן לאזור סטטיסטי של הלמ"ס (לא לאזור התעשייה), והוא ממוצע של ארבעה מדדים לתושבי האזור: ${Object.values(MG.fields).join(', ')}. "תחרותיות" משווה את זמן הנסיעה באוטובוס ליעדים מול הנסיעה ברכב; "נגישות" סופרת לכמה יעדים מגיעים בזמן נתון. הדו"ח הזה מודד דבר אחד: האם עובד מגיע לאזור בשעות השיא, ברגל מהתחנה.`));
  kids.push(P(`לכן ההשוואה נעשית רק כשיש למשרד ${MG.rule} — כלומר ציון שניתן לאזור התעשייה עצמו ולא לשכונות שסביבו. כאלה יש ${MG.n} מתוך ${N.n} אזורים. ל-${MG.n_wide_only} אזורים נוספים יש רק ציון של האזור הסטטיסטי הסובב; הוא מופיע להקשר, מסומן בכוכבית, ואינו נכנס להשוואה.`));
  if (MG.corr != null) kids.push(Note(`על ${MG.n} האזורים שיש להם ציון ישיר: מתאם ${MG.corr} בין שני הציונים — אותו כיוון, לא אותו סרגל.`));
  const motCell = r => r.mot != null ? fmt(r.mot) : (r.motw != null ? `${r.motw}*` : '—');
  const motTable = rows => T(['האזור', 'הרשות', 'הציון שלנו', 'ציון המשרד', 'פער', ...Object.values(MG.fields), 'הקו החזק', 'הנקודה הרחוקה'],
    rows.map(r => [r.name, r.city, [`${r.score}`, scaleColor(r.score), inkOn(scaleColor(r.score))], motCell(r), r.gap != null ? `${r.gap > 0 ? '+' : ''}${r.gap}` : '—',
      ...Object.values(MG.fields).map(k => fmt(r.sub && r.sub[k] != null ? Math.round(r.sub[k]) : null)), r.bl_headway ? `כל ~${r.bl_headway} דק׳` : 'אין', r.far != null ? `${r.far} דק׳` : '—']),
    [0.20, 0.11, 0.08, 0.08, 0.06, 0.08, 0.08, 0.08, 0.08, 0.08, 0.07], { center: true, size: 15, tight: true });
  if (MG.named && MG.named.length) {
    kids.push(H2('הדוגמאות שנשאלו: צומת הקריות, גב ים, צור שלום'));
    kids.push(motTable(MG.named));
    const direct = MG.named.filter(r => r.direct).length;
    kids.push(P(direct === 0
      ? 'לשלושתן אין אזור סטטיסטי בתוך האזור: הציון שהוצג עד היום (מסומן בכוכבית) היה של השכונות הסובבות — הקריות, מפרץ חיפה — ולא של אזור התעשייה. לכן אין כאן פער אמיתי בין שני ציונים, אלא שני דברים שנמדדו על שטחים שונים. אצלנו שלושתן 92: הקו החזק כל 5–7 דקות, תחנה בתוך האזור, והעובד המרוחק בטווח 5–12 דקות הליכה.'
      : 'הציון המסומן בכוכבית הוא של האזור הסטטיסטי הסובב, להקשר בלבד. אצלנו שלושתן 92: הקו החזק כל 5–7 דקות, תחנה בתוך האזור, והעובד המרוחק בטווח 5–12 דקות הליכה.'));
    kids.push(Note('* ציון האזור הסטטיסטי הסובב — אין אזור סטטיסטי בתוך האזור, ולכן אין השוואה ישירה.'));
  }
  kids.push(H2('הפערים הגדולים ביותר לשני הכיוונים'));
  kids.push(P('אצלנו גבוה, במשרד נמוך:')); kids.push(motTable(MG.ours_high));
  kids.push(sp());
  kids.push(P('במשרד גבוה, אצלנו נמוך:')); kids.push(motTable(MG.mot_high));
  kids.push(Note('הכיוון השני (המשרד גבוה, אנחנו נמוכים) הוא לרוב אזור בתוך עיר משורתת שהתחנות סביבו קרובות לשכונות אבל לא לאזור עצמו, או אזור גדול שהקצה שלו רחוק מכל תחנה.'));
}

// 10. הניתוח לפי ציון משרד התחבורה (בקשת איריס 02.09: פרק נפרד — פריפריה מול מרכז, יהודים מול ערבים)
if (data.mot_chapter && data.mot_chapter.groups) {
  const MC = data.mot_chapter, FL = Object.values(MC.fields);
  kids.push(H1('10. אותם פערים, לפי ציון משרד התחבורה'));
  kids.push(P(`הפרק הזה חוזר על ניתוח הקבוצות של סעיף 6, אבל עם המדד של משרד התחבורה במקום הציון שלנו. הערך שמשמש כאן הוא ציון האזור הסטטיסטי שאזור התעשייה נמצא בו או חופף לו ("הסובב") — מה שהמשרד אומר על השירות במקום, לתושביו. יש כזה ל-${MC.n_wide} מתוך ${N.n} אזורים; ממוצע ארצי ${fmt(MC.national_wide_mean)}. ציון ישיר, של אזור סטטיסטי שבתוך אזור התעשייה, יש רק ל-${MC.n_direct} אזורים, והוא מופיע בעמודה האחרונה לצד המספר שלהם.`));
  kids.push(Note('הסולם של המשרד: 0–100, ממוצע ארבעת המדדים. בקירוב: מתחת ל-30 חלש מאוד, 30–45 חלש, 45–60 בינוני, 60 ומעלה טוב.'));
  const motGrp = G => T(['קבוצה', 'אזורים', 'הציון שלנו', 'ציון המשרד (סובב)', 'מתחת ל-30', '60 ומעלה', ...FL, 'ציון ישיר (אזורים)'],
    Object.entries(G).map(([k, s]) => [k, `${s.n}`, [`${fmt(s.score_mean)}`, scaleColor(s.score_mean), inkOn(scaleColor(s.score_mean))],
      s.wide_n ? `${fmt(s.wide_mean)} (${s.wide_n})` : '—', s.wide_n ? `${s.wide_lt30}%` : '—', s.wide_n ? `${s.wide_ge60}%` : '—',
      ...['av', 'ac', 'co', 're'].map(k => fmt(s['sub_' + k] != null ? Math.round(s['sub_' + k]) : null)),
      s.direct_n ? `${fmt(s.direct_mean)} (${s.direct_n})` : '—']),
    [0.17, 0.07, 0.08, 0.11, 0.08, 0.08, 0.08, 0.08, 0.08, 0.08, 0.09], { center: true, size: 15, tight: true });
  let gi = 0;
  for (const [sect, groups] of Object.entries(MC.groups)) {
    kids.push(H2(sect, { pb: gi > 0 }));
    kids.push(motGrp(groups));
    kids.push(sp());
    if (fs.existsSync(IMG(`bar-mot-${gi}.png`))) kids.push(Img(`bar-mot-${gi}.png`, 480));
    if (fs.existsSync(IMG(`bar-motsub-${gi}.png`))) kids.push(Img(`bar-motsub-${gi}.png`, 480));
    gi++;
  }
  kids.push(P('מה רואים בהשוואה לסעיף 6: המדד של המשרד מודד את מה שקורה לתושבים סביב האזור, ולכן הפערים בו הם פערי מקום — מרכז מול פריפריה — ופחות פערי אזור תעשייה. במקומות שבהם שני המדדים מסכימים, הממצא חזק. במקומות שבהם הם חולקים, סעיף 9 מסביר למה.'));
}

// 11. דוגמאות — שתיים מכל סוג (איריס 02.09, נקודות 8–11), עמוד לכל אזור, עם מפה
const MAP_LEGEND = 'גבול כחול = האזור · ✚ = מרכז האזור · תחנות: ירוק = בתוך האזור, ירוק בהיר = עד 5 דק׳ הליכה, צהוב = 5–10, כתום = 10–20 · רקע: © OpenStreetMap contributors';
kids.push(H1('11. דוגמאות: הגרועים ביותר, המצטיינים, והמצטיינים מחוץ למרכזי הערים'));
kids.push(P(`שתי דוגמאות מכל סוג, מתוך האזורים בשטח ${data.min_area_for_top} קמ"ר ומעלה. "מחוץ למרכזי הערים" = יותר מ-15 ק"מ מכל אחד מארבעת מרכזי המטרופולין (תל אביב, חיפה, ירושלים, באר שבע). אתרי פסולת ומחצבות אינם דוגמה, ו"הגרועים ביותר" נבחרים רק מאזורים שבדיקת המבנים מסמנת כבנויים בוודאות. כל דוגמה על רקע מפת רחובות: גבול האזור, התחנות בצבעי מרחק ההליכה, ומרכז האזור.`));
let lastKind = null, exi = 0;
for (const e of data.examples) {
  const first = exi++ === 0;
  let newPage = true;
  if (e.kind !== lastKind) { kids.push(H2(e.kind, { pb: !first })); lastKind = e.kind; newPage = false; }
  const mapf = `map-${e.f.replace('.json', '')}.png`;
  // עמוד לכל דוגמה: המעבר על כותרת האזור עצמה (לא פסקת מעבר נפרדת — ראה H1/H2)
  kids.push(new Paragraph({ pageBreakBefore: newPage, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 120, after: 120 },
    children: [run(`${e.name} · ${e.city}`, { bold: true, size: 26, color: BRAND })] }));
  kids.push(T(['הציון שלנו', 'ציון משרד התחבורה', 'שטח', 'קווים', 'הקו החזק בשיא', 'הנקודה הרחוקה', 'ממרכז האזור לתחנה'],
    [[[`${e.score}`, scaleColor(e.score), inkOn(scaleColor(e.score))], fmt(e.mot), `${e.area} קמ"ר`, `${e.lines ?? '—'}`, e.bl_headway ? `כל ~${e.bl_headway} דק׳` : 'אין קו בשיא', e.ww != null ? `${Math.round(e.ww)} דק׳` : 'אין תחנה בטווח', e.nearw != null ? `${Math.round(e.nearw)} דק׳` : '—']],
    [0.12, 0.15, 0.12, 0.09, 0.18, 0.17, 0.17], { center: true, size: 17 }));
  if (e.streets && e.streets.length) kids.push(P(`תחנות בתוך האזור (לזיהוי המקום): ${e.streets.join(' · ')}`));
  else if (e.stops && e.stops.length) kids.push(P(`התחנות הקרובות: ${[...new Set(e.stops.filter(s => s.n).map(s => s.n))].slice(0, 4).join(' · ')}`));
  if (fs.existsSync(IMG(mapf))) { kids.push(Img(mapf, 520)); kids.push(Note(MAP_LEGEND)); }
  else kids.push(Note('[המפה נוצרת בבניית GitHub Actions — סביבת העבודה המקומית חוסמת את שרת האריחים]'));
}

// נספח ב: הרשימות המלאות (איריס 02.09, נקודות 2, 5–7)
kids.push(H1('נספח ב: רשימות מלאות'));
const zoneList = rows => T(['האזור', 'הרשות', 'מחוז', 'שטח', 'קווים', 'הנקודה הרחוקה', 'מבנים (OSM)', 'תחנות בסביבה'],
  rows.map(r => [r.name, r.city, r.region || '—', `${fmt(r.area, ' קמ"ר')}`, `${r.lines}`, r.far != null ? `${r.far} דק׳` : 'אין תחנה בטווח', fmt(r.buildings), `${r.stops_near}`]),
  [0.26, 0.14, 0.10, 0.10, 0.07, 0.13, 0.10, 0.10], { center: true, size: 16, tight: true });
kids.push(H2(`אזורים בלי אף תחנה בטווח 20 דקות הליכה (${(data.no_stop_zones || []).length})`));
kids.push(P('הרף: תחנת אוטובוס פעילה בטווח 20 דקות הליכה אמיתית מכל נקודה באזור. אזורים שהוצאו מהדירוג (בהקמה, לא פעילים, מתקנים סגורים) אינם כאן — הם בטבלה השלישית.'));
kids.push(zoneList(data.no_stop_zones || []));
kids.push(sp());
kids.push(H2(`אזורים בלי אף יציאת אוטובוס שימושית בשעות השיא (${(data.no_peak_zones || []).length})`));
kids.push(P('יש בהם תחנה בטווח, אבל אף קו לא נכנס בשיא הבוקר ולא יוצא בשיא אחר הצהריים (קווי תלמידים ולילה אינם נספרים).'));
kids.push(zoneList(data.no_peak_zones || []));
if (data.excluded) {
  kids.push(sp());
  kids.push(H2('אזורים שהוצאו מהדירוג, ולמה'));
  kids.push(P(`ביד, אחרי בדיקה (איריס דור-און ומקורות פתוחים): ${(data.excluded.manual || []).length} אזורים. אוטומטית, לפי ספירת מבנים ב-OpenStreetMap ("טרם נבנה" — בלי מבנים ובלי סימני חיים): ${data.excluded.auto_n} אזורים.`));
  if (data.excluded.partial_n)
    kids.push(Note(`עוד ${data.excluded.partial_n} אזורים מסומנים בבדיקת המבנים "בנוי חלקית" (מעט מבנים ממופים, אבל תחנות בפנים, רשת כבישים או עסקים). הם נשארים בדירוג: הסימון משקף בעיקר מיפוי חלקי של מבנים ב-OpenStreetMap, שחלש יותר ביישובים ערביים ובפארקים עם מבנים גדולים ומעטים — לא סטטוס בנייה. ביניהם: ${(data.excluded.partial_names || []).slice(0, 8).join(', ')}.`));
  if ((data.excluded.manual || []).length)
    kids.push(T(['האזור', 'הסיבה', 'המקור'], data.excluded.manual.map(x => [x.name, x.reason || '', x.source || '']), [0.22, 0.48, 0.30], { size: 16 }));
  if ((data.excluded.auto || []).length) {
    kids.push(sp());
    kids.push(T(['האזור', 'הרשות', 'שטח', 'סטטוס', 'מבנים (OSM)'], data.excluded.auto.map(x => [x.name, x.city, `${fmt(x.area, ' קמ"ר')}`, x.st === 'planned' ? 'טרם נבנה' : 'בנוי חלקית', fmt(x.bld)]), [0.36, 0.20, 0.14, 0.15, 0.15], { center: true, size: 16, tight: true }));
  }
}
// נספח
kids.push(H1('נספח: איך לאמת כל מספר'));
kids.push(P('כל אזור שמופיע בדו"ח ניתן לפתיחה באתר: הציון, רכיביו, רשימת הקווים המלאה עם לוחות הזמנים, והמפה. הדו"ח נבנה אוטומטית מאותם קבצים שהאתר קורא.'));
kids.push(P(`נוסחה ${F.version} · GTFS ${data.gtfs_date} · הדו"ח חושב ${data.generated} (שעון ישראל)`));

// ── מסמך ──────────────────────────────────────────────────────────────────
const doc = new Document({
  creator: 'הקו הבוחן', title: 'נגישות אזורי התעשייה בישראל לתחבורה ציבורית',
  features: { updateFields: true },   // תוכן העניינים מתמלא בפתיחה ב-Word
  styles: {
    default: {
      // ברירת המחדל של כל פסקה: ימין-לשמאל ומיושר לימין (איריס 02.09: "הכל מיושר לימין")
      document: { run: { font: FONT, size: 22, rightToLeft: true }, paragraph: { alignment: AlignmentType.RIGHT } },
      // רמות מתאר מפורשות לכותרות המובנות: Word משלים אותן לפי שם הסגנון, LibreOffice לא —
      // ובלעדיהן עדכון תוכן העניינים בהמרה ל-PDF לא מוצא אף כותרת
      heading1: { paragraph: { outlineLevel: 1 } },
      heading2: { paragraph: { outlineLevel: 2 } },
    },
    // שורות תוכן העניינים (toc 1 / toc 2 = "Contents 1/2" ב-LibreOffice): ימין-לשמאל, כמו שאר המסמך
    paragraphStyles: [
      { id: 'TOC1', name: 'toc 1', basedOn: 'Normal', next: 'Normal', paragraph: { bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 60, after: 60 } }, run: { size: 22, font: FONT } },
      { id: 'TOC2', name: 'toc 2', basedOn: 'Normal', next: 'Normal', paragraph: { bidirectional: true, alignment: AlignmentType.RIGHT, indent: { right: 360 } }, run: { size: 20, font: FONT, color: '444444' } },
    ],
  },
  numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.RIGHT, style: { paragraph: { indent: { left: 0, right: 360, hanging: 260 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['עמוד ', PageNumber.CURRENT], font: FONT, size: 18, color: MUT })] })] }) },
    children: kids,
  }],
});
const out = path.join(REP, 'נגישות-אזורי-תעשייה.docx');
Packer.toBuffer(doc).then(b => { fs.writeFileSync(out, b); console.log('נכתב', out, Math.round(b.length / 1024), 'KB ·', kids.length, 'רכיבים'); });
