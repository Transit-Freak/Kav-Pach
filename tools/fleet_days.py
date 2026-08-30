#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — ימי הפעילות שנמדדו וסך הנסיעות של כל רכב.

הצעת הסוקר (30.08): רכב שירד מהשירות מעניין כמה ימים הוא בכלל פעל
לפני כן — הופעה של יום אחד וחזרה להשבתה שונה משירות רצוף. הנתונים
כבר נצברים בקובץ המצב של הסריקה; כאן הם נחשפים לאתר:
fleet/data/fleet-days.json — {'d': {'מפעיל:לוחית': [ימי פעילות, סך נסיעות]}}
"""
import datetime
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'fleet/data')


def main():
    state = json.load(open(f'{OUTDIR}/fleet-state.json', encoding='utf-8'))['vehicles']
    fleet = json.load(open(f'{OUTDIR}/fleet.json', encoding='utf-8'))
    out = {}
    for op in fleet['operators']:
        for v in op['vehicles']:
            key = f"{op['ref']}:{v[0]}"
            st = state.get(key)
            if st and len(st) > 3 and st[3]:
                out[key] = [st[3], st[2]]
    res = {'updated': datetime.date.today().isoformat(), 'd': out}
    tmp = f'{OUTDIR}/fleet-days.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, f'{OUTDIR}/fleet-days.json')
    print(f'ימי פעילות: {len(out)} רכבים', flush=True)


if __name__ == '__main__':
    sys.exit(main())
