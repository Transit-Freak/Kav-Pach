#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""השלמת "הוזזה מ־" באירועי הזזה שנוצרו מהארכיון.

הסורק הארכיוני רשם באירוע הזזה רק את המיקום החדש ואת המרחק, בעוד הממשק
מציג "הוזזה מ־(א) ← (ב)". התוצאה הייתה שורה עם חצים ריקים משני הצדדים:
"הוזזה מ׳ · (, ) ← (31.72769, 34.73929)".

המיקום הישן לא אבד — הוא יושב בצילום שקדם לאירוע. הכלי מאתר לכל תאריך
הזזה את הצילום הקודם ברשימת הצילומים, קורא ממנו את התחנות הרלוונטיות,
ומשלים ola/olo/dist בשמות שהממשק קורא.

הקריאה היא מהצילום הקודם ולא מהאירוע הקודם של אותה תחנה בכוונה: לתחנה
שנצפתה כבר בצילום הראשון אין אירוע "חדשה", ולתחנות אחרות ההפרש בין
האירועים הוא חודשים.

MAX_MIN תקציב זמן · DRY=1 מדווח בלבד. הכלי אידמפוטנטי וממשיך מהמצב שנשמר.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_stops_tf import dist_m, snap_stops  # noqa: E402
from backfill_tf import iso  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))


def main():
    days = [l.strip() for l in open(f'{OUTDIR}/tf-days.txt') if l.strip()]
    idx = {iso(d): i for i, d in enumerate(days)}

    hp = f'{OUTDIR}/stops-hist.json'
    hist = json.load(open(hp, encoding='utf-8'))
    need = {}
    for code, evs in hist.items():
        for e in evs:
            if e['k'] == 'moved' and not e.get('ola'):
                need.setdefault(e['d'], set()).add(code)
    if not need:
        print('אין אירועי הזזה חסרי מיקום קודם', file=sys.stderr)
        return
    print(f'{sum(len(v) for v in need.values())} אירועי הזזה ב-{len(need)} תאריכים',
          file=sys.stderr)

    fixed = {}                       # (code, date) -> [ola, olo, dist]
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    miss = 0
    for d in sorted(need):
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר — מה שהושלם נשמר', file=sys.stderr)
            break
        i = idx.get(d)
        if not i:                    # אין צילום קודם — אין ממה לגזור
            miss += len(need[d])
            continue
        try:
            prev = snap_stops(days[i - 1])
        except BaseException as e:
            print(f'  {d}: דילוג — {type(e).__name__}', file=sys.stderr)
            continue
        for code in need[d]:
            o = prev.get(code)
            if not o:
                miss += 1
                continue
            for e in hist[code]:
                if e['d'] == d and e['k'] == 'moved':
                    dm = round(dist_m(o[2], o[3], e['la'], e['lo']))
                    fixed[(code, d)] = [o[2], o[3], dm]

    if not fixed:
        print('לא הושלם דבר', file=sys.stderr)
        return

    for (code, d), (ola, olo, dm) in fixed.items():
        for e in hist[code]:
            if e['d'] == d and e['k'] == 'moved':
                e['ola'], e['olo'], e['dist'] = ola, olo, dm
                e.pop('m', None)

    if not DRY:
        json.dump(hist, open(hp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        months = {d[:7] for _, d in fixed}
        for mo in sorted(months):
            p = f'{OUTDIR}/changes/stops-{mo}.json'
            if not os.path.exists(p):
                continue
            j = json.load(open(p, encoding='utf-8'))
            ch = False
            for c in j['changes']:
                v = fixed.get((c['c'], c['d']))
                if v and c['k'] == 'moved':
                    c['ola'], c['olo'], c['dist'] = v
                    c.pop('m', None)
                    ch = True
            if ch:
                json.dump(j, open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {len(fixed)} אירועי הזזה קיבלו מיקום קודם · '
          f'{miss} לא נמצאו בצילום הקודם', file=sys.stderr)


if __name__ == '__main__':
    main()
