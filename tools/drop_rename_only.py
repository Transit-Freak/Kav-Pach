#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""אירוע בקו שכל תוכנו הוא שינוי שם של תחנת הקצה — לא אירוע של הקו.

הסורק משווה את route_long_name, שהוא מחרוזת בנויה משמות תחנות הקצה.
כשעיריית רחובות שינתה "ת. רכבת רחובות" ל"ת. רכבת רחובות/רציפים עירוני",
המחרוזת השתנתה בכל קו שנוגע בתחנה — ובכל אחד מהם נרשם "היעד שוּנה".
הקו לא השתנה בשום צורה: אותו מק"ט, אותו מסלול, אותן תחנות. שינוי השם
מתועד בהיסטוריית התחנה, ושם מקומו.

fix_dest_kind כבר זיהה את המקרים האלה והחליף את הסיווג ל"שינוי שם תחנת
קצה", אבל השאיר אותם בציר הזמן של הקו. כאן הם יורדים ממנו:

  · אירוע בלי רצף תחנות, או עם רצף ושרטוט זהים לגרסה הקודמת — נמחק.
  · אירוע שבו המסלול באמת השתנה נשאר, אבל מסווג לפי מה שהשתנה בו
    (תחנות נוספו/ירדו/שונו, או תיקון שרטוט) במקום לפי שם היעד.

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
MARK = 'החלפת שם בלבד'


def codes(v):
    return [s[0] for s in (v.get('stops') or [])]


def reclass(prev, v):
    """הסיווג שמתאר את מה שבאמת השתנה בגרסה הזו."""
    a, b = set(codes(prev)), set(codes(v))
    if a != b:
        if b > a:
            return 'stops-add', 'תחנות נוספו למסלול'
        if b < a:
            return 'stops-del', 'תחנות ירדו מהמסלול'
        return 'stops', 'רצף התחנות שוּנה'
    if codes(prev) != codes(v):
        return 'stops', 'סדר התחנות שוּנה'
    return 'redraw', 'השרטוט שוּנה'


def main():
    n_del = n_keep = n_files = 0
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = lf.get('versions') or []
        out, dirty = [], False
        for i, v in enumerate(vs):
            if MARK not in (v.get('note') or ''):
                out.append(v)
                continue
            prev = next((vs[j] for j in range(i - 1, -1, -1) if vs[j].get('stops')), None)
            has = bool(v.get('stops') or v.get('shp'))
            if not has or (prev is not None and codes(prev) == codes(v)
                           and prev.get('shp') == v.get('shp')):
                n_del += 1
                dirty = True
                continue                      # שינוי שם בלבד — יורד מהקו
            if prev is None:
                out.append(v)
                continue
            k, why = reclass(prev, v)
            v['k'] = k
            v['note'] = f'{why} (שם תחנת הקצה שוּנה באותו יום, בלי קשר לשינוי)'
            n_keep += 1
            dirty = True
            out.append(v)
        if dirty:
            lf['versions'] = out
            n_files += 1
            if not DRY:
                json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_del} אירועי "שינוי שם תחנת קצה" הוסרו מהקווים · '
          f'{n_keep} סווגו מחדש לפי מה שבאמת השתנה · {n_files} קבצים',
          file=sys.stderr)


if __name__ == '__main__':
    main()
