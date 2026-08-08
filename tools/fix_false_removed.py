#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ניקוי אירועי "בוטל" שנרשמו בתאריך שגוי.

הסורק היומי מסמן כמבוטל כל וריאנט שאינו ברישום של היום. כשנכנסו לאתר
קווים ממילוי הארכיון — רכבת, מוניות שירות, וריאנטים היסטוריים — הוא מצא
קבצים שמעולם לא היו במצב היומי שלו וסימן את כולם "בוטל היום", אף שהם
נעלמו מהפיד שנים קודם.

התוצאה גרועה משתיקה: תאריך ביטול שגוי בשנים נראה כמו עובדה מדודה.

הכלי מסיר את האירועים האלה — רק כאלה שנרשמו בתאריך הריצה, רק בקווים
שאינם במצב הסורק היומי, ורק כשהם האירוע האחרון. הכלי אידמפוטנטי.

DRY=1 מדווח בלבד.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
SINCE = os.environ.get('SINCE', '2026-08-08')   # מהתאריך שבו התקלה נוצרה


def main():
    try:
        tracked = set(json.load(open(f'{OUTDIR}/state-routes.json', encoding='utf-8')))
    except Exception:
        raise SystemExit('אין state-routes.json — בלעדיו אי אפשר לדעת מה הסורק ראה')

    fixed = kept = 0
    gap_days = []
    for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
        if not fn.endswith('.json'):
            continue
        p = f'{OUTDIR}/lines/{fn}'
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = lf.get('versions') or []
        if not vs or vs[-1].get('k') != 'removed' or vs[-1].get('d') < SINCE:
            continue
        rd = lf.get('rd')
        if rd in tracked:
            kept += 1          # הסורק אכן ראה אותו חי — הביטול אמיתי
            continue
        if len(vs) > 1:
            a = datetime.date.fromisoformat(vs[-2]['d'])
            b = datetime.date.fromisoformat(vs[-1]['d'])
            gap_days.append((b - a).days)
        if not DRY:
            lf['versions'] = vs[:-1]
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
        fixed += 1

    mode = 'סימולציה' if DRY else 'בוצע'
    avg = sum(gap_days) // len(gap_days) if gap_days else 0
    print(f'{mode}: הוסרו {fixed} אירועי "בוטל" שגויים · {kept} ביטולים אמיתיים נשמרו',
          file=sys.stderr)
    if gap_days:
        print(f'       הפער בין האירוע הקודם ל"ביטול" היה בממוצע {avg} ימים '
              f'(מקסימום {max(gap_days)}) — כלומר התאריך היה שגוי בשנים',
              file=sys.stderr)


if __name__ == '__main__':
    main()
