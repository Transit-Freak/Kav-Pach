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

# ---------- שליפת מדגם: 10 תב"עות מול כל שכבת-תוכניות מועמדת ----------
sample = tabas[:10]
best = None
for p in plan_layers[:8]:
    # אילו שדות יש בשכבה — מחפשים שדה מספר-תוכנית
    try:
        meta = jget(f"{base}/{p['service']}/{p['type']}/{p['id']}?f=json")
        fields = [fl['name'] for fl in meta.get('fields', [])]
    except Exception as e:
        print(p['service'], p['id'], 'שגיאת שדות:', str(e)[:60]); continue
    numf = [fl for fl in fields if re.search(r'pl_?num|plan_?num|number|mispar', fl, re.I)]
    print(f"{p['service']}/{p['id']} ({p['layer']}): שדות: {fields[:12]} | שדות מספר: {numf}")
    if not numf:
        continue
    hits = 0
    for t, nm in sample:
        ok = False
        # פורמטים: כמו-שהוא, הפוך (היפוך RTL בקובץ המקור), ו-LIKE על החלק המספרי
        digits = re.sub(r'\D+', '', t)
        wheres = [f"{{f}}='{t}'", f"{{f}}='{t[::-1]}'"]
        if len(digits) >= 3:
            wheres.append(f"{{f}} LIKE '%{digits}%'")
        for fld in numf[:2]:
            for w in wheres:
                q = (f"{base}/{p['service']}/{p['type']}/{p['id']}/query?"
                     + urllib.parse.urlencode({'where': w.format(f=fld), 'outFields': fld,
                                               'returnGeometry': 'false', 'f': 'json'}))
                try:
                    r = jget(q, 60)
                    if r.get('features'):
                        ok = True
                        print(f"      התאמה: {w.format(f=fld)} → {r['features'][0].get('attributes')}")
                        break
                except Exception:
                    pass
            if ok:
                break
        hits += ok
        print(f"    {t} ({nm[:25]}): {'✓' if ok else '✗'}")
    print(f"  ==> פגיעות: {hits}/10")
    if best is None or hits > best['hits']:
        best = {'service': p['service'], 'type': p['type'], 'layer_id': p['id'],
                'layer': p['layer'], 'fields': numf, 'hits': hits}
    if hits >= 8:
        break
report['best'] = best
print('הטוב ביותר:', best)

# אם יש פגיעה טובה — שולפים גאומטריה אחת לדוגמה (אשקלון צפון אם אפשר)
if best and best['hits'] > 0:
    t = next((t for t, n in tabas if 'אשקלון צפון' in n), sample[0][0])
    q = (f"{base}/{best['service']}/{best['type']}/{best['layer_id']}/query?"
         + urllib.parse.urlencode({'where': f"{best['fields'][0]}='{t}'", 'outFields': '*',
                                   'returnGeometry': 'true', 'outSR': '4326', 'f': 'json'}))
    try:
        r = jget(q, 90)
        ft = (r.get('features') or [{}])[0]
        rings = (ft.get('geometry') or {}).get('rings') or []
        pts = sum(len(rg) for rg in rings)
        print(f'גאומטריה לדוגמה ({t}): טבעות={len(rings)} נקודות={pts}')
        report['sample_geometry'] = {'taba': t, 'rings': len(rings), 'points': pts,
                                     'first': rings[0][0] if rings and rings[0] else None}
    except Exception as e:
        print('שליפת גאומטריה נכשלה:', str(e)[:100])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
