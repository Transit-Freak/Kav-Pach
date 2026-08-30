#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — נפילות-וחזרות: רכבים שנעלמו חודש קלנדרי מלא וחזרו לשדר.

רעיון שלמה (30.08): "הרכב הכי מקולקל" — היעלמות של חודש+ וחזרה היא
סימן מובהק לתקלה ממושכת/מוסך (או השאלה בין מפעילים). מקור: מסיכות
חודשי-הפעילות שנאספות בסריקה. נבדק רק הטווח שכבר מולא במלואו
(months_done ואילך) — כדי שחודש שטרם נסרק לא ייספר כתקלה.

הפלט: fleet/data/fleet-gaps.json —
{'from': חודש-תחילת-הכיסוי, 'g': {'מפעיל:לוחית': [['מחודש','עד-חודש'],...]}}
"""
import datetime
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'fleet/data')
MBASE = 2020 * 12


def ym(idx):
    t = MBASE + idx
    return f'{t // 12}-{t % 12 + 1:02d}'


def main():
    root = json.load(open(f'{OUTDIR}/fleet-state.json', encoding='utf-8'))
    st = root['vehicles']
    fleet = json.load(open(f'{OUTDIR}/fleet.json', encoding='utf-8'))
    md = root.get('months_done')
    if not md:
        print('אין עדיין מסיכות חודשים — אין מה לחשב')
        return
    upd = fleet['updated']
    # החודש הראשון המכוסה במלואו — החודש שאחרי גבול המילוי (הגבול עצמו חלקי)
    lo = int(md[:4]) * 12 + int(md[5:7]) - 1 - MBASE + 1
    # עד החודש שלפני חודש-העדכון (החודש הנוכחי תמיד חלקי)
    hi = int(upd[:4]) * 12 + int(upd[5:7]) - 1 - MBASE - 1
    if hi - lo < 1:
        print('טווח מכוסה קצר מדי')
        return
    gaps_out = {}
    for op in fleet['operators']:
        for v in op['vehicles']:
            key = f"{op['ref']}:{v[0]}"
            s = st.get(key)
            if not s or len(s) < 6 or not s[5]:
                continue
            bits = [(s[5] >> i) & 1 for i in range(lo, hi + 1)]
            if sum(bits) == 0:
                continue
            eps = []
            i = 0
            while i < len(bits):
                if bits[i] == 1:
                    j = i + 1
                    while j < len(bits) and bits[j] == 0:
                        j += 1
                    if j < len(bits) and j - i - 1 >= 1:   # חור של חודש+ ואז חזרה
                        eps.append([ym(lo + i + 1), ym(lo + j - 1)])
                    i = j
                else:
                    i += 1
            if eps:
                gaps_out[key] = eps
    res = {'updated': datetime.date.today().isoformat(),
           'from': ym(lo), 'to': ym(hi), 'g': gaps_out}
    tmp = f'{OUTDIR}/fleet-gaps.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, f'{OUTDIR}/fleet-gaps.json')
    print(f'נפילות-וחזרות: {len(gaps_out)} רכבים · טווח {ym(lo)} ← {ym(hi)}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
