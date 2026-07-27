# -*- coding: utf-8 -*-
# הצלבת אזורי התעשייה מול שכבת האזורים הסטטיסטיים של הלמ"ס (סעיף 0).
# מוריד את השכבה הארצית (מעדיף 2022 מאתר הלמ"ס, נסיגה ל-2008 מ-data.gov.il),
# ממפה כל אזור תעשייה לאזור הסטטיסטי שמכיל את מרכזו, ומדגל אזורים שנופלים
# מחוץ לכל פוליגון. הפלט: parks/data/cbs-crosscheck.json + סיכום ללוג.
# רץ ב-CI (שרתי הלמ"ס חסומים מסביבת הפיתוח).
import io, json, os, re, subprocess, sys, urllib.request, zipfile

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
OUT = os.environ.get('OUT', 'parks/data/cbs-crosscheck.json')

def get(url, timeout=180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

# --- שלב 1: איתור קובץ השכבה ---
def find_2022_url():
    page = get('https://www.cbs.gov.il/he/Pages/geo-layers.aspx').decode('utf-8', 'replace')
    hrefs = re.findall(r'href="([^"]+)"', page)
    cands = []
    for h in hrefs:
        hl = h.lower()
        if any(hl.endswith(ext) for ext in ('.zip', '.7z')) or 'download' in hl:
            score = 0
            if '2022' in h: score += 4
            if 'statis' in hl or 'ezor' in hl or '%d7%90%d7%96%d7%95%d7%a8' in hl: score += 3
            if 'shp' in hl or 'shape' in hl: score += 2
            if 'gdb' in hl: score -= 1
            cands.append((score, h))
    cands.sort(reverse=True)
    print('מועמדים מעמוד השכבות של הלמ"ס:')
    for s, h in cands[:15]:
        print(f'  [{s}] {h}')
    for s, h in cands:
        if s >= 5:
            return h if h.startswith('http') else 'https://www.cbs.gov.il' + h
    return None

def load_shp_from_zip(blob):
    import shapefile
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()
    print('בתוך הארכיון:', names[:20])
    shp = next((n for n in names if n.lower().endswith('.shp')), None)
    if not shp: return None, None
    base = shp[:-4]
    def member(ext):
        n = next((x for x in names if x.lower() == (base + ext).lower()), None)
        return io.BytesIO(zf.read(n)) if n else None
    r = shapefile.Reader(shp=member('.shp'), dbf=member('.dbf'), shx=member('.shx'))
    prj = next((n for n in names if n.lower().endswith('.prj')), None)
    prj_txt = zf.read(prj).decode('utf-8', 'replace') if prj else ''
    return r, prj_txt

blob = None
src = None
url = None
try:
    url = find_2022_url()
except Exception as e:
    print('עמוד הלמ"ס נכשל:', e)
if url:
    try:
        print('מוריד:', url)
        blob = get(url)
        src = f'למ"ס ({url.rsplit("/", 1)[-1]})'
    except Exception as e:
        print('הורדת 2022 נכשלה:', e)

reader, prj = (None, '')
if blob:
    try:
        reader, prj = load_shp_from_zip(blob)
    except Exception as e:
        print('קריאת ארכיון 2022 נכשלה:', e)

if reader is None:
    # נסיגה: השכבה של מפקד 2008 מ-data.gov.il (ארכיון 7z)
    u = 'https://e.data.gov.il/dataset/6b729165-dc9c-49b3-afc6-eceabd8fef70/resource/3b88cb58-62cd-43ea-9156-7b81ead557b1/download/50400-2008.7z'
    print('נסיגה לשכבת 2008:', u)
    open('sa.7z', 'wb').write(get(u))
    subprocess.run(['7z', 'x', '-osa2008', 'sa.7z'], check=True, capture_output=True)
    shp = next((os.path.join(dp, f) for dp, _, fs in os.walk('sa2008') for f in fs if f.lower().endswith('.shp')), None)
    print('shp:', shp)
    import shapefile
    reader = shapefile.Reader(shp)
    p = shp[:-4] + '.prj'
    prj = open(p, encoding='utf-8', errors='replace').read() if os.path.exists(p) else ''
    src = 'למ"ס, מפקד 2008 (data.gov.il)'

fields = [f[0] for f in reader.fields[1:]]
print('שדות:', fields, '| רשומות:', len(reader))
print('היטל:', prj[:120])

# --- שלב 2: המרת מרכזי האזורים ל-ITM אם צריך ---
itm = 'Israel' in prj or 'ITM' in prj or '2039' in prj
parks = json.load(open('parks/data/parks.json', encoding='utf-8'))
if itm:
    from pyproj import Transformer
    tr = Transformer.from_crs(4326, 2039, always_xy=True)
    pts = {p['name']: tr.transform(p['lo'], p['la']) for p in parks}
else:
    pts = {p['name']: (p['lo'], p['la']) for p in parks}

# --- שלב 3: נקודה-בפוליגון (קרן אופקית, אי-זוגיות — מטפל גם בחורים) ---
def inside(pt, shape):
    x, y = pt
    bx0, by0, bx1, by1 = shape.bbox
    if not (bx0 <= x <= bx1 and by0 <= y <= by1): return False
    parts = list(shape.parts) + [len(shape.points)]
    hit = False
    for i in range(len(parts) - 1):
        ring = shape.points[parts[i]:parts[i + 1]]
        for j in range(len(ring) - 1):
            (x1, y1), (x2, y2) = ring[j], ring[j + 1]
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                hit = not hit
    return hit

recs = reader.shapeRecords()
name_f = next((f for f in fields if f.upper() in ('SHEM_YISHU', 'SHEM_YISH', 'SHEM_YISHUV', 'NAME')), None)
sa_f = next((f for f in fields if 'STAT' in f.upper()), None)
sem_f = next((f for f in fields if 'SEMEL' in f.upper() or f.upper() == 'YISHUV'), None)

out, outside = [], []
for p in parks:
    pt = pts[p['name']]
    found = None
    for sr in recs:
        if inside(pt, sr.shape):
            d = dict(zip(fields, sr.record))
            found = {'sa': d.get(sa_f), 'yishuv': d.get(sem_f), 'yname': str(d.get(name_f) or '').strip()}
            break
    row = {'name': p['name'], 'city': p.get('city') or '', 'la': p['la'], 'lo': p['lo'], 'cbs': found}
    out.append(row)
    if not found: outside.append(p['name'])

print()
print(f'מקור: {src}')
print(f'מופו לאזור סטטיסטי: {sum(1 for r in out if r["cbs"])}/{len(out)}')
print('מחוץ לכל אזור סטטיסטי:', len(outside))
for n in outside: print('  ⚠', n)
json.dump({'source': src, 'fields': {'sa': sa_f, 'yishuv': sem_f, 'yname': name_f},
           'zones': out, 'outside': outside},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('נשמר:', OUT)
