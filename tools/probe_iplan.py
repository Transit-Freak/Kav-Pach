# -*- coding: utf-8 -*-
# ניסוי שליפת גבולות תב"ע ממנהל התכנון (iplan) עבור אזורי התעשייה-תעסוקה
# של משרד התחבורה: לכל אזור יש TABA_NUM, ולמנהל התכנון שרת ArcGIS ציבורי.
# שלב א: גילוי השירותים; שלב ב: שליפת-מדגם לפי מספרי תב"ע ומדידת אחוז פגיעה.
# הפלט: parks/checks/iplan-probe.json + לוג מפורט.
import json, os, re, sys, urllib.parse, urllib.request

OUT = os.environ.get('OUT', 'parks/checks/iplan-probe.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
report = {}

def get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

def jget(url, timeout=120):
    return json.loads(get(url, timeout))

# ---------- מספרי התב"ע מהשכבה של משרד התחבורה ----------
ds = jget('https://data.gov.il/api/3/action/datastore_search?'
          + urllib.parse.urlencode({'resource_id': '71799e72-7a1f-45cf-9d81-5cd1d5f3b201', 'limit': 32000}))
recs = ds['result']['records']
print('רשומות משרד התחבורה:', len(recs))
tabas = [(str(r.get('TABA_NUM') or '').strip(), str(r.get('NAME') or '')) for r in recs]
tabas = [(t, n) for t, n in tabas if t and t not in ('None', '0', '-')]
print('עם מספר תב"ע:', len(tabas), '| דוגמאות:', tabas[:8])
report['taba_count'] = len(tabas)
report['taba_samples'] = tabas[:10]

# ---------- גילוי שרתי ArcGIS של מנהל התכנון ----------
ROOTS = [
    'https://ags.iplan.gov.il/arcgisiplan/rest/services',
    'https://ags.iplan.gov.il/arcgis/rest/services',
    'https://mavat.iplan.gov.il/rest/api',
    'https://apps.land.gov.il/arcgis/rest/services',
]
root = None
for u in ROOTS:
    try:
        d = jget(u + '?f=json')
        if 'folders' in d or 'services' in d:
            root = (u, d)
            print('נגיש:', u, '| תיקיות:', d.get('folders'), '| שירותים:', [s['name'] for s in d.get('services', [])][:10])
            break
    except Exception as e:
        print('לא נגיש:', u, '—', str(e)[:80])
report['root'] = root[0] if root else None
if not root:
    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    sys.exit('אף שורש לא נגיש')

base, d0 = root
# כל שמות השירותים בכל התיקיות — קודם רואים מה יש, בלי סינון מוקדם
all_services = []
folders = [''] + d0.get('folders', [])
for f in folders[:40]:
    try:
        fd = jget(f'{base}/{f}?f=json' if f else f'{base}?f=json')
    except Exception as e:
        print('תיקייה', f, 'שגיאה:', str(e)[:60]); continue
    for s in fd.get('services', []):
        all_services.append((s.get('name', ''), s.get('type', '')))
print('סה"כ שירותים:', len(all_services))
for nm, ty in all_services:
    print('  ', nm, ty)
report['services'] = [f'{nm}|{ty}' for nm, ty in all_services]

# שכבות תוכניות: רק שירותים ששמם מרמז על תוכניות (xplan/plan/mavat)
plan_layers = []
for nm, ty in all_services:
    if ty not in ('MapServer', 'FeatureServer'):
        continue
    if not re.search(r'xplan|plan|mavat|taba', nm, re.I) or 'compilation' in nm.lower():
        continue
    try:
        svc = jget(f'{base}/{nm}/{ty}?f=json')
    except Exception as e:
        print(nm, 'שגיאה:', str(e)[:60]); continue
    for lyr in svc.get('layers', []) or []:
        plan_layers.append({'service': nm, 'type': ty, 'id': lyr['id'], 'layer': lyr.get('name', '')})
print('שכבות תוכניות שאותרו:', len(plan_layers))
for p in plan_layers[:25]:
    print('  *', p['service'], p['type'], p['id'], '—', p['layer'])
report['plan_layers'] = plan_layers[:40]

# ---------- שליפת מדגם: שכבות פוליגונים בלבד (גבולות, לא נקודות) ----------
sample = tabas[:10]
CANDS = [
    ('PlanningPublic/Xplan', 'MapServer', None),
    ('PlanningPublic/XplanNoKanam', 'MapServer', None),
    ('PlanningPublic/ttl_all_blue_lines', 'MapServer', None),
    ('PlanningPublic/entities_without_77_78', 'MapServer', [3]),
    ('PlanningPublic/entities', 'MapServer', [3]),
    ('PlanningPublic/plan_index', 'MapServer', None),
]
best = None
for svc_name, ty, only in CANDS:
    try:
        svc = jget(f'{base}/{svc_name}/{ty}?f=json')
    except Exception as e:
        print(svc_name, 'לא נגיש:', str(e)[:60]); continue
    for lyr in svc.get('layers', []) or []:
        if only and lyr['id'] not in only:
            continue
        try:
            meta = jget(f"{base}/{svc_name}/{ty}/{lyr['id']}?f=json")
        except Exception:
            continue
        gt = meta.get('geometryType', '')
        if gt != 'esriGeometryPolygon':
            continue
        fields = [fl['name'] for fl in meta.get('fields', [])]
        numf = [fl for fl in fields if re.search(r'pl_?num|plan_?num|number|mispar', fl, re.I)]
        print(f"{svc_name}/{lyr['id']} ({lyr.get('name','')}) {gt} | שדות מספר: {numf}")
        if not numf:
            continue
        hits = 0
        for t, nm in sample:
            ok = False
            digits = re.sub(r'\D+', '', t)
            wheres = [f"{{f}}='{t}'", f"{{f}}='{t[::-1]}'"]
            if len(digits) >= 3:
                wheres.append(f"{{f}} LIKE '%{digits}%'")
            for fld in numf[:2]:
                for w in wheres:
                    q = (f"{base}/{svc_name}/{ty}/{lyr['id']}/query?"
                         + urllib.parse.urlencode({'where': w.format(f=fld), 'outFields': fld,
                                                   'returnGeometry': 'false', 'f': 'json'}))
                    try:
                        r = jget(q, 60)
                        if r.get('features'):
                            ok = True; break
                    except Exception:
                        pass
                if ok: break
            hits += ok
            print(f"    {t} ({nm[:22]}): {'V' if ok else 'X'}")
        print(f"  ==> {hits}/10")
        if best is None or hits > best['hits']:
            best = {'service': svc_name, 'type': ty, 'layer_id': lyr['id'],
                    'layer': lyr.get('name',''), 'fields': numf, 'hits': hits}
        if hits >= 9:
            break
    if best and best['hits'] >= 9:
        break
report['best'] = best
print('הטוב ביותר:', best)

if best and best['hits'] > 0:
    t = next((t for t, n in tabas if 'אשקלון צפון' in n), sample[0][0])
    fld = best['fields'][0]
    for w in (f"{fld}='{t}'", f"{fld}='{t[::-1]}'", f"{fld} LIKE '%{re.sub(r'[^0-9]','',t)}%'"):
        q = (f"{base}/{best['service']}/{best['type']}/{best['layer_id']}/query?"
             + urllib.parse.urlencode({'where': w, 'outFields': '*',
                                       'returnGeometry': 'true', 'outSR': '4326', 'f': 'json'}))
        try:
            r = jget(q, 90)
            fts = r.get('features') or []
            if not fts: continue
            ft = fts[0]
            rings = (ft.get('geometry') or {}).get('rings') or []
            pts = sum(len(rg) for rg in rings)
            at = ft.get('attributes', {})
            print(f'גאומטריה ({t} via {w[:40]}): טבעות={len(rings)} נקודות={pts}')
            keep = {k: str(v)[:60] for k, v in list(at.items())[:10]}
            print('  תכונות:', keep)
            report['sample_geometry'] = {'taba': t, 'where': w, 'rings': len(rings), 'points': pts,
                                         'attrs': keep, 'first': rings[0][0] if rings and rings[0] else None}
            break
        except Exception as e:
            print('נסיון גאומטריה נכשל:', str(e)[:80])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
