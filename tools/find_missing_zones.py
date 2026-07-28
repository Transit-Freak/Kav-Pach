# -*- coding: utf-8 -*-
# חיפוש אזורי תעשייה שהצינור הנוכחי מפספס: הרשת הרגילה מביאה רק פוליגונים
# המתויגים landuse=industrial, אבל אזור אמיתי יכול להיות מתויג אחרת
# (commercial, brownfield) או בכלל לא — ורק שמו מסגיר אותו ("אזור תעשייה",
# "אזור מלאכה", "פארק תעסוקה"). כאן שולפים כל אלמנט ששמו מרמז על אזור
# תעשייה/תעסוקה, מסננים רחובות ותחנות, ומדווחים על מועמדים שרחוקים מכל
# אזור שכבר מוכר לנו. הפלט: parks/checks/osm-candidates.json — לבדיקת פאנל
# ולעין אנושית, לא נכנס לאתר אוטומטית.
import json, math, os, sys, time, urllib.request

OUT = os.environ.get('OUT', 'parks/checks/osm-candidates.json')
BBOX = os.environ.get('BBOX', '29.4,34.2,33.45,35.95')
KNOWN_M = float(os.environ.get('KNOWN_M', '700'))   # מרחק שממנו מועמד נחשב "חדש"
SERVERS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]

Q = f'''[out:json][timeout:300];
nwr["name"~"תעשי|מלאכה|תעסוק"]({BBOX});
out tags center;
'''

raw = None
for attempt in range(6):
    url = SERVERS[attempt % len(SERVERS)]
    try:
        req = urllib.request.Request(url, data=Q.encode(),
                                     headers={'User-Agent': 'kav-bochan/parks (missing-zone sweep)'})
        with urllib.request.urlopen(req, timeout=320) as r:
            raw = json.load(r)
        break
    except Exception as e:
        print(f'attempt {attempt + 1} @ {url}: {e}', file=sys.stderr)
        time.sleep(30)
if raw is None:
    sys.exit('overpass unreachable after retries')

# אלמנטים שהשם שלהם תעשייתי אבל הם בבירור לא אזור: רחובות, תחנות, קווי חשמל
DROP_KEYS = ('highway', 'railway', 'waterway', 'power', 'route',
             'public_transport', 'amenity', 'shop', 'office', 'tourism')

def center_of(e):
    if e.get('center'):
        return e['center']['lat'], e['center']['lon']
    if e.get('lat') is not None:
        return e['lat'], e['lon']
    return None

cands = []
for e in raw.get('elements', []):
    t = e.get('tags') or {}
    if any(k in t for k in DROP_KEYS):
        continue
    c = center_of(e)
    if not c:
        continue
    cands.append({'id': f"{e['type'][0]}{e['id']}",
                  'name': ' '.join((t.get('name') or '').split()),
                  'la': round(c[0], 5), 'lo': round(c[1], 5),
                  'landuse': t.get('landuse', ''), 'place': t.get('place', '')})
print('אלמנטים עם שם תעשייתי (אחרי סינון):', len(cands))

# האזורים שכבר מוכרים: האתר עצמו + כל שכבת ה-OSM שכבר נמשכה
known = []
try:
    for p in json.load(open('parks/data/parks.json', encoding='utf-8')):
        known.append((p['la'], p['lo']))
except Exception as e:
    print('parks.json:', e)
try:
    osm = json.load(open('parks/osm-check/osm-industrial.json', encoding='utf-8'))
    for z in osm.get('zones', []):
        known.append((z['la'], z['lo']))
except Exception as e:
    print('osm-industrial:', e)
print('נקודות מוכרות:', len(known))

def dist_m(a, b):
    cl = math.cos(math.radians(a[0]))
    return math.hypot((a[1] - b[1]) * 111320 * cl, (a[0] - b[0]) * 110540)

new = []
for c in cands:
    d = min((dist_m((c['la'], c['lo']), k) for k in known), default=1e9)
    if d >= KNOWN_M:
        c['dist'] = int(d)
        new.append(c)
new.sort(key=lambda c: c['name'])

# איחוד כפילויות קרובות (אותו אזור ממופה גם כ-way וגם כ-node)
merged = []
for c in new:
    if any(dist_m((c['la'], c['lo']), (m['la'], m['lo'])) < 400 for m in merged):
        continue
    merged.append(c)

print(f'מועמדים חדשים (רחוקים {int(KNOWN_M)}מ׳+ מכל אזור מוכר): {len(merged)}')
for c in merged[:20]:
    print('  ', c['name'], f"({c['la']},{c['lo']})", c['landuse'] or c['place'] or '-')

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'fetched': time.strftime('%Y-%m-%d'), 'matched': len(cands),
           'known_points': len(known), 'candidates': merged},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
