# -*- coding: utf-8 -*-
# "הקו בזמן" — עוגני ארכיון לקווים "שקטים": וריאנט שלא היה לו אף אירוע
# רישום מאז 2022 לא קיבל אף רשומת ארכיון, ולכן שינוי תחנות אצלו נעלם
# לגמרי. כאן שולפים לכל קו כזה צילום אחד ("עוגן") מהנקודה המוקדמת ביותר
# שהארכיון מכסה. ההשוואה מול היום (enrich_stop_diffs) ותיארוך השינוי
# (backfill_stop_dates) קורים אחר כך בשרשרת הקיימת.
import json, os, sys, time, datetime, urllib.request, urllib.parse

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.35'))
MAX_MIN = float(os.environ.get('MAX_MIN', '35'))
T0 = time.time()

# תאריכי ניסיון לעוגן, מהמוקדם למאוחר (תחילת 2022 ריקה בארכיון).
# ימי חול בלבד — קווים של ימי חול לא רשומים בקובצי סוף השבוע (לקח מקו 1א)
ANCHOR_DATES = ['2022-03-01', '2022-06-01', '2022-10-03', '2023-03-01',
                '2023-09-04', '2024-06-03', '2025-06-02']

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (quiet-line anchors; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(8 * (attempt + 1))
    return None

def seq_for(rd, d):
    parts = rd.split('-', 2)
    if len(parts) != 3: return None
    mkt, dr, alt = parts
    routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt,
                 route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes:
        routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt.zfill(5),
                     route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes: return None
    rid = routes[0]['id']
    rides = api('/gtfs_rides/list', gtfs_route_id=rid, limit=1,
                start_time_from=f'{d}T00:00:00+02:00', start_time_to=f'{d}T23:59:00+02:00')
    if not isinstance(rides, list) or not rides: return None
    if rides[0].get('gtfs_route_id') != rid: return None
    ride_id = rides[0]['id']
    rs = api('/gtfs_ride_stops/list', gtfs_ride_ids=ride_id, limit=300)
    if not isinstance(rs, list) or len(rs) < 2: return None
    rs = [r for r in rs if r.get('gtfs_ride_id') == ride_id]
    rs.sort(key=lambda r: r.get('stop_sequence') or 0)
    seq = []
    for r in rs:
        try:
            seq.append([str(r.get('gtfs_stop__code') or ''), r.get('gtfs_stop__name') or '',
                        round(float(r['gtfs_stop__lat']), 5), round(float(r['gtfs_stop__lon']), 5)])
        except Exception:
            pass
    return seq if len(seq) >= max(2, len(rs) // 2) else None

def seq_near(rd, d):
    base = datetime.date.fromisoformat(d)
    for off in (0, 2, 4):
        s = seq_for(rd, (base + datetime.timedelta(days=off)).isoformat())
        if s: return s, (base + datetime.timedelta(days=off)).isoformat()
    return None, None

skip_p = f'{OUTDIR}/backfill-anchors-skip.json'
try: skip = json.load(open(skip_p, encoding='utf-8'))
except Exception: skip = {}

targets = []   # (עדיפות, קובץ, תאריך-גבול לעוגן או None)
for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
    if not fn.endswith('.json'): continue
    try: lf = json.load(open(f'{OUTDIR}/lines/{fn}', encoding='utf-8'))
    except Exception: continue
    rd = lf.get('rd', '')
    if not rd or rd in skip: continue
    vs = lf.get('versions', [])
    if not vs: continue
    if any(v.get('src') == 'ob' for v in vs):
        # יש רשומות ארכיון — אבל אם הראשונה שבהן היא שינוי (יעד/מפעיל/מספר),
        # הקו היה קיים עוד קודם וצריך עוגן מלפניה, אחרת השינויים בתחנות
        # שבוצעו באירוע הראשון בלתי-נראים (קו 49010: שינוי יעד 12.2024)
        f0 = vs[0]
        if f0.get('src') == 'ob' and f0.get('k') in ('dest', 'operator', 'renum'):
            targets.append((0, fn, f0['d']))
    else:
        targets.append((1, fn, None))   # קו שקט — עוגן מוקדם ככל האפשר
targets.sort()
n_pre = sum(1 for t in targets if t[0] == 0)
print(f'ממתינים לעוגן: {len(targets)} (מהם {n_pre} עוגני לפני-אירוע-ראשון, {len(targets)-n_pre} קווים שקטים)')

n_ok = n_absent = 0
for _, fn, limit in targets:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    p = f'{OUTDIR}/lines/{fn}'
    lf = json.load(open(p, encoding='utf-8'))
    rd = lf['rd']
    if limit:
        # העוגן חייב להיות מוקדם מהאירוע הראשון (עם שוליים לדגימות הסמוכות)
        lim = datetime.date.fromisoformat(limit)
        cands = [d for d in ANCHOR_DATES if datetime.date.fromisoformat(d) <= lim - datetime.timedelta(days=14)]
        cands.append((lim - datetime.timedelta(days=45)).isoformat())
    else:
        cands = ANCHOR_DATES
    seq = found_d = None
    for d in cands:
        seq, found_d = seq_near(rd, d)
        if seq: break
    if not seq:
        skip[rd] = 'לא נמצא בארכיון באף תאריך ניסיון'
        n_absent += 1
        continue
    lf['versions'].insert(0, {'d': found_d, 'k': 'snapshot', 'src': 'ob', 'stops': seq,
                              'note': 'צילום עוגן מהארכיון — נקודת ההשוואה המוקדמת ביותר הזמינה'})
    lf['versions'].sort(key=lambda x: x['d'])
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n_ok += 1
    if (n_ok + n_absent) % 50 == 0:
        json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'{n_ok+n_absent}/{len(targets)} | עוגנים {n_ok} | לא בארכיון {n_absent} | {int((time.time()-T0)/60)} דק׳')

json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'סיום: {n_ok} עוגנים נוספו | {n_absent} לא נמצאו בארכיון')
