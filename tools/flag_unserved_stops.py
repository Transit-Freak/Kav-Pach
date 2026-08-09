#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סימון תחנות שאף קו לא עצר בהן.

הסורק קורא את stops.txt, שהוא רישום התחנות — ולא רשימת התחנות שבשירות.
חלק מהרשומות שם מעולם לא נכללו במסלול של אף קו: הן קיימות על הנייר בלבד.
מי שרואה "תחנה חדשה" מבין שנוספה תחנה שאפשר לחכות בה, וזה לא נכון לגביהן.

הבדיקה נשענת על קבצי הקווים שכבר קיימים: כל מק"ט שהופיע אי-פעם ברצף
התחנות של גרסה כלשהי נחשב "בשירות". התחנות שלא — מסומנות ב-'ns'.

הסימון ולא המחיקה בכוונה: העובדה שרשומה נוצרה ברישום היא מידע אמיתי,
והכיסוי שלנו אינו מושלם — מחיקה הייתה מוחקת גם מה שאולי כן שורת.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def main():
    served = set()
    for p in glob.glob(f'{OUTDIR}/lines/*.json'):
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        for v in lf.get('versions') or []:
            for s in (v.get('stops') or []):
                if s and s[0]:
                    served.add(str(s[0]))
    if not served:
        raise SystemExit('לא נמצאו רצפי תחנות — אין על מה להסתמך')

    hp = f'{OUTDIR}/stops-hist.json'
    hist = json.load(open(hp, encoding='utf-8'))
    n_st = n_ev = 0
    for code, evs in hist.items():
        if code in served:
            for e in evs:
                e.pop('ns', None)        # חזרה לשירות מבטלת סימון קודם
            continue
        n_st += 1
        for e in evs:
            if not e.get('ns'):
                e['ns'] = 1
                n_ev += 1

    if not DRY:
        json.dump(hist, open(hp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        for p in glob.glob(f'{OUTDIR}/changes/stops-*.json'):
            d = json.load(open(p, encoding='utf-8'))
            ch = False
            for c in d['changes']:
                want = 1 if c['c'] not in served else None
                if want and not c.get('ns'):
                    c['ns'] = 1; ch = True
                elif not want and c.pop('ns', None):
                    ch = True
            if ch:
                json.dump(d, open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_st} תחנות שאף קו לא עצר בהן · {n_ev} אירועים סומנו · '
          f'{len(served)} מק"טים בשירות', file=sys.stderr)


if __name__ == '__main__':
    main()
