# -*- coding: utf-8 -*-
"""נתונים מוכנים ל"קו הנהגים": מה-GTFS של משרד התחבורה — נסיעה מייצגת, תחנות,
צורה והוראות נהיגה לכל קו, כך שהאפליקציה לא צריכה לפרוס את ה-zip בטלפון
ולא לפנות לשרת ניתוב בזמן אמת.

הוראות הנהיגה (פניות, כיכרות עם מספר יציאה) מחושבות בהתאמת מפה (/match) של
צורת הקו לרשת OpenStreetMap בשרת OSRM משלנו עם פרופיל אוטובוס. הבדיקה
docs/osrm-shape-probe.md הראתה שההתאמה משחזרת את הקו ב-±0.5% אורך ו-95%
ממנו בתוך ~10 מ׳; ניתוב דרך נקודות ביניים (השיטה הקודמת של האפליקציה) לא.

פלט (תיקיית --out, לענף nahagim-data):
  index.json / index.json.gz      כל הקווים: id, מספר, שם, מק"ט, מפעיל, סוג, סטטוס ניווט
  routes/<route_id>.json.gz       נסיעה מייצגת, תחנות עם f, צורה, הוראות, איכות
  stats.json                      סיכום הריצה

    python3 tools/nahagim_build.py gtfs.zip --osrm http://localhost:5000 --out nahagim-out
    python3 tools/nahagim_build.py gtfs.zip --limit 50            # בלי הוראות, לבדיקה
"""
import argparse
import collections
import csv
import datetime
import gzip
import io
import json
import math
import pathlib
import re
import sys
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

ROUTE_TYPE = {'0': 'רכבת קלה', '1': 'מטרו', '2': 'רכבת', '3': 'אוטובוס', '4': 'מעבורת', '5': 'קרונית', '6': 'רכבל',
              '7': 'פוניקולר', '11': 'טרוליבוס', '12': 'מונורייל', '715': 'שירות'}
BUS_TYPES = {'3', '715', '11'}
DAY_KEYS = [('sunday', 'א'), ('monday', 'ב'), ('tuesday', 'ג'), ('wednesday', 'ד'), ('thursday', 'ה'), ('friday', 'ו'), ('saturday', 'ש')]
EXIT_HE = ['', 'הראשונה', 'השנייה', 'השלישית', 'הרביעית', 'החמישית', 'השישית']
TURN_MODS = {'left', 'slight left', 'sharp left', 'right', 'slight right', 'sharp right'}
IL = datetime.timezone(datetime.timedelta(hours=3))


# ── קריאת GTFS ───────────────────────────────────────────────────────────────
def reader(z, name):
    with z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))
        hdr = [h.strip() for h in next(r)]
        yield hdr
        yield from r


def dict_rows(z, name):
    it = reader(z, name)
    hdr = next(it)
    for row in it:
        yield dict(zip(hdr, row))


def hm(t):
    if not t:
        return ''
    m = t.split(':')
    if len(m) < 2:
        return t
    try:
        return f'{int(m[0]) % 24:02d}:{m[1]}'
    except ValueError:
        return t


def service_days(cal):
    on = [l for k, l in DAY_KEYS if cal.get(k) == '1']
    if len(on) == 7:
        return 'כל ימות השבוע'
    return '׳, '.join(on) + '׳' if on else ''


# ── גאומטריה ────────────────────────────────────────────────────────────────
class Polyline:
    """מטריקה של צורה (lat, lon): אורך מצטבר במטרים ו-locate(lat, lon) → שבר לאורכה."""

    def __init__(self, pts):
        self.pts = pts
        lat0 = sum(p[0] for p in pts) / len(pts)
        self.kx = math.cos(math.radians(lat0)) * 111320.0
        self.ky = 110540.0
        self.xy = [(lo * self.kx, la * self.ky) for la, lo in pts]
        self.cum = [0.0]
        for i in range(1, len(self.xy)):
            self.cum.append(self.cum[-1] + math.hypot(self.xy[i][0] - self.xy[i - 1][0], self.xy[i][1] - self.xy[i - 1][1]))
        self.total = self.cum[-1] or 1.0

    def locate(self, lat, lon, f_min=0.0):
        """הנקודה הקרובה ביותר על הצורה → (שבר לאורכה, מרחק במטרים). f_min מגביל את
        החיפוש לחלק שאחרי שבר נתון: הוראות מגיעות לפי סדר הנסיעה, ובלולאה (מחלף,
        רמפה) המסלול עובר פעמיים באותו מקום — בלי ההגבלה ההוראה נדבקת למעבר הלא נכון."""
        px, py = lon * self.kx, lat * self.ky
        best, best_len = float('inf'), 0.0
        xy = self.xy
        start = 1
        if f_min > 0:
            target = f_min * self.total
            while start < len(xy) - 1 and self.cum[start] < target:
                start += 1
        for i in range(start, len(xy)):
            ax, ay = xy[i - 1]
            bx, by = xy[i]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy or 1e-9
            t = ((px - ax) * dx + (py - ay) * dy) / L2
            t = 0.0 if t < 0 else 1.0 if t > 1 else t
            cx, cy = ax + t * dx, ay + t * dy
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            if d2 < best:
                best, best_len = d2, self.cum[i - 1] + math.sqrt(L2) * t
        return best_len / self.total, math.sqrt(best)


def thin(pts, n):
    n = max(2, min(n, len(pts)))
    step = (len(pts) - 1) / (n - 1)
    return [pts[round(i * step)] for i in range(n)]


# ── OSRM: התאמת מפה → הוראות ────────────────────────────────────────────────
def classify(man, name):
    t, mod = man.get('type', ''), man.get('modifier', '') or ''
    if t in ('roundabout', 'rotary'):
        ex = man.get('exit')
        ord_ = EXIT_HE[ex] if ex and ex < len(EXIT_HE) else (f'ה־{ex}' if ex else '')
        text = (f'בכיכר — צאו ביציאה {ord_}' if ex else 'בכיכר') + (f' אל {name}' if name else '')
        return {'kind': 'roundabout', 'exit': ex, 'name': name, 'street': name, 'text': text}
    if t in ('exit roundabout', 'exit rotary', 'arrive', 'depart', 'merge'):
        return None          # התמזגות אינה הוראת פנייה
    if mod not in TURN_MODS:
        return None
    if mod.startswith('slight') and t in ('continue', 'new name'):
        return None
    d = 'right' if 'right' in mod else 'left'
    # הבחנה ששלמה דרש (02.09, מחלף עד הלום): התפצלות/רמפה היא "היצמדו לימין", לא "פנו ימינה"
    if t in ('fork', 'off ramp', 'on ramp'):
        side = 'לימין' if d == 'right' else 'לשמאל'
        return {'kind': f'keep-{d}', 'exit': None, 'name': name, 'street': name, 'text': f'היצמדו {side}' + (f' אל {name}' if name else ''), 'type': t}
    lead = 'בסוף הדרך פנו ' if t == 'end of road' else 'פנו '
    dd = 'ימינה' if d == 'right' else 'שמאלה'
    return {'kind': d, 'exit': None, 'name': name, 'street': name, 'text': lead + dd + (f' אל {name}' if name else ''), 'type': t}


def http_json(url, timeout=120):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def match_chunk(osrm, pts, radius=25, tidy=True):
    coords = ';'.join(f'{lo:.6f},{la:.6f}' for la, lo in pts)
    url = (f'{osrm}/match/v1/driving/{coords}?steps=true&overview=false&gaps=ignore'
           f'&radiuses={";".join([str(radius)] * len(pts))}&waypoints=0;{len(pts) - 1}' + ('&tidy=true' if tidy else ''))
    return http_json(url)


def maneuvers_for(osrm, pl, chunk_pts=90, spacing_m=70, overlap=12, margin=5):
    """הצורה מדוללת לריווח ~70 מ׳ ונחתכת לחתיכות של עד 90 נקודות, וכל חתיכה מותאמת בנפרד.
    חפיפה של 12 נקודות (~840 מ׳) בין חתיכות, והוראות נלקחות רק מ"פנים" החתיכה — לא
    מ-5 הנקודות (~350 מ׳) שבקצה שמשיק לחתיכה שכנה. בתפר ההתאמה מתחילה מנקודה
    שרירותית ומולידה הוראות שאינן בכביש: "פנו שמאלה / היצמדו לשמאל / היצמדו לימין"
    בקו 17 גן יבנה→אשדוד ישבו כולן בתוך 50 מ׳ מהתפר של החתיכה הרביעית (שלמה 02.09,
    הבדיקה: shots/nah/seam-23.png). הפנים של חתיכות שכנות עדיין חופפים ב-2 נקודות."""
    n = int(max(2, min(len(pl.pts), round(pl.total / spacing_m))))
    pts = thin(pl.pts, n)
    fpts = [pl.locate(la, lo)[0] for la, lo in pts]     # מיקום כל נקודה מדוללת על הקו
    chunks, i = [], 0
    while i < len(pts) - 1:
        j = min(len(pts), i + chunk_pts)
        lo_f = fpts[i + margin] if i > 0 and i + margin < j else -1.0
        hi_f = fpts[j - 1 - margin] if j < len(pts) and j - 1 - margin > i else 2.0
        chunks.append((pts[i:j], lo_f, hi_f))
        if j >= len(pts):
            break
        i += chunk_pts - overlap
    out, matched_m, conf, failed = [], 0.0, [], 0
    cursor = 0.0     # ההוראות מונוטוניות לאורך הקו: כל אחת נמצאת אחרי הקודמת (עד 60 מ׳ אחורה, לחפיפת החתיכות)
    for ch, lo_f, hi_f in chunks:
        if len(ch) < 2:
            continue
        j = None
        for attempt in ((25, True), (40, False)):
            try:
                j = match_chunk(osrm, ch, *attempt)
            except Exception:
                j = None
            if j and j.get('code') == 'Ok':
                break
        if not j or j.get('code') != 'Ok':
            failed += 1
            continue
        for m in j['matchings']:
            matched_m += m.get('distance', 0)
            conf.append(m.get('confidence', 0))
            for leg in m['legs']:
                for st in leg.get('steps', []):
                    mv = classify(st.get('maneuver', {}), st.get('name', ''))
                    if not mv:
                        continue
                    lon, lat = st['maneuver']['location']
                    f, d = pl.locate(lat, lon, f_min=max(0.0, cursor - 60.0 / pl.total))
                    if d > 60:       # הוראה רחוקה מהצורה — לא שלנו
                        continue
                    if f < lo_f or f > hi_f:   # בקצה החתיכה, בחפיפה עם השכנה — תפר, לא כביש
                        continue
                    cursor = max(cursor, f)
                    mv['f'] = round(f, 5)
                    out.append(mv)
    out.sort(key=lambda m: m['f'])
    dedup = []
    for mv in out:
        # כפילות = אותה הוראה (אותו סיווג ואותה יציאה בכיכר) שחוזרת בטווח 25 מ׳ — זה מה
        # שחפיפת החתיכות מייצרת. ימינה ואז שמאלה כמה מטרים אחר כך (צומת מוסט) היא
        # שתי פניות אמיתיות ונשארת (שאלת שלמה 02.09). הזוג ימינה/שמאלה שקפץ במחלף עד
        # הלום נבע מהמיקום השגוי, שכבר מטופל במיקום המונוטוני.
        if dedup and dedup[-1]['kind'] == mv['kind'] and dedup[-1].get('exit') == mv.get('exit') \
                and (mv['f'] - dedup[-1]['f']) * pl.total < 25:
            continue
        # שתי הוראות שונות באותה נקודה (מחלף: היצמדו לשמאל ואז לימין, קו 17 גן יבנה→אשדוד,
        # 18.7 ק"מ) — לנהג זו הוראה אחת מורכבת, לא שתיים שמתחלפות
        if dedup and (mv['f'] - dedup[-1]['f']) * pl.total < 25 and dedup[-1]['kind'] != 'roundabout' and mv['kind'] != 'roundabout':
            last = dedup[-1]
            last['text'] = f"{last['text']}, ואז {mv['text']}"
            last['then'] = mv['kind']
            continue
        dedup.append(mv)
    ratio = round(matched_m / pl.total, 3) if pl.total else None
    status = 'none' if not chunks or failed == len(chunks) else \
        ('ok' if failed == 0 and ratio and 0.95 <= ratio <= 1.06 and min(conf or [0]) >= 0.3 else 'weak')
    return dedup, {'status': status, 'ratio': ratio, 'confidence': round(min(conf), 3) if conf else None, 'chunks': len(chunks), 'failed': failed}


# ── בנייה ───────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('gtfs')
    ap.add_argument('--osrm', default='', help='כתובת OSRM (פרופיל אוטובוס); בלי — אין הוראות')
    ap.add_argument('--out', default='nahagim-out')
    ap.add_argument('--limit', type=int, default=0, help='רק N קווים ראשונים (בדיקה)')
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    t0 = time.time()
    out = pathlib.Path(a.out)
    (out / 'routes').mkdir(parents=True, exist_ok=True)
    z = zipfile.ZipFile(a.gtfs)
    zi = z.getinfo('routes.txt')
    gtfs_date = '%04d-%02d-%02d' % zi.date_time[:3]

    agencies = {r['agency_id']: r['agency_name'] for r in dict_rows(z, 'agency.txt')}
    routes = []
    for r in dict_rows(z, 'routes.txt'):
        if not r.get('route_id'):
            continue
        desc = r.get('route_desc') or ''
        routes.append({'id': r['route_id'], 'shortName': r.get('route_short_name') or r.get('route_long_name') or '—',
                       'longName': r.get('route_long_name') or '', 'makat': (desc.split('-')[0].strip() if desc else '') or r['route_id'],
                       'routeDesc': desc, 'agencyId': r.get('agency_id') or '_', 'agency': agencies.get(r.get('agency_id') or '_', ''),
                       'type': ROUTE_TYPE.get(r.get('route_type', ''), 'קו'), 'rtype': r.get('route_type', '')})
    if a.limit:
        routes = routes[:a.limit]
    route_ids = {r['id'] for r in routes}
    print(f'קווים: {len(routes)} · GTFS {gtfs_date}')

    # נסיעה מייצגת: הצורה הנפוצה ביותר בקו, והנסיעה הראשונה שנוסעת בה
    shape_count = collections.defaultdict(collections.Counter)
    first_trip = {}   # (route, shape) → trip dict
    for t in dict_rows(z, 'trips.txt'):
        rid = t['route_id']
        if rid not in route_ids:
            continue
        sid = t.get('shape_id') or ''
        shape_count[rid][sid] += 1
        first_trip.setdefault((rid, sid), {'tripId': t['trip_id'], 'shapeId': sid, 'headsign': t.get('trip_headsign', ''),
                                            'directionId': t.get('direction_id', ''), 'serviceId': t.get('service_id', '')})
    rep = {}
    for rid, cnt in shape_count.items():
        with_shape = [(c, s) for s, c in cnt.items() if s]
        sid = max(with_shape)[1] if with_shape else cnt.most_common(1)[0][0]
        rep[rid] = first_trip[(rid, sid)]
    print(f'נסיעות מייצגות: {len(rep)} ({time.time() - t0:.0f} ש׳)')

    rep_trip_ids = {t['tripId']: rid for rid, t in rep.items()}
    stop_times = collections.defaultdict(list)
    it = reader(z, 'stop_times.txt')
    hdr = next(it)
    i_t, i_s, i_q, i_a = hdr.index('trip_id'), hdr.index('stop_id'), hdr.index('stop_sequence'), hdr.index('arrival_time')
    for row in it:
        tid = row[i_t]
        if tid in rep_trip_ids:
            stop_times[tid].append((int(row[i_q] or 0), row[i_s], row[i_a]))
    print(f'זמני תחנות של הנסיעות המייצגות: {sum(len(v) for v in stop_times.values())} ({time.time() - t0:.0f} ש׳)')

    stops = {}
    for s in dict_rows(z, 'stops.txt'):
        try:
            stops[s['stop_id']] = (s.get('stop_name', ''), s.get('stop_code', ''), float(s['stop_lat']), float(s['stop_lon']))
        except (ValueError, KeyError):
            pass

    needed = {t['shapeId'] for t in rep.values() if t['shapeId']}
    shapes = collections.defaultdict(list)
    it = reader(z, 'shapes.txt')
    hdr = next(it)
    i_id, i_la, i_lo, i_sq = (hdr.index(k) for k in ('shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence'))
    for row in it:
        if row[i_id] in needed:
            shapes[row[i_id]].append((int(row[i_sq]), float(row[i_la]), float(row[i_lo])))
    for sid in shapes:
        shapes[sid] = [(la, lo) for _, la, lo in sorted(shapes[sid])]
    print(f'צורות: {len(shapes)} ({time.time() - t0:.0f} ש׳)')
    calendar = {c['service_id']: c for c in dict_rows(z, 'calendar.txt')} if 'calendar.txt' in z.namelist() else {}

    # ── קובץ לכל קו ────────────────────────────────────────────────────────
    stats = collections.Counter()

    def build(r):
        t = rep.get(r['id'])
        if not t:
            stats['no_trip'] += 1
            r['nav'] = 'none'
            return None
        st_rows = sorted(stop_times.get(t['tripId'], []))
        st = []
        for i, (_, sid, arr) in enumerate(st_rows):
            s = stops.get(sid)
            st.append({'id': sid, 'seq': i + 1, 'name': s[0] if s else sid, 'code': s[1] if s else '',
                       'lat': s[2] if s else None, 'lon': s[3] if s else None, 'time': hm(arr)})
        geom = shapes.get(t['shapeId']) or []
        if len(geom) < 2:
            geom = [(s['lat'], s['lon']) for s in st if s['lat'] is not None]
        maneuvers, nav = [], {'status': 'none'}
        if len(geom) >= 2:
            pl = Polyline(geom)
            last = 0.0
            for s in st:
                f = pl.locate(s['lat'], s['lon'])[0] if s['lat'] is not None else None
                if f is None or f < last:
                    f = last + 0.0001
                last = f
                s['f'] = round(min(0.999, max(0.0005, f)), 5)
            total = round(pl.total)
            if a.osrm and r['rtype'] in BUS_TYPES:
                maneuvers, nav = maneuvers_for(a.osrm, pl)
        else:
            total = 0
            for i, s in enumerate(st):
                s['f'] = round(i / (len(st) - 1), 5) if len(st) > 1 else 0.5
        r['nav'] = nav['status']
        stats['nav_' + nav['status']] += 1
        headsign = t['headsign'] or (st[-1]['name'] if st else r['longName'])
        doc = {'id': r['id'], 'shortName': r['shortName'], 'longName': r['longName'], 'makat': r['makat'], 'agency': r['agency'],
               'type': r['type'], 'gtfs_date': gtfs_date,
               'trip': {'routeId': r['id'], 'tripId': t['tripId'], 'headsign': headsign, 'direction': 'חזור' if t['directionId'] == '1' else 'הלוך',
                        'makat': r['makat'], 'departure': st[0]['time'] if st else '',
                        'serviceDays': service_days(calendar[t['serviceId']]) if t['serviceId'] in calendar else '', 'stops': st},
               'geom': [[round(la, 5), round(lo, 5)] for la, lo in geom], 'totalMeters': total,
               'maneuvers': maneuvers, 'nav': nav}
        with gzip.open(out / 'routes' / f"{r['id']}.json.gz", 'wt', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
        return r['id']

    with ThreadPoolExecutor(max_workers=a.workers if a.osrm else 2) as ex:
        done = 0
        for _ in ex.map(build, routes):
            done += 1
            if done % 500 == 0:
                print(f'  {done}/{len(routes)} ({time.time() - t0:.0f} ש׳)')

    built = datetime.datetime.now(IL).strftime('%d.%m.%Y %H:%M')
    index = {'built': built, 'gtfs_date': gtfs_date, 'source': 'GTFS משרד התחבורה · הוראות: OpenStreetMap (ODbL) דרך OSRM',
             'counts': {'routes': len(routes), 'stops': len(stops), 'trips': sum(sum(c.values()) for c in shape_count.values()),
                        'with_nav': stats['nav_ok'], 'weak_nav': stats['nav_weak']},
             'routes': [{k: r[k] for k in ('id', 'shortName', 'longName', 'makat', 'routeDesc', 'agency', 'type', 'nav')} for r in routes]}
    (out / 'index.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    with gzip.open(out / 'index.json.gz', 'wt', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, separators=(',', ':'))
    size = sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
    stats_doc = {'built': built, 'gtfs_date': gtfs_date, 'routes': len(routes), 'seconds': round(time.time() - t0), 'bytes': size, **stats}
    (out / 'stats.json').write_text(json.dumps(stats_doc, ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'README.md').write_text(
        f'# נתוני "קו הנהגים"\n\nנבנה {built} (שעון ישראל) מ-GTFS {gtfs_date} של משרד התחבורה.\n\n'
        f'- `index.json.gz` — {len(routes)} קווים\n- `routes/<route_id>.json.gz` — נסיעה מייצגת, תחנות, צורה, הוראות נהיגה\n\n'
        f'הוראות הנהיגה נגזרות מרשת OpenStreetMap (© OpenStreetMap contributors, ODbL) בהתאמת מפה ב-OSRM. '
        f'הענף נדרס בכל בנייה; ההיסטוריה בריפו הראשי (tools/nahagim_build.py).\n', encoding='utf-8')
    print(f'\nסיום: {len(routes)} קווים · ניווט ok {stats["nav_ok"]} · weak {stats["nav_weak"]} · none {stats["nav_none"]} · '
          f'{size / 1e6:.1f} MB · {time.time() - t0:.0f} ש׳')


if __name__ == '__main__':
    main()
