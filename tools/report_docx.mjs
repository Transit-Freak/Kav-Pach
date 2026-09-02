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
const H1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 240, after: 160 }, children: [run(t, { size: 34, bold: true, color: DEEP })] });
const H2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, bidirectional: true, alignment: AlignmentType.RIGHT, spacing: { before: 200, after: 100 }, children: [run(t, { size: 26, bold: true, color: BRAND })] });
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
const sp = (t, o = {}) => new Paragraph({ spacing: { after: o.after ?? 60 }, children: [] });

// ── תוכן ──────────────────────────────────────────────────────────────────
const N = data.national, F = data.formula, R = data.regions;
const kids = [];

// שער
kids.push(new Paragraph({ spacing: { before: 2600, after: 200 }, alignment: AlignmentType.RIGHT, bidirectional: true, children: [run('נגישות אזורי התעשייה בישראל לתחבורה ציבורית', { size: 52, bold: true, color: DEEP })] }));
kids.push(P([run(`תמונת מצב ארצית · ${N.n} אזורי תעשייה ותעסוקה`, { size: 28, color: BRAND })], { after: 400 }));
kids.push(P([run(`נתוני משרד התחבורה (GTFS) מיום ${data.gtfs_date} · הדו"ח חושב מהנתונים החיים ב-${data.generated} (שעון ישראל)`, { size: 20, color: MUT })]));
kids.push(P([run('הקו הבוחן · אתר "נגישות אזורי תעשייה" · transit-freak.github.io/kav-bochan/parks', { size: 20, color: MUT })]));
kids.push(P([run('[מקום להקדמה של איריס]', { size: 22, color: 'B45309', italics: true })], { after: 0 }));
kids.push(Break());

// תוכן עניינים
kids.push(H1('תוכן העניינים'));
kids.push(new TableOfContents('תוכן', { hyperlink: true, headingStyleRange: '1-2' }));
kids.push(Break());

// 2. מקורות
kids.push(H1('1. מקורות הנתונים'));
kids.push(P('כל נתון בדו"ח ובאתר נשאב ממקור ציבורי מזוהה. הטבלה מפרטת מאיזה מאגר הגיע כל רכיב, ומתי.'));
kids.push(T(['הנתון', 'המאגר', 'תאריך', 'הערה'], data.sources.map(s => [s.what, s.src, fmt(s.date), s.note || '']), [0.24, 0.40, 0.12, 0.24]));
kids.push(Note('הדו"ח נבנה מחדש מהנתונים החיים בכל הרצה, כמו האתר עצמו. אין בו מספר מוקלד.'));
kids.push(sp());

// 3. שיטת החישוב
kids.push(H1('2. שיטת החישוב'));
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
kids.push(H1('3. השוואה לתקנים בינלאומיים'));
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
kids.push(H1('4. מדריך שימוש באתר'));
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
kids.push(Break());

// 6. תמונת מצב ארצית
kids.push(H1('5. תמונת המצב הארצית'));
kids.push(P([run(`${N.n} אזורי תעשייה ותעסוקה בנויים. הציון החציוני: `), run(`${N.median}`, { bold: true }), run(`. הממוצע: ${N.mean}.`)]));
kids.push(Img('pie-national.png', 520));
kids.push(T(['הקבוצה', 'אזורים', 'אחוז'], N.traffic.map(t => [[t.label, t.color.replace('#', '').toUpperCase(), inkOn(t.color.replace('#', '').toUpperCase())], `${t.n}`, `${t.pct}%`]), [0.5, 0.25, 0.25], { center: true }));
kids.push(sp());
kids.push(H2('עובדות משלימות'));
kids.push(Bullet(`${N.no_line_n} אזורים (${N.no_line_pct}%) בלי אף קו אוטובוס בטווח 20 דקות הליכה.`));
kids.push(Bullet(`${N.no_peak_n} אזורים בלי אף יציאה שימושית בשעות השיא.`));
kids.push(Bullet(`השירות מרוכז: עשירית האזורים המובילים מרכזת ${N.top10_share}% מכל יציאות השיא בארץ; 5% המובילים מרכזים ${N.top5_share}%. האזור החציוני מקבל ${N.median_peak_departures} יציאות שימושיות בשיא.`));
kids.push(Bullet(`הליכת העובד המרוחק — חציון ארצי ${fmt(N.stats.far_median, ' דק׳')}; ב-${N.stats.pct_far_over20}% מהאזורים היא מעל 20 דקות או שאין תחנה כלל.`));
kids.push(Bullet(`הקו החזק — חציון ארצי: אוטובוס כל ${fmt(N.stats.bl_headway_median, ' דק׳')} בשיא הבוקר. ב-${N.stats.pct_bl_le15}% מהאזורים הוא כל רבע שעה או פחות, וב-${N.stats.pct_bl_ge60}% פעם בשעה או יותר.`));
kids.push(Break());

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
kids.push(Break());
kids.push(H2('צפון, מרכז, ירושלים ויהודה ושומרון, דרום'));
kids.push(P(`החלוקה לפי ${R.defs.district_source} (${R.defs.district_matched} מתוך ${N.n} אזורים; לשאר לפי קו רוחב). ${R.defs.groups}.`));
kids.push(grpTable(R.north_center_south));
kids.push(sp());
kids.push(Img('bar-ncs-score.png', 500)); kids.push(Img('bar-ncs-bl.png', 500)); kids.push(Img('bar-ncs-far.png', 500));
if (R.periphery_by_region && Object.keys(R.periphery_by_region).length >= 2) {
  kids.push(H2('הפריפריה בצפון מול הפריפריה בדרום'));
  kids.push(P('אותם אזורים שמחוץ ל-45 הק"מ מתל אביב, מפוצלים לפי מחוז:'));
  kids.push(grpTable(R.periphery_by_region));
}
kids.push(Break());
kids.push(H2('החברה היהודית מול החברה הערבית והבדואית'));
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
kids.push(Break());

// 8. עשירייה כפולה
kids.push(H1('7. עשרת המשורתים ביותר מול עשרת הפחות משורתים'));
kids.push(P(`לפי הציון המשוקלל. נכללים אזורים בשטח ${data.min_area_for_top} קמ"ר ומעלה, כי אזור זעיר מקבל את רכיבי ההליכה כמעט אוטומטית.`));
const tenTable = rows => T(['#', 'האזור', 'הרשות המקומית', 'הציון שלנו', 'ציון משרד התחבורה', 'הקו החזק בשיא', 'הנקודה הרחוקה'],
  rows.map((r, i) => [`${i + 1}`, r.name, r.city, [`${r.score}`, scaleColor(r.score), inkOn(scaleColor(r.score))], fmt(r.mot), r.bl_headway ? `כל ~${r.bl_headway} דק׳` : 'אין קו בשיא', r.far != null ? `${r.far} דק׳ הליכה` : 'אין תחנות בטווח']),
  [0.05, 0.27, 0.17, 0.10, 0.12, 0.15, 0.14], { center: true, size: 16, tight: true });
kids.push(H2('המשורתים ביותר')); kids.push(tenTable(data.top10));
kids.push(H2('הפחות משורתים')); kids.push(tenTable(data.bottom10));
kids.push(Break());

// 9. פערים בתוך רשות
kids.push(H1('8. פערים בתוך אותה רשות מקומית'));
kids.push(P('רשויות שבהן אזור אחד משורת היטב ואזור אחר באותה רשות כמעט לא. העמודה האחרונה מזהה את הרכיב שפותח את רוב הפער.'));
kids.push(T(['הרשות', 'האזור המשורת', 'ציון', 'האזור המנותק', 'ציון', 'פער', 'מה פותח את הפער'],
  data.gaps_within_city.map(g => [g.city, g.hi.name, [`${g.hi.score}`, scaleColor(g.hi.score), inkOn(scaleColor(g.hi.score))], g.lo.name, [`${g.lo.score}`, scaleColor(g.lo.score), inkOn(scaleColor(g.lo.score))], `${g.gap}`, g.why]),
  [0.12, 0.18, 0.07, 0.18, 0.07, 0.07, 0.31], { center: true, size: 16 }));
kids.push(Break());

// 10. חריגים — עמוד נפרד לכל אחד (המפרט), ובו גם מפת האזור כחלק מההסבר
const MAP_LEGEND = 'גבול כחול = האזור · ✚ = מרכז האזור · תחנות: ירוק = בתוך האזור, ירוק בהיר = עד 5 דק׳ הליכה, צהוב = 5–10, כתום = 10–20 · רקע: © OpenStreetMap contributors';
kids.push(H1('9. אזורים חריגים'));
for (const o of data.outliers) {
  kids.push(H2(o.city && o.city !== '—' ? `${o.name} · ${o.city}` : o.name));
  kids.push(T(['הציון שלנו', 'ציון משרד התחבורה', 'שטח', 'הקו החזק בשיא', 'הנקודה הרחוקה'],
    [[[`${o.score}`, scaleColor(o.score), inkOn(scaleColor(o.score))], fmt(o.mot), `${o.area} קמ"ר`, o.bl_headway ? `כל ~${o.bl_headway} דק׳` : 'אין קו בשיא', o.far != null ? `${o.far} דק׳` : 'אין תחנות']],
    [0.16, 0.2, 0.16, 0.24, 0.24], { center: true }));
  kids.push(P([run(`${o.kind}. `, { bold: true }), run(o.text)]));
  const omap = o.f ? `map-${o.f.replace('.json', '')}.png` : null;
  if (omap && fs.existsSync(IMG(omap))) { kids.push(Img(omap, 520)); kids.push(Note(MAP_LEGEND)); }
  kids.push(Break());
}

// 11. מפות
kids.push(H1('10. מפות של אזורים לדוגמה'));
kids.push(P('ארבעה אזורים על רקע מפת רחובות (OpenStreetMap): גבול האזור, התחנות בצבעי הסיווג לפי מרחק ההליכה, ומרכז האזור.'));
for (const e of data.examples) {
  const mapf = `map-${e.f.replace('.json', '')}.png`;
  kids.push(H2(`${e.name} · ${e.city} · ציון ${e.score}`));
  if (fs.existsSync(IMG(mapf))) { kids.push(Img(mapf, 560)); kids.push(Note(MAP_LEGEND)); }
  else kids.push(Note('[המפה נוצרת בבניית GitHub Actions — סביבת העבודה המקומית חוסמת את שרת האריחים]'));
  kids.push(P(`שטח ${e.area} קמ"ר · ${e.lines ?? '—'} קווים · הקו החזק ${e.bl_headway ? `כל ~${e.bl_headway} דק׳` : 'אין'} · הנקודה הרחוקה ${e.ww != null ? Math.round(e.ww) + ' דק׳' : '—'} · ממרכז האזור לתחנה ${e.nearw != null ? Math.round(e.nearw) + ' דק׳' : '—'}`));
  kids.push(Break());
}

// נספח
kids.push(H1('נספח: איך לאמת כל מספר'));
kids.push(P('כל אזור שמופיע בדו"ח ניתן לפתיחה באתר: הציון, רכיביו, רשימת הקווים המלאה עם לוחות הזמנים, והמפה. הדו"ח נבנה אוטומטית מאותם קבצים שהאתר קורא.'));
kids.push(P(`נוסחה ${F.version} · GTFS ${data.gtfs_date} · הדו"ח חושב ${data.generated} (שעון ישראל)`));

// ── מסמך ──────────────────────────────────────────────────────────────────
const doc = new Document({
  creator: 'הקו הבוחן', title: 'נגישות אזורי התעשייה בישראל לתחבורה ציבורית',
  features: { updateFields: true },   // תוכן העניינים מתמלא בפתיחה ב-Word
  styles: { default: { document: { run: { font: FONT, size: 22, rightToLeft: true } } } },
  numbering: { config: [{ reference: 'bul', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.RIGHT, style: { paragraph: { indent: { left: 0, right: 360, hanging: 260 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: PAGE_W, height: PAGE_H }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['עמוד ', PageNumber.CURRENT], font: FONT, size: 18, color: MUT })] })] }) },
    children: kids,
  }],
});
const out = path.join(REP, 'נגישות-אזורי-תעשייה.docx');
Packer.toBuffer(doc).then(b => { fs.writeFileSync(out, b); console.log('נכתב', out, Math.round(b.length / 1024), 'KB ·', kids.length, 'רכיבים'); });
