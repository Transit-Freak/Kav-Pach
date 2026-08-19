#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — שיוך רכבים לערים.

לכל רכב נשמרים בסריקה הקווים (line_ref) שבהם שידר. כאן ממפים כל קו
לערי המוצא והיעד שלו מתוך routes.txt של ה-GTFS היומי (בבקשות Range,
בלי להוריד את כל הקובץ), ובונים תמונת-עיר: כמה רכבים שונים פועלים
בכל עיר, מאילו חברות ומאילו שנתונים.

route_long_name בפורמט "תחנה-עיר<->תחנה-עיר-מק" — העיר היא הרכיב
האחרון בכל צד. הפלט: fleet/data/fleet-cities.json.
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402

S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
OUTDIR = os.environ.get('OUTDIR', 'fleet/data')
STATE = f'{OUTDIR}/fleet-state.json'
FLEET = f'{OUTDIR}/fleet.json'
OUT = f'{OUTDIR}/fleet-cities.json'


def route_cities():
    """route_id (=line_ref בסירי) → קבוצת ערים, מתוך ה-GTFS של אתמול."""
    day = datetime.date.today() - datetime.timedelta(days=1)
    url = S3.format(y=day.year, m=f'{day.month:02d}', d=f'{day.day:02d}')
    c, rows = member_rows(url, central_dir(url), 'routes.txt')
    out = {}
    for r in rows:
        rid = r[c['route_id']]
        name = (r[c['route_long_name']] or '')
        cities = set()
        for side in name.split('<->'):
            # קיצוץ סיומת מק"ט/כיוון/חלופה: "-12165-1#", "-2#", "-1ב" — לא ערים
            side = re.sub(r'(-\d+[א-ת]?#?\s*)+$', '', side).strip()
            if '-' in side:
                city = side.rsplit('-', 1)[1].strip()
                if city:
                    cities.add(city)
        if cities:
            out[rid] = cities
    print(f'GTFS: {len(out)} מסלולים עם ערים', flush=True)
    return out


def main():
    with open(STATE, encoding='utf-8') as f:
        state = json.load(f)['vehicles']
    with open(FLEET, encoding='utf-8') as f:
        fleet = json.load(f)
    # שנת ייצור לפי לוחית (אחרי העשרה, פורמט v2: שנה במקום 4)
    ybase = 4 if fleet.get('v') == 2 else 3
    year_of = {}
    # נספרים רק רכבים שמופיעים באתר עצמו (מפעילי אוטובוסים אמיתיים,
    # מאומתים מול מאגר הרישוי) — בלי רכבת/רק"ל ובלי מזהים פנימיים
    allowed = set()
    for op in fleet['operators']:
        for v in op['vehicles']:
            key = f"{op['ref']}:{v[0]}"
            allowed.add(key)
            if len(v) > ybase and v[ybase]:
                year_of[key] = v[ybase]

    rc = route_cities()
    cities = {}
    linked = 0
    for key, vals in state.items():
        if key not in allowed:
            continue
        lines = vals[4] if len(vals) > 4 else []
        if not lines:
            continue
        op = int(key.split(':', 1)[0])
        vset = set()
        for ln in lines:
            vset |= rc.get(str(ln), set())
        if vset:
            linked += 1
        for city in vset:
            ct = cities.setdefault(city, {'total': 0, 'ops': {}, 'years': {}})
            ct['total'] += 1
            ct['ops'][op] = ct['ops'].get(op, 0) + 1
            y = year_of.get(key)
            if y:
                ct['years'][str(y)] = ct['years'].get(str(y), 0) + 1

    # רק ערים עם נוכחות ממשית, ממוינות לפי גודל
    out = {'updated': datetime.date.today().isoformat(),
           'cities': {c: {'total': d['total'],
                          'ops': sorted(d['ops'].items(), key=lambda x: -x[1]),
                          'years': d['years']}
                      for c, d in cities.items() if d['total'] >= 3}}
    tmp = f'{OUT}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f'ערים: {len(out["cities"])} · רכבים משויכים: {linked}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
