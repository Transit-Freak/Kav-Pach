# -*- coding: utf-8 -*-
"""בדיקה אמיתית לטריק של "קו הנהגים" (osrm.js): מזינים ל-OSRM את צורת הקו מ-GTFS
כנקודות ביניים רבות, ומצפים שמנוע הרכב יחזיר את מסלול האוטובוס עצמו, עם הוראות
פנייה ומספרי יציאה בכיכרות.

רץ ב-GitHub Actions מול שני שרתי OSRM משלנו על מפת ישראל:
  car — הפרופיל הרשמי לרכב (מה ששרת ההדגמה הציבורי מריץ)
  bus — tools/osrm/bus-il.lua (נת"צים פתוחים, דרכי אוטובוס)

לכל קו נבדקים:
  route/95   — כמו האפליקציה: 95 נקודות ביניים, כל נקודה מקטע (legs)
  route/300  — צפוף יותר
  route/1leg — 300 נקודות אבל waypoints=0;299 → מקטע אחד, בלי "הגעה/יציאה" מזויפים
  match      — התאמת מפה אמיתית (/match), רק בשרת שלנו (הציבורי חוסם: TooBig)
ולכל בדיקה: יחס אורך המסלול לאורך הצורה, סטייה מרבית ואחוזון 95 מהצורה,
מספר הוראות פנייה, כיכרות (וכמה מהן עם מספר יציאה), וכמה "פניות" מזויפות
היו נספרות באפליקציה כי צעדי arrive/depart של כל נקודת ביניים נושאים modifier.

    python3 tools/osrm_shape_probe.py gtfs.zip http://localhost:5000 [http://localhost:5001]
"""
import collections
import csv
import datetime
import io
import json
import math
import pathlib
import random
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_MD = ROOT / 'docs' / 'osrm-shape-probe.md'
OUT_JSON = ROOT / 'docs' / 'osrm-shape-probe.json'

GTFS = pathlib.Path(sys.argv[1])
SERVERS = {'car': sys.argv[2].rstrip('/')}
if len(sys.argv) > 3 and sys.argv[3]:
    SERVERS['bus'] = sys.argv[3].rstrip('/')
random.seed(7)


# ── GTFS ────────────────────────────────────────────────────────────────────
def rows(z, name):
    with z.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))


def seg_m(a, b):
    """מרחק במטרים בין שתי נקודות (lat, lon) — קירוב שווה-מלבני, מספיק בקנה מידה עירוני."""
    lat0 = math.radians((a[0] + b[0]) / 2)
    dx = math.radians(b[1] - a[1]) * math.cos(lat0) * 6371000
    dy = math.radians(b[0] - a[0]) * 6371000
    return math.hypot(dx, dy)


def shape_lengths(z):
    """מעבר ראשון על shapes.txt: אורך כל צורה במטרים ומספר נקודותיה (בלי לשמור נקודות)."""
    L = {}
    with z.open('shapes.txt') as f:
        r = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))
        hdr = next(r)
        i_id, i_lat, i_lon = hdr.index('shape_id'), hdr.index('shape_pt_lat'), hdr.index('shape_pt_lon')
        last = {}
        for row in r:
            sid = row[i_id]
            p = (float(row[i_lat]), float(row[i_lon]))
            if sid in last:
                L[sid][0] += seg_m(last[sid], p)
                L[sid][1] += 1
            else:
                L[sid] = [0.0, 1]
            last[sid] = p
    return L


def shape_points(z, wanted):
    """מעבר שני: הנקודות של הצורות שנבחרו, מסודרות לפי shape_pt_sequence."""
    P = collections.defaultdict(list)
    with z.open('shapes.txt') as f:
        r = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))
        hdr = next(r)
        i_id, i_lat, i_lon, i_seq = (hdr.index(k) for k in ('shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence'))
        for row in r:
            if row[i_id] in wanted:
                P[row[i_id]].append((int(row[i_seq]), float(row[i_lat]), float(row[i_lon])))
    return {k: [(la, lo) for _, la, lo in sorted(v)] for k, v in P.items()}


def pick_routes(z):
    agencies = {a['agency_id']: a['agency_name'] for a in rows(z, 'agency.txt')}
    routes = {r['route_id']: r for r in rows(z, 'routes.txt') if r.get('route_type') == '3'}
    trip_of = {}   # route_id → (trip_id, shape_id, headsign) — הנסיעה הראשונה בכיוון 0 עם צורה
    for t in rows(z, 'trips.txt'):
        rid = t['route_id']
        if rid not in routes or not t.get('shape_id'):
            continue
        if rid not in trip_of or (t.get('direction_id') == '0' and trip_of[rid][3] != '0'):
            trip_of[rid] = (t['trip_id'], t['shape_id'], t.get('trip_headsign', ''), t.get('direction_id', ''))
    print(f'קווי אוטובוס: {len(routes)} · עם צורה: {len(trip_of)}')
    L = shape_lengths(z)
    print(f'צורות: {len(L)}')
    cands = []
    for rid, (tid, sid, hs, _) in trip_of.items():
        if sid in L and L[sid][1] >= 20:
            r = routes[rid]
            cands.append({'route_id': rid, 'trip_id': tid, 'shape_id': sid, 'agency': agencies.get(r['agency_id'], r['agency_id']),
                          'short': r['route_short_name'], 'long': r['route_long_name'], 'len_m': L[sid][0], 'pts': L[sid][1]})
    chosen, seen = [], set()

    def add(c, why):
        if c and c['shape_id'] not in seen:
            seen.add(c['shape_id']); c['why'] = why; chosen.append(c)

    def find(pred):
        m = [c for c in cands if pred(c)]
        return m[0] if m else None
    # קווים מוכרים
    add(find(lambda c: c['short'] == '5' and 'דן' in c['agency'] and 'תל אביב' in c['long']), 'עירוני מוכר — דן 5')
    add(find(lambda c: c['short'] == '480' and 'אגד' in c['agency']), 'בינעירוני מוכר — אגד 480')
    add(find(lambda c: 'מטרונית' in c['long'] or ('חיפה' in c['long'] and c['short'] in ('1', '2', '3') and 'נתיב אקספרס' in c['agency'])), 'מטרונית / נתיב ייעודי')
    # מדגם מדורג לפי אורך, עם ערים שבהן הרבה נת"צים
    def sample(pred, n, why):
        pool = [c for c in cands if pred(c) and c['shape_id'] not in seen]
        for c in random.sample(pool, min(n, len(pool))):
            add(c, why)
    sample(lambda c: 'ירושלים' in c['long'] and c['len_m'] < 15000, 1, 'עירוני ירושלים (נת"צים)')
    sample(lambda c: 'חיפה' in c['long'] and c['len_m'] < 15000, 1, 'עירוני חיפה')
    sample(lambda c: 'באר שבע' in c['long'] and c['len_m'] < 15000, 1, 'עירוני באר שבע')
    sample(lambda c: c['len_m'] < 7000, 2, 'עירוני קצר, אקראי')
    sample(lambda c: 7000 <= c['len_m'] < 25000, 2, 'בינוני, אקראי')
    sample(lambda c: c['len_m'] >= 45000, 2, 'בינעירוני ארוך, אקראי')
    return chosen


# ── גאומטריה ────────────────────────────────────────────────────────────────
def to_xy(pts, lat0):
    k = math.cos(math.radians(lat0)) * 111320.0
    return [(lo * k, la * 110540.0) for la, lo in pts]


def deviation(route_xy, shape_xy):
    """לכל נקודת מסלול — המרחק לקטע הקרוב ביותר בצורה. מחזיר (מקסימום, אחוזון 95, אחוז מעל 30 מ׳)."""
    if len(shape_xy) < 2 or not route_xy:
        return None
    # רשת גסה של קטעים כדי לא לעבור על כל הצורה לכל נקודה
    cell = 250.0
    grid = collections.defaultdict(list)
    for i in range(len(shape_xy) - 1):
        (x1, y1), (x2, y2) = shape_xy[i], shape_xy[i + 1]
        for gx in range(int(min(x1, x2) // cell), int(max(x1, x2) // cell) + 1):
            for gy in range(int(min(y1, y2) // cell), int(max(y1, y2) // cell) + 1):
                grid[(gx, gy)].append(i)
    def d_seg(px, py, i):
        (x1, y1), (x2, y2) = shape_xy[i], shape_xy[i + 1]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
    ds = []
    for px, py in route_xy:
        gx, gy = int(px // cell), int(py // cell)
        best = None
        for ring in range(0, 4):           # מתרחבים עד שמוצאים קטעים
            idx = set()
            for ax in range(gx - ring, gx + ring + 1):
                for ay in range(gy - ring, gy + ring + 1):
                    idx.update(grid.get((ax, ay), ()))
            if idx:
                best = min(d_seg(px, py, i) for i in idx)
                if ring >= 1 or best < cell / 2:
                    break
        ds.append(best if best is not None else 999.0)
    ds.sort()
    return {'max_m': round(ds[-1]), 'p95_m': round(ds[int(len(ds) * 0.95) - 1]), 'over30_pct': round(100 * sum(1 for d in ds if d > 30) / len(ds), 1)}


def poly_len_xy(xy):
    return sum(math.hypot(xy[i + 1][0] - xy[i][0], xy[i + 1][1] - xy[i][1]) for i in range(len(xy) - 1))


# ── OSRM ────────────────────────────────────────────────────────────────────
TURN_MODS = {'left', 'slight left', 'sharp left', 'right', 'slight right', 'sharp right'}


def classify(man, name):
    """כמו classify של האפליקציה, אבל בלי לספור arrive/depart — ומחזיר גם אם האפליקציה הייתה סופרת."""
    t, mod = man.get('type', ''), man.get('modifier', '') or ''
    if t in ('roundabout', 'rotary'):
        return {'kind': 'roundabout', 'exit': man.get('exit'), 'name': name}, False
    if t in ('exit roundabout', 'exit rotary'):
        return None, False
    if mod not in TURN_MODS:
        return None, False
    if mod.startswith('slight') and t in ('continue', 'new name'):
        return None, False
    if t in ('arrive', 'depart'):
        return None, True    # האפליקציה הייתה סופרת את זה כפנייה
    return {'kind': 'left' if 'left' in mod else 'right', 'name': name, 'type': t}, False


def get(url):
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read().decode('utf-8'))


def thin(pts, n):
    n = min(n, len(pts))
    step = (len(pts) - 1) / (n - 1)
    return [pts[round(i * step)] for i in range(n)]


def summarize(legs, geom, shape_xy, shape_len, lat0):
    mans, fake, rb, rb_exit = [], 0, 0, 0
    for leg in legs:
        for st in leg.get('steps', []):
            m, is_fake = classify(st.get('maneuver', {}), st.get('name', ''))
            fake += is_fake
            if m:
                mans.append(m)
                if m['kind'] == 'roundabout':
                    rb += 1; rb_exit += 1 if m.get('exit') else 0
    route_xy = to_xy([(la, lo) for lo, la in geom], lat0)
    dist = poly_len_xy(route_xy)
    dev = deviation(route_xy, shape_xy)
    return {'dist_m': round(dist), 'ratio': round(dist / shape_len, 3) if shape_len else None, 'turns': sum(1 for m in mans if m['kind'] != 'roundabout'),
            'roundabouts': rb, 'roundabouts_with_exit': rb_exit, 'fake_turns_app': fake, 'dev': dev, 'maneuvers': mans}


def test_route(server, pts, n, one_leg):
    wp = thin(pts, n)
    coords = ';'.join(f'{lo:.6f},{la:.6f}' for la, lo in wp)
    url = f'{server}/route/v1/driving/{coords}?steps=true&overview=full&geometries=geojson'
    if one_leg:
        url += f'&waypoints=0;{len(wp) - 1}'
    j = get(url)
    if j.get('code') != 'Ok':
        return {'error': j.get('code')}
    r = j['routes'][0]
    return r['legs'], r['geometry']['coordinates']


def test_match(server, pts, n):
    wp = thin(pts, n)
    coords = ';'.join(f'{lo:.6f},{la:.6f}' for la, lo in wp)
    url = (f'{server}/match/v1/driving/{coords}?steps=true&overview=full&geometries=geojson&gaps=ignore&tidy=true'
           f'&radiuses={";".join(["25"] * len(wp))}&waypoints=0;{len(wp) - 1}')
    j = get(url)
    if j.get('code') != 'Ok':
        return {'error': j.get('code')}
    ms = j['matchings']
    legs = [l for m in ms for l in m['legs']]
    geom = [c for m in ms for c in m['geometry']['coordinates']]
    return legs, geom, {'pieces': len(ms), 'confidence': round(min(m.get('confidence', 0) for m in ms), 3)}


# ── הרצה ────────────────────────────────────────────────────────────────────
def main():
    z = zipfile.ZipFile(GTFS)
    chosen = pick_routes(z)
    print('נבחרו:', len(chosen))
    shapes = shape_points(z, {c['shape_id'] for c in chosen})
    results = []
    for c in chosen:
        pts = shapes[c['shape_id']]
        lat0 = sum(p[0] for p in pts) / len(pts)
        shape_xy = to_xy(pts, lat0)
        shape_len = poly_len_xy(shape_xy)
        rec = {**c, 'shape_len_m': round(shape_len), 'tests': {}}
        print(f"\n{c['agency']} {c['short']} · {c['long'][:50]} · {shape_len/1000:.1f} ק״מ · {len(pts)} נקודות · {c['why']}")
        for prof, server in SERVERS.items():
            for name, n, one in (('route/95', 95, False), ('route/300', 300, False), ('route/1leg', 300, True)):
                try:
                    res = test_route(server, pts, n, one)
                    if isinstance(res, dict):
                        rec['tests'][f'{prof} {name}'] = res
                        print(f'  {prof} {name}: שגיאה {res["error"]}')
                        continue
                    s = summarize(res[0], res[1], shape_xy, shape_len, lat0)
                    rec['tests'][f'{prof} {name}'] = s
                    print(f"  {prof} {name}: יחס {s['ratio']} · סטייה מקס׳ {s['dev']['max_m']} מ׳ / p95 {s['dev']['p95_m']} · פניות {s['turns']} · כיכרות {s['roundabouts']} ({s['roundabouts_with_exit']} עם יציאה) · מזויפות באפליקציה {s['fake_turns_app']}")
                except Exception as e:
                    rec['tests'][f'{prof} {name}'] = {'error': str(e)[:120]}
                    print(f'  {prof} {name}: נכשל {e}')
            if prof == 'bus':
                try:
                    res = test_match(server, pts, 300)
                    if isinstance(res, dict):
                        rec['tests']['bus match'] = res; print(f'  bus match: שגיאה {res["error"]}')
                    else:
                        s = summarize(res[0], res[1], shape_xy, shape_len, lat0); s.update(res[2])
                        rec['tests']['bus match'] = s
                        print(f"  bus match: יחס {s['ratio']} · סטייה מקס׳ {s['dev']['max_m']} · חתיכות {s['pieces']} · ביטחון {s['confidence']} · פניות {s['turns']} · כיכרות {s['roundabouts']}")
                except Exception as e:
                    rec['tests']['bus match'] = {'error': str(e)[:120]}
                    print(f'  bus match: נכשל {e}')
        results.append(rec)
    write(results)


def write(results):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M')
    tests = ['car route/95', 'car route/300', 'car route/1leg', 'bus route/95', 'bus route/300', 'bus route/1leg', 'bus match']
    tests = [t for t in tests if any(t in r['tests'] for r in results)]
    L = [f'# בדיקת הטריק של "קו הנהגים": צורת GTFS כנקודות ביניים ל-OSRM', '',
         f'נבנה {now} (שעון ישראל) · GTFS {GTFS.name} · {len(results)} קווים · שרתים: {", ".join(SERVERS)}', '',
         'לכל בדיקה: **יחס** = אורך המסלול שחזר / אורך הצורה (1.00 = שחזור מדויק). **סטייה** = מרחק מקסימלי / אחוזון 95 של המסלול מהצורה במטרים. ',
         '**פניות / כיכרות** = הוראות שהיו מוצגות לנהג (כיכרות: כמה עם מספר יציאה). **מזויפות** = צעדי הגעה/יציאה בנקודות הביניים שנושאים כיוון, שהאפליקציה כיום סופרת כפניות.', '']
    for t in tests:
        L += [f'## {t}', '', '| קו | למה נבחר | צורה ק״מ | יחס | סטייה מקס׳ / p95 | מעל 30 מ׳ | פניות | כיכרות (עם יציאה) | מזויפות |' + (' חתיכות · ביטחון |' if 'match' in t else ''),
              '|---|---|---|---|---|---|---|---|---|' + ('---|' if 'match' in t else '')]
        for r in results:
            s = r['tests'].get(t)
            name = f"{r['agency']} {r['short']} · {r['long'][:40]}"
            if not s or 'error' in (s or {}):
                L.append(f"| {name} | {r['why']} | {r['shape_len_m']/1000:.1f} | שגיאה: {(s or {}).get('error','—')} | | | | | |" + (' |' if 'match' in t else ''))
                continue
            d = s['dev'] or {}
            L.append(f"| {name} | {r['why']} | {r['shape_len_m']/1000:.1f} | {s['ratio']} | {d.get('max_m')} / {d.get('p95_m')} | {d.get('over30_pct')}% | {s['turns']} | {s['roundabouts']} ({s['roundabouts_with_exit']}) | {s['fake_turns_app']} |"
                     + (f" {s.get('pieces')} · {s.get('confidence')} |" if 'match' in t else ''))
        L.append('')
    # דוגמה: ההוראות שהיו מוצגות לנהג בקו הראשון, מהבדיקה הטובה
    ex = results[0] if results else None
    # הדוגמה מהשיטה שעבדה בפועל: התאמת מפה. הניתוב דרך נקודות ביניים נתן רשימות חסרות משמעות.
    best = next((k for k in ('bus match', 'bus route/1leg', 'car route/1leg') if ex and k in ex['tests'] and 'maneuvers' in ex['tests'][k]), None)
    if ex and best:
        L += [f"## דוגמה: ההוראות לנהג — {ex['agency']} {ex['short']} · {ex['long'][:50]} ({best})", '']
        EXIT_HE = ['', 'הראשונה', 'השנייה', 'השלישית', 'הרביעית', 'החמישית', 'השישית']
        for m in ex['tests'][best]['maneuvers'][:40]:
            if m['kind'] == 'roundabout':
                ex_txt = (f"צאו ביציאה {EXIT_HE[m['exit']] if m.get('exit') and m['exit'] < len(EXIT_HE) else m.get('exit')}" if m.get('exit') else 'המשיכו')
                L.append(f"- בכיכר — {ex_txt}" + (f" אל {m['name']}" if m.get('name') else ''))
            else:
                L.append(f"- פנו {'ימינה' if m['kind']=='right' else 'שמאלה'}" + (f" אל {m['name']}" if m.get('name') else ''))
        L.append('')
    OUT_MD.write_text('\n'.join(L), encoding='utf-8')
    slim = [{**r, 'tests': {k: {kk: vv for kk, vv in v.items() if kk != 'maneuvers'} for k, v in r['tests'].items()}} for r in results]
    OUT_JSON.write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\nנכתב', OUT_MD)


if __name__ == '__main__':
    main()
