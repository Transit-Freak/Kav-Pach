# -*- coding: utf-8 -*-
# שלב-שני של pipeline האזורים: מקבל regions.json (תיבות-גבול של האזורים
# האמיתיים אחרי קיבוץ וסינון) ומושך מ-Overpass את שבילי-הולכי-הרגל שבתוכן
# בלבד. כך מכוסים כל האזורים — גם ללא-שם — בלי around על אלפי פוליגונים
# שתוקע את השרת. הפלט footways.json במבנה Overpass ({'elements':[...]}).
import json, os, time, urllib.request, urllib.parse

REGIONS = os.environ.get('REGIONS', 'regions.json')
OUT = os.environ.get('FOOT_OUT', 'footways.json')
CHUNK = int(os.environ.get('CHUNK', '100'))   # כמה תיבות בכל שאילתה
MIRRORS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]

regions = json.load(open(REGIONS))
print('אזורים לעיבוד:', len(regions))


def build_query(chunk):
    parts = []
    for la1, lo1, la2, lo2 in chunk:
        bb = '%s,%s,%s,%s' % (la1, lo1, la2, lo2)
        parts.append('way["highway"~"^(footway|path|pedestrian|steps)$"](%s);' % bb)
        parts.append('way["sidewalk"~"^(both|left|right|separate)$"](%s);' % bb)
    return '[out:json][timeout:300];(' + ''.join(parts) + ');out geom;'


all_elems = []
seen = set()
n_chunks = (len(regions) + CHUNK - 1) // CHUNK
failed = 0
for ci in range(0, len(regions), CHUNK):
    chunk = regions[ci:ci + CHUNK]
    q = build_query(chunk)
    data = urllib.parse.urlencode({'data': q}).encode()
    ok = False
    for ep in MIRRORS:
        try:
            req = urllib.request.Request(ep, data=data,
                                         headers={'User-Agent': 'kav-bochan-parks/1.0'})
            with urllib.request.urlopen(req, timeout=350) as r:
                j = json.load(r)
            for e in j.get('elements', []):
                key = (e.get('type'), e.get('id'))
                if key in seen:
                    continue
                seen.add(key)
                all_elems.append(e)
            ok = True
            print('chunk %d/%d: %d תיבות -> סה"כ %d שבילים'
                  % (ci // CHUNK + 1, n_chunks, len(chunk), len(all_elems)), flush=True)
            break
        except Exception as ex:
            print('  %s נכשל: %r' % (ep, ex), flush=True)
            time.sleep(10)
    if not ok:
        failed += 1
        print('chunk %d/%d נכשל בכל המראות — ממשיך (נתונים חלקיים)'
              % (ci // CHUNK + 1, n_chunks), flush=True)

json.dump({'elements': all_elems}, open(OUT, 'w'))
print('נכתבו %d שבילים -> %s (chunks שנכשלו: %d)' % (len(all_elems), OUT, failed))
