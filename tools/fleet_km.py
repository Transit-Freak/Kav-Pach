#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — הערכת קילומטראז' לכל רכב.

לכל רכב נשמרים בסריקה הקווים שבהם שידר, סך הנסיעות שנמדדו ומספר ימי
הפעילות. אורך המסלול של כל קו נלקח משרטוטי "הקו בזמן" שכבר בריפו
(הגרסה העדכנית ביותר עם שרטוט של כל וריאנט), והמיפוי line_ref→מק"ט
מגיע מ-routes.txt של ה-GTFS היומי בארכיון S3 (בבקשות Range — לא נוגע
ב-API של דאטאבוס). ההערכה גסה במכוון: לא ידוע כמה נסיעות בוצעו בכל
קו, לכן ממוצע אורכי הקווים של הרכב × הנסיעות שנמדדו.

הפלט: fleet/data/fleet-km.json —
{'km': {'מפעיל:לוחית': [ק"מ ליום פעילות, ק"מ סה"כ שנמדדו, קווים שזוהו]}}
"""
import datetime
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402
from backfill_change_segs import dec_polyline  # noqa: E402
from compact_lines import materialize  # noqa: E402

S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
OUTDIR = os.environ.get('OUTDIR', 'fleet/data')
LINES = os.environ.get('LINES_DIR', 'line-history/data/lines')
STATE = f'{OUTDIR}/fleet-state.json'
FLEET = f'{OUTDIR}/fleet.json'
OUT = f'{OUTDIR}/fleet-km.json'


def route_desc_map():
    """line_ref (=route_id) → route_desc "מקט-כיוון-חלופה", מה-GTFS של אתמול."""
    day = datetime.date.today() - datetime.timedelta(days=1)
    url = S3.format(y=day.year, m=f'{day.month:02d}', d=f'{day.day:02d}')
    c, rows = member_rows(url, central_dir(url), 'routes.txt')
    out = {}
    for r in rows:
        d = (r[c['route_desc']] or '').strip()
        if d:
            out[r[c['route_id']]] = d
    print(f'routes.txt: {len(out)} מסלולים ממופים למק"ט', flush=True)
    return out


def hav_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(h))


_len_cache = {}


def desc_km(desc):
    """אורך המסלול בק"מ מהשרטוט העדכני ביותר בקו בזמן; None אם אין."""
    if desc in _len_cache:
        return _len_cache[desc]
    km = None
    p = os.path.join(LINES, desc.replace('#', 'H').replace('/', '_') + '.json')
    try:
        lf = materialize(json.load(open(p, encoding='utf-8')))
        for v in sorted(lf.get('versions') or [],
                        key=lambda x: x.get('d', ''), reverse=True):
            if v.get('shp'):
                pts = dec_polyline(v['shp'])
                if len(pts) > 1:
                    km = sum(hav_km(pts[i], pts[i + 1])
                             for i in range(len(pts) - 1))
                break
    except Exception:  # noqa: BLE001 — וריאנט בלי קובץ: פשוט בלי אורך
        pass
    _len_cache[desc] = km
    return km


def main():
    with open(STATE, encoding='utf-8') as f:
        state = json.load(f)['vehicles']
    with open(FLEET, encoding='utf-8') as f:
        fleet = json.load(f)
    allowed = {f"{op['ref']}:{v[0]}"
               for op in fleet['operators'] for v in op['vehicles']}
    rd_map = route_desc_map()
    out, no_lines, no_len = {}, 0, 0
    for key, vals in state.items():
        if key not in allowed:
            continue
        lines = vals[4] if len(vals) > 4 else []
        rides = vals[2] if len(vals) > 2 else 0
        dcount = vals[3] if len(vals) > 3 else 0
        if not lines or not rides:
            no_lines += 1
            continue
        ls = []
        for ln in lines:
            desc = rd_map.get(str(ln))
            if desc:
                km = desc_km(desc)
                if km:
                    ls.append(km)
        if not ls:
            no_len += 1
            continue
        avg_len = sum(ls) / len(ls)
        km_day = round(rides / dcount * avg_len) if dcount else None
        out[key] = [km_day, round(rides * avg_len), len(ls)]
    res = {'updated': datetime.date.today().isoformat(), 'km': out}
    tmp = f'{OUT}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f"קילומטראז': {len(out)} רכבים · בלי קווים/נסיעות: {no_lines}"
          f' · קווים בלי אורך: {no_len}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
