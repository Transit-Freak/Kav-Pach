#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הצלבת מאגר "מגיעים" 2012 מול היסטוריית התחנות.

היסטוריית התחנות מתחילה ב-2017, כי שם מתחיל הארכיון. מאגר מגיעים שנשמר
כאן הוא מ-2012, ובו רצפי התחנות של 3,214 קווים — כלומר עדות ישירה לאילו
תחנות עצר בהן קו חמש שנים לפני תחילת הכיסוי שלנו.

שתי מסקנות נובעות ממנו, ושתיהן תיקון לטענות שכתובות היום באתר:

1. תחנה שסומנה "ברישום בלבד" ומופיעה במסלול של קו ב-2012 — הסימון שגוי
   לגביה. הוא נקבע מתוך הקווים שמתועדים אצלנו, וכאן יש הוכחה שקו כן עצר
   בה. הסימון יורד.

2. "תחנה חדשה" בתחנה שכבר הייתה ב-2012 אינה תחנה שנבנתה: היא חזרה לרישום
   אחרי היעדרות. האירוע נשאר — הוא קרה — אבל מקבל הערה שמסבירה זאת.

הסימון הוא m12 והוא נשען על מק"ט בלבד, כפי שהוא מופיע בשני המקורות.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי.
"""
import glob
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
M12DIR = os.environ.get('M12DIR', 'magihim-2012/data')
DRY = os.environ.get('DRY') == '1'


def m12_codes():
    """מק"טים שהופיעו ברצף התחנות של קו כלשהו ב-2012."""
    codes = set()
    for p in glob.glob(f'{M12DIR}/l*.json'):
        try:
            d = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        for r in d.get('routes') or []:
            for s in r.get('stops') or []:
                # [seq, שם, זמן, סוג עצירה, [מק"טים], lat, lon]
                if len(s) > 4 and isinstance(s[4], list):
                    for c in s[4]:
                        if c:
                            codes.add(str(c).strip())
    return codes


def main():
    codes = m12_codes()
    if len(codes) < 1000:
        raise SystemExit(f'רק {len(codes)} מק"טים מ-2012 — המאגר לא נקרא כראוי')

    hp = f'{OUTDIR}/stops-hist.json'
    hist = json.load(open(hp, encoding='utf-8'))
    n_st = n_cleared = n_new = 0
    for code, evs in hist.items():
        if code not in codes:
            continue
        n_st += 1
        for e in evs:
            if e.pop('ns', None):
                n_cleared += 1
            if not e.get('m12'):
                e['m12'] = 1
            if e['k'] == 'new':
                n_new += 1

    if not DRY:
        json.dump(hist, open(hp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        for p in glob.glob(f'{OUTDIR}/changes/stops-*.json'):
            d = json.load(open(p, encoding='utf-8'))
            ch = False
            for c in d['changes']:
                if c['c'] in codes:
                    if c.pop('ns', None):
                        ch = True
                    if not c.get('m12'):
                        c['m12'] = 1
                        ch = True
            if ch:
                json.dump(d, open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {len(codes)} מק"טים במגיעים 2012 · {n_st} מהם בהיסטוריה · '
          f'{n_cleared} אירועים איבדו את "ברישום בלבד" · '
          f'{n_new} אירועי "תחנה חדשה" קיבלו הערה', file=sys.stderr)


if __name__ == '__main__':
    main()
