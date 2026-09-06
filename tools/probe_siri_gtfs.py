#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקת ההצמדה בין SIRI גולמי (stride-siri-requester) ל-GTFS של אותו יום —
לקראת מדד דיוק לאוטובוסים. מריצים ב-Actions (S3 חסום מהמכולה).

    python3 tools/probe_siri_gtfs.py 2026-09-01 gtfs.zip siri/08/00.br siri/08/01.br ...

בודק: DatedVehicleJourneyRef + '_' + ddmmyy == trip_id ב-trips.txt? LineRef ==
route_id של אותה נסיעה? StopPointRef ב-MonitoredCall == stop_code של התחנה
ב-stop_times לפי Order (stop_sequence)? וכמה רשומות "0" (בלי נסיעה מזוהה).
"""
import collections
import csv
import io
import json
import sys
import zipfile

import brotli

day, gtfs_path = sys.argv[1], sys.argv[2]
files = sys.argv[3:]
ddmmyy = day[8:10] + day[5:7] + day[2:4]

z = zipfile.ZipFile(gtfs_path)
print('GTFS:', [(i.filename, i.file_size) for i in z.infolist()])


def rows(name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))


trips = {}
for r in rows('trips.txt'):
    trips[r['trip_id']] = r['route_id']
print('trips:', len(trips), '· דוגמה:', next(iter(trips.items())))
stop_code = {}
stop_city = {}
for r in rows('stops.txt'):
    stop_code[r['stop_id']] = r['stop_code']
    d = r.get('stop_desc') or ''
    stop_city[r['stop_id']] = d
print('stops:', len(stop_code), '· stop_desc לדוגמה:', next(iter(stop_city.values())))

# הצמדה: מהקבצים נאספות הנסיעות שנצפו, ואז stop_times רק להן
visits = []
for fn in files:
    j = json.loads(brotli.decompress(open(fn, 'rb').read()))
    for d in j['Siri']['ServiceDelivery']['StopMonitoringDelivery']:
        for v in d.get('MonitoredStopVisit', []):
            mvj = v['MonitoredVehicleJourney']
            visits.append({
                'ref': mvj['FramedVehicleJourneyRef']['DatedVehicleJourneyRef'],
                'frame': mvj['FramedVehicleJourneyRef']['DataFrameRef'],
                'line': mvj['LineRef'], 'op': mvj['OperatorRef'],
                'dep': mvj.get('OriginAimedDepartureTime'),
                'stop': (mvj.get('MonitoredCall') or {}).get('StopPointRef'),
                'order': (mvj.get('MonitoredCall') or {}).get('Order'),
                'dist': (mvj.get('MonitoredCall') or {}).get('DistanceFromStop'),
                't': v['RecordedAtTime'],
            })
print('רשומות:', len(visits), 'מ-', len(files), 'דקות')
zero = sum(1 for v in visits if v['ref'] in ('0', '', None))
print('DatedVehicleJourneyRef == 0 (בלי נסיעה):', zero, f'({zero / max(len(visits), 1):.1%})')
frames = collections.Counter(v['frame'] for v in visits)
print('DataFrameRef:', frames.most_common(3))
refs = {v['ref'] for v in visits if v['ref'] not in ('0', '', None)}
hit_trip = sum(1 for r in refs if f'{r}_{ddmmyy}' in trips)
print(f'נסיעות ייחודיות: {len(refs)} · trip_id = ref_{ddmmyy} קיים ב-GTFS: {hit_trip} ({hit_trip / max(len(refs), 1):.1%})')
# LineRef == route_id?
same_route = diff_route = 0
ex = []
for v in visits:
    tid = f'{v["ref"]}_{ddmmyy}'
    if tid in trips:
        if trips[tid] == v['line']:
            same_route += 1
        else:
            diff_route += 1
            if len(ex) < 3:
                ex.append((v['line'], trips[tid], tid))
print(f'LineRef == route_id: {same_route} · שונה: {diff_route} · דוגמאות לשונה: {ex}')
# stop_times לנסיעות שנצפו: Order == stop_sequence? StopPointRef == stop_code?
want = {f'{r}_{ddmmyy}' for r in refs}
st = collections.defaultdict(dict)
n = 0
for r in rows('stop_times.txt'):
    if r['trip_id'] in want:
        st[r['trip_id']][int(r['stop_sequence'])] = (r['stop_id'], r['arrival_time'], r.get('shape_dist_traveled'))
        n += 1
print('stop_times לנסיעות שנצפו:', n, 'שורות ·', len(st), 'נסיעות')
ok = bad = nseq = 0
exb = []
for v in visits:
    tid = f'{v["ref"]}_{ddmmyy}'
    if tid not in st or not v['order']:
        continue
    seq = st[tid].get(int(v['order']))
    if not seq:
        nseq += 1
        continue
    if stop_code.get(seq[0]) == str(v['stop']):
        ok += 1
    else:
        bad += 1
        if len(exb) < 3:
            exb.append((tid, v['order'], v['stop'], stop_code.get(seq[0])))
print(f'StopPointRef תואם stop_code לפי Order: {ok} · לא תואם: {bad} · Order מחוץ לטווח: {nseq} · דוגמאות: {exb}')
seqs = sorted(next(iter(st.values())).items())[:3]
print('stop_sequence מתחיל ב:', seqs[0][0] if seqs else None, '· דוגמה:', seqs)
