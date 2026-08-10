#!/usr/bin/env python3
# -*- coding: utf-8 -*-
""""וריאנט חדש" על קו שקיים שנים — תיעוד ראשון של המסלול, לא הופעה חדשה.

הצינור היומי סינן כל route_type שאינו אוטובוס, ולכן רכבת, רכבת קלה
ומוניות שירות נכנסו אליו רק כשהסינון תוקן. ביום שהוא ראה אותן לראשונה
הוא רשם "וריאנט חדש ברישום" — והרכבת הקלה של תל אביב, שקיימת בפיד
מ-21.03.2023, הוצגה כאילו נוספה באוגוסט 2026.

האירוע לא נמחק: סריקת הארכיון רושמת קיום בלבד, בלי רצף תחנות ובלי
שרטוט, ולכן הגרסה הזו היא היחידה שנושאת את המסלול — מחיקה הייתה משאירה
את הקו בלי מפה. במקום זה היא מסווגת כתיעוד ראשון של המסלול, וההופעה
המקורית נשארת בתאריך האמיתי שלה.

FROM  התאריך שממנו הצינור היומי כולל את הסוגים האלה (ברירת מחדל 25.07.2026)
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
FROM = os.environ.get('FROM', '2026-07-25')
START = {'new', 'baseline', 'snapshot'}


def main():
    n = 0
    seen_lines = []
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        if not lf.get('tt'):
            continue                      # אוטובוסים היו בצינור מלכתחילה
        vs = sorted(lf.get('versions') or [], key=lambda v: v['d'])
        live = False
        dirty = False
        for v in vs:
            k = v.get('k')
            if k in ('removed', 'removed-year'):
                live = False
                continue
            if k not in START:
                continue
            if live and k == 'new' and v['d'] >= FROM and (v.get('stops') or v.get('shp')):
                first = vs[0]['d']
                v['k'] = 'baseline'
                v['note'] = ('התיעוד הראשון של המסלול — הווריאנט קיים בפיד '
                             f'מ-{first[8:10]}.{first[5:7]}.{first[:4]}, אבל '
                             'הסריקה היומית כללה רק אוטובוסים עד כה')
                n += 1
                dirty = True
                seen_lines.append(f"{lf['rd']} ({lf['tt']})")
            live = True
        if dirty and not DRY:
            lf['versions'] = vs
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n} אירועי "וריאנט חדש" סווגו כתיעוד ראשון של המסלול',
          file=sys.stderr)
    for s in seen_lines:
        print('   ', s, file=sys.stderr)


if __name__ == '__main__':
    main()
