# -*- coding: utf-8 -*-
"""ציד ספים (סיירת 2, בקשת איריס): אזורים שהציון המשוקלל שלהם יושב על
קצה מדרגה — שינוי קטן בקלט היה מזיז אותם מדרגה. אלה המקומות שבהם
הדו"ח פגיע: עיתונאי מבקר ישאל "למה 80 ולא 85" ואין תשובה טובה."""
import json, sys
# הנוסחה — העתק מילה במילה מ-tools/parks.py:897-920 (ייבוא מריץ את כל הצינור)
IRIS_HEADWAY = [(5, 100), (10, 90), (15, 85), (20, 80), (30, 70), (40, 60), (60, 55)]
IRIS_WALK = [(2, 100), (7, 90), (10, 80), (12, 75), (15, 65), (20, 55)]
IRIS_W = {'uf': .15, 'bl': .35, 'far': .25, 'near': .25}
def _band(v, table):
    if v is None or v <= 0:
        return 0
    for t, sc in table:
        if v <= t:
            return sc
    return 0
def iris_score(pkd, bl1, ww, near_walk):
    c = {'uf': _band(420.0 / pkd if pkd else None, IRIS_HEADWAY),
         'bl': _band(180.0 / bl1 if bl1 else None, IRIS_HEADWAY),
         'far': _band(ww, IRIS_WALK), 'near': _band(near_walk, IRIS_WALK)}
    return round(sum(c[k] * IRIS_W[k] for k in IRIS_W)), c

P = json.load(open('parks/data/parks.json', encoding='utf-8'))
S = [p for p in P if p.get('score') is not None]
print(f'{len(S)} אזורים עם ציון משוקלל\n')

# 1. אימות: הציון שנכתב = הנוסחה על הקלטים שנכתבו (בלי סטייה)
bad = 0
for p in S:
    sc, parts = iris_score(p.get('pkd'), p.get('bl1'), p.get('ww'), p.get('nearw'))
    if sc != p['score'] or parts != p.get('sparts'):
        bad += 1
        if bad <= 5:
            print(f"  ✗ {p['name']}: נכתב {p['score']} {p.get('sparts')} · חישוב מחדש {sc} {parts}")
print(f"אימות חישוב-מחדש: {'✓ כל הציונים משוחזרים מהקלטים' if not bad else f'✗ {bad} סטיות'}\n")

# 2. רגישות: לכל רכיב, כמה אחוז שינוי בקלט מזיז את הציון המשוקלל
def perturb(p, k, f):
    pkd, bl1, ww, nw = p.get('pkd'), p.get('bl1'), p.get('ww'), p.get('nearw')
    if k == 'uf' and pkd: pkd = pkd * f
    if k == 'bl' and bl1: bl1 = bl1 * f
    if k == 'far' and ww: ww = ww * f
    if k == 'near' and nw: nw = nw * f
    return iris_score(pkd, bl1, ww, nw)[0]

TOL = 0.05   # 5% — סדר הגודל של רעש שבועי בלוח זמנים או של הזזת תחנה ב-OSM
frag = []
for p in S:
    base = p['score']
    worst = 0; wk = None
    for k in IRIS_W:
        for f in (1 - TOL, 1 + TOL):
            d = abs(perturb(p, k, f) - base)
            if d > worst: worst, wk = d, k
    if worst:
        frag.append((worst, wk, p))

frag.sort(key=lambda x: -x[0])
n5 = sum(1 for w, _, _ in frag if w >= 5)
print(f'רגישות לשינוי של ±{int(TOL*100)}% בקלט יחיד:')
print(f'  {len(frag)} אזורים משנים ציון · {n5} מהם ב-5 נקודות ומעלה · '
      f'{sum(1 for w,_,_ in frag if w>=10)} ב-10 ומעלה\n')
print('  20 השבירים ביותר:')
lbl = {'uf': 'תדירות', 'bl': 'קו חזק', 'far': 'נק׳ רחוקה', 'near': 'הליכה למרכז'}
for w, k, p in frag[:20]:
    v = {'uf': f"pkd={p.get('pkd')}", 'bl': f"bl1={p.get('bl1')}",
         'far': f"ww={p.get('ww')}", 'near': f"nearw={p.get('nearw')}"}[k]
    print(f"   {p['score']:3} ±{w:2}  {lbl[k]:12} {v:12}  {p['name'][:32]} ({p.get('city','')})")

# 3. ריכוז על גבולות: קלטים שיושבים בדיוק על סף מדרגה (±2%)
def near_edge(v, table, tol=0.02):
    if not v: return None
    for t, _ in table:
        if abs(v - t) <= t * tol: return t
    return None
edges = {'uf': 0, 'bl': 0, 'far': 0, 'near': 0}
for p in S:
    if p.get('pkd') and near_edge(420.0 / p['pkd'], IRIS_HEADWAY): edges['uf'] += 1
    if p.get('bl1') and near_edge(180.0 / p['bl1'], IRIS_HEADWAY): edges['bl'] += 1
    if near_edge(p.get('ww'), IRIS_WALK): edges['far'] += 1
    if near_edge(p.get('nearw'), IRIS_WALK): edges['near'] += 1
print(f"\nקלטים שיושבים על סף מדרגה (±2%): {edges}")
json.dump({'n': len(S), 'recompute_mismatch': bad, 'fragile_ge5': n5,
           'fragile_ge10': sum(1 for w,_,_ in frag if w>=10), 'edges': edges,
           'top': [{'name': p['name'], 'city': p.get('city'), 'score': p['score'],
                    'delta': w, 'component': k} for w, k, p in frag[:30]]},
          open('parks/checks/threshold-hunt.json', 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('נכתב parks/checks/threshold-hunt.json')
