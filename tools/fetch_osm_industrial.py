# -*- coding: utf-8 -*-
# משיכת כל אזורי התעשייה (landuse=industrial) מ-OpenStreetMap דרך Overpass.
# פלט: OUT (ברירת מחדל parks/osm-check/osm-industrial.json) — רשימה קומפקטית
# של כל פוליגון: מזהה OSM, שם, מרכז, שטח בקמ"ר. הגאומטריה המלאה לא נשמרת
# כדי לא לנפח את הריפו — רק מה שנדרש לבדיקת קיום מול המאגר הרשמי.
import json, math, os, sys, time, urllib.request

OUT = os.environ.get('OUT', 'parks/osm-check/osm-industrial.json')
BBOX = os.environ.get('BBOX', '29.4,34.2,33.45,35.95')
SERVERS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]

Q = f'''[out:json][timeout:240];
(
  way["landuse"="industrial"]({BBOX});
  relation["landuse"="industrial"]({BBOX});
);
out tags geom;
'''

raw = None
for attempt in range(6):
    url = SERVERS[attempt % len(SERVERS)]
    try:
        req = urllib.request.Request(url, data=Q.encode(),
                                     headers={'User-Agent': 'kav-bochan/parks (industrial-zone check)'})
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.load(r)
        break
    except Exception as e:
        print(f'attempt {attempt + 1} @ {url}: {e}', file=sys.stderr)
        time.sleep(30)
if raw is None:
    sys.exit('overpass unreachable after retries')

def area_km2(pts):
    if len(pts) < 4:
        return 0.0
    cl = math.cos(math.radians(sum(p[0] for p in pts) / len(pts)))
    q = [(lo * 111320 * cl, la * 110540) for la, lo in pts]
    s = sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1]
            for i in range(len(q)))
    return abs(s) / 2 / 1e6

def centroid(pts):
    return (round(sum(p[0] for p in pts) / len(pts), 5),
            round(sum(p[1] for p in pts) / len(pts), 5))

zones = []
for e in raw.get('elements', []):
    t = e.get('tags') or {}
    rings = []
    if e.get('type') == 'way' and e.get('geometry'):
        rings = [[(p['lat'], p['lon']) for p in e['geometry']]]
    elif e.get('type') == 'relation':
        rings = [[(p['lat'], p['lon']) for p in m['geometry']]
                 for m in e.get('members', [])
                 if m.get('role') == 'outer' and m.get('geometry')]
    rings = [r for r in rings if len(r) >= 4]
    if not rings:
        continue
    allpts = [p for r in rings for p in r]
    la, lo = centroid(allpts)
    zones.append({
        'id': f"{e['type'][0]}{e['id']}",
        'name': ' '.join((t.get('name') or '').split()),
        'he': ' '.join((t.get('name:he') or '').split()),
        'en': ' '.join((t.get('name:en') or '').split()),
        'la': la, 'lo': lo,
        'area': round(sum(area_km2(r) for r in rings), 4),
    })

named = sum(1 for z in zones if z['name'])
print(f'polygons: {len(zones)} | named: {named} | unnamed: {len(zones) - named}')
if len(zones) < 100:
    sys.exit('suspiciously few polygons — aborting instead of committing junk')

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'fetched': time.strftime('%Y-%m-%d'), 'bbox': BBOX, 'zones': zones},
              f, ensure_ascii=False, separators=(',', ':'))
print('wrote', OUT, os.path.getsize(OUT), 'bytes')
