#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סיווג מחדש של "שינוי יעד" — רק כשמק"ט תחנת הקצה באמת השתנה.

הסורק היומי משווה את מחרוזת ה-route_long_name, ולכן החלפת שם בלבד
("מסוף כרמי גת" ← "מסוף כרמי גת/הורדה") נרשמה כשינוי יעד אף שמדובר
באותה תחנה פיזית. כאן משווים את המק"ט עצמו.

השוואה שמרנית: מסתמכים על רשימות התחנות הקרובות משני צידי האירוע —
אירועי יעד אינם נושאים רצף תחנות בעצמם. הסיווג משתנה ל"שינוי שם" רק
כששני קצות הקו נושאים אותו מק"ט לפני ואחרי; בכל ספק נשאר "שינוי יעד".

DRY=1 מדווח בלבד. הכלי אידמפוטנטי.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def ends(stops):
    return (stops[0][0], stops[-1][0]) if stops and len(stops) > 1 else None


NUM = re.compile(r'מספר הקו שוּנה: (\S+) ← (\S+)')


def noise_renum(v):
    """אירוע "שינוי מספר" שאינו שינוי אמיתי.

    בקובץ המקורי הסיומת "-1" נכתבת ונמחקת חליפות (קו 386 למשל התחלף
    386 ↔ 386-1 שש פעמים בשלושה חודשים). אחרי נירמול הסיומת שני הצדדים
    זהים — זה רעש רישום. נמחק רק כשהאירוע אינו נושא שום מידע אחר.
    """
    if v.get('k') != 'renum':
        return False
    m = NUM.search(v.get('note') or '')
    if not m:
        return False
    norm = lambda x: re.sub(r'-\d+$', '', x)
    if norm(m.group(1)) != norm(m.group(2)):
        return False
    return not any(v.get(f) for f in ('stops', 'shp', 'add', 'rem', 'tb'))


def main():
    changed = examined = renamed = undecided = dropped = 0
    for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
        if not fn.endswith('.json'):
            continue
        p = f'{OUTDIR}/lines/{fn}'
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = lf.get('versions') or []
        dirty = False
        keep = [v for v in vs if not noise_renum(v)]
        if len(keep) != len(vs):
            dropped += len(vs) - len(keep)
            vs = keep
            lf['versions'] = vs
            dirty = True
        for i, v in enumerate(vs):
            if v.get('k') != 'dest':
                continue
            examined += 1
            before = next((ends(vs[j].get('stops')) for j in range(i - 1, -1, -1)
                           if vs[j].get('stops')), None)
            after = next((ends(vs[j].get('stops')) for j in range(i, len(vs))
                          if vs[j].get('stops')), None)
            if not before or not after:
                undecided += 1
                continue
            if before == after:
                # אותם מק"טים בשני הקצוות — רק השם השתנה
                v['k'] = 'renamed'
                note = v.get('note') or ''
                v['note'] = (note + ' · מק״ט תחנות הקצה לא השתנה — החלפת שם בלבד').strip(' ·')
                renamed += 1
                dirty = True
        if dirty and not DRY:
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            changed += 1

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: נבדקו {examined} אירועי "שינוי יעד" · '
          f'{renamed} הם החלפת שם בלבד · {undecided} ללא הכרעה · '
          f'{dropped} אירועי "שינוי מספר" מזויפים נמחקו · '
          f'{changed} קבצים עודכנו', file=sys.stderr)


if __name__ == '__main__':
    main()
