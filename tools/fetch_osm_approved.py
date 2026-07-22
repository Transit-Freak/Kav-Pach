# -*- coding: utf-8 -*-
# משיכת הגאומטריה המלאה של אזורי התעשייה המאומתים (parks/osm-check/osm-approved.json)
# מ-Overpass, לפי מזהי OSM. הפלט בפורמט Overpass גולמי — קלט ישיר ל-parks.py.
# האישור נעשה חד-פעמית ע"י פאנל בוטים (ראו parks/osm-check/README.md); כאן רק
# מרעננים גאומטריה, כך שעדכוני-מיפוי ב-OSM נקלטים בלי לפתוח את שאלת הקיום מחדש.
import json, os, sys, time, urllib.request

APPROVED = os.environ.get('APPROVED', 'parks/osm-check/osm-approved.json')
OUT = os.environ.get('OUT', 'osm-approved-raw.json')
SERVERS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]

zones = json.load(open(APPROVED, encoding='utf-8'))['zones']
way_ids = sorted(int(i[1:]) for z in zones for i in z['ids'] if i.startswith('w'))
rel_ids = sorted(int(i[1:]) for z in zones for i in z['ids'] if i.startswith('r'))
print(f'approved: {len(zones)} zones | {len(way_ids)} ways, {len(rel_ids)} relations')

parts = []
if way_ids:
    parts.append(f"way(id:{','.join(map(str, way_ids))});")
if rel_ids:
    parts.append(f"relation(id:{','.join(map(str, rel_ids))});")
Q = f"[out:json][timeout:240];({''.join(parts)});out tags geom;"

raw = None
for attempt in range(6):
    url = SERVERS[attempt % len(SERVERS)]
    try:
        req = urllib.request.Request(url, data=Q.encode(),
                                     headers={'User-Agent': 'kav-bochan/parks (approved zones geometry)'})
        with urllib.request.urlopen(req, timeout=300) as r:
            raw = json.load(r)
        break
    except Exception as e:
        print(f'attempt {attempt + 1} @ {url}: {e}', file=sys.stderr)
        time.sleep(30)
if raw is None:
    sys.exit('overpass unreachable after retries')

els = raw.get('elements', [])
want = len(way_ids) + len(rel_ids)
print(f'elements returned: {len(els)} / {want}')
# מזהה שנמחק מ-OSM מאז האישור לא מפיל את הריצה, אבל חוסר גדול כן.
if len(els) < want * 0.8:
    sys.exit('too many approved OSM ids missing — refusing to build partial data')

json.dump({'elements': els}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
print('wrote', OUT, os.path.getsize(OUT), 'bytes')
