#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הסרת אירועי "שינוי סיווג" שקדמו לתיעוד הראשון של הקו.

סורק הסיווג זוכר את הערך האחרון שראה לכל וריאנט, גם כשהוריאנט נעדר
מהפיד לתקופה. כשהוא חזר עם סיווג אחר נרשם "שינוי סיווג" בתאריך החזרה —
ואם התיעוד הראשון של הקו אצלנו הוא אותו יום, נוצר צמד סותר:

    2019-08-21  התיעוד הראשון   קו שירות לפי דרישה
    2019-08-21  שינוי סיווג      אוטובוס רגיל ← שירות לפי דרישה

התיעוד הראשון כבר אומר מה סוג הקו, ולפניו אין "לפני". הסורקים עצמם כבר
לא כותבים אירוע כזה; הכלי הזה מנקה את מה שכבר נכתב.

הסיווג הנוכחי ('tt') לא נוגעים בו — הוא נגזר מהמצב האחרון ונכון.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def main():
    n_ev = n_line = 0
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = lf.get('versions') or []
        real = [v['d'] for v in vs if v.get('k') != 'mode']
        if not real:
            continue
        first = min(real)
        keep = [v for v in vs if not (v.get('k') == 'mode' and v['d'] <= first)]
        if len(keep) == len(vs):
            continue
        n_ev += len(vs) - len(keep)
        n_line += 1
        lf['versions'] = keep
        if not DRY:
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_ev} אירועי סיווג שקדמו לתיעוד הראשון הוסרו '
          f'ב-{n_line} קווים', file=sys.stderr)


if __name__ == '__main__':
    main()
