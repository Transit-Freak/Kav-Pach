#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""תחנות ומסלול של 2017 — מארכיון TransitFeeds, לכל הקווים בבת אחת.

הצילום היחיד נסרק פעם אחת ומתוכו נשלפים כל הקווים; כך משיכה אחת (135MB)
משרתת אלפי קווים, במקום פנייה לכל קו בנפרד לשרת שאינו שלנו.

הפלט יושב בתיקייה נפרדת (data/y2017) ולא בקבצי הקווים — סריקות הרקע
כותבות לקבצי הקווים, וכך אין התנגשות. השילוב לציר הזמן ייעשה בהמשך.

פלט: line-history/data/y2017/<rd>.json  +  y2017-index.json
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import (central_dir, enc_polyline, fsafe,  # noqa: E402
                          member_rows, stream_member, thin)

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DAY = os.environ.get('DAY', '20170316')


def main():
    url = f'{BASE}/{DAY}/gtfs.zip'
    members = central_dir(url)
    print(f'צילום {DAY}: {len(members)} קבצים', file=sys.stderr)

    # מזהי המסלולים של הצילום → מפתח הווריאנט שלנו (מק"ט-כיוון-חלופה)
    c, rows = member_rows(url, members, 'routes.txt')
    rid2rd = {}
    for row in rows:
        rd = row[c['route_desc']].strip()
        if rd.count('-') >= 2:
            rid2rd[row[c['route_id']]] = rd
    print(f'מסלולים: {len(rid2rd)}', file=sys.stderr)

    # נסיעה מייצגת אחת לכל וריאנט — ממנה נגזרים רצף התחנות והשרטוט
    c, rows = member_rows(url, members, 'trips.txt')
    picked = {}
    for row in rows:
        rd = rid2rd.get(row[c['route_id']])
        if rd and rd not in picked:
            picked[rd] = (row[c['trip_id']], row[c['shape_id']] if 'shape_id' in c else '')
    print(f'נסיעות מייצגות: {len(picked)}', file=sys.stderr)

    trip2rd = {v[0].encode(): k for k, v in picked.items()}
    seqs, buf, hdr = {}, [b''], {}

    def on_st(data):
        buf[0] += data
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not hdr:
                for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr[h.strip()] = i
                continue
            f = ln.split(b',')
            try:
                rd = trip2rd.get(f[hdr['trip_id']].strip())
                if rd is None:
                    continue
                seqs.setdefault(rd, []).append((int(f[hdr['stop_sequence']]),
                                                f[hdr['stop_id']].decode()))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    print('קורא רצפי תחנות (הקובץ הכבד)...', file=sys.stderr)
    stream_member(url, members, 'stop_times.txt', on_st)
    print(f'וריאנטים עם רצף תחנות: {len(seqs)}', file=sys.stderr)

    need = {sid for lst in seqs.values() for _, sid in lst}
    c, rows = member_rows(url, members, 'stops.txt')
    sinfo = {}
    for row in rows:
        sid = row[c['stop_id']]
        if sid in need:
            sinfo[sid] = [row[c['stop_code']] or sid, row[c['stop_name']].strip(),
                          round(float(row[c['stop_lat']]), 5),
                          round(float(row[c['stop_lon']]), 5)]

    shp_wanted = {v[1] for v in picked.values() if v[1]}
    shp_pts, buf2, hdr2 = {}, [b''], {}

    def on_shp(data):
        buf2[0] += data
        *lines, buf2[0] = buf2[0].split(b'\n')
        for ln in lines:
            if not hdr2:
                for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr2[h.strip()] = i
                continue
            f = ln.split(b',')
            try:
                sid = f[hdr2['shape_id']].decode()
                if sid in shp_wanted:
                    shp_pts.setdefault(sid, []).append((int(f[hdr2['shape_pt_sequence']]),
                                                        float(f[hdr2['shape_pt_lat']]),
                                                        float(f[hdr2['shape_pt_lon']])))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    if shp_wanted:
        print('קורא שרטוטי מסלול...', file=sys.stderr)
        stream_member(url, members, 'shapes.txt', on_shp)

    out = f'{OUTDIR}/y2017'
    os.makedirs(out, exist_ok=True)
    iso = f'{DAY[:4]}-{DAY[4:6]}-{DAY[6:]}'
    written = 0
    index = {}
    for rd, lst in seqs.items():
        lst.sort()
        stops = [sinfo[sid] for _, sid in lst if sid in sinfo]
        if len(stops) < 2:
            continue
        pts = shp_pts.get(picked[rd][1]) or []
        pts.sort()
        shp = enc_polyline(thin([(p[1], p[2]) for p in pts])) if pts else ''
        json.dump({'d': iso, 'rd': rd, 'stops': stops, 'shp': shp},
                  open(f'{out}/{fsafe(rd)}.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        index[rd] = len(stops)
        written += 1

    json.dump({'d': iso, 'lines': index},
              open(f'{OUTDIR}/y2017-index.json', 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'נכתבו {written} קווים עם תחנות ומסלול', file=sys.stderr)


if __name__ == '__main__':
    main()
