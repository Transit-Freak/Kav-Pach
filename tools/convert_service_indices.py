# -*- coding: utf-8 -*-
# המרת שכבת "מדדי שירות" של משרד התחבורה (shapefile ברשת ישראל) לקובץ
# קומפקטי ב-WGS84 שהאתר יכול לקרוא. ארבעה מדדים לכל אזור סטטיסטי:
# זמינות, נגישות, תחרותיות, אמינות — וציון משוקלל.
#
# הרצה חד-פעמית (או בכל פעם שמתפרסמת גרסה חדשה):
#   SHP=<נתיב ל-madadey_shirut> python3 tools/convert_service_indices.py
import json, math, os, sys

SHP = os.environ.get('SHP', 'madadey_shirut')
OUT = os.environ.get('OUT', 'parks/checks/service-indices.json')
MAXPTS = int(os.environ.get('MAXPTS', '60'))
UPDATED = os.environ.get('UPDATED', '2025-11')

import shapefile
from pyproj import Transformer

sf = shapefile.Reader(SHP, encoding='utf-8')
flds = [f[0] for f in sf.fields[1:]]
tr = Transformer.from_crs(2039, 4326, always_xy=True)   # רשת ישראל → WGS84


def simplify(pts):
    if len(pts) <= MAXPTS:
        return pts
    step = len(pts) / MAXPTS
    out = [pts[int(i * step)] for i in range(MAXPTS)]
    out.append(pts[-1])
    return out


def ring_area_km2(rg):
    if len(rg) < 4:
        return 0.0
    cl = math.cos(math.radians(sum(p[0] for p in rg) / len(rg)))
    q = [(p[1] * 111320 * cl, p[0] * 110540) for p in rg]
    s = sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1]
            for i in range(len(q)))
    return abs(s) / 2 / 1e6


areas = []
skipped = 0
for rec, shp in zip(sf.records(), sf.shapes()):
    d = dict(zip(flds, rec))
    if not shp.points:
        skipped += 1
        continue
    # חלוקה לטבעות לפי parts, המרה ל-WGS84 ופישוט
    parts = list(shp.parts) + [len(shp.points)]
    rings = []
    for a, b in zip(parts, parts[1:]):
        seg = shp.points[a:b]
        if len(seg) < 4:
            continue
        wgs = [(round(la, 5), round(lo, 5)) for lo, la in
               (tr.transform(x, y) for x, y in simplify(seg))]
        rings.append([[la, lo] for la, lo in wgs])
    if not rings:
        skipped += 1
        continue
    areas.append({
        'sa': d.get('YISHUV_STA'), 'city': (d.get('SHEM_YISHU') or '').strip(),
        'av': d.get('AVAILABILI'), 'ac': d.get('ACCESSIBIL'),
        'co': d.get('COMPETITIO'), 're': d.get('RELIABILIT'), 'fs': d.get('FINAL_SCOR'),
        'km2': round(sum(ring_area_km2(rg) for rg in rings), 3),
        'polys': rings,
    })

print(f'אזורים סטטיסטיים: {len(areas)} | דולגו: {skipped}')
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'src': 'מדדי שירות בתחבורה ציבורית — משרד התחבורה והבטיחות בדרכים',
           'updated': UPDATED,
           'fields': {'av': 'זמינות', 'ac': 'נגישות', 'co': 'תחרותיות',
                      're': 'אמינות', 'fs': 'ציון משוקלל'},
           'areas': areas},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('wrote', OUT, round(os.path.getsize(OUT) / 1024), 'KB')
