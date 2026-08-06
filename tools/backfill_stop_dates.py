# -*- coding: utf-8 -*-
# "הקו בזמן" — איתור תאריך לשינויי תחנות שהתגלו בין שתי רשומות רחוקות.
# במקום לדגום כל קו כל שבוע מאז 2022 (מיליוני קריאות), חיפוש בינארי
# בארכיון אופן באס רק בפערים שידוע שמשהו השתנה בהם: דוגמים את אמצע
# הפער, בודקים אם השינוי כבר קרה, וחוצים שוב — עד דיוק של שבוע.
# פער של 3 שנים נפתר ב~8 דגימות. השינוי המתוארך נהפך לאירוע עצמאי
# בציר הזמן (stops / stops-add / stops-del) והדיף יורד מרשומת העוגן.
import json, os, sys, time, datetime, urllib.request, urllib.parse
import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from compact_lines import materialize

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.35'))
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
MAX_GAPS = int(os.environ.get('MAX_GAPS', '0'))   # 0 = בלי תקרה (מלבד הזמן)
T0 = time.time()

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (stop-change dating; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(8 * (attempt + 1))
    return None

def seq_for(rd, d):
    """רצף תחנות של rd בתאריך d, או None. אותם אימותים כמו בשלב ב' —
    השרת מתעלם בשקט מפרמטרים לא מוכרים, אז כל תשובה נבדקת."""
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
    """דגימה עם נסיונות בימים סמוכים — יום בלי נסיעות (שבת/חג) לא מפיל."""
    base = datetime.date.fromisoformat(d)
    for off in (0, 2, -2, 4):
        s = seq_for(rd, (base + datetime.timedelta(days=off)).isoformat())
        if s: return s
    return None

def days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days

def mid_date(a, b):
    da = datetime.date.fromisoformat(a)
    return (da + datetime.timedelta(days=days(a, b) // 2)).isoformat()

def bisect(rd, lo_d, hi_d, lo_seq, hi_seq):
    """מחזיר רשימת (תאריך, רצף לפני, רצף אחרי) לכל שינוי שאותר,
    או None אם הארכיון לא מאפשר לחדד (אין נתונים באמצע)."""
    if (time.time() - T0) / 60 > MAX_MIN: return None
    if days(lo_d, hi_d) <= 7:
        return [(hi_d, lo_seq, hi_seq)]
    m = mid_date(lo_d, hi_d)
    ms = seq_near(rd, m)
    if ms is None: return None
    mc = {s[0] for s in ms}
    lc = {s[0] for s in lo_seq}
    hc = {s[0] for s in hi_seq}
    out = []
    if mc != lc:
        r = bisect(rd, lo_d, m, lo_seq, ms)
        if r is None: return None
        out += r
    if mc != hc:
        r = bisect(rd, m, hi_d, ms, hi_seq)
        if r is None: return None
        out += r
    return out

def diff(a, b):
    ac = {s[0] for s in a}; bc = {s[0] for s in b}
    return [s[1] for s in b if s[0] not in ac], [s[1] for s in a if s[0] not in bc]

skip_p = f'{OUTDIR}/backfill-dates-skip.json'
try: skip = json.load(open(skip_p, encoding='utf-8'))
except Exception: skip = {}

# ---- מטרות: אירועים עם דיף מצורף שעוד לא תוארך. פערי ה"תיעוד הראשון" (gd)
# קודם — הם הארוכים והמטעים ביותר ----
targets = []
for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
    if not fn.endswith('.json'): continue
    try: lf = materialize(json.load(open(f'{OUTDIR}/lines/{fn}', encoding='utf-8')))
    except Exception: continue
    vs = lf.get('versions', [])
    prev_i = None
    for i, v in enumerate(vs):
        if not (v.get('stops') or []): continue
        if prev_i is not None and (v.get('add') or v.get('rem')) and not v.get('dated') \
           and (v.get('gd') or v.get('src') == 'ob') and f"{lf.get('rd','')}|{v['d']}" not in skip:
            gap = days(vs[prev_i]['d'], v['d'])
            if gap > 10:
                targets.append((gap + (100000 if v.get('gd') else 0), fn, i, prev_i))
        prev_i = i
targets.sort(reverse=True)
print('פערים שממתינים לתיארוך:', len(targets))
if MAX_GAPS: targets = targets[:MAX_GAPS]

n_dated = n_events = n_skip = 0
for _, fn, i, prev_i in targets:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    p = f'{OUTDIR}/lines/{fn}'
    lf = json.load(open(p, encoding='utf-8'))
    vs = lf.get('versions', [])
    v, pv = vs[i], vs[prev_i]
    rd = lf.get('rd', '')
    res = bisect(rd, pv['d'], v['d'], pv['stops'], v['stops'])
    if res is None:
        skip[f'{rd}|{v["d"]}'] = 'הארכיון לא מאפשר לחדד את הפער'
        n_skip += 1
        continue
    changed = False
    for d_found, s_before, s_after in res:
        add, rem = diff(s_before, s_after)
        if not add and not rem: continue
        if days(d_found, v['d']) <= 7:
            # השינוי קרה ממש בשבוע של אירוע העוגן — הדיף נשאר עליו
            continue
        kind = 'stops' if (add and rem) else ('stops-add' if add else 'stops-del')
        ev = {'d': d_found, 'k': kind, 'src': 'ob', 'stops': s_after,
              'note': 'התאריך אותר בחיפוש בארכיון — דיוק של עד שבוע'}
        if add: ev['add'] = add
        if rem: ev['rem'] = rem
        vs.append(ev); n_events += 1; changed = True
    # אם כל השינויים תוארכו והוצאו לאירועים משלהם — מורידים את הדיף מהעוגן
    residual = [r for r in res if days(r[0], v['d']) <= 7 and (diff(r[1], r[2])[0] or diff(r[1], r[2])[1])]
    if not residual:
        for k in ('add', 'rem'): v.pop(k, None)
        if v.get('gd'):
            v.pop('gd', None); v.pop('note', None)
    else:
        # נשאר שינוי בשבוע העוגן — מצמצמים את הדיף עליו לשינוי הזה בלבד
        add, rem = diff(residual[-1][1], residual[-1][2])
        if add: v['add'] = add
        else: v.pop('add', None)
        if rem: v['rem'] = rem
        else: v.pop('rem', None)
        if v.get('gd'): v.pop('note', None); v.pop('gd', None)
    v['dated'] = 1
    vs.sort(key=lambda x: x['d'])
    lf['versions'] = vs
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n_dated += 1
    if n_dated % 20 == 0:
        json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'{n_dated}/{len(targets)} פערים | {n_events} אירועים חדשים | {int((time.time()-T0)/60)} דק׳')

json.dump(skip, open(skip_p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

# ---- עדכון האינדקס לקווים שנגעו בהם (ספירת שינויים, קטגוריות, אחרון) ----
idxp = f'{OUTDIR}/lines.json'
try:
    idx = json.load(open(idxp, encoding='utf-8'))
    for e in idx.get('lines', []):
        p = f"{OUTDIR}/lines/{e['rd'].replace('#', 'H').replace('/', '_')}.json"
        if not os.path.exists(p): continue
        try: vs = json.load(open(p, encoding='utf-8')).get('versions', [])
        except Exception: continue
        if not any(x.get('note', '').startswith('התאריך אותר') or x.get('dated') for x in vs): continue
        ks = {x['k'] for x in vs if x['k'] != 'baseline'}
        for x in vs:
            if (x.get('src') == 'ob' or x.get('gd')) and x.get('k') != 'removed':
                a, r = x.get('add'), x.get('rem')
                if a and r: ks.add('stops')
                elif a: ks.add('stops-add')
                elif r: ks.add('stops-del')
        e['v'] = len(vs)
        if ks: e['ks'] = sorted(ks)
        e['lk'] = vs[-1]['k']; e['ld'] = vs[-1]['d']
    json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
except Exception as ex:
    print('עדכון אינדקס נכשל (יתעדכן בריצה היומית):', ex)

print(f'סיום: תוארכו {n_dated} פערים | נוצרו {n_events} אירועים | בלתי-ניתנים לחידוד {n_skip}')
