#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מסלולי הרכבת (צורות ה-GTFS) — כדי שמפת הנסיעה במדד אמינות הרכבת תראה
את המסילה עצמה ולא קו ישר בין תחנות (הכלל של שלמה: מסלול מפורט, לא רק תחנות).

קורא מארכיון ה-GTFS היומי של אופן באס (ריצה במכונת Actions בלבד): מזהי
המסלולים של רכבת ישראל (agency 2) → shape_id של כל מסלול (trips.txt) →
הנקודות (shapes.txt, בזרימה). התוצר rail/data/shapes.json: {route_id: פוליליין
מקודד} — route_id הוא ה-line_ref של דאטאבוס. מסלולים שכבר בקובץ נשמרים;
הריצה מדלגת כשכל מסלולי היום האחרון כבר בקובץ והוא בן פחות מ-30 יום.
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, enc_polyline, member_rows, stream_member  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'rail/data')
OUT = f'{OUTDIR}/shapes.json'
S3GTFS = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
          '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
AGENCY = '2'
MAX_AGE_DAYS = 30
FORCE = os.environ.get('FORCE') == '1'


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return d


def needed_lines():
    """line_ref-ים של היום האחרון שעובד — מהקובץ היומי האחרון."""
    days = sorted(f for f in os.listdir(f'{OUTDIR}/days') if f.endswith('.json')) if os.path.isdir(f'{OUTDIR}/days') else []
    if not days:
        return set(), None
    day = jload(f'{OUTDIR}/days/{days[-1]}', {})
    return {str(r['ln']) for r in day.get('rides', []) if r.get('ln') is not None}, days[-1][:-5]


def main():
    cur = jload(OUT, {})
    shapes = cur.get('shapes', {})
    need, day = needed_lines()
    missing = need - set(shapes)
    age = (time.time() - os.path.getmtime(OUT)) / 86400 if os.path.exists(OUT) else 1e9
    if not FORCE and not missing and age < MAX_AGE_DAYS:
        print(f'מסלולים: {len(shapes)} בקובץ, כולם מכוסים ({age:.0f} ימים) — אין צורך בריצה')
        return
    # הארכיון של היום שעובד (או אתמול) — אותו לו"ז שממנו נמדדו הנסיעות
    d = datetime.date.fromisoformat(day) if day else datetime.date.today() - datetime.timedelta(days=1)
    url = None
    for back in range(0, 4):
        dd = d - datetime.timedelta(days=back)
        u = S3GTFS.format(y=dd.year, m=f'{dd.month:02d}', d=f'{dd.day:02d}')
        try:
            members = central_dir(u)
            url = u
            break
        except Exception as e:  # noqa: BLE001
            print(f'  {dd}: אין ארכיון ({e})')
    if not url:
        raise SystemExit('אין ארכיון GTFS זמין')
    print(f'ארכיון: {url}')
    c, rows = member_rows(url, members, 'routes.txt')
    rail = {r[c['route_id']].strip() for r in rows if r[c['agency_id']].strip() == AGENCY}
    print(f'מסלולי רכבת ב-routes.txt: {len(rail)} · חסרים בקובץ: {len(missing)}')
    c, rows = member_rows(url, members, 'trips.txt')
    cnt = {}
    for r in rows:
        rid = r[c['route_id']].strip()
        if rid in rail:
            sid = r[c['shape_id']].strip()
            if sid:
                cnt.setdefault(rid, {}).setdefault(sid, 0)
                cnt[rid][sid] += 1
    shape_of = {rid: max(v.items(), key=lambda kv: kv[1])[0] for rid, v in cnt.items()}
    want = set(shape_of.values())
    pts = {}
    buf = [b'']

    def cb(chunk):
        data = buf[0] + chunk
        lines = data.split(b'\n')
        buf[0] = lines.pop()
        for ln in lines:
            parts = ln.decode('utf-8', 'ignore').rstrip('\r').split(',')
            if len(parts) < 4 or parts[0] not in want:
                continue
            try:
                pts.setdefault(parts[0], []).append((int(parts[3]), float(parts[1]), float(parts[2])))
            except ValueError:
                continue

    # shapes.txt: shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence
    stream_member(url, members, 'shapes.txt', cb)
    if buf[0]:
        cb(b'\n')
    n_new = 0
    for rid, sid in shape_of.items():
        p = pts.get(sid)
        if not p:
            continue
        p.sort()
        enc = enc_polyline([(la, lo) for _, la, lo in p])
        if shapes.get(rid) != enc:
            n_new += 1
        shapes[rid] = enc
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump({'updated': datetime.date.today().isoformat(), 'archive': url, 'shapes': shapes},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    still = need - set(shapes)
    print(f'נשמרו {len(shapes)} מסלולים ({n_new} חדשים/עודכנו) · עדיין חסרים: {len(still)} {sorted(still)[:10]}')


if __name__ == '__main__':
    main()
