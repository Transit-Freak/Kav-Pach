# -*- coding: utf-8 -*-
# הצלבת אזורי התעשייה מול שכבת האזורים הסטטיסטיים של הלמ"ס (סעיף 0).
# בעמוד השכבות של הלמ"ס: העדכנית ביותר היא 2020 בפורמט GDB (נקראת עם fiona),
# והעדכנית בפורמט SHP היא 2017 (גיבוי, נקראת עם pyshp). ממפה כל אזור תעשייה
# לאזור הסטטיסטי שמכיל את מרכזו ומדגל אזורים שמחוץ לכל פוליגון.
# הפלט: parks/checks/cbs-crosscheck.json (מחוץ ל-parks/data — הריצה השבועית
# בונה את data מחדש ומוחקת קבצים זרים). רץ ב-CI.
import io, json, os, re, urllib.parse, urllib.request, zipfile

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
OUT = os.environ.get('OUT', 'parks/checks/cbs-crosscheck.json')
CBS = 'https://www.cbs.gov.il'

def get(url, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

page = get(f'{CBS}/he/Pages/geo-layers.aspx').decode('utf-8', 'replace')
hrefs = [h for h in re.findall(r'href="([^"]+)"', page) if 'statisticalareas' in h.lower()]
print('קובצי אזורים סטטיסטיים בעמוד:', hrefs)

def year_of(h):
    m = re.findall(r'20\d\d', h)
    return int(m[0]) if m else 0

gdbs = sorted([h for h in hrefs if '.gdb' in h.lower()], key=year_of, reverse=True)
shps = sorted([h for h in hrefs if '.gdb' not in h.lower() and h.lower().endswith('.zip')], key=year_of, reverse=True)

feats = None   # [(bbox, rings, attrs)] — rings: [[(x,y),...], ...]
src = None
fields = []
crs_epsg = None

def rings_of_geojson(geom):
    t, c = geom['type'], geom['coordinates']
    polys = c if t == 'MultiPolygon' else [c]
    return [[(x, y) for x, y, *_ in ring] for poly in polys for ring in poly]

if gdbs:
    url = gdbs[0] if gdbs[0].startswith('http') else CBS + urllib.parse.quote(gdbs[0])
    print('מוריד GDB:', url)
    open('sa.zip', 'wb').write(get(url))
    with zipfile.ZipFile('sa.zip') as zf:
        zf.extractall('sa_gdb')
    gdb = next((os.path.join(dp, d) for dp, ds, _ in os.walk('sa_gdb') for d in ds if d.lower().endswith('.gdb')), None)
    print('gdb:', gdb)
    import fiona
    layers = fiona.listlayers(gdb)
    print('שכבות:', layers)
    lyr = next((l for l in layers if 'stat' in l.lower()), layers[0])
    with fiona.open(gdb, layer=lyr) as f:
        crs_epsg = f.crs.to_epsg() if f.crs else None
        fields = list(f.schema['properties'].keys())
        feats = []
        for ft in f:
            if not ft['geometry']: continue
            rings = rings_of_geojson(dict(ft['geometry']))
            xs = [x for r in rings for x, _ in r]; ys = [y for r in rings for _, y in r]
            feats.append(((min(xs), min(ys), max(xs), max(ys)), rings, dict(ft['properties'])))
    src = f'למ"ס — {os.path.basename(gdbs[0])} (שכבה {lyr})'
elif shps:
    url = shps[0] if shps[0].startswith('http') else CBS + urllib.parse.quote(shps[0])
    print('מוריד SHP:', url)
    import shapefile
    zf = zipfile.ZipFile(io.BytesIO(get(url)))
    names = zf.namelist()
    shp = next(n for n in names if n.lower().endswith('.shp'))
    base = shp[:-4]
    def member(ext):
        n = next((x for x in names if x.lower() == (base + ext).lower()), None)
        return io.BytesIO(zf.read(n)) if n else None
    rd = shapefile.Reader(shp=member('.shp'), dbf=member('.dbf'), shx=member('.shx'))
    prj = next((n for n in names if n.lower().endswith('.prj')), None)
    prj_txt = zf.read(prj).decode('utf-8', 'replace') if prj else ''
    crs_epsg = 2039 if ('Israel' in prj_txt or '2039' in prj_txt or 'ITM' in prj_txt) else 4326
    fields = [f[0] for f in rd.fields[1:]]
    feats = []
    for sr in rd.shapeRecords():
        s = sr.shape
        parts = list(s.parts) + [len(s.points)]
        rings = [s.points[parts[i]:parts[i + 1]] for i in range(len(parts) - 1)]
        feats.append((tuple(s.bbox), rings, dict(zip(fields, sr.record))))
    src = f'למ"ס — {os.path.basename(shps[0])}'
else:
    raise SystemExit('לא נמצא אף קובץ שכבה בעמוד הלמ"ס')

print('רשומות:', len(feats), '| שדות:', fields, '| EPSG:', crs_epsg)

parks = json.load(open('parks/data/parks.json', encoding='utf-8'))
# רשימה לפי סדר האזורים ולא מילון לפי שם — יש אזורים עם שם זהה בערים שונות
# ("אזור תעשייה חדש" באילת וגם בראשון לציון), ומילון גורם להם להתמזג
if crs_epsg and crs_epsg != 4326:
    from pyproj import Transformer
    tr = Transformer.from_crs(4326, crs_epsg, always_xy=True)
    pts = [tr.transform(p['lo'], p['la']) for p in parks]
else:
    pts = [(p['lo'], p['la']) for p in parks]

def inside(pt, bbox, rings):
    x, y = pt
    if not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]): return False
    hit = False
    for ring in rings:
        for j in range(len(ring) - 1):
            (x1, y1), (x2, y2) = ring[j], ring[j + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
    return hit

FU = [f.upper() for f in fields]
def pick(*subs):
    for i, f in enumerate(FU):
        if any(s in f for s in subs): return fields[i]
    return None
sa_f = pick('STAT')
sem_f = pick('SEMEL')
name_f = pick('SHEM_YISH', 'NAME')

out, outside = [], []
for i, p in enumerate(parks):
    pt = pts[i]
    found = None
    for bbox, rings, attrs in feats:
        if inside(pt, bbox, rings):
            found = {'sa': attrs.get(sa_f), 'yishuv': attrs.get(sem_f),
                     'yname': str(attrs.get(name_f) or '').strip()}
            break
    out.append({'name': p['name'], 'city': p.get('city') or '', 'la': p['la'], 'lo': p['lo'], 'cbs': found})
    if not found: outside.append(p['name'])

print()
print('מקור:', src)
print(f'מופו לאזור סטטיסטי: {sum(1 for r in out if r["cbs"])}/{len(out)}')
print('מחוץ לכל אזור סטטיסטי:', len(outside))
for n in outside: print('  ⚠', n)
json.dump({'source': src, 'fields': {'sa': sa_f, 'yishuv': sem_f, 'yname': name_f},
           'zones': out, 'outside': outside},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('נשמר:', OUT)
