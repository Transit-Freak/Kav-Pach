#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""קובץ נפרד לכל תחנה — כדי שקישור לתחנה לא יוריד את כל ההיסטוריה.

קורות החיים של כל התחנות הם קובץ אחד של 4.5 מגה (750 קילובייט דחוסים).
כשנכנסים לקישור ‎#stop=14592‎ צריך מתוכו רשומה אחת בת 200 בייט, והדפדפן
הוריד ופענח את הכל — בסלולרי זה שניות של מסך ריק.

הפיצול הוא לפי שתי הספרות הראשונות של המק"ט: data/stops/<קידומת>.json.
קובץ לכל תחנה היה מדויק יותר אבל גם 18,600 קבצים, ו-74 מגה על הדיסק בגלל
גודל הבלוק — מאה קבצים של כמה עשרות קילובייט הם אותו שיפור בפועל.

הקובץ המלא נשאר לשימוש של "כל התקופה", שבה באמת צריך הכל.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי ומוחק שברים של תחנות שכבר אינן.
"""
import json
import os
import shutil
import sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def shard_of(code):
    """הקידומת שקובעת באיזה קובץ התחנה יושבת. חייבת להיות זהה בממשק."""
    return (code[:2] or '0').rjust(2, '0')


def main():
    hist = json.load(open(f'{OUTDIR}/stops-hist.json', encoding='utf-8'))
    d = f'{OUTDIR}/stops'
    have = set(os.listdir(d)) if os.path.isdir(d) else set()
    buckets = {}
    for code, evs in hist.items():
        buckets.setdefault(shard_of(code), {})[code] = evs
    want = {f'{b}.json' for b in buckets}
    n_w = n_d = 0

    if not DRY:
        os.makedirs(d, exist_ok=True)
        for b, part in buckets.items():
            body = json.dumps(part, ensure_ascii=False, separators=(',', ':'))
            p = f'{d}/{b}.json'
            # כתיבה רק כשהתוכן השתנה, אחרת כל ריצה מייצרת שינויים בגיט
            if os.path.exists(p) and open(p, encoding='utf-8').read() == body:
                continue
            open(p, 'w', encoding='utf-8').write(body)
            n_w += 1
        for stale in have - want:
            os.remove(f'{d}/{stale}')
            n_d += 1

    mode = 'סימולציה' if DRY else 'בוצע'
    big = max((len(json.dumps(v, ensure_ascii=False)) for v in buckets.values()),
              default=0)
    print(f'{mode}: {len(hist)} תחנות ב-{len(want)} קבצים · {n_w} נכתבו · '
          f'{n_d} נמחקו · הגדול ביותר {big // 1024} ק"ב', file=sys.stderr)
    if not DRY and len(want) > 300:
        # שמירה מפני פיצוץ מספר הקבצים אם מבנה המק"טים ישתנה
        shutil.rmtree(d)
        raise SystemExit('יותר מדי שברים — הפיצול בוטל')


if __name__ == '__main__':
    main()
