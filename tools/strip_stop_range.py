#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מחיקת אירועי תחנות בטווח תאריכים, לקראת סריקה מחדש.

היסטוריית התחנות מ-08.01.2023 עד 18.07.2026 נבנתה מ-API של אופן באס, והוא
מחזיר רק תחנות שמשויכות לקו. התוצאה: 0.3% מהתחנות שנוספו בתקופה הזו הן
"ברישום בלבד", מול 22% בכל מקור שקורא את הקובץ הגולמי. שלוש וחצי שנים בלי
תחנות הרישוי — בדיוק סוג התחנות שהכי מעניין כאן.

הקבצים הגולמיים של אופן באס כן מכילים אותן (4,309 תחנות ללא קו בצילום
של 03.06.2023), ולכן הטווח נסרק מחדש מהם. הכלי הזה מפנה את המקום.

FROM/TO · DRY=1 מדווח בלבד
"""
import glob
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
FROM = os.environ.get('FROM', '2023-01-08')
TO = os.environ.get('TO', '2026-07-18')


def main():
    hp = f'{OUTDIR}/stops-hist.json'
    hist = json.load(open(hp, encoding='utf-8'))
    n_ev = n_stop = 0
    for code, evs in list(hist.items()):
        keep = [e for e in evs if not (FROM <= e['d'] <= TO)]
        if len(keep) == len(evs):
            continue
        n_ev += len(evs) - len(keep)
        n_stop += 1
        if keep:
            hist[code] = keep
        else:
            del hist[code]

    n_mon = 0
    months = []
    for p in glob.glob(f'{OUTDIR}/changes/stops-*.json'):
        mo = os.path.basename(p)[6:13]
        if not (FROM[:7] <= mo <= TO[:7]):
            continue
        d = json.load(open(p, encoding='utf-8'))
        keep = [c for c in d['changes'] if not (FROM <= c['d'] <= TO)]
        if len(keep) == len(d['changes']):
            continue
        n_mon += 1
        months.append(mo)
        if not DRY:
            if keep:
                json.dump({'month': d['month'], 'changes': keep},
                          open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
            else:
                os.remove(p)

    if not DRY:
        json.dump(hist, open(hp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        # months.json נבנה מחדש מהקבצים שנשארו, אחרת נשארים חודשים ריקים
        mp = f'{OUTDIR}/months.json'
        mj = json.load(open(mp, encoding='utf-8'))
        have = {os.path.basename(x)[6:13] for x in glob.glob(f'{OUTDIR}/changes/stops-*.json')}
        mj['stopMonths'] = sorted(have, reverse=True)
        json.dump(mj, open(mp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_ev} אירועי תחנות בטווח {FROM}–{TO} נמחקו · '
          f'{n_stop} תחנות נגעו · {n_mon} קובצי חודש עודכנו', file=sys.stderr)


if __name__ == '__main__':
    main()
