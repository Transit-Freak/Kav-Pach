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

def api(path, soft=False, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(2 if soft else 5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (stops registry backfill; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(10 * (attempt + 1))
    # soft: שאילתות העשרה (רשימת קווים) — כשל בהן לא מפיל את כל הריצה.
    # ריצת הלילה של 28.07 מתה על תחנה אחת שהחזירה 400 שוב ושוב.
    if soft: return None
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
                          round(float(r.get('lat')), 5), round(float(r.get('lon')), 5),
                          r.get('id')]
            except Exception: pass
        if len(rows) < 1000: break
        offset += 1000
    return out

# אילו קווים עצרו בתחנה — מרשומות הנסיעות של אותו יום בארכיון. עם אימות
# שהתשובה באמת שייכת לתחנה (השרת מתעלם בשקט מפרמטרים לא מוכרים).
rs_by_stop_fails = 0
def lines_at_stop(sid):
    """רשימת הקווים שעצרו בתחנה, או None כשאי-אפשר לדעת (כשל/מפסק) —
    להבדיל מ-[] שפירושו תשובה סופית: אין רשומות נסיעה לתחנה בארכיון."""
    global rs_by_stop_fails
    if sid is None or rs_by_stop_fails >= 3: return None
    rows = api('/gtfs_ride_stops/list', soft=True, gtfs_stop_ids=sid, limit=60)
    if rows is None:   # כשל HTTP עקבי (למשל 400 על מזהה ישן) — נספר למפסק
        rs_by_stop_fails += 1
        return None
    if not isinstance(rows, list): return None
    if not rows: return []
    if any(r.get('gtfs_stop_id') != sid for r in rows):
        rs_by_stop_fails += 1
        return None
    return sorted({str(r.get('gtfs_route__route_short_name') or '') for r in rows} - {''})[:12]

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

def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days

def drop_recent_del(code, ds, max_d=35):
    """תחנה שנעלמה וחזרה תוך עד ~חודש = חור בארכיון/הפסקה קצרה — מוחקים
    את רשומת הביטול בשקט (כמו זוגות החג בקווים). מחזיר True אם מוזג."""
    evs = shist.get(code) or []
    if not (evs and evs[-1].get('k') == 'del' and days_between(evs[-1]['d'], ds) <= max_d):
        return False
    dd = evs[-1]['d']
    shist[code] = evs[:-1]
    if not shist[code]: shist.pop(code)
    mm = mload(month_of(dd))
    mm['changes'] = [x for x in mm['changes'] if not (x.get('c') == code and x.get('k') == 'del' and x.get('d') == dd)]
    return True

def flush():
    os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
    # סימון "פעילה כיום": ביטול היסטורי של תחנה שקיימת ברישום הנוכחי מקבל
    # דגל now — האתר מציג אותה כ"פעילה כיום" ולא כמבוטלת (בקשת המשתמש)
    cur_reg = jload(f'{OUTDIR}/stops-state.json', {})
    for c, evs in shist.items():
        if evs and evs[-1].get('k') == 'del':
            if c in cur_reg: evs[-1]['now'] = 1
            else: evs[-1].pop('now', None)
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
                if drop_recent_del(c, ds):
                    continue
                sev(ds, c, {'k': 'new', 'n': v[0], 't': '', 'la': v[1], 'lo': v[2]}); n_ev += 1
                continue
            if pv[0] != v[0] and v[0]:
                sev(ds, c, {'k': 'renamed', 'on': pv[0], 'nn': v[0], 't': '', 'la': v[1], 'lo': v[2]}); n_ev += 1
            dm = dist_m(pv[1], pv[2], v[1], v[2])
            if dm > MOVE_M:
                sev(ds, c, {'k': 'moved', 'n': v[0], 't': '', 'dist': round(dm), 'ola': pv[1], 'olo': pv[2], 'la': v[1], 'lo': v[2]}); n_ev += 1
        for c, pv in prev.items():
            if c not in cur:
                lns = lines_at_stop(pv[3] if len(pv) > 3 else None)
                ev = {'k': 'del', 'n': pv[0], 't': '', 'la': pv[1], 'lo': pv[2], 'lines': lns or []}
                if lns == []: ev['lc'] = 1   # תשובה סופית: אין קווים בארכיון
                sev(ds, c, ev); n_ev += 1
    else:
        print(ds, '— נקודת עיגון ראשונה:', len(cur), 'תחנות')
    print(ds, '|', len(cur), 'תחנות | אירועים עד כה:', n_ev)
    prev = cur
    state = {'last_date': ds, 'stops': prev}
    d += datetime.timedelta(days=STEP)
    if n_ev and n_ev % 2000 < 50: flush()

# השלמה רטרואקטיבית: ביטולים קיימים בלי רשימת קווים מקבלים אותה —
# מאתרים את מזהה התחנה בשבוע שלפני הביטול ושולפים מי עצר בה.
cur_reg = jload(f'{OUTDIR}/stops-state.json', {})
n_fix = 0
def mark_checked(e):
    """אין ולא יהיו נתוני קווים לתחנה הזו בארכיון — לא מנסים שוב בלילות
    הבאים (בלי זה תחנה בלי קווים הייתה נבדקת מחדש לנצח)."""
    e['lc'] = 1

for c, evs in list(shist.items()):
    if (time.time() - T0) / 60 > MAX_MIN + 10: break
    e = evs[-1]
    if not (e.get('k') == 'del' and not e.get('lines') and not e.get('lc')): continue
    if c in cur_reg: continue   # פעילה כיום — ממילא מוסתרת מהרשימה
    probe = (datetime.date.fromisoformat(e['d']) - datetime.timedelta(days=7)).isoformat()
    rows = api('/gtfs_stops/list', soft=True, date_from=probe, date_to=probe, code=c, limit=5)
    if rows is None: continue   # כשל HTTP זמני — ננסה שוב בריצה הבאה
    if not isinstance(rows, list): continue
    row = next((r for r in rows if str(r.get('code')) == c), None)
    if row is None:   # התחנה לא נמצאה בארכיון גם שבוע לפני הביטול — אין מה למצוא
        mark_checked(e); n_fix += 1
        continue
    lns = lines_at_stop(row.get('id'))
    if lns:
        e['lines'] = lns
        mm = mload(month_of(e['d']))
        for x in mm['changes']:
            if x.get('c') == c and x.get('k') == 'del' and x.get('d') == e['d']:
                x['lines'] = lns
        n_fix += 1
    elif lns == []:
        # תשובה סופית מהשרת: אין רשומות נסיעה לתחנה בארכיון
        mark_checked(e); n_fix += 1
    # lns is None: כשל זמני/מפסק — נשאיר לניסיון בלילה אחר
if n_fix: print('הושלמו/סומנו רטרואקטיבית:', n_fix)

flush()
print('סיום ריצה:', n_ev, 'אירועי תחנות | נדגם עד', state.get('last_date'))
