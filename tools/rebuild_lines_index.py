#!/usr/bin/env python3
# בונה מחדש את שורות lines.json מקובצי הקווים עצמם (lines/*.json) — הקבצים
# הם מקור האמת. רץ בצעד ה-commit של תהליכי העבודה אחרי מיזוג קבצים בין
# ריצות מקביליות, כדי שהאינדקס תמיד ישקף את מה שבאמת נמצא בקבצים
# (אותה גזירה כמו בזנב האינדקס של backfill_routes_exact.py).
import json
import os

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


idxp = f'{OUTDIR}/lines.json'
idx = jload(idxp, {})
if idx.get('lines') is None:
    raise SystemExit('אין אינדקס — מדלגים')

byrd = {e['rd']: e for e in idx['lines']}
ntr = jload(f'{OUTDIR}/line-trips.json', {})
# עוגן 2012 מוטמע בקובץ הקו עצמו (פאנל שלב ב, סעיף 13): עמוד הקו קורא
# אותו משם במקום להוריד 1.2MB של כל העוגנים בכל פתיחה. הכתיבה רק כשיש
# שינוי — אחרי ההטמעה החד-פעמית זו השוואה בלבד.
anchors = jload(f'{OUTDIR}/anchor-2012.json', {}).get('anchors', {})
# קובץ עוגנים ריק/פגום אינו הוראת-מחיקה: בלי השומר הזה תקלה בקובץ אחד
# הייתה מוחקת בשקט את מקטע 2012 מכל העמודים (ציד הבאגים, סבב ב)
KEEP_ANC = not anchors
n_anc = 0
n_new = 0
for fn in os.listdir(f'{OUTDIR}/lines'):
    if not fn.endswith('.json'):
        continue
    lf = jload(f'{OUTDIR}/lines/{fn}', {})
    rd = lf.get('rd')
    if not rd:
        continue
    a = anchors.get(rd)
    if (not KEEP_ANC) and a != lf.get('anc'):
        if a is None:
            lf.pop('anc', None)
        else:
            lf['anc'] = a
        json.dump(lf, open(f'{OUTDIR}/lines/{fn}', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        n_anc += 1
    vs = lf.get('versions', [])
    e = byrd.get(rd)
    if e is None:
        e = {'rd': rd, 'line': lf.get('line', ''), 'dest': lf.get('dest', '')[:80],
             'op': lf.get('op', ''), 'ty': lf.get('ty', '')}
        idx['lines'].append(e)
        byrd[rd] = e
        n_new += 1
    else:
        e['line'] = lf.get('line', e.get('line', ''))
        e['dest'] = (lf.get('dest') or e.get('dest', ''))[:80]
        e['op'] = lf.get('op', e.get('op', ''))
    # סוג התחבורה — לסינון באתר. חובה גם למחוק: קו שחזר להיות אוטובוס רגיל
    # נמחק לו השדה בקובץ, ובלי השורה השנייה האינדקס נשאר עם הסיווג הישן
    # לנצח. כך קו 15 ברחובות הוצג כ"שירות לפי דרישה" שנים אחרי שחזר.
    if lf.get('tt'):
        e['tt'] = lf['tt']
    else:
        e.pop('tt', None)
    if lf.get('wa'):
        e['wa'] = lf['wa']
    # מספר הנסיעות שבתוקף — מבדיל בין קו שפורסם לקראת פתיחה לבין קו שנוסע.
    # מגיע מקובץ צדדי כי הוא משתנה יומית; מי שאינו בו נמחק, אחרת מספר ישן
    # של קו שבוטל היה נשאר תלוי באוויר.
    if rd in ntr:
        e['ntr'] = ntr[rd]
    else:
        e.pop('ntr', None)
    # 'times' (הלו"ז האחרון של קו מבוטל) הוא צילום-מידע, לא שינוי — לא קטגוריה
    ks = {v['k'] for v in vs if v['k'] not in ('baseline', 'times')}
    # הגדרת המשתמש: 'freq' (שינוי מספר הרכבים) = רק תגבור באותה דקה;
    # שינויי כמות/שעות רגילים נספרים תחת הלו"ז ('sched')
    if 'freq' in ks:
        ks.add('sched')
        if not any(v['k'] == 'freq' and 'תגבור' in (v.get('note') or '') for v in vs):
            ks.discard('freq')
    for v in vs:   # קטגוריות התחנות הנגזרות מההשוואות
        if (v.get('src') == 'ob' or v.get('gd')) and v.get('k') != 'removed':
            a, rr = v.get('add'), v.get('rem')
            if a and rr:
                ks.add('stops')
            elif a:
                ks.add('stops-add')
            elif rr:
                ks.add('stops-del')
    ks = sorted(ks)
    e['v'] = len(vs)
    if ks:
        e['ks'] = ks
    else:
        e.pop('ks', None)
    if vs:
        e['lk'] = vs[-1]['k']
        e['ld'] = vs[-1]['d']

idx['lines'].sort(key=lambda x: (x.get('line', ''), x['rd']))
json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'אינדקס נבנה מחדש: {len(idx["lines"])} שורות ({n_new} חדשות) · עוגני 2012 שהוטמעו/עודכנו: {n_anc}')
