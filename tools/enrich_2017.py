#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""שילוב מצב 2017 לתוך ציר הזמן של כל קו — כגרסה רגילה, לא כקטגוריה נפרדת.

הצילום מ-2017 מתווסף כגרסה הראשונה בקו, ומול הגרסה שאחריה מחושב ההפרש
האמיתי: אילו תחנות נוספו, אילו ירדו, והאם היעדים השתנו. כך השינוי שבין
2017 לתיעוד הראשון מופיע בדיוק כמו כל שינוי אחר — עם אותן קטגוריות,
באותו יומן, ועם המסלול על המפה.

הכלי אידמפוטנטי ומיועד לרוץ אחרי כל בנייה: אם מיזוג של סריקת רקע ידרוס
את הגרסה, ההרצה הבאה תחזיר אותה.

קלט:  line-history/data/y2017/<rd>.json  (נוצר ע"י snap2017.py)
פלט:  עדכון קבצי הקווים במקום
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
SRC = 'tf17'          # מקור: ארכיון TransitFeeds, צילום 2017
DATE = '2017-03-16'


def main():
    src_dir = f'{OUTDIR}/y2017'
    if not os.path.isdir(src_dir):
        raise SystemExit('אין נתוני 2017 — יש להריץ קודם snap2017.py')

    added = skipped = missing = 0
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith('.json'):
            continue
        lp = f'{OUTDIR}/lines/{fn}'
        if not os.path.exists(lp):
            missing += 1          # קו שפעל ב-2017 ואין לו עמוד היום
            continue
        y = json.load(open(f'{src_dir}/{fn}', encoding='utf-8'))
        lf = materialize(json.load(open(lp, encoding='utf-8')))
        vs = lf.get('versions') or []
        if any(v.get('src') == SRC for v in vs):
            skipped += 1
            continue
        if not vs or vs[0]['d'] <= DATE:
            skipped += 1          # כבר יש תיעוד מוקדם יותר
            continue

        # מודגש: השינוי שבין 2017 לתיעוד הבא אירע בתאריך לא ידוע — הארכיון
        # מדלג על 2018-2021. לכן נרשם כאן מצב 2017 בלבד, ואין ייחוס של
        # השינוי לגרסה מאוחרת יותר; זה היה ממציא תאריך שלא נמדד.
        vs.insert(0, {'d': DATE, 'k': 'snapshot', 'src': SRC,
                      'stops': y['stops'], 'shp': y.get('shp', ''),
                      'note': 'מצב הקו ב-2017 — מארכיון TransitFeeds של הפיד הארצי '
                              'של משרד התחבורה. השינויים שבין 2017 לתיעוד הבא '
                              'אירעו בתאריכים שטרם נמדדו.'})
        lf['versions'] = vs
        json.dump(compact(lf), open(lp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        added += 1

    print(f'שולבו {added} קווים · דולגו {skipped} · ללא עמוד היום {missing}',
          file=sys.stderr)


if __name__ == '__main__':
    main()
