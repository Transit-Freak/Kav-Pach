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
         ');out meta center;') % BBOX
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
            p = json.load(open(os.path.join(DATA, z['f'])))   # f כבר כולל ‎.json
        except Exception:
            continue
        for ring in p.get('polys') or []:
            if len(ring) < 3: continue
            las = [q[0] for q in ring]; los = [q[1] for q in ring]
            zrings.append((i, (min(las), min(los), max(las), max(los)), ring))
    print('zones: %d, rings: %d' % (len(zones), len(zrings)), flush=True)
    if not zrings:
        sys.exit('no zone rings loaded — refusing to publish an empty census')

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
        ts = e.get('timestamp') or ''
        yr = int(ts[:4]) if ts[:4].isdigit() else None
        if yr:
            r.setdefault('yrs', []).append(yr)
        nm = t.get('name:he') or t.get('name')
        if nm and len(r['names']) < 8 and not any(n[0] == nm for n in r['names']):
            r['names'].append([nm, yr])

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

    # שלב 2 — לאזורים בלי אף עסק: ספירת *כל* המבנים בתוך הגבול (רוב המבנים
    # ב-OSM מתויגים סתם building=yes, לא "industrial"). זה מה שמפריד בין
    # "פעיל אבל לא ממופה ברמת העסק" לבין "שטח ריק באמת".
    print('== all-buildings pass for zones with no tagged business ==', flush=True)
    byzone = {}
    for i, bb, ring in zrings:
        byzone.setdefault(i, []).append(ring)
    for i, z in enumerate(zones):
        r = res[i]
        if r['shop'] + r['office'] + r['craft'] + r['ind'] + r['amen'] > 0:
            continue
        rings = sorted(byzone.get(i, []), key=len, reverse=True)[:3]
        if not rings:
            continue
        cls = []
        for ring in rings:
            step = max(1, len(ring) // 80)
            pts = ring[::step]
            poly = ' '.join('%.5f %.5f' % (q[0], q[1]) for q in pts)
            cls.append('way["building"](poly:"%s");' % poly)
        q = '[out:json][timeout:60];(%s);out count;' % ''.join(cls)
        try:
            d = overpass(q)
            n = sum(int(e.get('tags', {}).get('total', 0)) for e in d.get('elements', []))
            r['bldall'] = n
        except SystemExit:
            raise
        except Exception as e:
            print('  bldall failed for %s: %s' % (z['name'], e), flush=True)
        time.sleep(0.7)

    for r in res:
        r['biz'] = r['shop'] + r['office'] + r['craft'] + r['ind'] + r['amen']
        ys = sorted(r.pop('yrs', []))
        if ys:
            r['y_new'] = ys[-1]                # העריכה האחרונה באזור
            r['y_med'] = ys[len(ys) // 2]      # חציון — מתי רוב העדות עודכנה
            r['y_fresh'] = sum(1 for y in ys if y >= 2023)  # כמה נגעו בהם לאחרונה
    if not any(r['biz'] or r['bld'] for r in res):
        sys.exit('country-wide data fetched but nothing assigned to any zone — assignment bug, refusing to publish')
    import datetime
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({'generated': datetime.date.today().isoformat(), 'src': 'OpenStreetMap (Overpass)',
               'zones': res}, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))

    named = [r for r in res if r['biz'] > 0]
    unmapped = [r for r in res if r['biz'] == 0 and (r['bld'] > 0 or r.get('bldall', 0) > 0)]
    bare = [r for r in res if r['biz'] == 0 and r['bld'] == 0 and r.get('bldall', 0) == 0]
    print('== summary ==')
    print('A tagged businesses: %d' % len(named))
    print('B buildings but no tagged business (unmapped, not empty): %d' % len(unmapped))
    print('C no buildings at all (truly bare): %d' % len(bare))
    for r in bare:
        print('  BARE %s %s' % (r['f'], r['name']))
    top = sorted(res, key=lambda r: -r['biz'])[:10]
    for r in top:
        print('  TOP %s %s biz=%d bld=%d y_new=%s %s' % (r['f'], r['name'], r['biz'], r['bld'], r.get('y_new'), ', '.join(n[0] for n in r['names'][:4])))


if __name__ == '__main__':
    main()
