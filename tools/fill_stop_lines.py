#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""השלמת "הקווים שעצרו בתחנה" באירועי תחנות מהארכיון.

באירועי התחנות שנבנו מהפיד היומי מופיעה שורת הקווים שעצרו בתחנה באותו
יום. באירועים שנבנו מהארכיון היא לא מופיעה בכלל, כי הסורק הארכיוני קרא
את stops.txt בלבד — קובץ קל שיש בו שם ומיקום, ואין בו שום קשר לקווים.

את הקשר הזה אין צורך להוריד שוב: הוא כבר יושב אצלנו. לכל וריאנט יש
גרסאות עם רצף התחנות שלו ותאריך, וכל גרסה תקפה עד הגרסה הבאה. תחנה
שנמצאת ברצף של וריאנט בתאריך מסוים — הקו הזה עצר בה אז.

גרסאות בלי רצף תחנות (שינוי תדירות, לוח זמנים) אינן משנות את הרצף
ולכן ממשיכות את הקודמת. גרסת "הקו נעלם" מאפסת אותו.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי, וממלא רק אירועים שאין בהם קווים.
"""
import bisect
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
END = '9999-99-99'


def lsort(n):
    """מיון קווים כמו שקוראים אותם: 1, 2, 10, 10א — ולא 1, 10, 10א, 2."""
    m = re.match(r'(\d+)(.*)', n or '')
    return (int(m.group(1)), m.group(2)) if m else (10 ** 9, n or '')


def main():
    hist = json.load(open(f'{OUTDIR}/stops-hist.json', encoding='utf-8'))
    want = {}                      # מק"ט -> תאריכים שצריך למלא
    for code, evs in hist.items():
        ds = sorted({e['d'] for e in evs if not e.get('lines')})
        if ds:
            want[code] = ds
    if not want:
        print('אין אירועי תחנות בלי קווים', file=sys.stderr)
        return
    n_ev = sum(len(v) for v in want.values())
    print(f'{n_ev} אירועים ב-{len(want)} תחנות מחכים לקווים', file=sys.stderr)

    found = {}                     # (מק"ט, תאריך) -> {קווים}
    files = glob.glob(f'{OUTDIR}/lines/*.json')
    for i, p in enumerate(files):
        if i % 2000 == 0:
            print(f'  {i}/{len(files)}', file=sys.stderr)
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        label = lf.get('line')
        if not label:
            continue
        # רצף התחנות של כל גרסה תקף עד הגרסה הבאה שמחליפה אותו
        spans, cur, since = [], None, None
        for v in sorted(lf.get('versions') or [], key=lambda x: x.get('d') or ''):
            if 'stops' not in v:
                continue           # תדירות/לוח זמנים — הרצף לא השתנה
            if cur:
                spans.append((since, v['d'], cur))
            cur, since = [s[0] for s in (v.get('stops') or []) if s and s[0]], v['d']
        if cur:
            spans.append((since, END, cur))
        for a, b, codes in spans:
            for c in codes:
                ds = want.get(c)
                if not ds:
                    continue
                for d in ds[bisect.bisect_left(ds, a):bisect.bisect_left(ds, b)]:
                    found.setdefault((c, d), set()).add(label)

    n_st = n_fill = 0
    for code, evs in hist.items():
        hit = False
        for e in evs:
            ls = found.get((code, e['d']))
            if ls and not e.get('lines'):
                e['lines'] = sorted(ls, key=lsort)
                n_fill += 1
                hit = True
        n_st += 1 if hit else 0

    if not DRY:
        json.dump(hist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        for p in glob.glob(f'{OUTDIR}/changes/stops-*.json'):
            d = json.load(open(p, encoding='utf-8'))
            ch = False
            for c in d['changes']:
                ls = found.get((c['c'], c['d']))
                if ls and not c.get('lines'):
                    c['lines'] = sorted(ls, key=lsort)
                    ch = True
            if ch:
                json.dump(d, open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_fill} אירועים קיבלו קווים ב-{n_st} תחנות · '
          f'{n_ev - n_fill} נשארו בלי — לא נמצא קו שעצר בהן באותו תאריך',
          file=sys.stderr)


if __name__ == '__main__':
    main()
