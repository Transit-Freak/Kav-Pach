#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מחיקת אירועי הארכיון מקבצי הקווים, לקראת בנייה מחדש.

הכלל לבחירת נסיעה נציגה היה תלוי בסדר השורות ב-trips.txt, וסדר זה אינו
יציב בין צילומים. התוצאה היא אירועים שלא קרו: במדידה על שני זוגות צילומים
מלאים 93% ו-59% מהשינויים היו של הכלל ולא של הנתונים. אחרי תיקון הכלל אין
דרך לתקן את מה שכבר נרשם חוץ מלבנות מחדש.

הכלי מוחק אך ורק גרסאות שמקורן בארכיון (src ∈ tf, tf17). כל השאר — ארכיון
אופן באס, הסריקה היומית, קובץ הרישוי — אינו נגזר מבחירת הנציג ואינו נוגע.
היסטוריית התחנות נבנית מ-stops.txt ולכן גם היא אינה נוגעת.

קובץ קו שכל תוכנו מהארכיון נמחק, כי גרסה ריקה אינה מצב חוקי. הוא ייווצר
מחדש בריצה.

DRY=1 מדווח בלבד.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
ARCHIVE = {'tf', 'tf17'}
STATES = ['tf-state.json', 'tf-mode-state.json']


def main():
    n_ev = n_keep = n_files = n_del = 0
    for p in glob.glob(f'{OUTDIR}/lines/*.json'):
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = lf.get('versions') or []
        keep = [v for v in vs if (v.get('src') or '') not in ARCHIVE]
        n_ev += len(vs) - len(keep)
        n_keep += len(keep)
        if len(keep) == len(vs):
            continue
        if not keep:
            n_del += 1
            if not DRY:
                os.remove(p)
            continue
        n_files += 1
        if not DRY:
            lf['versions'] = keep
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))

    for st in STATES:
        p = f'{OUTDIR}/{st}'
        if os.path.exists(p) and not DRY:
            os.remove(p)

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_ev} אירועי ארכיון נמחקו · {n_keep} אירועים אחרים נשארו · '
          f'{n_files} קבצים קוצרו · {n_del} קבצים נמחקו לגמרי', file=sys.stderr)


if __name__ == '__main__':
    main()
