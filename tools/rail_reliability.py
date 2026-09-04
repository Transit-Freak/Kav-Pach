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
import concurrent.futures
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
    # שאילתה על כל המפעיל בבת אחת נופלת על statement timeout בדאטאבוס; הדרך
    # שעובדת (כמו בעמוד הרכבת של אופן באס) היא לפי מזהי קו: קודם מסלולי
    # היום של רכבת ישראל, ואז התחנות והשידורים לפי המזהים האלה.
    routes = fetch_all('/gtfs_routes/list', operator_refs=OP,
                       date_from=d.isoformat(), date_to=d.isoformat())
    line_refs = sorted({r['line_ref'] for r in routes if r.get('line_ref') is not None})
    log(f'  מסלולי רכבת בלו"ז: {len(routes)} ({len(line_refs)} מזהי קו)')
    if not line_refs:
        raise ValueError('אין מסלולי רכבת ביום הזה')
    # חלון ההגעה נפתח עד 03:00 למחרת כדי שנסיעה שיצאה לפני חצות תישמר על כל
    # תחנותיה; הנסיעות עצמן מסוננות לפי שעת היציאה (בצד שלנו)
    stops = []
    for i in range(0, len(line_refs), 20):
        batch = line_refs[i:i + 20]
        stops.extend(fetch_all('/gtfs_ride_stops/list',
                               gtfs_route__line_refs=','.join(map(str, batch)),
                               gtfs_route__operator_refs=OP,
                               gtfs_route__date_from=d.isoformat(), gtfs_route__date_to=d.isoformat(),
                               arrival_time_from=iso(start),
                               arrival_time_to=iso(end + datetime.timedelta(hours=3))))
    s0, s1 = start.timestamp(), end.timestamp()
    stops = [s for s in stops if (ts(s.get('gtfs_ride__start_time')) or 0) >= s0 - 1
             and (ts(s.get('gtfs_ride__start_time')) or 0) < s1]
    log(f'  לו"ז: {len(stops)} תחנות-נסיעה ({elapsed_min():.1f} דק׳)')

    def locs_of(lr):
        return fetch_all('/siri_vehicle_locations/list',
                         siri_routes__line_ref=str(lr), siri_routes__operator_ref=OP,
                         siri_rides__scheduled_start_time_from=iso(start),
                         siri_rides__scheduled_start_time_to=iso(end))

    locs = []
    # שלושה חוטים — מהיר פי שלושה, ועדיין עדין כלפי דאטאבוס
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        for rows in ex.map(locs_of, line_refs):
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


def diagnose(by_ride, fixes):
    """אבחון (DIAG=1): איפה נופלים השידורים ביחס לתחנות — לכיול כללי ההצמדה."""
    def q(vals, p):
        if not vals:
            return None
        vals = sorted(vals)
        return round(vals[min(len(vals) - 1, int(len(vals) * p))], 1)

    pos_stats = {'first': [], 'mid': [], 'last': []}
    last_gap_t, last_gap_d, first_gap_t, spans, nfix = [], [], [], [], []
    for rid, v in by_ride.items():
        fx = fixes.get(rid, [])
        if not fx:
            continue
        nfix.append(len(fx))
        pa0, paN = ts(v[0].get('departure_time')), ts(v[-1].get('arrival_time'))
        if pa0 and paN:
            first_gap_t.append((fx[0][0] - pa0) / 60)
            last_gap_t.append((fx[-1][0] - paN) / 60)
            spans.append((fx[-1][0] - fx[0][0]) / 60)
            last_gap_d.append(hav(v[-1]['gtfs_stop__lat'], v[-1]['gtfs_stop__lon'], fx[-1][1], fx[-1][2]))
        for i, s in enumerate(v):
            pt = ts(s.get('arrival_time'))
            near = min((hav(s['gtfs_stop__lat'], s['gtfs_stop__lon'], la, lo)
                        for t, la, lo in fx if abs(t - pt) <= TIME_WIN), default=None)
            key = 'first' if i == 0 else 'last' if i == len(v) - 1 else 'mid'
            pos_stats[key].append(near if near is not None else 1e9)
    log(f'  אבחון: שידורים לנסיעה חציון {q(nfix, .5)} · משך שידור חציון {q(spans, .5)} דק׳')
    log(f'  שידור ראשון מול יציאה מתוכננת (דק׳): 10%={q(first_gap_t, .1)} 50%={q(first_gap_t, .5)} 90%={q(first_gap_t, .9)}')
    log(f'  שידור אחרון מול הגעה מתוכננת ליעד (דק׳): 10%={q(last_gap_t, .1)} 50%={q(last_gap_t, .5)} 90%={q(last_gap_t, .9)}')
    log(f'  מרחק השידור האחרון מתחנת היעד (מ׳): 10%={q(last_gap_d, .1)} 50%={q(last_gap_d, .5)} 90%={q(last_gap_d, .9)}')
    for key, vals in pos_stats.items():
        n = len(vals)
        if not n:
            continue
        log(f'  תחנה {key}: n={n} · מרחק מזערי בחלון ±45: ≤300מ׳ {sum(1 for x in vals if x <= 300) / n:.0%} · '
            f'≤1000 {sum(1 for x in vals if x <= 1000) / n:.0%} · ≤2000 {sum(1 for x in vals if x <= 2000) / n:.0%} · '
            f'אין שידור בחלון {sum(1 for x in vals if x >= 1e9) / n:.0%} · חציון {q([x for x in vals if x < 1e9], .5)}')
    # שלוש נסיעות לדוגמה — התחנות והשידורים הקרובים
    for rid, v in list(by_ride.items())[:3]:
        fx = fixes.get(rid, [])
        log(f'  דוגמה {rid} {v[0].get("gtfs_route__route_long_name")} · {len(fx)} שידורים · '
            f'{datetime.datetime.fromtimestamp(fx[0][0], IL).strftime("%H:%M") if fx else "-"}–'
            f'{datetime.datetime.fromtimestamp(fx[-1][0], IL).strftime("%H:%M") if fx else "-"}')
        for s in v:
            pt = ts(s.get('arrival_time'))
            tm = station_timing(s, fx) if fx else None
            log(f'     {s.get("gtfs_stop__name")[:22]:<22} מתוכנן {datetime.datetime.fromtimestamp(pt, IL).strftime("%H:%M")} · '
                + (f'הגעה {datetime.datetime.fromtimestamp(tm[0], IL).strftime("%H:%M")} יציאה {datetime.datetime.fromtimestamp(tm[1], IL).strftime("%H:%M")} מרחק {int(tm[2])}מ׳' if tm else 'אין שידור ≤2000מ׳ בחלון'))


def process_day(d, stations):
    start, stops, locs = fetch_day(d)
    by_ride, fixes, vehs = build_rides(stops, locs)
    if os.environ.get('DIAG') == '1':
        diagnose(by_ride, fixes)
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
