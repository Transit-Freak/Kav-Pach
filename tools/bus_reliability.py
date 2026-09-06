#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מדד דיוק האוטובוסים — מ-SIRI גולמי של דאטאבוס ו-GTFS של משרד התחבורה.

מקור בזמן אמת: stride-siri-requester ב-S3 של דאטאבוס — תשובת משרד התחבורה
(SIRI SM) לכל דקה, כל הרכבים בארץ: קובץ Brotli לדקה (~230KB דחוס בשיא, ~4MB
פרוס, ~8,500 רכבים). לכל רכב: LineRef (= route_id ב-GTFS), DatedVehicleJourneyRef
(= trip_id בלי סיומת התאריך), OriginAimedDepartureTime, VehicleLocation,
MonitoredCall {StopPointRef = מק"ט התחנה הבאה, Order = מספרה הסידורי, DistanceFromStop
במטרים}. הורדה מ-S3 אינה מעמיסה על שרת ה-API של דאטאבוס (אישור המיזם 06.09).

שיטה: לכל נסיעה (מפתח: יום המסגרת + מזהה הנסיעה) עוקבים אחרי Order: כשהוא
עולה מ-k ל-k+1 הרכב עבר את תחנה k בין שתי הדגימות, וזמן המעבר משוערך
בקו ישר לפי DistanceFromStop והמרחק בין התחנות (shape_dist_traveled).
דגימה עם DistanceFromStop קטן ממש היא הגעה. איחור = זמן המעבר פחות
זמן ההגעה המתוכנן ב-stop_times. קטגוריות: מוקדם (<-2 דק׳), בזמן (-2..5),
5–10, 10–20, מעל 20. נסיעה עם DatedVehicleJourneyRef=0 (בלי מזהה) מוצמדת לפי
route_id + שעת היציאה המתוכננת.

    python3 tools/bus_reliability.py --day 2026-09-01 --gtfs gtfs.zip --siri siri/ --out bus/data

ב-siri/ מצופים קבצי HH/MM.br של היום ושל שלוש השעות הראשונות של מחרת
(נסיעות אחרי חצות שייכות ליום השירות הקודם — לפי DataFrameRef).
פלט: bus/data/days/YYYY-MM-DD.json (מצומצם), bus/data/routes.json (קטלוג),
bus/data/index.json.
"""
import argparse
import collections
import csv
import datetime
import io
import json
import math
import os
import statistics
import sys
import zipfile
from multiprocessing import Pool

try:
    import brotli
except ImportError:  # noqa
    brotli = None

FMT = 1
EARLY, ONTIME, L5, L10, L20 = range(5)          # אינדקסים בקטגוריות
BUCKETS = [(-120, 'early'), (300, 'ontime'), (600, 'l5'), (1200, 'l10'), (10 ** 9, 'l20')]
MAX_ABS = 90 * 60                                # איחור/הקדמה מעבר לזה — הצמדה שגויה
ARRIVE_M = 25                                    # DistanceFromStop עד כאן = הגעה
MIN_STOPS_RIDE = 2


def cat(delay):
    if delay < -120:
        return EARLY
    if delay <= 300:
        return ONTIME
    if delay <= 600:
        return L5
    if delay <= 1200:
        return L10
    return L20


def hms(s):
    """"HH:MM:SS" (יכול לעבור 24) → שניות מחצות של יום השירות."""
    h, m, sec = s.split(':')
    return int(h) * 3600 + int(m) * 60 + int(sec)


def hav(a, b):
    r = 6371000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(x))


# ---------------------------------------------------------------- GTFS
def load_gtfs(path, day):
    z = zipfile.ZipFile(path)

    def rows(name):
        with z.open(name) as f:
            yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig'))

    d = datetime.date.fromisoformat(day)
    wd = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'][(d.weekday() + 1) % 7]
    ymd = day.replace('-', '')
    services = set()
    for r in rows('calendar.txt'):
        if r['start_date'] <= ymd <= r['end_date'] and r.get(wd) == '1':
            services.add(r['service_id'])
    try:
        for r in rows('calendar_dates.txt'):
            if r['date'] == ymd:
                (services.add if r['exception_type'] == '1' else services.discard)(r['service_id'])
    except KeyError:
        pass
    agencies = {r['agency_id']: r['agency_name'] for r in rows('agency.txt')}
    routes = {}
    for r in rows('routes.txt'):
        desc = (r.get('route_desc') or '').split('-')
        routes[r['route_id']] = {
            'mkt': desc[0] if desc else '', 'dir': desc[1] if len(desc) > 1 else '', 'alt': desc[2] if len(desc) > 2 else '',
            'short': r.get('route_short_name') or '', 'long': r.get('route_long_name') or '',
            'agency': agencies.get(r['agency_id'], r['agency_id']), 'type': r.get('route_type') or '',
        }
    trips = {}          # trip_id → route_id (רק שירותים פעילים היום)
    by_num = {}         # מספר הנסיעה (לפני '_') → trip_id
    for r in rows('trips.txt'):
        if r['service_id'] in services:
            trips[r['trip_id']] = r['route_id']
            by_num[r['trip_id'].split('_')[0]] = r['trip_id']
    stops = {}
    for r in rows('stops.txt'):
        desc = r.get('stop_desc') or ''
        city = ''
        if 'עיר:' in desc:
            city = desc.split('עיר:', 1)[1].split('רציף:')[0].split('קומה:')[0].strip()
        stops[r['stop_id']] = (r['stop_code'], r['stop_name'], float(r['stop_lat'] or 0), float(r['stop_lon'] or 0), city)
    return {'routes': routes, 'trips': trips, 'by_num': by_num, 'stops': stops, 'zip': z}


def load_stop_times(g, want_trips):
    """רצף התחנות של הנסיעות המבוקשות: trip_id → רשימה לפי stop_sequence של
    (stop_id, arrival_sec, departure_sec, shape_dist)."""
    z = g['zip']
    st = collections.defaultdict(list)
    with z.open('stop_times.txt') as f:
        rd = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig'))
        head = next(rd)
        ix = {k: i for i, k in enumerate(head)}
        it, ia, idp, isid, iseq = ix['trip_id'], ix['arrival_time'], ix['departure_time'], ix['stop_id'], ix['stop_sequence']
        ish = ix.get('shape_dist_traveled')
        for row in rd:
            tid = row[it]
            if tid not in want_trips:
                continue
            sh = row[ish] if ish is not None and row[ish] else ''
            st[tid].append((int(row[iseq]), row[isid], hms(row[ia]), hms(row[idp]), float(sh) if sh else None))
    for tid, lst in st.items():
        lst.sort()
    return st


# ---------------------------------------------------------------- SIRI
def parse_minute(args):
    """קובץ דקה → רשומות מצומצמות: (frame, ref, line, op, dep, veh, t_sec, order, dist, stopcode)."""
    fn, day = args
    try:
        raw = open(fn, 'rb').read()
        j = json.loads(brotli.decompress(raw))
    except Exception:  # noqa: BLE001
        return []
    out = []
    base = datetime.datetime.fromisoformat(day + 'T00:00:00+03:00')
    for dlv in j.get('Siri', {}).get('ServiceDelivery', {}).get('StopMonitoringDelivery', []) or []:
        for v in dlv.get('MonitoredStopVisit', []) or []:
            m = v.get('MonitoredVehicleJourney') or {}
            fr = (m.get('FramedVehicleJourneyRef') or {})
            if fr.get('DataFrameRef') != day:
                continue
            call = m.get('MonitoredCall') or {}
            try:
                t = int((datetime.datetime.fromisoformat(v['RecordedAtTime']) - base).total_seconds())
                order = int(call.get('Order') or 0)
                dist = int(call.get('DistanceFromStop') or 0)
            except Exception:  # noqa: BLE001
                continue
            out.append((fr.get('DatedVehicleJourneyRef') or '0', m.get('LineRef') or '', m.get('OperatorRef') or '',
                        m.get('OriginAimedDepartureTime') or '', m.get('VehicleRef') or '', t, order, dist,
                        str(call.get('StopPointRef') or '')))
    return out


def dep_sec(dep, day):
    """OriginAimedDepartureTime → שניות מחצות של יום השירות."""
    try:
        base = datetime.datetime.fromisoformat(day + 'T00:00:00+03:00')
        return int((datetime.datetime.fromisoformat(dep) - base).total_seconds())
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- מעברי תחנות
def passages(recs, seq):
    """מרשומות (t, order, dist) ממוינות ורצף תחנות GTFS — זמן המעבר בכל תחנה.
    מחזיר {stop_sequence: t_sec}."""
    out = {}
    n = len(seq)
    cum = [0.0] * n     # מרחק מצטבר לאורך המסלול
    for i in range(1, n):
        a, b = seq[i - 1], seq[i]
        if a[4] is not None and b[4] is not None and b[4] >= a[4]:
            cum[i] = cum[i - 1] + (b[4] - a[4])
        else:
            cum[i] = cum[i - 1] + 400.0   # אין shape_dist — הערכה גסה
    prev = None
    for t, order, dist in recs:
        if order < 1 or order > n:
            prev = (t, order, dist)
            continue
        if dist <= ARRIVE_M and order not in out:
            out[order] = t
        if prev is not None:
            t1, o1, d1 = prev
            if 1 <= o1 < order <= n:
                # הרכב עבר את התחנות o1..order-1 בין t1 ל-t. מיקום בזמן t1:
                # d1 לפני תחנה o1; בזמן t: dist לפני תחנה order.
                p1 = cum[o1 - 1] - d1
                p2 = cum[order - 1] - dist
                span = max(p2 - p1, 1.0)
                for k in range(o1, order):
                    if k in out:
                        continue
                    frac = min(max((cum[k - 1] - p1) / span, 0.0), 1.0)
                    out[k] = int(t1 + (t - t1) * frac)
        prev = (t, order, dist)
    return out


# ---------------------------------------------------------------- ריצה
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True)
    ap.add_argument('--gtfs', required=True)
    ap.add_argument('--siri', required=True, help='תיקייה עם HH/MM.br (היום + תחילת מחר)')
    ap.add_argument('--out', default='bus/data')
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    day = a.day
    t0 = datetime.datetime.now()

    files = []
    for hh in sorted(os.listdir(a.siri)):
        p = os.path.join(a.siri, hh)
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith('.br')]
    print(f'קבצי SIRI: {len(files)}', flush=True)

    # --- SIRI: רשומות לפי נסיעה (בזרימה, בסדר כרונולוגי) ---
    journeys = collections.defaultdict(list)   # key → [(t, order, dist)]
    meta = {}                                  # key → (line, op, dep, veh, stopcode_sample)
    n_rec = 0
    with Pool(a.workers) as pool:
        for recs in pool.imap(parse_minute, [(f, day) for f in files], chunksize=4):
            for ref, line, op, dep, veh, t, order, dist, code in recs:
                n_rec += 1
                key = (ref, line, dep, veh) if ref == '0' else (ref, line)
                journeys[key].append((t, order, dist))
                if key not in meta:
                    meta[key] = (line, op, dep, veh)
    print(f'רשומות: {n_rec:,} · נסיעות (מפתחות): {len(journeys):,} · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)

    g = load_gtfs(a.gtfs, day)
    print(f'GTFS: {len(g["trips"]):,} נסיעות פעילות · {len(g["routes"]):,} מסלולים · {len(g["stops"]):,} תחנות', flush=True)
    # אינדקס לנסיעות בלי מזהה: (route_id, שניית יציאה) → trip_id — נבנה רק אם צריך
    need_dep = any(k[0] == '0' for k in journeys)
    by_dep = {}
    # הצמדת נסיעה → trip_id
    jt = {}
    unmatched = collections.Counter()
    for key in journeys:
        ref, line = key[0], key[1]
        if ref != '0':
            tid = g['by_num'].get(ref)
            if tid and g['trips'].get(tid) == line:
                jt[key] = tid
            elif tid:
                jt[key] = tid          # מזהה נסיעה תקין, route שונה (חלופה) — סומכים על המזהה
                unmatched['route_diff'] += 1
            else:
                unmatched['no_trip'] += 1
        else:
            unmatched['ref0'] += 1
    want = set(jt.values())
    print(f'הוצמדו ל-GTFS: {len(jt):,} · לא: {dict(unmatched)}', flush=True)
    st = load_stop_times(g, want)
    if need_dep:
        # נסיעות בלי מזהה: לפי route_id + שעת יציאה מתוכננת (departure של התחנה הראשונה)
        first_dep = {tid: lst[0][3] for tid, lst in st.items() if lst}
        # צריך גם נסיעות שלא נצפו במזהה — טוענים stop_times לכל הנסיעות של המסלולים הרלוונטיים
        lines0 = {k[1] for k in journeys if k[0] == '0'}
        extra = {tid for tid, rid in g['trips'].items() if rid in lines0 and tid not in want}
        if extra:
            st2 = load_stop_times(g, extra)
            for tid, lst in st2.items():
                st[tid] = lst
                if lst:
                    first_dep[tid] = lst[0][3]
        for tid, sec in first_dep.items():
            by_dep[(g['trips'].get(tid), sec)] = tid
        n0 = 0
        for key in journeys:
            if key[0] == '0':
                ds = dep_sec(key[2], day)
                tid = by_dep.get((key[1], ds)) if ds is not None else None
                if tid and tid not in jt.values():
                    jt[key] = tid
                    n0 += 1
        print(f'נסיעות בלי מזהה שהוצמדו לפי יציאה: {n0:,}', flush=True)
    print(f'stop_times: {sum(len(v) for v in st.values()):,} שורות · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)

    # --- מדידה ---
    routes = g['routes']
    stops = g['stops']
    # מצברים
    R = collections.defaultdict(lambda: {'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': [], 'o': [0] * 5, 'on': 0,
                                         'hours': collections.defaultdict(lambda: [0, 0]), 'stops': collections.defaultdict(lambda: [0, 0.0, 0])})
    A = collections.defaultdict(lambda: {'sched': 0, 'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': []})
    C = collections.defaultdict(lambda: {'meas': 0, 'c': [0] * 5, 'd': []})
    H = collections.defaultdict(lambda: [0, 0])
    tot = {'sched': 0, 'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': []}
    worst = []
    sched_per_route = collections.Counter(g['trips'].values())
    for rid, n in sched_per_route.items():
        A[routes.get(rid, {}).get('agency', '?')]['sched'] += n
        tot['sched'] += n
    for key, tid in jt.items():
        seq = st.get(tid)
        if not seq:
            continue
        recs = sorted(journeys[key])
        rid = g['trips'].get(tid)
        pas = passages(recs, seq)
        if len(pas) < MIN_STOPS_RIDE:
            continue
        r = R[rid]
        r['obs'] += 1
        ag = routes.get(rid, {}).get('agency', '?')
        A[ag]['obs'] += 1
        tot['obs'] += 1
        ride_max = None
        for k, t in pas.items():
            s = seq[k - 1]
            sched = s[3] if k == 1 else s[2]
            delay = t - sched
            if abs(delay) > MAX_ABS:
                continue
            c = cat(delay)
            r['meas'] += 1
            r['c'][c] += 1
            r['d'].append(delay)
            hr = (sched // 3600) % 24
            r['hours'][hr][0] += 1
            r['hours'][hr][1] += 1 if c == ONTIME else 0
            H[hr][0] += 1
            H[hr][1] += 1 if c == ONTIME else 0
            stp = r['stops'][s[1]]
            stp[0] += 1
            stp[1] += delay
            stp[2] += 1 if c >= L5 else 0
            if k == 1:
                r['o'][c] += 1
            A[ag]['meas'] += 1
            A[ag]['c'][c] += 1
            A[ag]['d'].append(delay)
            city = stops.get(s[1], ('', '', 0, 0, ''))[4]
            if city:
                C[city]['meas'] += 1
                C[city]['c'][c] += 1
                C[city]['d'].append(delay)
            tot['meas'] += 1
            tot['c'][c] += 1
            tot['d'].append(delay)
            if ride_max is None or delay > ride_max[0]:
                ride_max = (delay, s[1], sched)
        if ride_max and ride_max[0] >= 1200:
            worst.append((ride_max[0], rid, tid, ride_max[1], ride_max[2]))
    print(f'מדידות: {tot["meas"]:,} · נסיעות נצפו: {tot["obs"]:,} מתוך {tot["sched"]:,} · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)

    def stats(d):
        if not d:
            return [None, None, None]
        d = sorted(d)
        return [round(statistics.mean(d) / 60, 1), round(d[len(d) // 2] / 60, 1), round(d[int(len(d) * 0.9)] / 60, 1)]

    # --- פלט ---
    os.makedirs(f'{a.out}/days', exist_ok=True)
    catalog_path = f'{a.out}/routes.json'
    try:
        catalog = json.load(open(catalog_path, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        catalog = {}
    out_routes = []
    for rid, r in R.items():
        info = routes.get(rid, {})
        catalog[rid] = [info.get('mkt', ''), info.get('short', ''), info.get('long', ''), info.get('agency', ''), info.get('dir', ''), info.get('alt', ''), info.get('type', '')]
        ws = sorted(r['stops'].items(), key=lambda kv: -(kv[1][1] / kv[1][0]))[:3]
        out_routes.append([rid, sched_per_route.get(rid, 0), r['obs'], r['meas'], r['c'], stats(r['d']), r['o'],
                           [[h, v[0], v[1]] for h, v in sorted(r['hours'].items())],
                           [[stops.get(sid, ('',))[0], stops.get(sid, ('', ''))[1], v[0], round(v[1] / v[0] / 60, 1)] for sid, v in ws]])
    out_routes.sort(key=lambda x: -x[3])
    day_obj = {
        'd': day, 'fmt': FMT, 'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'minutes': len(files), 'records': n_rec,
        'tot': {'sched': tot['sched'], 'obs': tot['obs'], 'meas': tot['meas'], 'c': tot['c'], 's': stats(tot['d'])},
        'hours': [[h, v[0], v[1]] for h, v in sorted(H.items())],
        'agencies': sorted([[ag, v['sched'], v['obs'], v['meas'], v['c'], stats(v['d'])] for ag, v in A.items()], key=lambda x: -x[3]),
        'cities': sorted([[c, v['meas'], v['c'], stats(v['d'])] for c, v in C.items() if v['meas'] >= 50], key=lambda x: -x[1]),
        'routes': out_routes,
        'worst': [[rid, tid.split('_')[0], round(dl / 60), stops.get(sid, ('', ''))[1], sched] for dl, rid, tid, sid, sched in sorted(worst, reverse=True)[:40]],
        'cols': {'routes': ['route_id', 'sched', 'obs', 'meas', 'cats[early,ontime,5-10,10-20,20+]', 'stats[avg,med,p90 min]', 'origin cats', 'hours[[h,n,on]]', 'worst stops[[code,name,n,avg]]'],
                 'agencies': ['name', 'sched', 'obs', 'meas', 'cats', 'stats'], 'cities': ['city', 'meas', 'cats', 'stats'],
                 'worst': ['route_id', 'trip', 'max delay min', 'stop', 'sched sec']},
    }
    json.dump(day_obj, open(f'{a.out}/days/{day}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(catalog, open(catalog_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    days = sorted(f[:-5] for f in os.listdir(f'{a.out}/days') if f.endswith('.json'))
    idx = {'days': days, 'updated': day_obj['built']}
    json.dump(idx, open(f'{a.out}/index.json', 'w', encoding='utf-8'), ensure_ascii=False)
    sz = os.path.getsize(f'{a.out}/days/{day}.json')
    print(f'נכתב {a.out}/days/{day}.json ({sz / 1e6:.1f}MB) · מסלולים: {len(out_routes):,} · בזמן ארצי: {tot["c"][ONTIME] / max(tot["meas"], 1):.1%} · {(datetime.datetime.now() - t0).seconds} שנ׳')


if __name__ == '__main__':
    main()
