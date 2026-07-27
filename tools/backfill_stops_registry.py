# -*- coding: utf-8 -*-
# "הקו בזמן" — שלב ב'2: היסטוריית רישום התחנות הארצי מארכיון אופן באס.
# דוגם את רשימת התחנות אחת לשבוע (2022 עד תחילת התיעוד היומי) ומזהה:
# תחנה חדשה / בוטלה / שינוי שם / הזזת מיקום — לקובצי החודש של טאב התחנות.
#
# checkpoint: stops-backfill-state.json (התאריך והתמונה האחרונים שנדגמו).
import json, math, os, re, sys, time, datetime, urllib.request, urllib.parse

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.35'))
MAX_MIN = float(os.environ.get('MAX_MIN', '80'))
FROM = os.environ.get('FROM', '2022-01-01')
TO = os.environ.get('TO', '2026-07-18')   # משם ואילך מכסה התיעוד היומי
STEP = int(os.environ.get('STEP_DAYS', '7'))
MOVE_M = 25
T0 = time.time()

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (stops registry backfill; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    raise SystemExit(f'API failed repeatedly: {url}')

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

def stops_on(date):
    out = {}
    offset = 0
    while True:
        rows = api('/gtfs_stops/list', date_from=date, date_to=date, limit=1000, offset=offset)
        if not isinstance(rows, list) or not rows: break
        for r in rows:
            c = str(r.get('code') or '')
            if not c: continue
            try:
                out[c] = [' '.join((r.get('name') or '').split()),
                          round(float(r.get('lat')), 5), round(float(r.get('lon')), 5)]
            except Exception: pass
        if len(rows) < 1000: break
        offset += 1000
    return out

def dist_m(a_la, a_lo, b_la, b_lo):
    cl = math.cos(math.radians((a_la + b_la) / 2))
    return math.hypot((a_la - b_la) * 110540, (a_lo - b_lo) * 111320 * cl)

statep = f'{OUTDIR}/stops-backfill-state.json'
state = jload(statep, {})
shist = jload(f'{OUTDIR}/stops-hist.json', {})
months = {}   # 'YYYY-MM' -> chm dict (נטען לפי צורך)

def month_of(d): return d[:7]
def mload(m):
    if m not in months:
        months[m] = jload(f'{OUTDIR}/changes/stops-{m}.json', {'month': m, 'changes': []})
    return months[m]

def sev(d, code, ev):
    mload(month_of(d))['changes'].append({'d': d, 'c': code, **ev})
    shist.setdefault(code, [])
    shist[code] = [e for e in shist[code] if not (e['d'] == d and e['k'] == ev['k'])]
    shist[code].append({'d': d, **ev})

def flush():
    os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
    for m, chm in months.items():
        json.dump(chm, open(f'{OUTDIR}/changes/stops-{m}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(shist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    # רשימת החודשים לטאב התחנות
    json.dump({'months': sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$', f)}, reverse=True),
               'stopMonths': sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')}, reverse=True)},
              open(f'{OUTDIR}/months.json', 'w', encoding='utf-8'), ensure_ascii=False)

d0 = datetime.date.fromisoformat(FROM)
d1 = datetime.date.fromisoformat(TO)
if state.get('last_date'):
    resume = datetime.date.fromisoformat(state['last_date']) + datetime.timedelta(days=STEP)
    if resume > d0:
        d0 = resume
        print('ממשיך מ-', d0)

prev = state.get('stops') or {}
d = d0
n_ev = 0
while d <= d1:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    ds = d.isoformat()
    cur = stops_on(ds)
    if not cur:
        print(ds, '— אין נתונים, מדלג')
        d += datetime.timedelta(days=STEP)
        continue
    if prev:
        for c, v in cur.items():
            pv = prev.get(c)
            if pv is None:
                sev(ds, c, {'k': 'new', 'n': v[0], 't': '', 'la': v[1], 'lo': v[2]}); n_ev += 1
                continue
            if pv[0] != v[0] and v[0]:
                sev(ds, c, {'k': 'renamed', 'on': pv[0], 'nn': v[0], 't': '', 'la': v[1], 'lo': v[2]}); n_ev += 1
            dm = dist_m(pv[1], pv[2], v[1], v[2])
            if dm > MOVE_M:
                sev(ds, c, {'k': 'moved', 'n': v[0], 't': '', 'dist': round(dm), 'ola': pv[1], 'olo': pv[2], 'la': v[1], 'lo': v[2]}); n_ev += 1
        for c, pv in prev.items():
            if c not in cur:
                sev(ds, c, {'k': 'del', 'n': pv[0], 't': '', 'la': pv[1], 'lo': pv[2], 'lines': []}); n_ev += 1
    else:
        print(ds, '— נקודת עיגון ראשונה:', len(cur), 'תחנות')
    print(ds, '|', len(cur), 'תחנות | אירועים עד כה:', n_ev)
    prev = cur
    state = {'last_date': ds, 'stops': prev}
    d += datetime.timedelta(days=STEP)
    if n_ev and n_ev % 2000 < 50: flush()

flush()
print('סיום ריצה:', n_ev, 'אירועי תחנות | נדגם עד', state.get('last_date'))
