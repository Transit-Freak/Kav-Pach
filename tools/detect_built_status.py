# -*- coding: utf-8 -*-
# זיהוי אוטומטי: אילו אזורי תעשייה כבר בנויים ואילו עדיין מתוכננים/בהקמה.
# הסימן המרכזי — צפיפות מבנים בתוך הפוליגון לפי OpenStreetMap (בישראל
# שכבת המבנים מיובאת ממקור ממשלתי ומכסה כמעט הכול): אזור פעיל מלא במבנים,
# אזור שטרם נבנה ריק כמעט לגמרי. סימנים משלימים: שטח מתויג כאתר בנייה
# בתוך הפוליגון, ומספר תחנות התחבורה בתוכו.
#
# הפלט: parks/checks/built-status.json — לכל אזור מספר מבנים, צפיפות
# והכרעה (built / partial / planned). נקרא ע"י tools/parks.py בריצה הבאה.
import json, math, os, sys, time, urllib.request

IDX = os.environ.get('PARKS_IDX', 'parks/data/parks.json')
DATA = os.environ.get('PARKS_DATA', 'parks/data')
OUT = os.environ.get('OUT', 'parks/checks/built-status.json')
CHUNK = int(os.environ.get('CHUNK', '25'))
SERVERS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
]

# ספי ההכרעה: מבנים לקמ"ר. אזור תעשייה פעיל בישראל — עשרות עד מאות.
PLANNED_BPK = 12      # מתחת לזה: כמעט ריק — מתוכנן/בהקמה
PARTIAL_BPK = 40      # מתחת לזה: בנוי חלקית
MIN_BLD_BUILT = 5     # אזור זעיר: לפחות כמה מבנים כדי להיחשב בנוי

idx = json.load(open(IDX, encoding='utf-8'))
zones = []
for e in idx:
    try:
        d = json.load(open(os.path.join(DATA, e['f']), encoding='utf-8'))
    except Exception:
        continue
    polys = [rg for rg in d.get('polys', []) if len(rg) >= 4]
    if not polys:
        continue
    la1 = min(p[0] for rg in polys for p in rg); la2 = max(p[0] for rg in polys for p in rg)
    lo1 = min(p[1] for rg in polys for p in rg); lo2 = max(p[1] for rg in polys for p in rg)
    zones.append({'name': e['name'], 'city': e.get('city', ''), 'la': e['la'], 'lo': e['lo'],
                  'area': e.get('area', 0), 'in': e.get('in', 0), 'polys': polys,
                  'bbox': (la1, lo1, la2, lo2)})
print('אזורים לבדיקה:', len(zones))


def fetch(bboxes):
    parts = []
    for (la1, lo1, la2, lo2) in bboxes:
        b = f'{la1:.5f},{lo1:.5f},{la2:.5f},{lo2:.5f}'
        parts.append(f'way["building"]({b});relation["building"]({b});')
        parts.append(f'way["landuse"~"construction|greenfield|brownfield"]({b});')
    q = f'[out:json][timeout:300];({"".join(parts)});out center tags;'
    for attempt in range(5):
        url = SERVERS[attempt % len(SERVERS)]
        try:
            req = urllib.request.Request(url, data=q.encode(),
                                         headers={'User-Agent': 'kav-bochan/parks (built-status; polite)'})
            with urllib.request.urlopen(req, timeout=330) as r:
                return json.load(r).get('elements', [])
        except Exception as e:
            print(f'  ניסיון {attempt + 1} @ {url.split("/")[2]}: {str(e)[:70]}', file=sys.stderr)
            time.sleep(25)
    return None


def in_poly(la, lo, pts):
    n = len(pts); j = n - 1; c = False
    for i in range(n):
        if ((pts[i][1] > lo) != (pts[j][1] > lo)) and \
           (la < (pts[j][0] - pts[i][0]) * (lo - pts[i][1]) / ((pts[j][1] - pts[i][1]) or 1e-12) + pts[i][0]):
            c = not c
        j = i
    return c


for z in zones:
    z['bld'] = 0
    z['constr'] = 0

T0 = time.time()
fails = 0
for i in range(0, len(zones), CHUNK):
    grp = zones[i:i + CHUNK]
    els = fetch([z['bbox'] for z in grp])
    if els is None:
        fails += 1
        print(f'  מנה {i // CHUNK + 1}: כשל רשת — האזורים בה יסומנו "לא ידוע"')
        for z in grp:
            z['bld'] = None
        continue
    for e in els:
        c = e.get('center') or ({'lat': e.get('lat'), 'lon': e.get('lon')} if e.get('lat') else None)
        if not c or c.get('lat') is None:
            continue
        la, lo = c['lat'], c['lon']
        t = e.get('tags') or {}
        kind = 'constr' if (t.get('landuse') and not t.get('building')) else 'bld'
        for z in grp:
            b = z['bbox']
            if not (b[0] <= la <= b[2] and b[1] <= lo <= b[3]):
                continue
            if any(in_poly(la, lo, rg) for rg in z['polys']):
                if z[kind] is not None:
                    z[kind] += 1
                break
    print(f'{min(i + CHUNK, len(zones))}/{len(zones)} | {int(time.time() - T0)}s')
    time.sleep(2)

out = []
from collections import Counter
cnt = Counter()
for z in zones:
    bld = z['bld']
    area = max(z['area'], 0.01)
    if bld is None:
        st = 'unknown'; bpk = None
    else:
        bpk = round(bld / area, 1)
        if bld < MIN_BLD_BUILT or bpk < PLANNED_BPK:
            st = 'planned'
        elif bpk < PARTIAL_BPK:
            st = 'partial'
        else:
            st = 'built'
        # שטח מתויג כאתר בנייה בתוך אזור כמעט ריק מחזק את ההכרעה
        if st == 'partial' and z['constr'] and bpk < 25:
            st = 'planned'
    cnt[st] += 1
    out.append({'name': z['name'], 'city': z['city'], 'la': z['la'], 'lo': z['lo'],
                'area': z['area'], 'bld': bld, 'bpk': bpk, 'constr': z['constr'],
                'stops_in': z['in'], 'st': st})

print('סיכום:', dict(cnt), '| מנות שנכשלו:', fails)
print('--- מועמדים ל"טרם נבנה" (הגדולים ראשונים) ---')
for z in sorted([o for o in out if o['st'] == 'planned'], key=lambda o: -o['area'])[:30]:
    print(f"  {z['name'][:40]:42} | {str(z['city'])[:14]:16} | {z['area']} קמ\"ר | מבנים: {z['bld']} ({z['bpk']}/קמ\"ר) | תחנות: {z['stops_in']}")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'checked': time.strftime('%Y-%m-%d %H:%M'), 'thresholds': {'planned': PLANNED_BPK, 'partial': PARTIAL_BPK},
           'summary': dict(cnt), 'zones': out},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
