# -*- coding: utf-8 -*-
# נגישות תחבורה ציבורית לאזורי תעשייה — חילוץ.
# קלט: פוליגונים של landuse=industrial + שבילי הולכי-רגל מ-Overpass (PARKS_RAW),
#       GTFS מלא (stops/stop_times/trips/routes/calendar).
# פלט: OUTDIR/p<i>.json לכל פארק + OUTDIR/parks.json (אינדקס).
#
# העיקרון המרכזי (בקשת המשתמש): להבדיל בין תחנה שבאמת בתוך הפארק לתחנת
# צומת/כניסה — השיוך גאומטרי (בתוך הפוליגון / עד 150מ' / עד 450מ'), ושמות
# צומת/מחלף/כביש לעולם לא נספרים כ"בתוך".
import csv, json, math, os, re, datetime, time, urllib.request, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_type import classify as _classify_zone   # תיוג סוג + סינון לא-מקום-עבודה

RAW = os.environ.get('PARKS_RAW', 'parks-raw.json')
OFFICIAL = os.environ.get('OFFICIAL', '')   # official.json (משרד הכלכלה); ריק = לדלג
# מצב "ממשלתי בלבד": האזורים מגיעים אך ורק מהדאטהסט הרשמי (data.gov.il), לא מ-OSM.
OFFICIAL_ONLY = bool(os.environ.get('OFFICIAL_ONLY'))
STOPS = os.environ.get('STOPS', 'stops.txt')
STOPTIMES = os.environ.get('STOPTIMES', 'stop_times.txt')
TRIPS = os.environ.get('TRIPS', 'trips.txt')
ROUTES = os.environ.get('ROUTES', 'routes.txt')
CAL = os.environ.get('CAL', 'calendar.txt')
OUTDIR = os.environ.get('OUTDIR', 'parks-out')

GATE_M = 150      # עד כאן מגבול הפארק — "כניסה"
NEAR_M = 450      # עד כאן — "צומת/ליד"; רחוק יותר לא רלוונטי לפארק
COVER_M = 400     # רדיוס הליכה סבירה לחישוב כיסוי שטח
MIN_AREA_KM2 = 0.04
GAP_MIN = 90      # פער בדקות בין הגעות עוקבות שנחשב "חור" בשירות
GAP_WIN = ('05:30', '20:00')
JUNCTION_RE = re.compile(r'צומת|מחלף|מסעף|כביש \d')
# תשתית רכבת (דיפו/מסילה/מוסך) מתויגת לפעמים ב-OSM כ-landuse=industrial אך אינה
# אזור תעשייה-תעסוקה. רצועה דקה לאורך המסילה חופפת תחנות-כביש ומנפחת ספירת-קווים
# כוזבת — לכן מסוננת החוצה.
INFRA_RE = re.compile(r'דיפו|מסיל[הת] ברזל|מוסך רכב|מחסני רכבת')

# ---- קריאת Overpass ----
raw = json.load(open(RAW, encoding='utf-8')) if os.path.exists(RAW) else {'elements': []}
polys = []   # (name-or-'', [(la,lo),...])
foot = []    # [(la,lo),...]
for e in raw.get('elements', []):
    t = e.get('tags', {}) or {}
    if t.get('landuse') == 'industrial':
        nm = re.sub(r'\s+', ' ', t.get('name', '')).strip()
        if nm and INFRA_RE.search(nm):
            continue   # תשתית רכבת — לא אזור תעשייה
        if e.get('type') == 'way' and e.get('geometry'):
            pts = [(p['lat'], p['lon']) for p in e['geometry']]
            if len(pts) >= 4:
                polys.append((nm, pts))
        elif e.get('type') == 'relation':
            for m in e.get('members', []):
                if m.get('role') == 'outer' and m.get('geometry'):
                    pts = [(p['lat'], p['lon']) for p in m['geometry']]
                    if len(pts) >= 4:
                        polys.append((nm, pts))
    elif e.get('type') == 'way' and e.get('geometry'):
        hw = t.get('highway', '')
        if hw in ('footway', 'path', 'pedestrian', 'steps') or \
           t.get('sidewalk') in ('both', 'left', 'right', 'separate'):
            foot.append([(p['lat'], p['lon']) for p in e['geometry']])
print('פוליגונים תעשייתיים עם שם:', len(polys), '| קטעי הולכי-רגל:', len(foot))

# ---- גאומטריה מטרית ----
def xy(la, lo, cl): return (lo * 111320 * cl, la * 110540)

def poly_area_km2(pts, cl):
    q = [xy(a, b, cl) for a, b in pts]
    s = sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1]
            for i in range(len(q)))
    return abs(s) / 2 / 1e6

def in_poly(la, lo, pts):
    n = len(pts); inside = False
    j = n - 1
    for i in range(n):
        (y1, x1), (y2, x2) = pts[i], pts[j]
        if (x1 > lo) != (x2 > lo) and la < (y2 - y1) * (lo - x1) / ((x2 - x1) or 1e-12) + y1:
            inside = not inside
        j = i
    return inside

def seg_dist(p, a, b):
    px, py = p; ax, ay = a; bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))

def dist_to_poly_m(la, lo, pts, cl):
    p = xy(la, lo, cl)
    q = [xy(a, b, cl) for a, b in pts]
    return min(seg_dist(p, q[i], q[(i + 1) % len(q)]) for i in range(len(q)))

# ---- קיבוץ פוליגונים לפארקים ----
# בעלי שם: אותו שם + קרובים = פארק אחד (א.ת. מפוצל). חסרי שם: נצמדים לפארק
# בעל-שם סמוך (עד 250מ'), אחרת מתקבצים בינם לבין עצמם (עד 500מ') ויקבלו שם
# מהיישוב — "הכול ולא רק חלק": אזור תעשייה ממופה בלי שם עדיין מוצג.
parks = []   # {'name', 'noname', 'polys':[pts,...], 'cen':(la,lo), 'cl', 'area'}
def _cen(pts):
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
named = [(nm, pts) for nm, pts in polys if nm]
unnamed = [pts for nm, pts in polys if not nm]
for nm, pts in named:
    cla, clo = _cen(pts)
    cl = math.cos(math.radians(cla))
    hit = None
    for pk in parks:
        if pk['name'] == nm and math.hypot((pk['cen'][0] - cla) * 110540,
                                           (pk['cen'][1] - clo) * 111320 * cl) < 3000:
            hit = pk; break
    if hit:
        hit['polys'].append(pts)
    else:
        parks.append({'name': nm, 'noname': False, 'polys': [pts], 'cen': (cla, clo), 'cl': cl})
for pts in unnamed:
    cla, clo = _cen(pts)
    cl = math.cos(math.radians(cla))
    best = None
    for pk in parks:
        dd = math.hypot((pk['cen'][0] - cla) * 110540, (pk['cen'][1] - clo) * 111320 * cl)
        if dd > 2500: continue
        if any(in_poly(cla, clo, q) for q in pk['polys']) or            min(dist_to_poly_m(cla, clo, q, cl) for q in pk['polys']) <= (250 if not pk['noname'] else 500):
            if best is None or dd < best[1]: best = (pk, dd)
    if best:
        best[0]['polys'].append(pts)
    else:
        parks.append({'name': '', 'noname': True, 'polys': [pts], 'cen': (cla, clo), 'cl': cl})
for pk in parks:
    pk['area'] = sum(poly_area_km2(p, pk['cl']) for p in pk['polys'])
parks = [p for p in parks if p['area'] >= MIN_AREA_KM2]
if OFFICIAL_ONLY:
    parks = []   # מתעלמים מ-OSM; כל האזורים ייווצרו מהדאטהסט הרשמי בהמשך
print('פארקים אחרי קיבוץ וסינון שטח:', len(parks), '(ממשלתי-בלבד)' if OFFICIAL_ONLY else '')

# ---- סטטוס בנוי/מתוכנן (tools/detect_built_status.py) ----
# נמדד לפי צפיפות מבנים בתוך הפוליגון; ההתאמה לפי מרכז האזור (עד 300מ'),
# כדי שגם שינוי קל בגבול בין ריצות לא ינתק את האזור מהסטטוס שלו.
BUILT = os.environ.get('BUILT_STATUS', 'parks/checks/built-status.json')
_built = []
if os.path.exists(BUILT):
    try:
        _built = [z for z in json.load(open(BUILT, encoding='utf-8'))['zones']
                  if z.get('st') in ('planned', 'partial')]
        print('סטטוס בנייה נטען:', len(_built), 'אזורים לא-בנויים-במלואם')
    except Exception as e:
        print('טעינת סטטוס בנייה נכשלה:', e)

def built_status(cen):
    best = None
    cl = math.cos(math.radians(cen[0]))
    for z in _built:
        d = math.hypot((z['lo'] - cen[1]) * 111320 * cl, (z['la'] - cen[0]) * 110540)
        if d <= 300 and (best is None or d < best[1]):
            best = (z['st'], d)
    return best[0] if best else ''

# ---- מדדי השירות של משרד התחבורה (זמינות/נגישות/תחרותיות/אמינות) ----
# ציונים רשמיים לכל אזור סטטיסטי. לכל אזור תעשייה מחפשים את האזורים
# הסטטיסטיים שהוא נמצא בהם; כשיש כמה — ממוצע משוקלל לפי שטח האזור
# הסטטיסטי, והציון של האזור שבו יושב המרכז מקבל משקל כפול.
SVCIDX = os.environ.get('SERVICE_INDICES', 'parks/checks/service-indices.json')
_svc = []
_svc_meta = {}
if os.path.exists(SVCIDX):
    try:
        _sj = json.load(open(SVCIDX, encoding='utf-8'))
        _svc_meta = {'updated': _sj.get('updated'), 'src': _sj.get('src')}
        for a in _sj['areas']:
            pts = [p for rg in a['polys'] for p in rg]
            la1 = min(p[0] for p in pts); la2 = max(p[0] for p in pts)
            lo1 = min(p[1] for p in pts); lo2 = max(p[1] for p in pts)
            a['bb'] = (la1, lo1, la2, lo2)
            _svc.append(a)
        print('מדדי שירות נטענו:', len(_svc), 'אזורים סטטיסטיים | עדכון', _svc_meta.get('updated'))
    except Exception as e:
        print('טעינת מדדי שירות נכשלה:', e)

def service_scores(pk):
    """ציוני מדדי השירות לאזור: ממוצע משוקלל של האזורים הסטטיסטיים שהוא חופף."""
    if not _svc:
        return None
    cen = pk['cen']
    # דוגמים את הפוליגון: המרכז + קודקודי הגבול, ובודקים בכל אזור סטטיסטי
    sample = [cen] + [p for rg in pk['polys'] for p in rg[::max(1, len(rg) // 12)]][:24]
    hits = {}
    for i, a in enumerate(_svc):
        bb = a['bb']
        for (la, lo) in sample:
            if not (bb[0] <= la <= bb[2] and bb[1] <= lo <= bb[3]):
                continue
            if any(in_poly(la, lo, rg) for rg in a['polys']):
                w = 2.0 if (la, lo) == cen else 1.0
                hits[i] = hits.get(i, 0) + w
                break
    if not hits:
        return None
    tot = sum(hits.values())
    def wavg(k):
        vals = [(_svc[i].get(k), w) for i, w in hits.items() if isinstance(_svc[i].get(k), (int, float))]
        if not vals:
            return None
        return round(sum(v * w for v, w in vals) / sum(w for _, w in vals), 1)
    return {'av': wavg('av'), 'ac': wavg('ac'), 'co': wavg('co'),
            're': wavg('re'), 'fs': wavg('fs'), 'n': len(hits),
            'sa_city': _svc[max(hits, key=hits.get)].get('city', '')}

# ---- מקור שלישי: אזורי תעשייה-תעסוקה של משרד התחבורה ----
# הגבולות מהשכבה הרשמית של משרד התחבורה עצמו (parks/osm-check/mot-zones.json,
# נבנה ב-tools/fetch_mot_shapes.py). ly='hub' מסמן מוקד תעסוקה שאינו אזור
# תעשייה קלאסי (נמל, מחצבה, קמפוס...) — שכבת תצוגה נפרדת באתר.
MOT = os.environ.get('MOT_ZONES', 'parks/osm-check/mot-zones.json')
if os.path.exists(MOT):
    _mot = json.load(open(MOT, encoding='utf-8'))['zones']
    _mnew = _mdup = _mexc = 0
    for z in _mot:
        mpolys = [[(a, b) for a, b in rg] for rg in z['polys'] if len(rg) >= 4]
        if not mpolys:
            continue
        zc = _classify_zone(z['name'])
        if zc.get('exclude'):   # שכונת מגורים, מוסד חינוכי... — לא מקום עבודה
            _mexc += 1
            continue
        if zc.get('rename'):
            z = dict(z, name=zc['rename'])
        cla, clo = _cen([p for rg in mpolys for p in rg])
        cl = math.cos(math.radians(cla))
        # אותו שם עד 3 ק"מ = שתי תוכניות תב"ע של אותו אזור (כמו אדמות ק.ק.ל
        # חפ/598 + חפ/604 במפרץ חיפה) — מאוחדות לאזור אחד מרובה-פוליגונים
        same = None
        for pk in parks:
            if pk['name'] == z['name'] and math.hypot((pk['cen'][0] - cla) * 110540,
                                                      (pk['cen'][1] - clo) * 111320 * cl) < 3000:
                same = pk; break
        if same is not None:
            same['polys'].extend(mpolys)
            same['area'] = sum(poly_area_km2(p, same['cl']) for p in same['polys'])
            # אותו שם: אם האזור עצמו מהשכבה — הגבול כולו רשמי (1); אם המקור
            # OSM — הגאומטריה מעורבת ולכן רק אימות (2)
            same['mot'] = same.get('mot') or 2
            _mdup += 1
            continue
        # כפילות מול אזור שכבר קיים (OSM מאומת / הוספה ידנית): אם המרכז של אחד
        # נמצא בתוך הפוליגון של השני — זה אותו אזור. מסמנים אותו כמאושר ע"י
        # משרד התחבורה ולא מוסיפים אזור שני באותו מקום.
        dup = None
        for pk in parks:
            if math.hypot((pk['cen'][0] - cla) * 110540,
                          (pk['cen'][1] - clo) * 111320 * cl) > 3000:
                continue
            if (any(in_poly(cla, clo, q) for q in pk['polys'])
                    or any(in_poly(pk['cen'][0], pk['cen'][1], q) for q in mpolys)):
                dup = pk; break
        if dup is not None:
            # חפיפה גאוגרפית לאזור שכבר קיים (OSM/מאגר רשמי): האזור מאומת
            # מול השכבה, אבל השם והגבול נשארים של המקור — mot=2, לא 1,
            # כדי שהאתר לא יציג "הגבול מהשכבה הרשמית" על גבול שאינו משם
            if not dup.get('mot'):
                dup['mot'] = 2
            if not dup.get('name'):
                dup['name'] = z['name']; dup['noname'] = False
            if z.get('city') and not dup.get('mot_city'):
                dup['mot_city'] = z['city']
            _mdup += 1
            continue
        pk = {'name': z['name'], 'noname': False, 'polys': mpolys, 'cen': (cla, clo), 'cl': cl,
              'area': sum(poly_area_km2(p, cl) for p in mpolys), 'mot': 1}
        if z.get('ly') == 'hub':
            pk['hub'] = 1
        if z.get('city'):
            pk['mot_city'] = z['city']
        parks.append(pk)
        _mnew += 1
    print('משרד התחבורה: נוספו', _mnew, '| זוהו כאזור שכבר קיים', _mdup,
          '| סוננו (לא מקום עבודה)', _mexc, '| בקובץ', len(_mot))

# ---- מקור רשמי (משרד הכלכלה): השלמת חסרים + העשרה ----
# כל אזור רשמי מוצמד לפארק-OSM הקרוב (עד 1500מ'); אם אין קרוב — נוסף כפארק חדש
# עם הפוליגון הרשמי. כך משלימים אזורים (בעיקר בפריפריה) ש-OSM לא מיפה, ומצרפים
# נתוני עובדים/שטח/מחוז לכל אזור רשמי.
OFF_MATCH_M = 1500
if OFFICIAL and os.path.exists(OFFICIAL):
    official = json.load(open(OFFICIAL, encoding='utf-8'))
    added = enriched = 0
    for z in official:
        opolys = [[(a, b) for a, b in ring] for ring in z.get('polys', [])]
        if not opolys:
            continue
        allpts = [p for ring in opolys for p in ring]
        zla = sum(p[0] for p in allpts) / len(allpts)
        zlo = sum(p[1] for p in allpts) / len(allpts)
        zcl = math.cos(math.radians(zla))
        meta = {k: z.get(k) for k in ('district', 'avail', 'occ', 'cur_emp', 'fut_emp', 'open')}
        meta['oname'] = z.get('name')
        best = None
        for pk in parks:
            dd = math.hypot((pk['cen'][0] - zla) * 110540, (pk['cen'][1] - zlo) * 111320 * zcl)
            if best is None or dd < best[1]:
                best = (pk, dd)
        if best and best[1] <= OFF_MATCH_M:
            if 'official' not in best[0] or best[1] < best[0].get('_offd', 9e9):
                best[0]['official'] = meta
                best[0]['_offd'] = best[1]
                enriched += 1
        else:
            nm = z.get('name') or 'אזור תעשייה רשמי'
            npk = {'name': nm, 'noname': False, 'polys': opolys, 'cen': (zla, zlo),
                   'cl': zcl, 'official': meta, '_offd': 0}
            npk['area'] = sum(poly_area_km2(p, zcl) for p in opolys)
            parks.append(npk)
            added += 1
    print('מקור רשמי: הוצמדו/הועשרו', enriched, '| נוספו כחדשים', added)

# ---- אינדקס מרחבי גס לפארקים ----
def bbox(pk):
    las = [a for pts in pk['polys'] for a, b in pts]
    los = [b for pts in pk['polys'] for a, b in pts]
    return min(las), max(las), min(los), max(los)

# ---- סינון אזורים מקוננים (בקשת המשתמש) ----
# אזור קטן שרוב-שטחו בתוך אזור גדול יותר (למשל תחנת-כוח בתוך אזור-תעשייה, או
# פוליגון-כפול way+relation) לא יוצג — הגדול ממילא תופס את אותן תחנות (הכלה
# גאומטרית). מסירים את הקטן, ומעבירים אליו מטא רשמי אם לגדול חסר.
CONTAIN_FRAC = 0.6
def _frac_inside(small, big):
    # אחוז שטח הקטן (דגימת רשת ~60מ') שנמצא גם בתוך הגדול
    tot = hit = 0
    for pts in small['polys']:
        la1 = min(a for a, b in pts); la2 = max(a for a, b in pts)
        lo1 = min(b for a, b in pts); lo2 = max(b for a, b in pts)
        sla = 60 / 110540; slo = 60 / (111320 * small['cl'])
        la = la1
        while la <= la2:
            lo = lo1
            while lo <= lo2:
                if in_poly(la, lo, pts):
                    tot += 1
                    if any(in_poly(la, lo, q) for q in big['polys']):
                        hit += 1
                lo += slo
            la += sla
    return hit / tot if tot else 0.0

parks.sort(key=lambda p: -p['area'])   # גדולים קודם — קטן נבלע רק בגדול-שכבר-נשמר
_kept = []
_nested = 0
for pk in parks:
    pb = bbox(pk)
    host = None
    for big in _kept:
        bb = bbox(big)
        if pb[1] < bb[0] or pb[0] > bb[1] or pb[3] < bb[2] or pb[2] > bb[3]:
            continue   # אין חפיפת-תיבות — דילוג מהיר
        if _frac_inside(pk, big) >= CONTAIN_FRAC:
            host = big; break
    if host is not None:
        if 'official' in pk and 'official' not in host:   # לא לאבד העשרה רשמית
            host['official'] = pk['official']
        _nested += 1
    else:
        _kept.append(pk)
parks = _kept
print('סינון אזורים מקוננים: הוסרו', _nested, '| נשארו', len(parks))

# מצב "אזורים בלבד": פולט את תיבות-הגבול (מרופדות) של האזורים האמיתיים ועוצר.
# משמש את ה-workflow לשלב-שני — משיכת שבילי-הולכי-רגל מ-Overpass רק סביבם,
# כדי לכסות את כל האזורים (גם ללא-שם) בלי להתקע ב-around על אלפי פוליגונים.
if os.environ.get('EMIT_REGIONS'):
    REG_PAD = 0.0027   # ~300מ' ריפוד לתפיסת שבילים בשולי האזור
    regions = []
    for pk in parks:
        la1, la2, lo1, lo2 = bbox(pk)
        regions.append([round(la1 - REG_PAD, 5), round(lo1 - REG_PAD, 5),
                        round(la2 + REG_PAD, 5), round(lo2 + REG_PAD, 5)])
    out = os.environ.get('REGIONS_OUT', 'regions.json')
    json.dump(regions, open(out, 'w'), separators=(',', ':'))
    print('אזורים שנפלטו:', len(regions), '->', out)
    raise SystemExit(0)
CELL = 0.02   # ~2 ק"מ
grid = defaultdict(list)
for i, pk in enumerate(parks):
    la1, la2, lo1, lo2 = bbox(pk)
    pk['bbox'] = (la1, la2, lo1, lo2)
    pad = 0.006
    for gy in range(int((la1 - pad) / CELL), int((la2 + pad) / CELL) + 1):
        for gx in range(int((lo1 - pad) / CELL), int((lo2 + pad) / CELL) + 1):
            grid[(gy, gx)].append(i)

# ---- תחנות ----
def city_of(desc):
    i = (desc or '').find('עיר:')
    return desc[i + 4:].split('רציף:')[0].strip() if i >= 0 else ''

stop_hits = defaultdict(list)   # stop_id -> [(park_idx, tier, dist_m)]
stop_info = {}                  # stop_id -> (name, code, la, lo, city)
for r in csv.DictReader(open(STOPS, encoding='utf-8-sig')):
    if r.get('location_type', '0') not in ('', '0'):
        continue
    try:
        la = float(r['stop_lat']); lo = float(r['stop_lon'])
    except (ValueError, KeyError):
        continue
    for pi in grid.get((int(la / CELL), int(lo / CELL)), []):
        pk = parks[pi]
        la1, la2, lo1, lo2 = pk['bbox']
        pad = NEAR_M / 100000
        if not (la1 - pad < la < la2 + pad and lo1 - pad < lo < lo2 + pad):
            continue
        inside = any(in_poly(la, lo, pts) for pts in pk['polys'])
        d = 0 if inside else min(dist_to_poly_m(la, lo, pts, pk['cl']) for pts in pk['polys'])
        if not inside and d > NEAR_M:
            continue
        junction = bool(JUNCTION_RE.search(r.get('stop_name', '')))
        tier = 'near' if junction else ('in' if inside else ('gate' if d <= GATE_M else 'near'))
        stop_hits[r['stop_id']].append((pi, tier, int(d)))
        stop_info[r['stop_id']] = (r.get('stop_name', ''), r.get('stop_code', ''),
                                   round(la, 5), round(lo, 5), city_of(r.get('stop_desc', '')))
print('תחנות בטווח של פארק כלשהו:', len(stop_hits))

# ---- לוח שנה: שירותים תקפים היום, לפי יום ----
today = datetime.date.today()
svc_days = {}
if os.path.exists(CAL):
    for r in csv.DictReader(open(CAL, encoding='utf-8-sig')):
        try:
            d1 = datetime.datetime.strptime(r['start_date'], '%Y%m%d').date()
            d2 = datetime.datetime.strptime(r['end_date'], '%Y%m%d').date()
        except (ValueError, KeyError):
            continue
        if not (d1 <= today <= d2):
            continue
        svc_days[r['service_id']] = {k for k in
            ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')
            if r.get(k) == '1'}

# ---- קווים ----
trip_meta = {}   # trip_id -> (route_id, service_id)
for r in csv.DictReader(open(TRIPS, encoding='utf-8-sig')):
    trip_meta[r['trip_id']] = (r['route_id'], r.get('service_id', ''))
route_meta = {}
for r in csv.DictReader(open(ROUTES, encoding='utf-8-sig')):
    short = r.get('route_short_name', '')
    if not short:   # לרכבות אין מספר קו — מתייגים לפי הסוג
        rt = r.get('route_type', '3')
        short = 'רכבת' if rt == '2' else ('רק"ל' if rt in ('0', '1') else '?')
    mkt = (r.get('route_desc') or '').split('-')[0].lstrip('0')   # מק"ט = זהות הקו
    route_meta[r['route_id']] = (short, r.get('route_long_name', ''), mkt)

# ---- stop_times: הגעות בתחנות הרלוונטיות בלבד ----
deps = defaultdict(list)   # (stop_id, route_id, daygroup) -> [minutes]
DAYGROUPS = (('wd', 'tuesday'), ('fr', 'friday'), ('sa', 'saturday'))
seen_active = set()
for r in csv.DictReader(open(STOPTIMES, encoding='utf-8-sig')):
    sid = r.get('stop_id')
    if sid not in stop_hits:
        continue
    seen_active.add(sid)
    tm = trip_meta.get(r.get('trip_id'))
    if not tm:
        continue
    rid, svc = tm
    days = svc_days.get(svc)
    if days is None:
        days = {'sunday', 'monday', 'tuesday', 'wednesday', 'thursday'}
    t = (r.get('departure_time') or r.get('arrival_time') or '').strip()
    m = re.match(r'^(\d+):(\d\d)', t)
    if not m:
        continue
    mins = (int(m.group(1)) % 24) * 60 + int(m.group(2))
    for gk, day in DAYGROUPS:
        if day in days:
            deps[(sid, rid, gk)].append(mins)

def hhmm(m): return f'{m // 60:02d}:{m % 60:02d}'

deps_by_sid = defaultdict(dict)   # sid -> {(rid,gk): [minutes]}
for (sid, rid, gk), mins in deps.items():
    deps_by_sid[sid][(rid, gk)] = mins

# ---- הליכה אמיתית (OSRM foot): סיווג-מחדש לפי זמן-הליכה בפועל ----
# במקום מרחק אווירי — כמה דקות באמת צריך ללכת מהתחנה לגבול האזור (עוקף מחסומים).
# ספים: עד WALK_OK_SEC=נגיש ('gate') · עד WALK_FAR_SEC=רחוק ('near') · מעבר=חסום.
# תחנה שה-OSRM לא החזיר לה מסלול נשארת בסיווג הגאומטרי (ספק) עם wm/wt=None.
# best-effort ומוגבל-זמן — כשל/מגבלת-קצב נופלים חזרה לגאומטרי, לא שוברים בנייה.
OSRM_URL = os.environ.get('OSRM_URL', '')
WALK_OK_SEC, WALK_FAR_SEC = 300, 600   # 5 / 10 דקות הליכה
OSRM_BUDGET = int(os.environ.get('OSRM_BUDGET', '900'))   # תקציב-זמן שניות לכל הניתוב
OSRM_SLEEP = float(os.environ.get('OSRM_SLEEP', '0.4'))   # השהיה בין קריאות (קצב שרת ציבורי; מקומי=0)

def _boundary_samples(pk, k=8):
    # K נקודות פרוסות על גבול האזור — יעדי-ניתוב משותפים לכל תחנות האזור.
    # כך מטריצת ה-OSRM היא N×K במקום N×N (פי ~6 פחות חישוב), ותחנה בוחרת
    # את נקודת-הגבול הקרובה ביותר בהליכה.
    pts = [p for ring in pk['polys'] for p in ring]
    if len(pts) <= k:
        return pts
    step = len(pts) / k
    return [pts[int(i * step)] for i in range(k)]

def _osrm_walk(origins, bdests, center):
    # קריאה אחת מחזירה לכל origin שני מדדים: עד הקצה הקרוב (min על bdests) ועד
    # מרכז האזור (center, יעד נוסף). מחזיר (edge_m, edge_s, center_m, center_s).
    dests = bdests + [center]
    coords = origins + dests
    no, nb, nd = len(origins), len(bdests), len(dests)
    locs = ';'.join('%f,%f' % (lo, la) for la, lo in coords)
    src = ';'.join(str(i) for i in range(no))
    dst = ';'.join(str(i) for i in range(no, no + nd))
    url = '%s/table/v1/foot/%s?sources=%s&destinations=%s&annotations=duration,distance' % (OSRM_URL, locs, src, dst)
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-parks/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.load(r)
    dist = j.get('distances') or []
    dur = j.get('durations') or []
    out = []
    for i in range(no):
        drow = dur[i] if i < len(dur) else []
        mrow = dist[i] if i < len(dist) else []
        best = None   # הקצה הקרוב: (שניות, מטרים) מינימלי על bdests
        for jx in range(nb):
            s = drow[jx] if jx < len(drow) else None
            if s is None:
                continue
            if best is None or s < best[0]:
                best = (s, mrow[jx] if jx < len(mrow) else None)
        em, es = (best[1], best[0]) if best else (None, None)
        cs = drow[nb] if nb < len(drow) else None       # מרכז = היעד האחרון
        cm = mrow[nb] if nb < len(mrow) else None
        out.append((int(em) if em is not None else None, int(es) if es is not None else None,
                    int(cm) if cm is not None else None, int(cs) if cs is not None else None))
    return out

walk = {}   # (pi, sid) -> (edge_m, edge_s, center_m, center_s) או None
if OSRM_URL:
    # cache מתמיד: השרת הציבורי איטי מכדי לנתב את כל האזורים בריצה אחת, אז
    # שומרים תוצאות בין ריצות. מפתח = תחנה + מרכז-אזור מעוגל (יציב בין ריצות).
    # כל ריצה משתמשת מחדש בקיים ומנתבת רק חדשים — הכיסוי גדל עד מלא תוך כמה ריצות.
    CACHE_IN = os.environ.get('WALK_CACHE_IN', '')
    cache = {}
    if CACHE_IN and os.path.exists(CACHE_IN):
        try:
            cache = json.load(open(CACHE_IN))
        except Exception:
            cache = {}
    newcache = {}
    def _ckey(sid, pk):
        return '%s|%.3f|%.3f' % (sid, pk['cen'][0], pk['cen'][1])

    park_cands = defaultdict(list)   # pi -> [(sid, la, lo)]
    for sid, hits in stop_hits.items():
        if sid not in seen_active:
            continue
        _, _, sla, slo, _ = stop_info[sid]
        for (pi, tier, d) in hits:
            if tier != 'in':
                park_cands[pi].append((sid, sla, slo))
    t0 = time.monotonic()
    routed = failed = skipped = fromcache = 0
    for pi, cands in park_cands.items():
        pk = parks[pi]
        todo = []
        for (sid, sla, slo) in cands:   # קודם מ-cache, מה שחסר -> לניתוב
            k = _ckey(sid, pk)
            v = cache.get(k)
            if v and len(v) == 4:        # פורמט 4-ערכי בלבד (ישן -> ננתב מחדש)
                walk[(pi, sid)] = tuple(v)
                newcache[k] = v
                fromcache += 1
            else:
                todo.append((sid, sla, slo))
        if not todo:
            continue
        if time.monotonic() - t0 > OSRM_BUDGET:
            skipped += len(todo)
            continue
        dests = _boundary_samples(pk, 8)   # יעדי-גבול משותפים; +מרכז האזור בפנים
        center = (pk['cen'][0], pk['cen'][1])
        for c0 in range(0, len(todo), 80):   # 80 מקורות + 9 יעדים ≤ מגבלת הטבלה
            chunk = todo[c0:c0 + 80]
            origins = [(sla, slo) for _, sla, slo in chunk]
            try:
                res = _osrm_walk(origins, dests, center)
                routed += 1
            except Exception:
                res = [(None, None, None, None)] * len(chunk)
                failed += 1
            for (sid, _, _), v in zip(chunk, res):
                walk[(pi, sid)] = v
                if v and v[1] is not None:   # שומרים רק תוצאה תקינה (כשל -> ננסה שוב)
                    newcache[_ckey(sid, pk)] = list(v)
            if OSRM_SLEEP:
                time.sleep(OSRM_SLEEP)   # קצב-שרת ציבורי; שרת מקומי -> 0
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump(newcache, open(os.path.join(OUTDIR, 'walk-cache.json'), 'w'), separators=(',', ':'))
    print('OSRM: נותבו', routed, '| מ-cache', fromcache, '| נכשלו', failed,
          '| זוגות', len(walk), '| דולגו (תקציב)', skipped, '| cache', len(newcache))

def _walk_tier(geo_tier, sec):
    # סיווג לפי זמן-הליכה אמיתי — כולל צמתים: צומת ≤5 דק' הליכה נגיש ונספר.
    if geo_tier == 'in':
        return 'in'
    if sec is None:
        return geo_tier            # OSRM לא זמין/נכשל — ספק, נשאר גאומטרי
    if sec <= WALK_OK_SEC:
        return 'gate'
    if sec <= WALK_FAR_SEC:
        return 'near'
    return 'blocked'

# סיווג-מחדש: כל hit -> (pi, d, tc, te, cm, cmin, em, emin)
#   tc/cm/cmin = מרכז (ברירת-מחדל) · te/em/emin = קצה (כניסה). כשאין OSRM שניהם גאומטריים.
def _mins(sec):
    return round(sec / 60) if sec is not None else None
for sid, hits in stop_hits.items():
    nh = []
    for (pi, tier, d) in hits:
        v = walk.get((pi, sid))
        em, es, cm, cs = v if (v and len(v) == 4) else (None, None, None, None)
        nh.append((pi, d, _walk_tier(tier, cs), _walk_tier(tier, es),
                   cm, _mins(cs), em, _mins(es)))
    stop_hits[sid] = nh

# ---- הרכבת פלט לכל פארק ----
os.makedirs(OUTDIR, exist_ok=True)
TIER_RANK = {'in': 0, 'gate': 1, 'near': 2, 'blocked': 3}
w1, w2 = [int(x[:2]) * 60 + int(x[3:]) for x in GAP_WIN]

# אינדקס מרחבי לשבילים (פעם אחת) — בלעדיו כל פארק סורק את כל עשרות-אלפי
# השבילים (O(פארקים×שבילים)). עם האינדקס כל פארק לוקח רק שבילים באזורו.
FOOT_CELL = 0.02
foot_grid = defaultdict(set)
for si, seg in enumerate(foot):
    for a, b in seg:
        foot_grid[(int(a / FOOT_CELL), int(b / FOOT_CELL))].add(si)

def _foot_near(la1_p, la2_p, lo1_p, lo2_p, pad=0.008):
    si = set()
    for gy in range(int((la1_p - pad) / FOOT_CELL), int((la2_p + pad) / FOOT_CELL) + 1):
        for gx in range(int((lo1_p - pad) / FOOT_CELL), int((lo2_p + pad) / FOOT_CELL) + 1):
            si |= foot_grid.get((gy, gx), set())
    return si

def build_lines(stops_here, tk):
    # בונה את רשימת הקווים והספירות לפי מפתח-tier נתון: 'tc' (מרכז) או 'te' (קצה).
    # תחנה 'blocked' באותו מצב אינה משרתת — לא נספרת.
    best_stop = {}
    seen_rids = set()
    for s in stops_here:
        if s[tk] == 'blocked':
            continue
        for (rid, gk) in deps_by_sid.get(s['sid'], ()):
            seen_rids.add(rid)
            cur = best_stop.get(rid)
            rank = (TIER_RANK[s[tk]], s['d'])
            if cur is None or rank < cur[0]:
                best_stop[rid] = (rank, s)
    lines = []
    for rid in seen_rids:
        _, s = best_stop[rid]
        num, longnm, mkt = route_meta.get(rid, ('?', '', ''))
        dest = longnm.split('<->')[-1].split('-')[0].strip() if '<->' in longnm else longnm[:30]
        rec = {'num': num, 'dest': dest, 'stop': s['n'], 'code': s['c'], 't': s[tk], 'mk': mkt or num}
        for gk, _ in DAYGROUPS:
            mins = sorted(set(deps.get((s['sid'], rid, gk), [])))
            rec[gk] = [hhmm(m) for m in mins]
            if gk == 'wd':
                gaps = []
                win = [m for m in mins if w1 <= m <= w2]
                for a, b in zip(win, win[1:]):
                    if b - a >= GAP_MIN:
                        gaps.append([hhmm(a), hhmm(b), b - a])
                if mins and win and win[0] - w1 >= GAP_MIN:
                    gaps.insert(0, [GAP_WIN[0], hhmm(win[0]), win[0] - w1])
                rec['gaps'] = gaps
        if any(rec[gk] for gk, _ in DAYGROUPS):
            lines.append(rec)
    lines.sort(key=lambda L: (TIER_RANK[L['t']],
                              int(re.match(r'\d+', L['num']).group(0)) if re.match(r'\d+', L['num']) else 999))
    # ספירה לפי קו אמיתי (מק"ט) ולא לפי כיוון/חלופה — שני הכיוונים של אותו
    # קו נספרים פעם אחת, בדרגה הטובה מביניהם (בקשת המשתמשים: בלי ניפוח)
    best_line = {}
    peak_best = {}   # רק קווים עם יציאה בשעות שיא של יום עבודה (06–09, 15–19)
    is_peak = lambda t: ('06:00' <= t < '09:00') or ('15:00' <= t < '19:00')
    for L in lines:
        r0 = TIER_RANK[L['t']]
        k0 = L['mk']
        if k0 not in best_line or r0 < best_line[k0]:
            best_line[k0] = r0
        if any(is_peak(t) for t in (L.get('wd') or [])):
            if k0 not in peak_best or r0 < peak_best[k0]:
                peak_best[k0] = r0
    counts = (sum(1 for v in best_line.values() if v == TIER_RANK['in']),
              sum(1 for v in best_line.values() if v == TIER_RANK['gate']),
              sum(1 for v in best_line.values() if v == TIER_RANK['near']))
    peaks = (sum(1 for v in peak_best.values() if v == TIER_RANK['in']),
             sum(1 for v in peak_best.values() if v == TIER_RANK['gate']))
    # סך יציאות ביום חול (לו"ז): כל כיוון/חלופה נספר פעם אחת — נפח השירות בפועל
    deps_cnt = (sum(len(L.get('wd') or []) for L in lines if L['t'] == 'in'),
                sum(len(L.get('wd') or []) for L in lines if L['t'] == 'gate'))
    return lines, counts, peaks, deps_cnt

index = []
out_i = 0
_noname_ser = {}
for pi, pk in enumerate(parks):
    stops_here = []
    for sid, hits in stop_hits.items():
        if sid not in seen_active:
            continue
        for hit in hits:
            if hit[0] == pi:
                hpi, d, tc, te, cm, cmin, em, emin = hit
                nm, code, la, lo, city = stop_info[sid]
                stops_here.append({'sid': sid, 'n': nm, 'c': code, 'la': la, 'lo': lo, 'd': d, 'city': city,
                                   'tc': tc, 'te': te, 'wmc': cm, 'wtc': cmin, 'wme': em, 'wte': emin})
    # קווים+ספירות פעמיים: מרכז (ברירת-מחדל) וקצה (כניסה)
    lines_c, (lic, lgc, lnc), (pki, pkg), (dwi, dwg) = build_lines(stops_here, 'tc')
    lines_e, (lie, lge, lne), (pkie, pkge), (dwie, dwge) = build_lines(stops_here, 'te')
    # כיסוי שטח: דגימת רשת בתוך הפוליגונים מול footways בטווח 100מ'. נספרים רק
    # שבילים ש**נקודה מהם בתוך אזור התעשייה** — לא מדרכות של כבישים גובלים בחוץ.
    # כל שביל נשמר עם תיבת-גבול מטרית לדחייה-מהירה.
    cl = pk['cl']
    foot_segs = []   # (segment_xy, bx1, bx2, by1, by2)
    la1_p = min(a for pts in pk['polys'] for a, b in pts)
    la2_p = max(a for pts in pk['polys'] for a, b in pts)
    lo1_p = min(b for pts in pk['polys'] for a, b in pts)
    lo2_p = max(b for pts in pk['polys'] for a, b in pts)
    for si in _foot_near(la1_p, la2_p, lo1_p, lo2_p):
        seg = foot[si]
        if len(seg) > 1 and any(in_poly(a, b, pts) for a, b in seg for pts in pk['polys']):
            sxy = [xy(a, b, cl) for a, b in seg]
            bx1 = min(x for x, y in sxy); bx2 = max(x for x, y in sxy)
            by1 = min(y for x, y in sxy); by2 = max(y for x, y in sxy)
            foot_segs.append((sxy, bx1, bx2, by1, by2))
    total = hitn = 0
    for pts in pk['polys']:
        la1 = min(a for a, b in pts); la2 = max(a for a, b in pts)
        lo1 = min(b for a, b in pts); lo2 = max(b for a, b in pts)
        step_la = 60 / 110540; step_lo = 60 / (111320 * cl)
        la_ = la1
        while la_ <= la2:
            lo_ = lo1
            while lo_ <= lo2:
                if in_poly(la_, lo_, pts):
                    total += 1
                    px, py = xy(la_, lo_, cl)
                    for sxy, bx1, bx2, by1, by2 in foot_segs:
                        if px < bx1 - 100 or px > bx2 + 100 or py < by1 - 100 or py > by2 + 100:
                            continue   # דחייה-מהירה: הנקודה רחוקה מתיבת-השביל
                        if min(seg_dist((px, py), sxy[i], sxy[i+1]) for i in range(len(sxy)-1)) <= 100:
                            hitn += 1
                            break
                lo_ += step_lo
            la_ += step_la
    cov = round(hitn / total, 3) if total else 0.0
    # שבילי הולכי-רגל שבתוך האזור בלבד (נקודה מהם בתוך הפוליגון)
    la1, la2, lo1, lo2 = pk['bbox']
    fw = []
    flen = 0.0
    for si in _foot_near(la1, la2, lo1, lo2):
        seg = foot[si]
        if not any(in_poly(a, b, pts) for a, b in seg for pts in pk['polys']):
            continue
        fw.append([[round(a, 5), round(b, 5)] for a, b in seg])
        for (a1, b1), (a2, b2) in zip(seg, seg[1:]):
            flen += math.hypot((a2 - a1) * 110540, (b2 - b1) * 111320 * cl)
    city = ''
    if stops_here:
        cc = defaultdict(int)
        for s in stops_here:
            if s['city']:
                cc[s['city']] += 1
        if cc:
            city = max(cc, key=cc.get)
    if not city:
        city = pk.get('mot_city', '')   # אזורי משרד התחבורה בלי תחנות — העיר מהרשימה
    # מחוץ לישראל: ה-bbox של Overpass תופס גם ירדן/לבנון/סיני. אזור נשאר רק
    # אם שמו עברי או שיש לו תחנת GTFS ישראלית בטווח.
    if not re.search(r'[א-ת]', pk['name']) and not stops_here:
        continue
    if pk['noname']:
        base = ('אזור תעשייה — ' + city) if city else 'אזור תעשייה ללא שם'
        _noname_ser[base] = _noname_ser.get(base, 0) + 1
        pk['name'] = base + (f" ({_noname_ser[base]})" if _noname_ser[base] > 1 else '')
    # תיוג סוג + סינון (tools/zone_type.py) — גם לאזורים שהגיעו מ-OSM,
    # למשל השמות הערביים של רהט ועידן הנגב שמקבלים כאן שם עברי
    zc = _classify_zone(pk['name'])
    if zc.get('exclude'):
        continue
    if zc.get('rename'):
        pk['name'] = zc['rename']
    zt = zc['zt']
    if zt == 'ind' and pk.get('hub'):
        zt = 'emp'   # מוקד מהשכבה בלי כלל-שם משלו — תעסוקה, לא תעשייה
    # תחנה שחסומה בשני המצבים (מרכז וקצה) לא תוצג כלל; אחרת נשמרת עם שני
    # ה-tiers (t=מרכז ברירת-מחדל, te=קצה) ושני הזמנים, וה-frontend מחליף לפי המתג.
    outstops = [{'n': s['n'], 'c': s['c'], 'la': s['la'], 'lo': s['lo'], 'd': s['d'],
                 't': s['tc'], 'te': s['te'], 'wt': s['wtc'], 'wm': s['wmc'],
                 'wte': s['wte'], 'wme': s['wme']}
                for s in stops_here if not (s['tc'] == 'blocked' and s['te'] == 'blocked')]
    svc_sc = service_scores(pk)
    rec = {'name': pk['name'], 'city': city, 'area': round(pk['area'], 2),
           'polys': [[[round(a, 5), round(b, 5)] for a, b in pts] for pts in pk['polys']],
           'stops': outstops,
           'lines': lines_c, 'linesE': lines_e, 'cov400': cov,
           'foot': fw, 'footlen': int(flen), 'zt': zt,
           'gen': today.isoformat()}
    if svc_sc:
        rec['svc'] = svc_sc          # מדדי משרד התחבורה לאזור הסטטיסטי
        rec['svcmeta'] = _svc_meta
    off = pk.get('official')
    if off:
        rec['official'] = {k: off.get(k) for k in ('oname', 'district', 'avail', 'occ', 'cur_emp', 'fut_emp')}
    fn = f'p{out_i}.json'
    json.dump(rec, open(os.path.join(OUTDIR, fn), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    index.append({'f': fn, 'name': pk['name'], 'city': city, 'area': rec['area'],
                  'lines': len(lines_c),
                  'li': lic, 'lg': lgc, 'ln': lnc,             # מרכז (ברירת-מחדל)
                  'lie': lie, 'lge': lge, 'lne': lne,          # קצה (כניסה)
                  'pki': pki, 'pkg': pkg,                      # קווים בשעות שיא (בפנים/שער)
                  'pkie': pkie, 'pkge': pkge,
                  'dwi': dwi, 'dwg': dwg,                      # יציאות ביום חול (בפנים/שער)
                  'dwie': dwie, 'dwge': dwge,
                  'in': sum(1 for s in stops_here if s['tc'] == 'in'),
                  'cov': cov, 'la': round(pk['cen'][0], 4), 'lo': round(pk['cen'][1], 4),
                  'off': 1 if off else 0,
                  'ly': 'hub' if pk.get('hub') else 'ind',
                  'zt': zt,
                  'mt': pk.get('mot') or 0,   # 1=הגבול מהשכבה הרשמית · 2=אומת מולה, הגבול מ-OSM
                  'st': built_status(pk['cen']),
                  'sf': (svc_sc or {}).get('fs'),     # ציון משוקלל רשמי
                  'sr': (svc_sc or {}).get('re'),     # אמינות רשמית
                  'sa': (svc_sc or {}).get('av')})    # זמינות רשמית
    out_i += 1
index.sort(key=lambda x: (x['city'], x['name']))
json.dump(index, open(os.path.join(OUTDIR, 'parks.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
print('פארקים שנכתבו:', out_i)
print('מהם עם קווים:', sum(1 for x in index if x['lines']),
      '| בלי שירות בכלל:', sum(1 for x in index if not x['lines']))
