# -*- coding: utf-8 -*-
# "הקו בזמן" — מילוי-לאחור שלב ב': רצפי תחנות היסטוריים לגרסאות-עבר
# מארכיון אופן באס (הסדנא לידע ציבורי, Stride API).
#
# לכל גרסת-עבר בקובצי הקווים שמקורה בארכיון (src=ob) ואין לה תחנות,
# נשלף רצף התחנות של נסיעה אחת מאותו תאריך: route -> ride -> ride_stops
# -> פרטי תחנות. אין גאומטריה בארכיון — האתר מציג את הרצף כקו מקורב.
#
# בטוח להרצה חוזרת: גרסה שכבר מולאה מדולגת (הנתונים עצמם הם ה-checkpoint),
# וכישלונות קבועים נרשמים ב-backfill-stops-skip.json כדי לא לנסות שוב.
#
# קלט: OUTDIR, PAUSE, MAX_MIN (תקרת דקות לריצה), MAX_TARGETS (0=בלי תקרה)
import json, os, sys, time, datetime, urllib.request, urllib.parse

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.35'))
MAX_MIN = float(os.environ.get('MAX_MIN', '230'))
MAX_TARGETS = int(os.environ.get('MAX_TARGETS', '0') or '0')
FILL_KINDS = {'new', 'dest', 'renum', 'operator'}
# גרסת removed מתמלאת מהימים שלפני הביטול (בתאריך עצמו הווריאנט כבר איננו) —
# רק כשאין בקובץ אף רשימת תחנות אחרת, אחרת לקו המבוטל אין שום רצף באתר
# (סיפורי מכונת הדיוק יכולים להיות אירוע ביטול יחיד; קו 1 נס ציונה)
T0 = time.time()

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (stops backfill; polite)'})
            with urllib.request.urlopen(req, timeout=90) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(8 * (attempt + 1))
    print(f'  api failed: {url} :: {last}', file=sys.stderr)
    return None

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')

skip_p = f'{OUTDIR}/backfill-stops-skip.json'
skip = jload(skip_p, {})

def seq_for(rd, d):
    """רצף תחנות של וריאנט rd בתאריך d, או None + סיבה.
    שלוש קריאות בלבד: route -> ride -> ride_stops. רשומות ride_stops כוללות
    את פרטי התחנה מוצמדים (gtfs_stop__code/name/lat/lon) — אומת מול ה-API,
    כולל אימות שהסינון לפי gtfs_route_id באמת מכובד."""
    parts = rd.split('-', 2)
    if len(parts) != 3: return None, 'rd לא תקין'
    mkt, dr, alt = parts
    routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt,
                 route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes:
        routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt.zfill(5),
                     route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes:
        return None, 'route לא נמצא בארכיון'
    rid = routes[0]['id']
    rides = api('/gtfs_rides/list', gtfs_route_id=rid, limit=1,
                start_time_from=f'{d}T00:00:00+02:00', start_time_to=f'{d}T23:59:00+02:00')
    if not isinstance(rides, list) or not rides:
        return None, 'אין נסיעות בתאריך'
    if rides[0].get('gtfs_route_id') != rid:
        return None, 'הסינון לפי route לא כובד'   # הגנה מהתעלמות שקטה מפרמטר
    ride_id = rides[0]['id']
    rs = api('/gtfs_ride_stops/list', gtfs_ride_ids=ride_id, limit=300)
    if not isinstance(rs, list) or len(rs) < 2:
        return None, 'אין רצף תחנות לנסיעה'
    rs = [r for r in rs if r.get('gtfs_ride_id') == ride_id]
    rs.sort(key=lambda r: r.get('stop_sequence') or 0)
    seq = []
    for r in rs:
        try:
            seq.append([str(r.get('gtfs_stop__code') or ''), r.get('gtfs_stop__name') or '',
                        round(float(r['gtfs_stop__lat']), 5), round(float(r['gtfs_stop__lon']), 5)])
        except Exception:
            pass
    if len(seq) < max(2, len(rs) // 2):
        return None, 'פרטי תחנות חסרים'
    return seq, ''

def seq_before(rd, d):
    """לגרסת ביטול: מנסים ימים אחורה — מדלגים על שבתות/חגים בקווי ימי-חול."""
    base = datetime.date.fromisoformat(d)
    last_why = 'אין נסיעות לפני הביטול'
    for back in (1, 2, 3, 5, 7):
        dd = (base - datetime.timedelta(days=back)).isoformat()
        seq, why = seq_for(rd, dd)
        if seq is not None:
            return seq, ''
        last_why = why
    return None, last_why

# ---- איסוף מטרות: גרסאות ob בלי תחנות. סדר: קודם קווים מבוטלים בלי שום
# רשימת תחנות (החור הבולט למשתמש), ובראשם 32001/94001 (בקשת שלמה) ----
targets = []
for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
    if not fn.endswith('.json'): continue
    lf = jload(f'{OUTDIR}/lines/{fn}', {})
    rd = lf.get('rd', '')
    vs = lf.get('versions', [])
    has_any = any(v.get('stops') or v.get('shp') for v in vs)
    for v in vs:
        if v.get('src') != 'ob' or v.get('stops') or v.get('shp'): continue
        if v.get('k') in FILL_KINDS: pri = 1
        elif v.get('k') == 'removed' and not has_any: pri = 0
        else: continue
        if rd.split('-')[0] in ('32001', '94001'): pri = -1
        k = f"{rd}|{v['d']}"
        if k not in skip:
            targets.append((pri, fn, rd, v['d'], v['k']))
targets.sort()
targets = [t[1:] for t in targets]
print('גרסאות-עבר שממתינות לרצף תחנות:', len(targets))
if MAX_TARGETS: targets = targets[:MAX_TARGETS]

done = fails = 0
for fn, rd, d, kind in targets:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('הגעתי לתקרת הזמן — נמשיך בריצה הבאה'); break
    seq, why = seq_before(rd, d) if kind == 'removed' else seq_for(rd, d)
    p = f'{OUTDIR}/lines/{fn}'
    if seq is None:
        skip[f'{rd}|{d}'] = why
        fails += 1
    else:
        lf = jload(p, {})
        for v in lf.get('versions', []):
            if v.get('d') == d and v.get('src') == 'ob' and not v.get('stops'):
                v['stops'] = seq
        json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        done += 1
    if (done + fails) % 100 == 0:
        json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'{done+fails}/{len(targets)} | מולאו {done} | דילוגים {fails} | {int((time.time()-T0)/60)} דק׳')

json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'סיום ריצה: מולאו {done} | נכשלו/דולגו {fails} | נותרו ~{len(targets)-done-fails}')
