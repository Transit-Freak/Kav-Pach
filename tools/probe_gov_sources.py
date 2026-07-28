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

# ---------- 1ב. data.gov.il — מאגר המידע הממשלתי הפתוח (CKAN) ----------
# מפ"י והלמ"ס מפרסמות שם שכבות; חיפוש דאטהסטים של תעסוקה/מוקדי עניין
print('===== data.gov.il =====')
ckan_hits = []
try:
    for q in ('אזורי תעסוקה', 'מוקדי עניין', 'נקודות עניין', 'אזורי תעשייה'):
        u = ('https://data.gov.il/api/3/action/package_search?'
             + urllib.parse.urlencode({'q': q, 'rows': 20}))
        d = jget(u)
        res = d.get('result', {}).get('results', [])
        print(f'חיפוש "{q}": {len(res)} דאטהסטים')
        for pkg in res:
            org = (pkg.get('organization') or {}).get('title', '')
            title = pkg.get('title', '')
            if not re.search(r'תעסוק|תעשי|עניין', title):
                continue
            fmts = [(r.get('format', ''), r.get('url', '')) for r in pkg.get('resources', [])]
            print(f"  * {title} | {org}")
            for fm, ur in fmts[:4]:
                print(f"      {fm}: {ur[:110]}")
            ckan_hits.append({'title': title, 'org': org, 'name': pkg.get('name'),
                              'resources': [{'format': f, 'url': u2} for f, u2 in fmts]})
except Exception as e:
    print('data.gov.il שגיאה:', e)
# ייחוד לפי שם הדאטהסט
seen_pkg = set()
ckan_hits = [h for h in ckan_hits if not (h['name'] in seen_pkg or seen_pkg.add(h['name']))]
report['datagov'] = {'hits': ckan_hits}

# ---------- 2. govmap / מפ"י + פורטל המפות של הלמ"ס ----------
print('===== מרכז מיפוי ישראל (govmap) + gis.cbs =====')
ENDPOINTS = [
    'https://gis.cbs.gov.il/arcgis/rest/services?f=json',
    'https://gis.cbs.gov.il/server/rest/services?f=json',
    'https://ags.govmap.gov.il/arcgis02/rest/services?f=json',
    'https://ags.govmap.gov.il/proxy/proxy.ashx?https://ags.govmap.gov.il/arcgis/rest/services?f=json',
    'https://api.govmap.gov.il/arcgis/rest/services?f=json',
    'https://mapi.gov.il/arcgis/rest/services?f=json',
    'https://ags.mapi.gov.il/arcgis/rest/services?f=json',
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
        svcs = fd.get('services', [])
        if svcs:
            print(f'  תיקייה "{f or "/"}": {len(svcs)} שירותים —', ', '.join(s.get('name','')[:40] for s in svcs[:12]))
        for s in svcs:
            nm = s.get('name', '')
            if re.search(r'poi|interest|moked|מוקד|taasuk|employ|תעסוק|תעשי|mifkad|census|landuse', nm, re.I):
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

# ---------- 3. שכבת "תחום אזורי תעשיה תעסוקה" של משרד התחבורה ----------
# נמצאה ב-data.gov.il (סיבוב ב') — גבולות מדויקים ב-SHP. מורידים, קוראים
# עם pyshp, ומדווחים כל אזור שמרכזו רחוק 700מ'+ מכל אזור שכבר באתר.
print('===== משרד התחבורה: תחום אזורי תעשיה תעסוקה =====')
try:
    meta = jget('https://data.gov.il/api/3/action/package_show?id=8db5effd-59ca-44ef-b561-86e0ce2911d1')
    resources = meta['result']['resources']
    for r in resources:
        print('  משאב:', r.get('format'), '|', r.get('id'), '|', (r.get('url') or '')[:110])
    mot_zones = []

    # אסטרטגיה 1: datastore של ה-CSV (הכי אמין ב-data.gov.il)
    csv_res = next((r for r in resources if (r.get('format') or '').upper() == 'CSV'), None)
    if csv_res:
        try:
            ds = jget('https://data.gov.il/api/3/action/datastore_search?'
                      + urllib.parse.urlencode({'resource_id': csv_res['id'], 'limit': 32000}), 180)
            recs = ds.get('result', {}).get('records', [])
            flds = [f['id'] for f in ds.get('result', {}).get('fields', [])]
            print('datastore: רשומות:', len(recs), '| שדות:', flds)
            # אין קואורדינטות ב-CSV (הגאומטריה ב-SHP חסום) — מצליבים לפי שם+עיר
            if recs and 'NAME' in flds:
                def norm(s):
                    s = str(s or '')
                    for w in ('אזור התעשייה', 'אזור תעשייה', 'אזור תעשיה', 'אזה"ת', 'א.ת.', 'א.ת',
                              'פארק תעשיות', 'פארק תעשייה', 'פארק תעשיה', 'אזור תעסוקה', 'פארק תעסוקה',
                              'קרית', 'קריית', '"', "'", '-', '(', ')'):
                        s = s.replace(w, ' ')
                    return set(t for t in s.split() if len(t) > 1)
                site = [(norm(p['name']) | norm(p.get('city')), p['name'], p.get('city', '')) for p in parks]
                matched = 0
                missing_nc = []
                for at in recs:
                    toks = norm(at.get('NAME')) | norm(at.get('CITY'))
                    best = 0
                    for stoks, snm, scity in site:
                        ov = len(toks & stoks)
                        if ov > best:
                            best = ov
                    if best >= 2:
                        matched += 1
                    else:
                        missing_nc.append({'name': str(at.get('NAME') or '')[:60],
                                           'city': str(at.get('CITY') or '')[:30],
                                           'district': str(at.get('DISTRICT') or '')[:20],
                                           'bruto_dunam': at.get('BRUTOAREA')})
                def _num(v):
                    try: return float(v)
                    except Exception: return 0.0
                missing_nc.sort(key=lambda z: -_num(z['bruto_dunam']))
                print(f'הותאמו לאתר: {matched} | ללא התאמה (חסרים כנראה): {len(missing_nc)}')
                for z in missing_nc[:50]:
                    print(f"  {z['name'][:44]:46} | {z['city'][:20]:22} | {z['district']:10} | {z['bruto_dunam']} דונם")
                report['mot_by_name'] = {'total': len(recs), 'matched': matched, 'missing': missing_nc}
            import pyproj
            tr = pyproj.Transformer.from_crs(2039, 4326, always_xy=True)
            for at in recs:
                nm = next((str(v) for v in at.values() if isinstance(v, str) and re.search(r'[א-ת]', str(v))), '')
                xy = [(k, v) for k, v in at.items() if isinstance(v, (int, float)) and v and abs(v) > 1]
                la = lo = None
                for k, v in xy:
                    lk = k.lower()
                    if lk in ('lat', 'y') or 'רוחב' in k: la = v
                    if lk in ('lon', 'long', 'x') or 'אורך' in k: lo = v
                wkt = next((str(v) for v in at.values() if isinstance(v, str) and str(v).startswith(('POLYGON', 'MULTIPOLYGON', 'POINT'))), None)
                if wkt:
                    ns = re.findall(r'(-?\d+\.?\d*) (-?\d+\.?\d*)', wkt)
                    if ns:
                        xs = [float(a) for a, b in ns]; ys = [float(b) for a, b in ns]
                        lo, la = sum(xs) / len(xs), sum(ys) / len(ys)
                if la is None or lo is None:
                    continue
                if abs(lo) > 1000:   # רשת ישראל
                    lo, la = tr.transform(lo, la)
                mot_zones.append({'name': ' '.join(nm.split())[:60], 'la': round(la, 5), 'lo': round(lo, 5)})
        except Exception as e:
            print('datastore נכשל:', e)

    # אסטרטגיה 2: KMZ (KML דחוס)
    if not mot_zones:
        kmz_res = next((r for r in resources if (r.get('format') or '').upper() in ('KMZ', 'KML')), None)
        if kmz_res:
            try:
                blob = get(kmz_res['url'], timeout=300, binary=True)
                print('KMZ:', len(blob), 'בייטים | מתחיל ב:', blob[:20])
                if blob[:2] == b'PK':
                    zf = zipfile.ZipFile(io.BytesIO(blob))
                    kml = next(n for n in zf.namelist() if n.lower().endswith('.kml'))
                    xml = zf.read(kml).decode('utf-8', 'replace')
                else:
                    xml = blob.decode('utf-8', 'replace')
                pms = re.findall(r'<Placemark>(.*?)</Placemark>', xml, re.S)
                print('Placemarks:', len(pms))
                for pm in pms:
                    nmm = re.search(r'<name>(.*?)</name>', pm, re.S)
                    nm = ' '.join((nmm.group(1) if nmm else '').split())
                    cs = re.findall(r'([\d.]+),([\d.]+)', pm)
                    if not cs:
                        continue
                    xs = [float(a) for a, b in cs]; ys = [float(b) for a, b in cs]
                    mot_zones.append({'name': nm[:60], 'la': round(sum(ys) / len(ys), 5),
                                      'lo': round(sum(xs) / len(xs), 5)})
            except Exception as e:
                print('KMZ נכשל:', e)

    # אסטרטגיה 3: SHP עם אבחון
    if not mot_zones:
        shp_res = next((r for r in resources if (r.get('format') or '').upper() == 'SHP'), None)
        if shp_res:
            blob = get(shp_res['url'], timeout=300, binary=True)
            print('SHP: הורדו', len(blob), 'בייטים | מתחיל ב:', blob[:60])
    print('אזורים בשכבה:', len(mot_zones))
    missing_mot = []
    for z in mot_zones:
        d0 = known_dist(z['la'], z['lo'])
        if d0 >= 700:
            z['dist'] = int(d0)
            missing_mot.append(z)
    missing_mot.sort(key=lambda z: -z['dist'])
    print('חסרים באתר (700מ׳+):', len(missing_mot))
    for z in missing_mot[:40]:
        print(f"  {z['name'] or '(בלי שם)':45} ({z['la']},{z['lo']}) {z['dist']}מ'")
    report['mot'] = {'total': len(mot_zones), 'missing': missing_mot}
except Exception as e:
    import traceback; traceback.print_exc()
    report['mot'] = {'error': str(e)}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
