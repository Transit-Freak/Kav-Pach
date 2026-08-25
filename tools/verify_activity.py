# -*- coding: utf-8 -*-
# מפקד פעילות עסקית לאזורי התעשייה — בדיקת "האם באמת עובדים שם".
#
# הרקע: המקורות הרשמיים (משרד התחבורה, משרד הכלכלה) מגדירים את האזורים
# תכנונית בלבד — אף שדה בהם לא מאשר שיש באזור תעסוקה בפועל (עמודות
# המועסקים במרשם משרד הכלכלה כמעט כולן 0). הכלי הזה בודק את זה מול
# OpenStreetMap: סופר כמה עסקים מתויגים (חנות/משרד/מלאכה/מפעל/שירות רכב)
# וכמה מבני תעשייה-מחסן נופלים בתוך הגבול של כל אחד מהאזורים באתר.
#
# קלט:  parks/data/parks.json + parks/data/p*.json (שדה polys — הגבולות)
# פלט:  parks/checks/activity.json — לכל אזור: ספירה לפי סוג + דוגמאות שמות
# הרצה: ב-CI בלבד (Overpass חסום מסביבות אחרות). python3 tools/verify_activity.py
import json, os, sys, time, urllib.parse, urllib.request

EPS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]
BBOX = '29.4,34.2,33.35,35.95'
DATA = os.environ.get('PARKS_DATA', 'parks/data')
OUT = os.environ.get('ACTIVITY_OUT', 'parks/checks/activity.json')

# עסקים מתויגים — עם התגיות (כדי לשלוף שמות)
Q_BIZ = ('[out:json][timeout:600][bbox:%s];('
         'nwr["shop"];nwr["office"];nwr["craft"];nwr["industrial"];'
         'nwr["man_made"="works"];'
         'nwr["amenity"~"^(fuel|restaurant|cafe|fast_food|bank|car_wash|car_rental|vehicle_inspection|charging_station)$"];'
         ');out tags center;') % BBOX
# מבני תעשייה/מחסן — ספירה בלבד (רובם בלי שם)
Q_BLD = ('[out:json][timeout:600][bbox:%s];('
         'way["building"~"^(industrial|warehouse|manufacture|factory)$"];'
         ');out ids center;') % BBOX


def overpass(q):
    for ep in EPS:
        for attempt in range(2):
            try:
                req = urllib.request.Request(ep, data=urllib.parse.urlencode({'data': q}).encode(),
                                             headers={'User-Agent': 'kav-bochan activity census'})
                with urllib.request.urlopen(req, timeout=700) as r:
                    return json.load(r)
            except Exception as e:
                print('  %s attempt %d failed: %s' % (ep, attempt + 1, e), flush=True)
                time.sleep(10)
    sys.exit('overpass unreachable on all endpoints')


def biz_kind(t):
    if t.get('man_made') == 'works' or 'industrial' in t: return 'ind'
    if 'craft' in t: return 'craft'
    if 'office' in t: return 'office'
    if 'shop' in t: return 'shop'
    return 'amen'


def latlon(e):
    la, lo = e.get('lat'), e.get('lon')
    if la is None:
        c = e.get('center') or {}
        la, lo = c.get('lat'), c.get('lon')
    return la, lo


def pip(la, lo, ring):
    # ray casting; ring = [[lat,lon],...]
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        yi, xi = ring[i]; yj, xj = ring[j]
        if (yi > la) != (yj > la) and lo < (xj - xi) * (la - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def main():
    zones = json.load(open(os.path.join(DATA, 'parks.json')))
    zrings = []   # (idx, bbox, ring)
    for i, z in enumerate(zones):
        try:
            p = json.load(open(os.path.join(DATA, z['f'] + '.json')))
        except Exception:
            continue
        for ring in p.get('polys') or []:
            if len(ring) < 3: continue
            las = [q[0] for q in ring]; los = [q[1] for q in ring]
            zrings.append((i, (min(las), min(los), max(las), max(los)), ring))
    print('zones: %d, rings: %d' % (len(zones), len(zrings)), flush=True)

    # אינדקס רשת גס (0.05 מעלות) — בלעדיו כל נקודה נבדקת מול כל 400+ הטבעות
    grid = {}
    for k, (i, bb, ring) in enumerate(zrings):
        for gy in range(int(bb[0] / .05), int(bb[2] / .05) + 1):
            for gx in range(int(bb[1] / .05), int(bb[3] / .05) + 1):
                grid.setdefault((gy, gx), []).append(k)

    res = [{'f': z['f'], 'name': z['name'], 'shop': 0, 'office': 0, 'craft': 0,
            'ind': 0, 'amen': 0, 'bld': 0, 'names': []} for z in zones]

    def assign(la, lo):
        for k in grid.get((int(la / .05), int(lo / .05)), ()):
            i, bb, ring = zrings[k]
            if bb[0] <= la <= bb[2] and bb[1] <= lo <= bb[3] and pip(la, lo, ring):
                return i
        return None

    print('== business POIs ==', flush=True)
    biz = overpass(Q_BIZ)
    els = biz.get('elements', [])
    print('country-wide business POIs: %d' % len(els), flush=True)
    for e in els:
        la, lo = latlon(e)
        if la is None: continue
        i = assign(la, lo)
        if i is None: continue
        t = e.get('tags', {})
        r = res[i]
        r[biz_kind(t)] += 1
        nm = t.get('name:he') or t.get('name')
        if nm and len(r['names']) < 8 and nm not in r['names']:
            r['names'].append(nm)

    print('== industrial buildings ==', flush=True)
    bld = overpass(Q_BLD)
    els = bld.get('elements', [])
    print('country-wide industrial buildings: %d' % len(els), flush=True)
    for e in els:
        la, lo = latlon(e)
        if la is None: continue
        i = assign(la, lo)
        if i is not None:
            res[i]['bld'] += 1

    for r in res:
        r['biz'] = r['shop'] + r['office'] + r['craft'] + r['ind'] + r['amen']
    import datetime
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'generated': datetime.date.today().isoformat(), 'src': 'OpenStreetMap (Overpass)',
               'zones': res}, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))

    empty = [r for r in res if r['biz'] == 0 and r['bld'] == 0]
    thin = [r for r in res if 0 < r['biz'] + r['bld'] <= 2]
    print('== summary ==')
    print('with activity evidence: %d / %d' % (len(res) - len(empty), len(res)))
    print('zero evidence (no tagged biz, no industrial building): %d' % len(empty))
    for r in empty[:40]:
        print('  EMPTY %s %s' % (r['f'], r['name']))
    print('thin evidence (1-2 items): %d' % len(thin))
    top = sorted(res, key=lambda r: -r['biz'])[:10]
    for r in top:
        print('  TOP %s %s biz=%d bld=%d %s' % (r['f'], r['name'], r['biz'], r['bld'], ', '.join(r['names'][:4])))


if __name__ == '__main__':
    main()
