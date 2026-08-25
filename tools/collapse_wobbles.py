# -*- coding: utf-8 -*-
"""מחיקת תנודות-נייר: זוג אירועים שסוגר את עצמו איננו אירוע.

הלקח מקו 80 כפר חב"ד (דרישת שלמה): בחופשת הקיץ הרישום "רפרף" — פרסם
זמנית תבנית ישנה וחזר לתבנית הנוכחית לקראת שנת הלימודים. מבחינת נוסע
לא השתנה דבר; השינויים האמיתיים מתועדים בתאריכיהם (הוכחה מהאתר עצמו:
מעון עולים בוטלה 26.10.2022, וכבר אז קו 80 לא עצר בה). הצגת הרפרוף
כשני "שינוי מסלול" ב-2026 היא זיהום של ציר הזמן.

הכלל: אירוע ששוחזר מהמצב היומי (note מתחיל "שוחזר בדיעבד") שאחריו,
בתוך עד 35 יום, גרסה שרצף התחנות שלה זהה לתיעוד שלפני האירוע — שניהם
נמחקים (הרישום חזר למה שהיה מתועד ממילא). אירוע משוחזר בלי סגירה נשאר
— הוא מתעד מסלול שבאמת תקף עכשיו ברישום. הזוגות שנמחקו נרשמים
(wobble-skip.json) כדי שהביקורת לא תשחזר אותם שוב.

DRY=1 ניתוח בלבד.
"""
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
MARK = 'שוחזר בדיעבד'
SKIP_F = f'{OUTDIR}/wobble-skip.json'


def codes(v):
    return [str(s[0]) for s in v.get('stops') or []]


def main():
    try:
        skip = json.load(open(SKIP_F, encoding='utf-8'))
    except Exception:
        skip = {}
    n_pairs = n_open = 0
    months = {}
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        raw = open(p, encoding='utf-8').read()
        if MARK not in raw:
            continue
        lf = materialize(json.loads(raw))
        rd = lf.get('rd')
        vs = sorted(lf.get('versions') or [], key=lambda v: v['d'])
        drop = set()
        for i, v in enumerate(vs):
            if not (v.get('note') or '').startswith(MARK) or id(v) in drop:
                continue
            prev = next((u for u in reversed(vs[:i]) if (u.get('stops') or [])
                         and id(u) not in drop), None)
            nxt = next((u for u in vs[i + 1:] if (u.get('stops') or [])
                        and id(u) not in drop), None)
            if prev is None:
                continue
            close_enough = nxt is not None and (
                datetime.date.fromisoformat(nxt['d'])
                - datetime.date.fromisoformat(v['d'])).days <= 35
            if close_enough and codes(nxt) == codes(prev):
                drop.add(id(v))
                drop.add(id(nxt))
                skip.setdefault(rd, [])
                for dd in (v['d'], nxt['d']):
                    if dd not in skip[rd]:
                        skip[rd].append(dd)
                n_pairs += 1
                print(f'  נמחק זוג: {rd} — {v["d"]} + {nxt["d"]} (חזר לתיעוד הקיים)')
            else:
                n_open += 1
        if drop and not DRY:
            gone = [v for v in vs if id(v) in drop]
            lf['versions'] = [v for v in vs if id(v) not in drop]
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            for v in gone:
                m = v['d'][:7]
                if m not in months:
                    try:
                        months[m] = json.load(open(f'{OUTDIR}/changes/{m}.json', encoding='utf-8'))
                    except Exception:
                        months[m] = None
                if months[m]:
                    months[m]['changes'] = [
                        c for c in months[m]['changes']
                        if not (c.get('rd') == rd and c.get('d') == v['d'])]
    if not DRY:
        for m, mm in months.items():
            if mm:
                json.dump(mm, open(f'{OUTDIR}/changes/{m}.json', 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
        json.dump(skip, open(SKIP_F, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'סיכום: {n_pairs} זוגות-תנודה נמחקו · {n_open} אירועים משוחזרים בלי סגירה נשארו'
          + (' · DRY' if DRY else ''))


if __name__ == '__main__':
    main()
