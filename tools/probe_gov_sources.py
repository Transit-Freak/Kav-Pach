# -*- coding: utf-8 -*-
# בדיקת שני מקורות ממשלתיים לאזורי תעשייה/תעסוקה חסרים (בקשת ההסתדרות):
#  1. למ"ס — עמוד השכבות הגיאוגרפיות: חיפוש שכבת אזורי תעסוקה/תעשייה,
#     הורדה אם קיימת, והשוואת האזורים ששמם כולל תעשייה/תעסוקה מול האתר.
#  2. מרכז מיפוי ישראל (govmap) — שכבת "מוקדי עניין": ניסיון גישה דרך
#     שירותי ה-ArcGIS REST הציבוריים ושליפת מוקדי תעשייה/תעסוקה/מסחר.
# הפלט: parks/checks/gov-sources-probe.json + לוג מפורט. דוח בלבד —
# שום דבר לא נכנס לאתר אוטומטית.
import io, json, math, os, re, sys, urllib.parse, urllib.request, zipfile

OUT = os.environ.get('OUT', 'parks/checks/gov-sources-probe.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
report = {'cbs': {}, 'govmap': {}}

def get(url, timeout=180, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    return data if binary else data.decode('utf-8', 'replace')

def jget(url, timeout=90):
    return json.loads(get(url, timeout))

# ---------- האזורים שכבר באתר — להשוואה ----------
parks = json.load(open('parks/data/parks.json', encoding='utf-8'))
def dist_m(la1, lo1, la2, lo2):
    cl = math.cos(math.radians(la1))
    return math.hypot((lo2 - lo1) * 111320 * cl, (la2 - la1) * 110540)
def known_dist(la, lo):
    return min((dist_m(la, lo, p['la'], p['lo']) for p in parks), default=1e9)

# ---------- 1. למ"ס ----------
print('===== למ"ס =====')
try:
    page = get('https://www.cbs.gov.il/he/Pages/geo-layers.aspx')
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
    layers = []
    for href, txt in links:
        txt = re.sub(r'<[^>]+>', '', txt).strip()
        if any(x in href.lower() for x in ('.zip', '.gdb')) or 'שכב' in txt:
            layers.append({'href': href, 'text': txt[:80]})
    print(f'קישורים לשכבות בעמוד: {len(layers)}')
    for l in layers:
        print('  ', l['text'], '→', l['href'][:100])
    report['cbs']['layers_on_page'] = layers
    emp = [l for l in layers if re.search(r'תעסוק|תעשי|taasuka|employment|industr', (l['text'] + l['href']), re.I)]
    report['cbs']['employment_layers'] = emp
    print('שכבות תעסוקה/תעשייה שאותרו:', len(emp))
    for l in emp:
        print('  *', l['text'], '→', l['href'])
except Exception as e:
    print('למ"ס: שגיאה —', e)
    report['cbs']['error'] = str(e)

# ---------- 2. govmap / מפ"י ----------
print('===== מרכז מיפוי ישראל (govmap) =====')
ENDPOINTS = [
    'https://ags.govmap.gov.il/arcgis/rest/services?f=json',
    'https://ags.govmap.gov.il/arcgis/rest/services?f=pjson',
    'https://open.govmap.gov.il/arcgis/rest/services?f=json',
    'https://gisserver.govmap.gov.il/arcgis/rest/services?f=json',
    'https://www.govmap.gov.il/arcgis/rest/services?f=json',
]
root = None
for url in ENDPOINTS:
    try:
        d = jget(url)
        if 'folders' in d or 'services' in d:
            root = (url.rsplit('?', 1)[0], d)
            print('נגיש:', url, '| תיקיות:', len(d.get('folders', [])), '| שירותים:', len(d.get('services', [])))
            break
    except Exception as e:
        print('לא נגיש:', url, '—', str(e)[:90])
report['govmap']['root'] = root[0] if root else None

poi_hits = []
if root:
    base, d = root
    report['govmap']['folders'] = d.get('folders', [])
    report['govmap']['services'] = [s.get('name') for s in d.get('services', [])]
    folders = [''] + d.get('folders', [])
    for f in folders[:40]:
        try:
            fd = jget(f'{base}/{f}?f=json' if f else f'{base}?f=json')
        except Exception as e:
            print('  תיקייה', f, 'שגיאה:', str(e)[:60]); continue
        for s in fd.get('services', []):
            nm = s.get('name', '')
            if re.search(r'poi|interest|moked|מוקד', nm, re.I):
                poi_hits.append({'service': nm, 'type': s.get('type')})
    print('שירותי מוקדי-עניין שאותרו:', len(poi_hits))
    for s in poi_hits:
        print('  *', s['service'], s['type'])
    report['govmap']['poi_services'] = poi_hits

# שליפה משכבת מוקדי עניין אם נמצאה — מסנן תעשייה/תעסוקה/מסחר
missing = []
for s in poi_hits[:3]:
    try:
        svc = jget(f"{root[0]}/{s['service']}/{s['type']}?f=json")
        for lyr in svc.get('layers', []):
            lname = lyr.get('name', '')
            print('  שכבה:', lyr.get('id'), lname)
            if not re.search(r'תעשי|תעסוק|מסחר|POI|מוקד', lname, re.I):
                continue
            q = (f"{root[0]}/{s['service']}/{s['type']}/{lyr['id']}/query?"
                 + urllib.parse.urlencode({
                     'where': "1=1", 'outFields': '*', 'f': 'json',
                     'returnGeometry': 'true', 'outSR': '4326', 'resultRecordCount': 2000}))
            fd = jget(q, 120)
            feats = fd.get('features', [])
            print(f'    תוצאות: {len(feats)}')
            for ft in feats:
                at = ft.get('attributes', {})
                txt = ' '.join(str(v) for v in at.values() if isinstance(v, str))
                if not re.search(r'תעשי|תעסוק', txt):
                    continue
                g = ft.get('geometry') or {}
                la, lo = g.get('y'), g.get('x')
                if la is None:
                    continue
                d0 = known_dist(la, lo)
                if d0 >= 700:
                    nmf = next((str(v) for v in at.values()
                                if isinstance(v, str) and re.search(r'תעשי|תעסוק', v)), '')
                    missing.append({'name': nmf[:60], 'la': round(la, 5), 'lo': round(lo, 5),
                                    'dist': int(d0), 'layer': lname, 'service': s['service']})
    except Exception as e:
        print('  שירות', s['service'], 'שגיאה:', str(e)[:100])
seen = set()
uniq = []
for m in sorted(missing, key=lambda x: x['name']):
    k = (m['name'], round(m['la'], 3), round(m['lo'], 3))
    if k in seen:
        continue
    seen.add(k)
    uniq.append(m)
report['govmap']['missing_candidates'] = uniq
print('מועמדים חסרים ממוקדי-עניין (700מ׳+ מכל אזור באתר):', len(uniq))
for m in uniq[:30]:
    print('  ', m['name'], f"({m['la']},{m['lo']})", f"{m['dist']}מ'")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
