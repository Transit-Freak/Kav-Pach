# -*- coding: utf-8 -*-
# "הקו בזמן" — מילוי-לאחור שלב א': ציר זמן בסיסי לכל וריאנט קו מארכיון אופן באס
# (הסדנא לידע ציבורי, Stride API). דוגם את רשימת הקווים אחת לשבוע בטווח המבוקש
# ומזהה: וריאנט הופיע / נעלם / שינה יעד (route_long_name) / שינה מספר קו.
# אין ב-API גאומטריה — שלב ב' (רצפי תחנות) משלים בנפרד.
#
# קלט: FROM, TO (YYYY-MM-DD), OUTDIR (line-history/data), STEP_DAYS (ברירת מחדל 7).
# פלט: עדכון lines/<rd>.json (גרסאות-עבר בלי גאומטריה, מסומנות src=ob),
#       backfill-state.json (המצב האחרון שנדגם — להמשכיות בין ריצות)
import json, os, re, sys, time, datetime, urllib.request, urllib.parse

API = 'https://open-bus-stride-api.hasadna.org.il'
FROM = os.environ['FROM']
TO = os.environ['TO']
STEP = int(os.environ.get('STEP_DAYS', '7'))
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.4'))   # נימוס בין קריאות

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (backfill; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f'API failed repeatedly: {url}')

def routes_on(date):
    out = {}
    offset = 0
    while True:
        rows = api('/gtfs_routes/list', date_from=date, date_to=date,
                   limit=1000, offset=offset)
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            if str(r.get('route_type')) != '3':
                continue
            mkt = str(r.get('route_mkt') or '').lstrip('0')
            if not mkt:
                continue
            rd = f"{mkt}-{r.get('route_direction','')}-{r.get('route_alternative','')}"
            out[rd] = {'line': r.get('route_short_name') or '',
                       'dest': (r.get('route_long_name') or '')[:120],
                       'op': r.get('agency_name') or ''}
        if len(rows) < 1000:
            break
        offset += 1000
    return out

def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

os.makedirs(f'{OUTDIR}/lines', exist_ok=True)
statep = f'{OUTDIR}/backfill-state.json'
state = jload(statep, {})   # {'last_date':..., 'routes': {rd: {...}}}

def add_version(rd, d, kind, info, note=''):
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    lf = jload(p, {'rd': rd, 'line': info.get('line',''), 'dest': info.get('dest',''),
                   'op': info.get('op',''), 'ty': '', 'versions': []})
    if any(v.get('d') == d and v.get('k') == kind for v in lf['versions']):
        return
    # קו שנעלם וחזר תוך עד ~חודש = הפסקת חג/פגרה — לא מעניין (בקשת המשתמש):
    # מוחקים את רשומת ה-removed בשקט ולא רושמים 'new'. ביטול של חודש+ נשאר.
    # חשוב: בודקים את השכן הכרונולוגי (הגרסה האחרונה שלפני d), לא את סוף
    # הרשימה — בקובץ יש גם גרסאות מאוחרות יותר (baseline של הצינור היומי).
    if kind == 'new':
        before = [v for v in lf['versions'] if v['d'] < d]
        if before:
            last = before[-1]
            if last.get('k') == 'removed' and last.get('src') == 'ob':
                gap = (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(last['d'])).days
                if gap <= 35:
                    lf['versions'].remove(last)
                    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                    return
    v = {'d': d, 'k': kind, 'shp': '', 'stops': [], 'src': 'ob'}
    if note: v['note'] = note
    lf['versions'].append(v)
    lf['versions'].sort(key=lambda x: x['d'])
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

d0 = datetime.date.fromisoformat(FROM)
d1 = datetime.date.fromisoformat(TO)
if state.get('last_date'):
    resume = datetime.date.fromisoformat(state['last_date']) + datetime.timedelta(days=STEP)
    if resume > d0:
        d0 = resume
        print('ממשיך מ-', d0)

prev = state.get('routes') or {}
d = d0
n_ev = 0
while d <= d1:
    ds = d.isoformat()
    cur = routes_on(ds)
    if not cur:
        print(ds, '— אין נתונים (חור בארכיון?), מדלג')
        d += datetime.timedelta(days=STEP)
        continue
    if prev:
        for rd, info in cur.items():
            pv = prev.get(rd)
            if pv is None:
                add_version(rd, ds, 'new', info, 'הווריאנט הופיע ברישום (ארכיון אופן באס)')
                n_ev += 1
            else:
                if pv['dest'] != info['dest']:
                    add_version(rd, ds, 'dest', info, f"היעד שוּנה: {pv['dest'][:60]} ← {info['dest'][:60]}")
                    n_ev += 1
                if pv['line'] != info['line']:
                    add_version(rd, ds, 'renum', info, f"מספר הקו שוּנה: {pv['line']} ← {info['line']}")
                    n_ev += 1
                if pv.get('op') and pv['op'] != info['op']:
                    add_version(rd, ds, 'operator', info, f"המפעיל הוחלף: {pv['op']} ← {info['op']}")
                    n_ev += 1
        for rd, pv in prev.items():
            if rd not in cur:
                add_version(rd, ds, 'removed', pv, 'הווריאנט נעלם מהרישום (ארכיון אופן באס)')
                n_ev += 1
    else:
        print(ds, '— נקודת עיגון ראשונה:', len(cur), 'וריאנטים')
    print(ds, '|', len(cur), 'וריאנטים | אירועים עד כה:', n_ev)
    prev = cur
    state = {'last_date': ds, 'routes': prev}
    json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    d += datetime.timedelta(days=STEP)

print('סיום:', n_ev, 'אירועי-עבר נכתבו | נדגם עד', state.get('last_date'))

# עדכון האינדקס: מוני גרסאות, קטגוריות (ks) וסטטוס אחרון (lk/ld), כולל
# הוספת וריאנטים שקיימים רק כקובץ (בוטלו לפני תחילת התיעוד היומי).
idxp = f'{OUTDIR}/lines.json'
idx = jload(idxp, None)
if idx:
    byrd = {l['rd']: l for l in idx.get('lines', [])}
    for fn in os.listdir(f'{OUTDIR}/lines'):
        if not fn.endswith('.json'): continue
        lf = jload(f'{OUTDIR}/lines/{fn}', {})
        rd0 = lf.get('rd')
        if not rd0: continue
        vs = lf.get('versions', [])
        e = byrd.get(rd0)
        if e is None:
            e = {'rd': rd0, 'line': lf.get('line', ''), 'dest': (lf.get('dest') or '')[:80],
                 'op': lf.get('op', ''), 'ty': lf.get('ty', '')}
            idx['lines'].append(e); byrd[rd0] = e
        e['v'] = len(vs)
        ks = sorted({v['k'] for v in vs if v['k'] != 'baseline'})
        if ks: e['ks'] = ks
        if vs: e['lk'] = vs[-1]['k']; e['ld'] = vs[-1]['d']
    idx['lines'].sort(key=lambda x: (x['line'], x['rd']))
    json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('אינדקס עודכן:', len(idx['lines']), 'וריאנטים')
