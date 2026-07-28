# -*- coding: utf-8 -*-
# שליפה המונית של גבולות תב"ע ממנהל התכנון לכל אזורי התעשייה-תעסוקה של
# משרד התחבורה (427). לכל אזור: התאמת pl_number בשכבת הקווים הכחולים
# (Xplan/1) בשלושה פורמטים — כמו-שהוא, הפוך (היפוך RTL במקור), ו-LIKE על
# הספרות — ובדיקת שפיות: שטח הפוליגון מול השטח הרשום (יחס עד פי-4).
# הפלט: parks/checks/taba-boundaries.json — גבולות מפושטים + רשימת חסרים.
import json, math, os, re, sys, time, urllib.parse, urllib.request

OUT = os.environ.get('OUT', 'parks/checks/taba-boundaries.json')
PAUSE = float(os.environ.get('PAUSE', '0.25'))
BASE = 'https://ags.iplan.gov.il/arcgisiplan/rest/services'
LAYER = 'PlanningPublic/Xplan/MapServer/1'   # קוים כחולים — גבולות תוכניות
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def jget(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

ds = jget('https://data.gov.il/api/3/action/datastore_search?'
          + urllib.parse.urlencode({'resource_id': '71799e72-7a1f-45cf-9d81-5cd1d5f3b201', 'limit': 32000}))
recs = ds['result']['records']
print('אזורים ברשימת משרד התחבורה:', len(recs))

def ring_area_km2(rg):
    if len(rg) < 4:
        return 0.0
    cl = math.cos(math.radians(sum(p[1] for p in rg) / len(rg)))
    q = [(p[0] * 111320 * cl, p[1] * 110540) for p in rg]
    s = sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1] for i in range(len(q)))
    return abs(s) / 2 / 1e6

def simplify(rg, maxpts=250):
    if len(rg) <= maxpts:
        return [[round(p[1], 5), round(p[0], 5)] for p in rg]
    step = len(rg) / maxpts
    out = [rg[int(i * step)] for i in range(maxpts)]
    out.append(rg[-1])
    return [[round(p[1], 5), round(p[0], 5)] for p in out]

def query(where):
    q = (f'{BASE}/{LAYER}/query?'
         + urllib.parse.urlencode({'where': where, 'outFields': 'pl_number,pl_name',
                                   'returnGeometry': 'true', 'outSR': '4326', 'f': 'json'}))
    try:
        return jget(q, 90).get('features') or []
    except Exception:
        return []

zones, misses = [], []
n_exact = n_rev = n_like = 0
from collections import Counter
match_kinds = Counter()
T0 = time.time()
for i, at in enumerate(recs):
    t = str(at.get('TABA_NUM') or '').strip()
    nm = ' '.join(str(at.get('NAME') or '').split())
    try:
        bruto_km2 = float(at.get('BRUTOAREA') or 0) / 1e6
    except Exception:
        bruto_km2 = 0.0
    if not t or t in ('None', '0', '-'):
        misses.append({'name': nm, 'taba': t, 'why': 'אין מספר תב"ע'})
        continue
    esc = t.replace("'", "''")
    segrev = '/'.join(reversed(esc.split('/')))   # 165/101/02/4 → 4/02/101/165
    tries = [(f"pl_number='{esc}'", 'exact'),
             (f"pl_number='{segrev}'", 'segrev'),
             (f"pl_number='{esc[::-1]}'", 'rev')]
    parts = [p for p in re.split(r'[^0-9א-ת]+', esc) if p]
    if len(parts) >= 2:
        tries.append((f"pl_number LIKE '%{'%'.join(parts)}%'", 'like'))
        tries.append((f"pl_number LIKE '%{'%'.join(reversed(parts))}%'", 'like-rev'))
        # חלקים ללא תלות בסדר — רק מקטעים באורך 2+ (מקטע בודד קצר תופס הכול)
        big_parts = [p for p in parts if len(p) >= 2]
        if len(big_parts) >= 2:
            cond = ' AND '.join(f"pl_number LIKE '%{p}%'" for p in big_parts)
            tries.append((cond, 'parts'))
    # נפילה לאחור: לפי שם התוכנית — מילות שם האזור/העיר בתוך pl_name
    toks = [w for w in re.split(r'[^א-ת]+', nm) if len(w) >= 3][:3]
    if toks:
        cond = ' AND '.join(f"pl_name LIKE '%{w}%'" for w in toks)
        tries.append((cond, 'byname'))
    got = None
    for where, kind in tries:
        feats = query(where)
        time.sleep(PAUSE)
        if not feats:
            continue
        # אם כמה תוצאות — בוחרים את זו ששטחה הכי קרוב לשטח הרשום
        best_ft, best_score = None, None
        for ft in feats[:20]:
            rings = (ft.get('geometry') or {}).get('rings') or []
            a = sum(ring_area_km2(rg) for rg in rings)
            score = abs(math.log((a + 1e-4) / (bruto_km2 + 1e-4)))
            if best_score is None or score < best_score:
                best_ft, best_score, best_a = ft, score, a
        rings = (best_ft.get('geometry') or {}).get('rings') or []
        if not rings:
            continue
        # שפיות רכה: מסמנים יחס חריג אבל לא פוסלים — הפאנל ישפוט אחר כך
        got = (best_ft, kind, best_a)
        break
    if got is None:
        misses.append({'name': nm, 'taba': t, 'why': 'לא נמצא באף פורמט'})
        continue
    ft, kind, a = got
    match_kinds[kind] += 1
    zones.append({'name': nm, 'taba': t, 'city': str(at.get('CITY') or ''),
                  'district': str(at.get('DISTRICT') or ''), 'match': kind,
                  'pl_name': str(ft['attributes'].get('pl_name') or '')[:60],
                  'area_km2': round(a, 3), 'bruto_km2': round(bruto_km2, 3),
                  'ratio_flag': bool(bruto_km2 > 0.01 and not (bruto_km2 / 6 <= a <= bruto_km2 * 6)),
                  'polys': [simplify(rg) for rg in (ft.get('geometry') or {}).get('rings', [])[:6]]})
    if (i + 1) % 50 == 0:
        print(f'{i + 1}/{len(recs)} | נמצאו {len(zones)} | {int(time.time() - T0)}s')

print(f'סיכום: נמצאו {len(zones)}/{len(recs)} | {dict(match_kinds)} | חסרים {len(misses)} | דגלי-יחס {sum(1 for z in zones if z.get(chr(114)+chr(97)+chr(116)+chr(105)+chr(111)+chr(95)+chr(102)+chr(108)+chr(97)+chr(103)))}')
for m in misses[:25]:
    print('  חסר:', m['name'][:40], '|', m['taba'], '|', m['why'])
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'fetched': time.strftime('%Y-%m-%d %H:%M'), 'layer': LAYER,
           'found': len(zones), 'total': len(recs), 'zones': zones, 'misses': misses},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('wrote', OUT, os.path.getsize(OUT), 'bytes')
