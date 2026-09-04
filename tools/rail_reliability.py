#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מדד אמינות הרכבת — מנתוני דאטאבוס (Stride API), בקשת שלמה 04.09.2026.

לכל יום נשלפות כל נסיעות רכבת ישראל שבלו"ז (GTFS, מפעיל 2) עם תחנותיהן
וזמני ההגעה המתוכננים, וכל שידורי המיקום של הרכבות (SIRI, מפעיל 2). שידורי
כל נסיעה מוצמדים לנסיעת הלו"ז שלה (לפי המזהה שדאטאבוס קבע, ובהיעדרו לפי
קו + שעת יציאה), ולכל תחנה נאמד זמן ההגעה בפועל: השידור הראשון בנקודת
ההתקרבות הקרובה ביותר לתחנה (עד 150 מ' מהמרחק המזערי, בחלון של ±45 דקות
סביב הזמן המתוכנן). האיחור = ההגעה שנאמדה פחות המתוכנן. רכבת נחשבת "בזמן"
כשהגיעה ליעדה הסופי באיחור של עד 5 דקות (ההגדרה המקובלת של דיוק הרכבת).

תוצרים (rail/data):
  days/YYYY-MM-DD.json — פירוט הנסיעות והתחנות של היום (לעמוד היום/הנסיעה)
  index.json           — סיכום יומי מצטבר: שיעור בזמן, איחור ממוצע/חציוני,
                         התפלגות, לפי קו/תחנה/שעה
  stations.json        — קוד תחנה → שם ומיקום
  state.json           — כמה ימים נותרו בטווח שהתבקש (לשרשור ריצות)

FROM/TO (YYYY-MM-DD; ברירת מחדל: אתמול, שעון ישראל) · MAX_MIN — עצירה
נקייה אחרי X דקות (0 = בלי מגבלה) · DRY=1 — ניתוח והדפסה בלי כתיבה ·
REDO=1 — חישוב מחדש גם לימים שכבר קיימים.
"""
import datetime
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

IL = ZoneInfo('Asia/Jerusalem')
API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'rail/data')
DAYS = f'{OUTDIR}/days'
INDEX = f'{OUTDIR}/index.json'
STATIONS = f'{OUTDIR}/stations.json'
STATE = f'{OUTDIR}/state.json'
OP = '2'            # רכבת ישראל
PAGE = 10000
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
DRY = os.environ.get('DRY') == '1'
REDO = os.environ.get('REDO') == '1'
NOW_IL = datetime.datetime.now(IL)
YESTERDAY = (NOW_IL - datetime.timedelta(days=1)).date()
FROM = datetime.date.fromisoformat(os.environ.get('FROM') or YESTERDAY.isoformat())
TO = datetime.date.fromisoformat(os.environ.get('TO') or YESTERDAY.isoformat())

# כללי ההצמדה
MAX_DIST = 2000       # מ' — שידור רחוק מזה אינו "ליד התחנה"
NEAR_BUFFER = 150     # מ' — כל השידורים עד כאן מעל המרחק המזערי הם "בתחנה"
SOLID_DIST = 1000     # מ' — התקרבות רחוקה מזה אינה נספרת (אובדן GPS במנהרות)
TIME_WIN = 45 * 60    # שניות — חלון סביב הזמן המתוכנן
ONTIME_MAX = 5.0      # דקות — "בזמן": איחור ביעד הסופי עד 5 דקות
BUCKETS = ((-1e9, 5), (5, 10), (10, 20), (20, 1e9))   # דקות; הראשון = בזמן
T0 = time.time()


def log(*a):
    print(*a, flush=True)


def elapsed_min():
    return (time.time() - T0) / 60


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return d


def jdump(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def get(path, **params):
    url = f'{API}{path}?' + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-rail/1.0'})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', 'ignore')[:400]
            except Exception:  # noqa: BLE001
                pass
            # שגיאת לקוח (4xx) לא תשתפר בניסיון חוזר — נכשלים מיד עם הסבר השרת
            if 400 <= e.code < 500 or attempt == 5:
                raise RuntimeError(f'HTTP {e.code} {url[:200]} … {body}') from None
            log(f'  retry {attempt + 1}: HTTP {e.code} {body[:120]}')
            time.sleep(5 * (attempt + 1))
        except Exception as e:  # noqa: BLE001 — רשת/‏5xx: ננסה שוב בהדרגה
            if attempt == 5:
                raise
            log(f'  retry {attempt + 1}: {e}')
            time.sleep(5 * (attempt + 1))


def fetch_all(path, **params):
    """כל הרשומות — בעמודים של PAGE לפי מזהה עולה."""
    out = []
    offset = 0
    while True:
        rows = get(path, limit=PAGE, offset=offset, order_by='id asc', **params)
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        offset += PAGE


def iso(dt):
    return dt.isoformat(timespec='seconds')


def ts(s):
    """זמן ISO של דאטאבוס → שניות מאז epoch (None כשאין)."""
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- שליפה
def fetch_day(d):
    start = datetime.datetime.combine(d, datetime.time(0), tzinfo=IL)
    end = start + datetime.timedelta(days=1)
    stops = fetch_all('/gtfs_ride_stops/list',
                      gtfs_route__operator_refs=OP,
                      gtfs_route__date_from=d.isoformat(), gtfs_route__date_to=d.isoformat(),
                      gtfs_ride__start_time_from=iso(start), gtfs_ride__start_time_to=iso(end))
    log(f'  לו"ז: {len(stops)} תחנות-נסיעה ({elapsed_min():.1f} דק׳)')
    # השידורים נשלפים בפרוסות של שעה — רשימה של יום שלם כבדה מדי לשרת.
    # נסיעות שהתחילו לפני חצות ממשיכות לשדר אחרי חצות, לכן 27 שעות.
    locs = []
    for h in range(27):
        a = start + datetime.timedelta(hours=h)
        b = a + datetime.timedelta(hours=1)
        rows = fetch_all('/siri_vehicle_locations/list',
                         siri_routes__operator_ref=OP,
                         siri_rides__scheduled_start_time_from=iso(start),
                         siri_rides__scheduled_start_time_to=iso(end),
                         recorded_at_time_from=iso(a), recorded_at_time_to=iso(b))
        locs.extend(rows)
    log(f'  שידורים: {len(locs)} ({elapsed_min():.1f} דק׳)')
    return start, stops, locs


# ---------------------------------------------------------------- הצמדה
def build_rides(stops, locs):
    by_ride = {}
    for s in stops:
        rid = s.get('gtfs_ride_id')
        if rid is None or s.get('gtfs_stop__lat') is None:
            continue
        by_ride.setdefault(rid, []).append(s)
    for v in by_ride.values():
        v.sort(key=lambda s: s.get('stop_sequence') or 0)
    # גיבוי להצמדה: קו + שעת יציאה מתוכננת (כשדאטאבוס לא קבע gtfs_ride_id)
    bykey = {}
    for rid, v in by_ride.items():
        first = v[0]
        for t in (ts(first.get('gtfs_ride__start_time')), ts(first.get('arrival_time')),
                  ts(first.get('departure_time'))):
            if t is not None:
                bykey.setdefault((first.get('gtfs_route__line_ref'), int(t)), rid)
    siri = {}
    for l in locs:
        sid = l.get('siri_ride__id')
        if sid is None or l.get('lat') is None or l.get('lon') is None:
            continue
        t = ts(l.get('recorded_at_time'))
        if t is None:
            continue
        sr = siri.setdefault(sid, {'g': l.get('siri_ride__gtfs_ride_id'),
                                   'line': l.get('siri_route__line_ref'),
                                   'st': ts(l.get('siri_ride__scheduled_start_time')),
                                   'veh': l.get('siri_ride__vehicle_ref'), 'fx': []})
        sr['fx'].append((t, l['lat'], l['lon']))
    fixes = {}
    vehs = {}
    n_unmatched = 0
    n_bykey = 0
    for sr in siri.values():
        rid = sr['g'] if sr['g'] in by_ride else None
        if rid is None and sr['st'] is not None:
            rid = bykey.get((sr['line'], int(sr['st'])))
            if rid is not None:
                n_bykey += 1
        if rid is None:
            n_unmatched += 1
            continue
        fixes.setdefault(rid, []).extend(sr['fx'])
        if sr['veh']:
            vehs.setdefault(rid, sr['veh'])
    for v in fixes.values():
        v.sort()
        # כפילויות (אותו שידור בשני snapshots) מסולקות
        w = []
        for f in v:
            if not w or f != w[-1]:
                w.append(f)
        v[:] = w
    log(f'  נסיעות בלו"ז: {len(by_ride)} · נסיעות SIRI: {len(siri)} '
        f'(הוצמדו לפי קו+שעה: {n_bykey}, בלי הצמדה: {n_unmatched}) · עם שידורים: {len(fixes)}')
    return by_ride, fixes, vehs


def station_timing(stop, fx):
    """אומדן הגעה/יציאה בתחנה מתוך השידורים: (הגעה, יציאה, מרחק מזערי, ob)."""
    pt = ts(stop.get('arrival_time'))
    if pt is None:
        return None
    lat, lon = stop['gtfs_stop__lat'], stop['gtfs_stop__lon']
    cands = []
    for t, la, lo in fx:
        if abs(t - pt) > TIME_WIN:
            continue
        dist = hav(lat, lon, la, lo)
        if dist <= MAX_DIST:
            cands.append((dist, t))
    if not cands:
        return None
    near = min(d for d, _ in cands)
    close = [t for d, t in cands if d <= near + NEAR_BUFFER]
    # השיטה של דאטאבוס (לשם השוואה בלוג): השידור האחרון עד 200 מ' מעל המזערי
    ob = max(t for d, t in cands if d <= min(near + 200, MAX_DIST))
    return min(close), max(close), near, ob


def analyse_ride(v, fx):
    """שורות התחנות של נסיעה: [קוד, הגעה מתוכננת, יציאה מתוכננת, איחור הגעה,
    איחור יציאה, מרחק מזערי] — הזמנים בדקות מתחילת היום, האיחורים בדקות."""
    rows = []
    obs = []
    for i, s in enumerate(v):
        pa, pd = ts(s.get('arrival_time')), ts(s.get('departure_time'))
        code = s.get('gtfs_stop__code')
        row = [code, pa, pd if pd is not None and pd != pa else None, None, None, None]
        tm = station_timing(s, fx) if fx else None
        if tm and tm[2] <= SOLID_DIST:
            arr, dep, near, ob = tm
            row[3] = round((arr - pa) / 60, 1)
            if pd is not None:
                row[4] = round((dep - pd) / 60, 1)
            row[5] = int(near)
            obs.append(((ob - pa) / 60, i == len(v) - 1))
        rows.append(row)
    return rows, obs


def day_minutes(t, start):
    return None if t is None else int(round((t - start.timestamp()) / 60))


def process_day(d, stations):
    start, stops, locs = fetch_day(d)
    by_ride, fixes, vehs = build_rides(stops, locs)
    rides = []
    ob_final = []
    for rid, v in sorted(by_ride.items(), key=lambda kv: ts(kv[1][0].get('arrival_time')) or 0):
        first = v[0]
        for s in v:
            code = s.get('gtfs_stop__code')
            if code is not None and code not in stations:
                stations[code] = [s.get('gtfs_stop__name') or '', round(s['gtfs_stop__lat'], 5),
                                  round(s['gtfs_stop__lon'], 5), s.get('gtfs_stop__city') or '']
        fx = fixes.get(rid, [])
        rows, obs = analyse_ride(v, fx)
        ob_final.extend(x for x, last in obs if last)
        srows = [[r[0], day_minutes(r[1], start), day_minutes(r[2], start) if r[2] is not None else None,
                  r[3], r[4], r[5]] for r in rows]
        ride = {'id': rid, 'ln': first.get('gtfs_route__line_ref'),
                'nm': (first.get('gtfs_route__route_long_name') or '').strip(),
                'sn': (first.get('gtfs_route__route_short_name') or '').strip(),
                'dir': first.get('gtfs_route__route_direction'),
                'tn': vehs.get(rid) or '', 'fx': len(fx), 's': srows}
        rides.append(ride)
    day = {'d': d.isoformat(), 'rides': rides,
           'n_fix': len(locs), 'built': iso(datetime.datetime.now(IL))}
    summ = summarize(day, stations)
    if ob_final:
        ob_on = sum(1 for x in ob_final if -1 <= x <= 5) / len(ob_final)
        log(f'  השוואה לשיטת דאטאבוס ביעד הסופי: ממוצע {statistics.mean(ob_final):.1f} דק׳, '
            f'בזמן (−1..5) {ob_on:.0%} · אצלנו: ממוצע {summ.get("avg", 0):.1f}, בזמן {summ.get("on", 0):.0%}')
    return day, summ


# ---------------------------------------------------------------- סיכום
def _agg(vals):
    """סטטיסטיקה של רשימת איחורים ביעד: n, בזמן, ממוצע, חציון, התפלגות."""
    if not vals:
        return None
    vals = sorted(vals)
    n = len(vals)
    return {'n': n, 'on': round(sum(1 for x in vals if x <= ONTIME_MAX) / n, 3),
            'avg': round(statistics.mean(vals), 1), 'med': round(vals[n // 2], 1),
            'p90': round(vals[int(n * 0.9) if n > 1 else 0], 1),
            'b': [sum(1 for x in vals if lo < x <= hi) for lo, hi in BUCKETS]}


def summarize(day, stations):
    rides = day['rides']
    finals = []          # איחור ביעד הסופי
    by_line = {}
    by_hour = {}
    by_station = {}
    n_fix = 0
    n_final = 0
    for r in rides:
        s = r['s']
        if r['fx']:
            n_fix += 1
        fd = s[-1][3] if s else None
        h = (s[0][1] // 60) % 24 if s and s[0][1] is not None else None
        if fd is not None:
            finals.append(fd)
            n_final += 1
        by_line.setdefault(r['nm'], []).append(fd)
        if h is not None:
            by_hour.setdefault(h, []).append(fd)
        for i, row in enumerate(s):
            code = row[0]
            if code is None:
                continue
            # בתחנת המוצא נמדדת היציאה, בשאר — ההגעה
            val = row[4] if i == 0 else row[3]
            by_station.setdefault(code, []).append(val)
    out = {'d': day['d'], 'rides': len(rides), 'fix': n_fix, 'meas': n_final}
    a = _agg(finals)
    if a:
        out.update(a)
    out['lines'] = {k: {'rides': len(v), **(_agg([x for x in v if x is not None]) or {})}
                    for k, v in sorted(by_line.items())}
    out['hours'] = {str(h): {'rides': len(v), **(_agg([x for x in v if x is not None]) or {})}
                    for h, v in sorted(by_hour.items())}
    out['stations'] = {str(k): {'rides': len(v), **(_agg([x for x in v if x is not None]) or {})}
                       for k, v in sorted(by_station.items())}
    return out


def main():
    os.makedirs(DAYS, exist_ok=True)
    stations = jload(STATIONS, {})
    index = jload(INDEX, {'days': []})
    have = {x['d'] for x in index['days']}
    todo = []
    d = FROM
    while d <= TO:
        if REDO or d.isoformat() not in have:
            todo.append(d)
        d += datetime.timedelta(days=1)
    log(f'ימים לעיבוד: {len(todo)} ({FROM}…{TO}) · MAX_MIN={MAX_MIN} · DRY={DRY}')
    done = 0
    for d in todo:
        if MAX_MIN and elapsed_min() > MAX_MIN:
            log('תקציב הזמן נגמר — עצירה נקייה')
            break
        log(f'{d}:')
        try:
            day, summ = process_day(d, stations)
        except Exception as e:  # noqa: BLE001 — יום שנכשל לא עוצר את השאר
            log(f'  נכשל: {e!r}')
            continue
        log(f'  נסיעות {summ["rides"]} · עם שידור {summ["fix"]} · נמדדו ביעד {summ["meas"]} · '
            f'בזמן {summ.get("on", 0):.0%} · ממוצע {summ.get("avg", 0)} דק׳ · חציון {summ.get("med", 0)}')
        done += 1
        if DRY:
            continue
        jdump(day, f'{DAYS}/{d.isoformat()}.json')
        index['days'] = [x for x in index['days'] if x['d'] != summ['d']] + [summ]
        index['days'].sort(key=lambda x: x['d'])
        index['updated'] = iso(datetime.datetime.now(IL))
        jdump(index, INDEX)
        jdump(stations, STATIONS)
    remaining = len(todo) - done
    if not DRY:
        jdump({'from': FROM.isoformat(), 'to': TO.isoformat(), 'remaining': remaining,
               'updated': iso(datetime.datetime.now(IL))}, STATE)
    log(f'סיום: {done} ימים עובדו, {remaining} נותרו ({elapsed_min():.1f} דק׳)')


if __name__ == '__main__':
    sys.exit(main())
