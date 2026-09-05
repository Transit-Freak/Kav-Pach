#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מסלול משוער לקווי 2012 (רשת מגיעים) — קו על הכבישים במקום קו ישר בין תחנות.

בצילום 2012 נשמרו רק רצפי תחנות, בלי מסלול. כ-71% מהתחנות הוצלבו למק"ט של
היום ולכן יש להן מיקום (tools/match_2012.py). כאן מזינים את התחנות הממוקמות,
לפי הסדר, למנוע הניווט שלנו (OSRM עם פרופיל אוטובוס, tools/osrm/bus-il.lua,
על מפת ישראל של היום) ומקבלים נסיעה בכבישים דרך כולן. זו הערכה: הכבישים הם
של היום ולא של 2012, ותחנה שלא הוצלבה נעלמת מהחישוב (המסלול "קופץ" לתחנה
הידועה הבאה). לכן נשמרים גם מספר התחנות הידועות מתוך הכלל, והאתר מציג את
המסלול כ"משוער" עם המספרים.

    python3 tools/shape_2012.py --osrm http://localhost:5000 4-528x6 4-528x7
    python3 tools/shape_2012.py --osrm http://localhost:5000 --all

פלט: magihim-2012/data/shapes/l<key>.json —
  {"routes": {"<אינדקס המסלול בקובץ>": {"pl": polyline, "n": ידועות, "tot": כל
   התחנות, "m": אורך במטרים, "air": סכום המרחקים האוויריים בין התחנות}},
   "updated": תאריך, "src": "OSRM bus-il"}
מסלול שפחות ממחצית תחנותיו ידועות לא מחושב (הערכה גסה מדי). מסלול שאורכו
יותר מפי 2.2 מהאווירי נפסל (המנוע הלך סחור-סחור סביב תחנה שמוקמה בצד הלא
נכון של הכביש).
"""
import argparse
import datetime
import glob
import json
import math
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'magihim-2012', 'data')
OUT = os.path.join(DATA, 'shapes')
MIN_KNOWN = 0.5
MAX_RATIO = 2.2
CHUNK = 80          # נקודות ביניים לבקשה — מעבר לזה OSRM איטי מאוד


def hav(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


def osrm_route(base, pts, tries=3):
    """נסיעה דרך כל הנקודות (lat, lon) לפי הסדר — פוליליין precision 5 ואורך."""
    coords = ';'.join(f'{lon:.6f},{lat:.6f}' for lat, lon in pts)
    url = f'{base}/route/v1/driving/{coords}?overview=full&geometries=polyline&steps=false&continue_straight=false'
    for t in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                j = json.load(r)
            if j.get('code') != 'Ok' or not j.get('routes'):
                return None, j.get('code')
            rt = j['routes'][0]
            return rt['geometry'], rt['distance']
        except Exception as ex:  # noqa: BLE001
            if t == tries - 1:
                return None, repr(ex)
            time.sleep(2)
    return None, 'no answer'


def decode(pl):
    pts, i, la, lo = [], 0, 0, 0
    while i < len(pl):
        vals = []
        for _ in range(2):
            b, shift, result = 0x20, 0, 0
            while b >= 0x20:
                b = ord(pl[i]) - 63
                i += 1
                result |= (b & 0x1f) << shift
                shift += 5
            vals.append(~(result >> 1) if result & 1 else result >> 1)
        la += vals[0]
        lo += vals[1]
        pts.append((la, lo))
    return pts


def encode(pts):
    out, la, lo = [], 0, 0
    for a, b in pts:
        for v in (a - la, b - lo):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        la, lo = a, b
    return ''.join(out)


def drop_spikes(known):
    """תחנה שהוצלבה לעיר אחרת: רחוקה מעל 25 ק"מ משתי שכנותיה הידועות, בעוד
    שהן קרובות זו לזו יחסית לקפיצה. ההצלבה (build_magihim_site.py) מסננת
    את זה גם היא — כאן הגנה נוספת, כדי שמסלול של 300 ק"מ דרך קרית אתא לא
    יגיע למפה (שלמה 05.09, קו 1 ירושלים)."""
    out = list(known)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            a, c, b = out[i - 1], out[i], out[i + 1]
            da, db, dab = hav(c, a), hav(c, b), hav(a, b)
            if da > 25000 and db > 25000 and dab < max(5000, min(da, db) / 3):
                del out[i]
                changed = True
                break
    return out


def route_shape(base, stops):
    known = [(s[5], s[6]) for s in stops if len(s) >= 7 and s[5] and s[6]]
    tot = len(stops)
    known = drop_spikes(known)
    if tot < 2 or len(known) < 2 or len(known) / tot < MIN_KNOWN:
        return None, f'ידועות {len(known)}/{tot}'
    air = sum(hav(known[i - 1], known[i]) for i in range(1, len(known)))
    pts, dist = [], 0.0
    # מקטעים חופפים בנקודה אחת, כדי שהקו יהיה רציף
    i = 0
    while i < len(known) - 1:
        chunk = known[i:i + CHUNK]
        pl, d = osrm_route(base, chunk)
        if pl is None:
            return None, f'OSRM: {d}'
        seg = decode(pl)
        if pts and seg and seg[0] == pts[-1]:
            seg = seg[1:]
        pts.extend(seg)
        dist += d
        i += CHUNK - 1
    if air > 0 and dist > air * MAX_RATIO + 1500:
        return None, f'ארוך מדי ({dist / 1000:.1f} ק״מ מול {air / 1000:.1f} אווירי)'
    return {'pl': encode(pts), 'n': len(known), 'tot': tot, 'm': int(dist), 'air': int(air)}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('keys', nargs='*', help='מפתחות קווי 2012 (כמו 4-528x6); ריק עם --all = כל הקבצים')
    ap.add_argument('--osrm', required=True)
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--force', action='store_true', help='חישוב מחדש גם למה שכבר קיים')
    a = ap.parse_args()
    keys = a.keys
    if a.all:
        keys = sorted(os.path.basename(f)[1:-5] for f in glob.glob(os.path.join(DATA, 'l*.json')))
    if not keys:
        raise SystemExit('אין מפתחות')
    os.makedirs(OUT, exist_ok=True)
    today = datetime.date.today().isoformat()
    n_ok = n_skip = n_fail = 0
    t0 = time.time()
    for k in keys:
        src = os.path.join(DATA, f'l{k}.json')
        dst = os.path.join(OUT, f'l{k}.json')
        if not os.path.exists(src):
            print(f'{k}: אין קובץ')
            continue
        if os.path.exists(dst) and not a.force:
            n_skip += 1
            continue
        d = json.load(open(src, encoding='utf-8'))
        res = {}
        for i, r in enumerate(d.get('routes') or []):
            shape, why = route_shape(a.osrm.rstrip('/'), r.get('stops') or [])
            if shape:
                res[str(i)] = shape
                n_ok += 1
            else:
                n_fail += 1
                if not a.all:
                    print(f'  {k}/{i}: {why}')
        if res:
            json.dump({'routes': res, 'updated': today, 'src': 'OSRM bus-il'},
                      open(dst, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            if not a.all:
                for i, s in res.items():
                    print(f'  {k}/{i}: {s["n"]}/{s["tot"]} תחנות ידועות · {s["m"] / 1000:.1f} ק״מ (אווירי {s["air"] / 1000:.1f})')
    print(f'מסלולים: {n_ok} חושבו · {n_fail} לא · {n_skip} קבצים כבר היו · {time.time() - t0:.0f} שנ׳')


if __name__ == '__main__':
    main()
