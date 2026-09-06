#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מדד דיוק האוטובוסים — מ-SIRI גולמי של דאטאבוס ו-GTFS של משרד התחבורה.

מקור בזמן אמת: stride-siri-requester ב-S3 של דאטאבוס — תשובת משרד התחבורה
(SIRI SM) לכל דקה, כל הרכבים בארץ: קובץ Brotli לדקה (~230KB דחוס בשיא, ~4MB
פרוס, ~8,500 רכבים). לכל רכב: LineRef (= route_id ב-GTFS), DatedVehicleJourneyRef
(= trip_id בלי סיומת התאריך), OriginAimedDepartureTime, VehicleLocation,
MonitoredCall {StopPointRef = מק"ט התחנה הבאה, Order = מספרה הסידורי, DistanceFromStop
במטרים}. הורדה מ-S3 אינה מעמיסה על שרת ה-API של דאטאבוס (אישור המיזם 06.09).

שיטה: לכל נסיעה (מפתח: קו + יציאה מתוכננת + רכב) עוקבים אחרי Order: כשהוא
עולה מ-k ל-k+1 הרכב עבר את תחנה k בין שתי הדגימות, וזמן המעבר משוערך
בקו ישר לפי DistanceFromStop והמרחק בין התחנות (shape_dist_traveled).
דגימה עם DistanceFromStop קטן ממש היא הגעה (הזמן משוערך לפי המרחק בדגימה
הקודמת). בתחנת המוצא נמדדת היציאה — הדגימה האחרונה שבה הרכב עוד עמד
בתחנה — ולא ההגעה (הרכב ממתין במסוף לפני היציאה). איחור = זמן המעבר פחות
הזמן המתוכנן ב-stop_times. קטגוריות: מוקדם (<-2 דק׳), בזמן (-2..5),
5–10, 10–20, מעל 20. ההצמדה ללו"ז: route_id + שעת היציאה המתוכננת (מזהה
הנסיעה של SIRI אינו trip_id — בדיקה 06.09). רק אוטובוסים (route_type 3).

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
MAX_ABS = 150 * 60                               # איחור/הקדמה מעבר לשעתיים וחצי — זו לא הנסיעה שבלו"ז (רכב שהוסב לנסיעה אחרת)
SPIKE = 20 * 60                                  # מדידה בודדת שרחוקה מזה משתי שכנותיה — תקלה, לא איחור
ARRIVE_M = 25                                    # DistanceFromStop עד כאן = הגעה
MIN_STOPS_RIDE = 2
BUS_TYPES = {'3'}                                # route_type של אוטובוס (רכבת=2, רכבת קלה=0 — לא כאן)


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
            'agency': agencies.get(r['agency_id'], r['agency_id']), 'agency_id': r['agency_id'], 'type': r.get('route_type') or '',
        }
    trips = {}          # trip_id → route_id (רק שירותים פעילים היום, רק אוטובוסים)
    for r in rows('trips.txt'):
        if r['service_id'] in services and routes.get(r['route_id'], {}).get('type') in BUS_TYPES:
            trips[r['trip_id']] = r['route_id']
    stops = {}
    for r in rows('stops.txt'):
        desc = r.get('stop_desc') or ''
        city = ''
        if 'עיר:' in desc:
            city = desc.split('עיר:', 1)[1].split('רציף:')[0].split('קומה:')[0].strip()
        stops[r['stop_id']] = (r['stop_code'], r['stop_name'], float(r['stop_lat'] or 0), float(r['stop_lon'] or 0), city)
    return {'routes': routes, 'trips': trips, 'stops': stops, 'zip': z}


def load_stop_times(g, want_trips):
    """רצף התחנות של הנסיעות המבוקשות (כל הנסיעות הפעילות היום — ~4 מיליון
    שורות מתוך קובץ של ~800MB): trip_id → רשימה לפי stop_sequence של
    (seq, stop_id, arrival_sec, departure_sec, shape_dist)."""
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
    gaps = 0
    for tid, lst in st.items():
        lst.sort()
        if lst[0][0] != 1 or lst[-1][0] != len(lst):
            gaps += 1
    if gaps:
        print(f'אזהרה: {gaps:,} נסיעות עם stop_sequence לא רציף (Order של SIRI ממופה לפי מיקום ברשימה)', flush=True)
    return st


# ---------------------------------------------------------------- סוגי רכב
VRANK = {'מיניבוס': 1, 'מידיבוס': 2, 'אוטובוס': 3, 'מפרקי': 4}


CKAN = 'https://data.gov.il/api/3/action'


def ckan_get(url, timeout=120):
    import urllib.request
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-bus/1.0', 'Referer': 'https://data.gov.il/'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def norm_size(t):
    t = str(t or '')
    if 'מפרק' in t:
        return 'מפרקי'
    if 'מיני' in t:
        return 'מיניבוס'
    if 'מידי' in t:
        return 'מידיבוס'
    if 'אוטובוס' in t:
        return 'אוטובוס'
    return None


def load_rishui_sizes(day):
    """גודל הרכב שנקבע לכל מק"ט ליום נתון, ממאגר "רישוי מערך האוטובוסים" של משרד
    התחבורה ב-data.gov.il (שורה לכל מק"ט לכל יום: VehicleSize_nm, trips_count).
    המקור הרשמי היומי (שלמה 06.09) במקום העמודה בקובץ הידני. אם אין שורות ליום —
    היום הקודם הקרוב (עד שבוע). מחזיר (מק"ט → גודל, תאריך המקור) או ({}, None)."""
    import urllib.parse
    year = day[:4]
    pkg = ckan_get(f'{CKAN}/package_show?id=licensing_bus_system')['result']
    rid = None
    for r in pkg.get('resources', []):
        if (r.get('format') or '').upper() == 'CSV' and year in (r.get('name') or '') and r.get('datastore_active'):
            rid = r['id']
    if not rid:
        raise RuntimeError(f'אין משאב רישוי לשנת {year}')
    d0 = datetime.date.fromisoformat(day)
    for back in range(0, 8):
        d = (d0 - datetime.timedelta(days=back)).isoformat()
        flt = urllib.parse.quote(json.dumps({'rishui_date': d}))
        rows, offset = [], 0
        while True:
            res = ckan_get(f'{CKAN}/datastore_search?resource_id={rid}&filters={flt}&fields=office_line_id,VehicleSize_nm,VehicleType_nm,trips_count&limit=32000&offset={offset}')['result']
            recs = res.get('records', [])
            rows.extend(recs)
            if len(recs) < 32000:
                break
            offset += 32000
        if rows:
            sizes = {}
            raw = collections.Counter()
            for r in rows:
                raw[str(r.get('VehicleSize_nm'))] += 1
                s = norm_size(r.get('VehicleSize_nm'))
                if s and r.get('office_line_id') is not None:
                    sizes[str(r['office_line_id'])] = s
            print(f'רישוי {d}: {len(rows):,} שורות · גדלי רכב במקור: {dict(raw.most_common(8))}', flush=True)
            return sizes, d
    return {}, None


def load_vehicle_classes(site, day=None):
    """הסוג שנקבע לכל קו (מק"ט → מיניבוס/מידיבוס/אוטובוס/מפרקי): קודם המקור הרשמי
    היומי (רישוי מערך האוטובוסים ב-data.gov.il), ובהיעדרו קובץ הקווים של האתר
    (data-main.json עמודה 13). הסוג של כל רכב לפי מספרו: קודם מאגר "ציי רכב
    אוטובוסים" של המשרד (fleet-official.json, שדה 5, אותו אוצר מילים), ובהיעדרו
    סיווג הרישוי (fleet.json: 'מפרק' → מפרקי, 'זעיר' → מיניבוס, אחרת אוטובוס)."""
    plan, veh = {}, {}
    src_date = None
    if day:
        try:
            plan, src_date = load_rishui_sizes(day)
        except Exception as e:  # noqa: BLE001
            print(f'אזהרה: מאגר הרישוי לא נטען ({e}) — נופלים לקובץ הקווים של האתר', flush=True)
    if not plan:
        try:
            for r in json.load(open(os.path.join(site, 'data-main.json'), encoding='utf-8')):
                if len(r) > 13 and r[13] in VRANK:
                    plan[str(r[0])] = r[13]
            src_date = 'data-main.json'
        except Exception as e:  # noqa: BLE001
            print(f'אזהרה: data-main.json לא נטען ({e})', flush=True)
    print(f'מקור סוג הרכב שנקבע לקו: {src_date}', flush=True)
    try:
        fl = json.load(open(os.path.join(site, 'fleet/data/fleet.json'), encoding='utf-8'))
        off = 1 if fl.get('v') == 2 else 0
        for op in fl.get('operators', []):
            for v in op.get('vehicles', []):
                t = str(v[6 + off] or '') if len(v) > 6 + off else ''
                if not t:
                    continue
                veh[str(v[0])] = 'מפרקי' if 'מפרק' in t else 'מיניבוס' if 'זעיר' in t or 'זעצ' in t else 'אוטובוס'
    except Exception as e:  # noqa: BLE001
        print(f'אזהרה: fleet.json לא נטען ({e})', flush=True)
    try:
        of = json.load(open(os.path.join(site, 'fleet/data/fleet-official.json'), encoding='utf-8')).get('of', {})
        for plate, row in of.items():
            t = str(row[5] or '') if len(row) > 5 else ''
            cls = 'מפרקי' if t.startswith('מפרקי') else t if t in VRANK else None
            if cls:
                veh[str(plate)] = cls
    except Exception as e:  # noqa: BLE001
        print(f'אזהרה: fleet-official.json לא נטען ({e})', flush=True)
    return plan, veh


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
FRAC = collections.Counter()   # אבחון: איפה נפל המרחק של GTFS בתוך קטע הדגימות שבו Order התקדם


def passages(recs, seq, codes=None):
    """מרשומות (t, order, dist, code) ממוינות ורצף תחנות GTFS — זמן המעבר בכל תחנה.
    מחזיר {stop_sequence: t_sec}.

    הסמנטיקה של השידור (מהרשומות הגולמיות, 06.09): DistanceFromStop הוא המרחק
    שהרכב נסע מתחילת הנסיעה (עולה בהתמדה לאורך כל הנסיעה), ו-Order הוא התחנה
    האחרונה שהרכב ביקר בה (לא הבאה). לפני היציאה המרחק 0 ו-Order לא אמין.
    codes: מק"ט התחנה לכל מקום ברצף — Order לא תמיד תואם stop_sequence, ולכן
    התחנה נקבעת לפי המק"ט ששודר, הקרוב ביותר ל-Order."""
    out = {}
    n = len(seq)
    if n < 2:
        return out
    fixed = []
    for rec in recs:
        t, order, dist = rec[0], rec[1], rec[2]
        code = rec[3] if len(rec) > 3 else ''
        if codes and code and not (1 <= order <= n and codes[order - 1] == code):
            cands = [i + 1 for i, c in enumerate(codes) if c == code]
            if cands:
                order = min(cands, key=lambda k: abs(k - order))
        fixed.append((t, order, dist))
    # רשומה "תקועה" (אותו RecordedAtTime חוזר בכמה קובצי דקה כשאין GPS חדש) — פעם אחת
    samples = []
    last_t = None
    for t, order, dist in sorted(fixed):
        if t == last_t:
            continue
        last_t = t
        samples.append((t, float(dist), order))
    if len(samples) < 2:
        return out
    cum = [0.0] * n     # מרחק מצטבר לאורך המסלול לפי GTFS (מטרים)
    for i in range(1, n):
        a, b = seq[i - 1], seq[i]
        if a[4] is not None and b[4] is not None and b[4] >= a[4]:
            cum[i] = cum[i - 1] + (b[4] - a[4])
        else:
            cum[i] = cum[i - 1] + 400.0   # אין shape_dist — הערכה גסה

    def sched_at(p):
        """הזמן שבלו"ז במיקום p לאורך המסלול (שיערוך ליניארי בין תחנות)."""
        if p <= 0:
            return seq[0][3]
        for i in range(1, n):
            if p <= cum[i]:
                seg = max(cum[i] - cum[i - 1], 1.0)
                return seq[i - 1][3] + (seq[i][2] - seq[i - 1][3]) * (p - cum[i - 1]) / seg
        return seq[-1][2]

    has_dist = max(s[1] for s in samples) > ARRIVE_M
    dep = None
    first_i = 0
    if has_dist:
        # --- יציאה מהמוצא: הרכב עמד בתחילת המסלול (שתי דגימות לפחות עם אותו מרחק) ואז
        # המרחק התחיל לגדול. דגימה בודדת "במרחק 0" לא נחשבת — המשרד מציב את הרכב
        # בתחנה 5 דק׳ לפני היציאה (בדיקה 06.09: שיא של 20,849 נסיעות ב-5 דק׳ "מוצא").
        # נלקחת העמידה האחרונה בתוך 300 המטרים הראשונים (רכב שזז בין רציפים במסוף),
        # ואיפוס מרחק (ירידה של 100+ מ׳ לפני היציאה — ערכים ישנים מנסיעה קודמת) מתחיל מחדש.
        prev = None
        stat = False
        cand = None
        first_i = 0
        for i, (t, p, o) in enumerate(samples):
            if prev is not None:
                t0, p0 = prev
                if p0 - p > 300 and (p0 <= 3000 or i < 10):
                    # איפוס מרחק בתחילת הנסיעה — ערכים ישנים (גם מעל 3 ק"מ, דוגמה 06.09:
                    # 2682 → 6354 → 395); מתחילים מחדש מכאן
                    prev = (t, p)
                    stat = False
                    cand = None
                    first_i = i
                    continue
                if p0 <= 300 and abs(p - p0) <= 30:
                    stat = True
                elif p - p0 > 30 and stat:
                    if t - t0 <= 120:
                        cand = t0 + min(30, (t - t0) // 2)
                    else:
                        # פער בשידור בין העמידה לנסיעה: לפי מהירות הלו"ז מהמיקום הראשון בדרך
                        cand = max(t0, min(t, t - (sched_at(p) - seq[0][3])))
                    stat = False
            prev = (t, p)
            if p > 3000 and i >= 10:
                break
        dep = cand
        if dep is None:
            t, p, o = samples[first_i]
            if ARRIVE_M < p <= 3000:
                # השידור התחיל כשהרכב כבר בדרך, קרוב למוצא: שיערוך אחורה — לפי המהירות
                # שנצפתה בדגימות הבאות, ואם אין — לפי הלו"ז
                v = None
                for t2, p2, o2 in samples[first_i + 1:first_i + 4]:
                    if t2 - t >= 30 and p2 > p:
                        v = (p2 - p) / (t2 - t)
                        break
                if v is not None and 2 <= v <= 30:
                    dep = t - p / v
                else:
                    dep = t - (sched_at(p) - seq[0][3])
        if dep is not None:
            out[1] = int(dep)

    # --- מעברים בתחנות 2..n. עיקרי: חציית המרחק המצטבר של GTFS על ידי המרחק ששודר
    # (מתחילת הנסיעה), בשיערוך ליניארי בין שתי הדגימות — ובתנאי ש-Order (התחנה
    # האחרונה שבוקרה) מאשר בהמשך שהרכב אכן ביקר בתחנה. Order לבדו הוא לא אמין מיד
    # אחרי היציאה (בדיקה 06.09: "ביקר ב-2" במרחק 50 מ׳ מהמוצא) — ערך Order שכבר
    # הופיע לפני היציאה לא נחשב למעבר. כשהחצייה ומעבר ה-Order רחוקים זה מזה ביותר
    # מ-5 דק׳ (מרחק שנתקע), מעבר ה-Order קובע. בלי מרחק — מעבר Order, אמצע הקטע.
    start_i = first_i if has_dist else 0    # אחרי איפוס מרחק — הדגימות שלפניו לא נחשבות
    pre_o = 1
    if has_dist:
        while start_i < len(samples) and samples[start_i][1] <= ARRIVE_M and (dep is None or samples[start_i][0] <= dep):
            pre_o = max(pre_o, samples[start_i][2])
            start_i += 1
    sufmax = [0] * (len(samples) + 1)
    for i in range(len(samples) - 1, -1, -1):
        sufmax[i] = max(sufmax[i + 1], samples[i][2])
    # זמן לפי מעבר Order: תחנה k → (t1, p1, t, p) של הקטע שבו Order הגיע ל-k לראשונה
    t_ord = {}
    prev = (dep, 0.0, 1) if dep is not None else None
    for j in range(start_i, len(samples)):
        t, p, o = samples[j]
        if prev is not None:
            t1, p1, o1 = prev
            if 1 <= o1 < o and t > t1:
                for k in range(o1 + 1, min(o, n) + 1):
                    frac = 0.5
                    if has_dist and p > p1:
                        frac = min(max((cum[k - 1] - p1) / (p - p1), 0.0), 1.0)
                    t_ord[k] = int(t1 + (t - t1) * frac)
                    if has_dist and j > 0:
                        FRAC[('off', max(-1000, min(1000, int((cum[k - 1] - p) // 250) * 250)))] += 1
        if prev is None or o >= prev[2]:
            prev = (t, p, o)
    if has_dist:
        k = 2
        t1, p1 = (dep, 0.0) if dep is not None else (None, None)
        for j in range(start_i, len(samples)):
            t, p, o = samples[j]
            if t1 is not None and p > p1 and t > t1:
                while k <= n and cum[k - 1] <= p:
                    if cum[k - 1] >= p1 and sufmax[max(j - 1, 0)] >= k:
                        tc = int(t1 + (t - t1) * (cum[k - 1] - p1) / (p - p1))
                        to = t_ord.get(k)
                        if to is not None and k > pre_o and abs(tc - to) > 300:
                            out[k] = to
                            FRAC['conflict'] += 1
                        else:
                            out[k] = tc
                            FRAC['dist'] += 1
                    k += 1
            if t1 is None or p >= p1:
                t1, p1 = t, p
    for k, to in t_ord.items():
        if k not in out and (not has_dist or k > pre_o):
            out[k] = to
            FRAC['order'] += 1
    return out


# ---------------------------------------------------------------- ריצה
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True)
    ap.add_argument('--gtfs', required=True)
    ap.add_argument('--siri', required=True, help='תיקייה עם HH/MM.br (היום + תחילת מחר)')
    ap.add_argument('--out', default='bus/data')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--site', default='.', help='שורש האתר — לקובצי סוגי הרכב (data-main.json, fleet/data)')
    ap.add_argument('--no-rishui', action='store_true', help='בלי מאגר הרישוי של המשרד (data.gov.il) לסוג הרכב שנקבע לקו')
    ap.add_argument('--dump-rides', default='', help='קובץ JSON עם שורה לכל נסיעה שנמדדה (להשוואה מול נתוני המשרד)')
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
                # מפתח הנסיעה: קו + יציאה מתוכננת + רכב (+ מזהה הנסיעה של SIRI, שאינו
                # trip_id של GTFS — הבדיקה 06.09: רק 0.2% תואמים — ולכן משמש רק להפרדה)
                key = (line, dep, veh, ref)
                journeys[key].append((t, order, dist, sys.intern(code)))
                if key not in meta:
                    meta[key] = (line, op, dep, veh)
    print(f'רשומות: {n_rec:,} · נסיעות (מפתחות): {len(journeys):,} · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)

    g = load_gtfs(a.gtfs, day)
    print(f'GTFS: {len(g["trips"]):,} נסיעות פעילות · {len(g["routes"]):,} מסלולים · {len(g["stops"]):,} תחנות', flush=True)
    plan_cls, veh_cls = load_vehicle_classes(a.site, None if a.no_rishui else day)
    print(f'סוגי רכב: {len(plan_cls):,} מק"טים עם סוג שנקבע · {len(veh_cls):,} רכבים עם סוג ידוע', flush=True)
    # רצפי התחנות של כל הנסיעות הפעילות היום — נדרש גם להצמדה (שעת היציאה
    # של התחנה הראשונה) וגם למדידה
    st = load_stop_times(g, set(g['trips']))
    print(f'stop_times: {sum(len(v) for v in st.values()):,} שורות ל-{len(st):,} נסיעות · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)
    # הצמדה: LineRef של SIRI = route_id של GTFS, ו-OriginAimedDepartureTime = שעת
    # היציאה המתוכננת מהתחנה הראשונה. (route_id, שנייה) → trip_id; ואם אין
    # התאמה מדויקת — הנסיעה הקרובה ביותר באותו מסלול עד 3 דקות.
    by_dep = {}
    deps_by_route = collections.defaultdict(list)
    for tid, lst in st.items():
        if lst:
            rid = g['trips'].get(tid)
            by_dep.setdefault((rid, lst[0][3]), tid)
            deps_by_route[rid].append((lst[0][3], tid))
    for v in deps_by_route.values():
        v.sort()
    jt = {}
    unmatched = collections.Counter()
    used = set()
    diag_dd = collections.Counter()      # מרחק ההצמדה (שניות) — אבחון
    diag_near = collections.Counter()    # לא הוצמדו: הנסיעה הקרובה ביותר (דקות)
    for key in journeys:
        line, dep = key[0], key[1]
        ds = dep_sec(dep, day)
        if ds is None or line not in deps_by_route:
            unmatched['no_route' if line not in deps_by_route else 'no_dep'] += 1
            continue
        tid = by_dep.get((line, ds))
        if tid is not None:
            diag_dd[0] += 1
        else:
            best = None
            for sec, t2 in deps_by_route[line]:
                dd = abs(sec - ds)
                if best is None or dd < best[0]:
                    best = (dd, t2)
            if best and best[0] <= 180:
                tid = best[1]
                diag_dd[60 if best[0] <= 60 else 180] += 1
            else:
                diag_near[min(best[0] // 60, 30) if best else -1] += 1
        if tid is None:
            unmatched['no_trip'] += 1
            continue
        jt[key] = tid
        used.add(tid)
    print(f'אבחון הצמדה — מדויק/עד דקה/עד 3 דק׳: {dict(sorted(diag_dd.items()))} · לא הוצמדו, הקרובה ביותר בדקות: {dict(sorted(diag_near.items()))}', flush=True)
    # כמה שידורים לאותה נסיעה (רכב תגבור, או רכב ששידר תחת שני מזהים) — נמדד
    # השידור הארוך ביותר בלבד, כדי שנסיעה בלו"ז תיספר פעם אחת
    by_tid = collections.defaultdict(list)
    for key, tid in jt.items():
        by_tid[tid].append(key)
    dup = 0
    for tid, keys in by_tid.items():
        if len(keys) > 1:
            keys.sort(key=lambda k: -len(journeys[k]))
            for k in keys[1:]:
                del jt[k]
                dup += 1
    print(f'הוצמדו ל-GTFS: {len(jt):,} נסיעות SIRI ({len(used):,} נסיעות GTFS שונות, {dup:,} שידורים כפולים הושמטו) · לא: {dict(unmatched)} · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)

    # --- מדידה ---
    routes = g['routes']
    stops = g['stops']
    # מצברים
    R = collections.defaultdict(lambda: {'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': [], 'o': [0] * 5, 'on': 0,
                                         'hours': collections.defaultdict(lambda: [0, 0]), 'stops': collections.defaultdict(lambda: [0, 0.0, 0, 10 ** 9])})
    A = collections.defaultdict(lambda: {'sched': 0, 'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': [], 'o': [0] * 5})
    C = collections.defaultdict(lambda: {'meas': 0, 'c': [0] * 5, 'd': []})
    H = collections.defaultdict(lambda: [0, 0])
    tot = {'sched': 0, 'obs': 0, 'meas': 0, 'c': [0] * 5, 'd': [], 'o': [0] * 5}
    # סוג הרכב מול מה שנקבע לקו: [נסיעות עם רכב וקו מזוהים, רכב קטן יותר, רכב גדול יותר]
    VT = collections.defaultdict(lambda: [0, 0, 0, collections.Counter()])   # route_id
    VA = collections.defaultdict(lambda: [0, 0, 0])                          # מפעיל
    vt_tot = [0, 0, 0]
    far = 0             # נסיעות ששודרו אך רוב מדידותיהן רחוקות מהלו"ז ביותר משעה
    beyond = 0          # מדידות בודדות מעבר לשעה בנסיעות שנשמרו
    diag_o = collections.Counter()       # היסטוגרמת איחור במוצא (דקות) — אבחון
    diag_mx = collections.Counter()      # היסטוגרמת האיחור המרבי לנסיעה (5 דק׳)
    diag_mx_o = collections.Counter()    # נסיעות עם מרבי ≥55 דק׳: האיחור במוצא (10 דק׳)
    diag_ex = []                         # דוגמאות של נסיעות כאלה שיצאו בזמן
    rides_dump = []                      # --dump-rides: [מק"ט, כיוון, חלופה, trip, יציאה מתוכננת, איחור במוצא, איחור אחרון, תחנה אחרונה, מדידות, רכב, זמן יציאה, זמן אחרון]
    diag_raw, diag_raw2, diag_raw3 = [], [], []   # רשומות גולמיות לאבחון המוצא, ונסיעות טיפוסיות
    spikes = 0
    n_rides = 0
    hms_ = lambda s: f'{s // 3600:02d}:{s % 3600 // 60:02d}'  # noqa: E731
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
        pas = passages(recs, seq, [stops.get(s[1], ('',))[0] for s in seq])
        if len(pas) < MIN_STOPS_RIDE:
            continue
        meas = []
        n_beyond = 0
        for k, t in pas.items():
            s = seq[k - 1]
            sched = s[3] if k == 1 else s[2]
            delay = t - sched
            if abs(delay) <= MAX_ABS:
                meas.append((k, s, sched, delay))
            else:
                n_beyond += 1
        # רוב המעברים רחוקים מהלו"ז ביותר משעה וחצי — זו לא הנסיעה שבלו"ז
        if len(meas) < MIN_STOPS_RIDE or n_beyond > len(meas):
            far += 1
            continue
        beyond += n_beyond
        # מדידה בודדת שקופצת ביותר מ-20 דק׳ משתי שכנותיה (שדומות זו לזו) — תקלת
        # מק"ט/שיערוך ולא איחור; מושמטת (דוגמה 06.09: +7, +56, +5)
        meas.sort()
        if len(meas) >= 3:
            keep = []
            last = len(meas) - 1
            for i, m in enumerate(meas):
                if 0 < i < last:
                    da, db = meas[i - 1][3], meas[i + 1][3]
                    if abs(m[3] - da) > SPIKE and abs(m[3] - db) > SPIKE and abs(da - db) < SPIKE / 2:
                        spikes += 1
                        continue
                elif i == last and m[3] - meas[i - 1][3] > SPIKE:
                    # תחנה אחרונה שקופצת ב-20+ דק׳ מהקודמת: הרכב חנה במסוף ליד התחנה
                    # ועבר אותה שוב הרבה אחר כך (דוגמאות 06.09: +5 ואז +80)
                    spikes += 1
                    continue
                elif i == 0 and m[3] - meas[1][3] > SPIKE:
                    # מוצא שנמדד 20+ דק׳ אחרי התחנה השנייה — לא ייתכן פיזית, תוצר שידור
                    spikes += 1
                    continue
                keep.append(m)
            meas = keep
        if len(meas) < MIN_STOPS_RIDE:
            far += 1
            continue
        if len(diag_raw) < 6 and meas[0][0] == 1 and -300 <= meas[0][3] < -240:
            diag_raw.append(f'מוצא -5 {rid}/{tid} יציאה {hms_(seq[0][3])} n={len(seq)} רשומות(שנ׳ מהיציאה,סדר,מרחק): '
                            + ' '.join(f'{r[0] - seq[0][3]:+d}/{r[1]}/{r[2]}' for r in recs[:10]) + ' · מעברים: ' + ' '.join(f'{k}:{d // 60:+d}' for k, s, sc, d in meas[:6]))
        if len(diag_raw2) < 4 and meas[0][0] == 1 and meas[0][3] >= 480 and len(meas) > 1 and meas[1][0] == 2 and meas[1][3] <= 120:
            diag_raw2.append(f'מוצא +8/תחנה 2 בזמן {rid}/{tid} יציאה {hms_(seq[0][3])} תחנה 2 בלו"ז {hms_(seq[1][2])} רשומות: '
                             + ' '.join(f'{r[0] - seq[0][3]:+d}/{r[1]}/{r[2]}' for r in recs[:14]) + ' · מעברים: ' + ' '.join(f'{k}:{d // 60:+d}' for k, s, sc, d in meas[:6]))
        n_rides += 1
        if n_rides % 30000 == 0:
            diag_raw3.append(f'טיפוסית {rid}/{tid} יציאה {hms_(seq[0][3])} n={len(seq)} מעברים: ' + ' '.join(f'{k}:{d // 60:+d}' for k, s, sc, d in meas))
        r = R[rid]
        r['obs'] += 1
        ag = routes.get(rid, {}).get('agency', '?')
        A[ag]['obs'] += 1
        tot['obs'] += 1
        # סוג הרכב שהגיע (לפי מספר הרכב בשידור) מול הסוג שנקבע לקו (לפי המק"ט)
        planned = plan_cls.get(routes.get(rid, {}).get('mkt', ''))
        actual = veh_cls.get(key[2])
        if planned and actual:
            vt = VT[rid]
            vt[0] += 1
            vt[3][actual] += 1
            VA[ag][0] += 1
            vt_tot[0] += 1
            if VRANK[actual] < VRANK[planned]:
                vt[1] += 1
                VA[ag][1] += 1
                vt_tot[1] += 1
            elif VRANK[actual] > VRANK[planned]:
                vt[2] += 1
                VA[ag][2] += 1
                vt_tot[2] += 1
        ride_max = None
        ride_pass = []                       # [מק"ט, מתוכנן, בפועל] לכל תחנה — לרשימת המאחרות
        t_of = {k: sc + d for k, s, sc, d in meas}
        for k, s, sched, delay in meas:
            c = cat(delay)
            r['meas'] += 1
            r['c'][c] += 1
            r['d'].append(delay)
            hr = (sched // 3600) % 24
            r['hours'][hr][0] += 1
            r['hours'][hr][1] += 1 if c == ONTIME else 0
            H[hr][0] += 1
            H[hr][1] += 1 if c == ONTIME else 0
            # פרופיל לאורך הקו: לכל תחנה — הגעות, סכום איחור, בזמן, המקום ברצף
            stp = r['stops'][s[1]]
            stp[0] += 1
            stp[1] += delay
            stp[2] += 1 if c == ONTIME else 0
            stp[3] = min(stp[3], k)
            ride_pass.append([stops.get(s[1], ('',))[0], sched, t_of[k]])
            if k == 1:
                r['o'][c] += 1
                tot['o'][c] += 1
                A[ag]['o'][c] += 1
                diag_o[max(-15, min(15, int(delay // 60)))] += 1
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
        if a.dump_rides:
            od = next((d for k, s, sc, d in meas if k == 1), None)
            info = routes.get(rid, {})
            rides_dump.append([info.get('mkt', ''), info.get('dir', ''), info.get('alt', ''), tid.split('_')[0], seq[0][3], od,
                               meas[-1][3], meas[-1][0], len(meas), key[2], t_of.get(1), max(t_of.values())])
        if ride_max and ride_max[0] >= 1200:
            worst.append((ride_max[0], rid, tid, ride_max[1], ride_max[2], ride_pass))
            diag_mx[int(ride_max[0] // 300) * 5] += 1
            if ride_max[0] >= 55 * 60:
                od = next((d for k, s, sc, d in meas if k == 1), None)
                diag_mx_o['אין' if od is None else int(od // 600) * 10] += 1
                if od is not None and od < 600 and len(diag_ex) < 8:
                    # דוגמאות: יצאה בזמן והגיעה ל-55+ דק׳ — איפה הקפיצה?
                    diag_ex.append(f'{rid}/{tid} רשומות={len(recs)} {hms_(recs[0][0])}–{hms_(recs[-1][0])} יציאה מתוכננת {hms_(seq[0][3])} n={len(seq)} מעברים: '
                                   + ' '.join(f'{k}:{d // 60:+d}' for k, s, sc, d in sorted(meas)))
    print(f'מדידות: {tot["meas"]:,} · נסיעות נצפו: {tot["obs"]:,} מתוך {tot["sched"]:,} · רחוקות מהלו"ז (הושמטו): {far:,} · מדידות בודדות מעבר לסף: {beyond:,} · קפיצות בודדות שהושמטו: {spikes:,} · מעברים לפי מרחק/לפי Order: {dict(FRAC)} · {(datetime.datetime.now() - t0).seconds} שנ׳', flush=True)
    if a.dump_rides:
        os.makedirs(os.path.dirname(a.dump_rides) or '.', exist_ok=True)
        json.dump({'d': day, 'cols': ['mkt', 'dir', 'alt', 'trip', 'sched dep sec', 'origin delay sec', 'last delay sec', 'last stop k', 'n meas', 'vehicle', 'dep sec', 'last pass sec'],
                   'sched_trips': [[routes.get(rid, {}).get('mkt', ''), routes.get(rid, {}).get('dir', ''), routes.get(rid, {}).get('alt', ''), tid.split('_')[0], lst[0][3]] for tid, lst in st.items() if lst for rid in [g['trips'].get(tid)]],
                   'rides': rides_dump}, open(a.dump_rides, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'נכתב {a.dump_rides}: {len(rides_dump):,} נסיעות שנמדדו', flush=True)
    for ex in diag_raw + diag_raw2 + diag_raw3:
        print('  גולמי:', ex, flush=True)
    print(f'אבחון מוצא (דקות → נסיעות): {dict(sorted(diag_o.items()))}', flush=True)
    print(f'אבחון איחור מרבי לנסיעה (5 דק׳ → נסיעות): {dict(sorted(diag_mx.items()))} · מרבי ≥55: איחור במוצא: {dict(sorted(diag_mx_o.items(), key=lambda kv: str(kv[0])))}', flush=True)
    for ex in diag_ex:
        print('  דוגמה:', ex, flush=True)

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
    profiles = {}       # route_id → [[מק"ט, הגעות, איחור ממוצע בעשיריות דקה, בזמן]] לאורך הקו
    stop_names = {}     # מק"ט → שם (קטלוג לתצוגה)
    for rid, r in R.items():
        info = routes.get(rid, {})
        # [מק"ט, מספר קו, שם, מפעיל, כיוון, חלופה, סוג, מזהה מפעיל (לקישור לדאטאבוס)]
        catalog[rid] = [info.get('mkt', ''), info.get('short', ''), info.get('long', ''), info.get('agency', ''), info.get('dir', ''), info.get('alt', ''), info.get('type', ''), info.get('agency_id', '')]
        # שלוש התחנות עם האיחור הממוצע הגבוה (לפחות 3 הגעות, אחרת מדידה בודדת מטה)
        ws = sorted([kv for kv in r['stops'].items() if kv[1][0] >= 3], key=lambda kv: -(kv[1][1] / kv[1][0]))[:3]
        vt = VT.get(rid)
        vt_row = [plan_cls.get(info.get('mkt', ''), ''), vt[0], vt[1], vt[2], vt[3].most_common(1)[0][0]] if vt else None
        out_routes.append([rid, sched_per_route.get(rid, 0), r['obs'], r['meas'], r['c'], stats(r['d']), r['o'],
                           [[h, v[0], v[1]] for h, v in sorted(r['hours'].items())],
                           [[stops.get(sid, ('',))[0], stops.get(sid, ('', ''))[1], v[0], round(v[1] / v[0] / 60, 1)] for sid, v in ws],
                           vt_row])
        prof = []
        for sid, v in sorted(r['stops'].items(), key=lambda kv: kv[1][3]):
            code, name = stops.get(sid, ('', ''))[0], stops.get(sid, ('', ''))[1]
            stop_names[code] = name
            prof.append([code, v[0], round(v[1] / v[0] / 6), v[2]])
        profiles[rid] = prof
    out_routes.sort(key=lambda x: -x[3])
    worst.sort(key=lambda w: -w[0])
    for w in worst[:40]:
        for code, _, _ in w[5]:
            stop_names.setdefault(code, '')
    # שמות התחנות של המאחרות — מהרישום (הפרופילים כבר כיסו את רובן)
    by_code = {v[0]: v[1] for v in stops.values()}
    for code in list(stop_names):
        if not stop_names[code]:
            stop_names[code] = by_code.get(code, '')
    day_obj = {
        'd': day, 'fmt': FMT, 'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'minutes': len(files), 'records': n_rec,
        'tot': {'sched': tot['sched'], 'obs': tot['obs'], 'meas': tot['meas'], 'c': tot['c'], 's': stats(tot['d']), 'o': tot['o'],
                'far': far, 'extra': unmatched.get('no_trip', 0), 'vt': vt_tot},
        'hours': [[h, v[0], v[1]] for h, v in sorted(H.items())],
        'agencies': sorted([[ag, v['sched'], v['obs'], v['meas'], v['c'], stats(v['d']), v['o'], VA.get(ag, [0, 0, 0])] for ag, v in A.items()], key=lambda x: -x[3]),
        'cities': sorted([[c, v['meas'], v['c'], stats(v['d'])] for c, v in C.items() if v['meas'] >= 50], key=lambda x: -x[1]),
        'routes': out_routes,
        'worst': [[rid, tid.split('_')[0], round(dl / 60), stops.get(sid, ('', ''))[1], sched, ps] for dl, rid, tid, sid, sched, ps in worst[:40]],
        'cols': {'routes': ['route_id', 'sched', 'obs', 'meas', 'cats[early,ontime,5-10,10-20,20+]', 'stats[avg,med,p90 min]', 'origin cats', 'hours[[h,n,on]]', 'worst stops[[code,name,n,avg]]', 'vehicle[planned class, rides with known vehicle, smaller, larger, most common actual]'],
                 'agencies': ['name', 'sched', 'obs', 'meas', 'cats', 'stats', 'origin cats', 'vehicle[known, smaller, larger]'], 'cities': ['city', 'meas', 'cats', 'stats'],
                 'worst': ['route_id', 'trip', 'max delay min', 'stop', 'sched sec', 'passages[[code,sched sec,actual sec]]'],
                 'tot': 'o = origin cats · far = rides beyond ±90 min (dropped) · extra = SIRI journeys with no GTFS trip',
                 'stops file': 'days/D.stops.json = {route_id: [[code, n, avg delay (tenths of min), on-time n]] along the route}; stops.json = {code: name}'},
    }
    json.dump(day_obj, open(f'{a.out}/days/{day}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(profiles, open(f'{a.out}/days/{day}.stops.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(catalog, open(catalog_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # קטלוג שמות תחנות — מצטבר (תחנות שנעלמו נשארות לימים ישנים)
    names_path = f'{a.out}/stops.json'
    try:
        old_names = json.load(open(names_path, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        old_names = {}
    old_names.update({k: v for k, v in stop_names.items() if v})
    json.dump(old_names, open(names_path, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # האינדקס נושא את הסיכום הארצי של כל יום, כדי שהעמוד יצייר מגמה ולוח שנה
    # בלי להוריד את קובצי הימים (1–3MB כל אחד)
    days = []
    for f in sorted(os.listdir(f'{a.out}/days')):
        if not f.endswith('.json') or f.endswith('.stops.json'):
            continue
        try:
            dj = json.load(open(f'{a.out}/days/{f}', encoding='utf-8'))
            days.append({'d': f[:-5], **{k: dj['tot'][k] for k in ('sched', 'obs', 'meas', 'c', 's', 'o') if k in dj['tot']}})
        except Exception:  # noqa: BLE001
            days.append({'d': f[:-5]})
    idx = {'days': days, 'updated': day_obj['built'], 'fmt': FMT}
    json.dump(idx, open(f'{a.out}/index.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    sz = os.path.getsize(f'{a.out}/days/{day}.json')
    print(f'נכתב {a.out}/days/{day}.json ({sz / 1e6:.1f}MB) · מסלולים: {len(out_routes):,} · בזמן ארצי: {tot["c"][ONTIME] / max(tot["meas"], 1):.1%} · {(datetime.datetime.now() - t0).seconds} שנ׳')


if __name__ == '__main__':
    main()
