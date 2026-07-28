# -*- coding: utf-8 -*-
# "הקו בזמן" — היסטוריה מדויקת לפי מק"ט (הרעיון של שלמה): במקום לדגום את
# כל הארץ פעם בשבוע ולהשוות תמונות, שואלים את הארכיון שאלה אחת לכל מק"ט —
# "כל הרשומות שלך מ-2022 עד היום" — ומקבלים שורה-ליום לכל וריאנט: היום
# המדויק שהופיע, נעלם, שינה יעד/מפעיל/מספר. בלי שום הטיית ימי-שבוע
# (הסריקה הישנה דגמה רק שבתות ופספסה קווי ימי-חול כמו 1א קרית מלאכי).
#
# כתיבה: וריאנט בלי קובץ — נוצר עם האירועים המדויקים; וריאנט שכל הגרסאות
# שלו מהארכיון ועוד בלי רצפי תחנות — מוחלף לתאריכים מדויקים (אין מה
# לאבד); וריאנט עם רצפים/תיארוך/מעקב יומי — לא נוגעים.
import json, os, sys, time, datetime, urllib.request, urllib.parse

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PAUSE = float(os.environ.get('PAUSE', '0.35'))
MAX_MIN = float(os.environ.get('MAX_MIN', '100'))
FROM = os.environ.get('FROM', '2022-01-01')
TO = os.environ.get('TO', '2026-07-18')   # משם ואילך — המעקב היומי
GAP_D = 35   # היעלמות עד ~חודש = חג/חור בארכיון, לא ביטול (כמו בצינור היומי)
T0 = time.time()

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (per-mkt exact history; polite)'})
            with urllib.request.urlopen(req, timeout=120) as r:
                time.sleep(PAUSE)
                return json.load(r)
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(8 * (attempt + 1))
    return None

def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

def days(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days

def next_day(d):
    return (datetime.date.fromisoformat(d) + datetime.timedelta(days=1)).isoformat()

def mkt_rows(mkt):
    """כל השורות של מק"ט לכל התקופה — שורה לכל וריאנט לכל יום שהוא רשום."""
    out = []
    offset = 0
    while True:
        rows = api('/gtfs_routes/list', route_mkt=mkt, date_from=FROM, date_to=TO,
                   limit=1000, offset=offset)
        if rows is None: return None
        if not isinstance(rows, list) or not rows: break
        out += rows
        if len(rows) < 1000: break
        offset += 1000
        if offset > 40000: break
    return out

def build_events(recs, mkt_first):
    """recs: [(date, line, dest, op)] ממוין לוריאנט אחד ← רשימת גרסאות מדויקות."""
    evs = []
    first_d = recs[0][0]
    # 'הופיע' אמיתי רק אם הווריאנט נולד אחרי שהמק"ט כבר היה בארכיון —
    # אחרת זו סתם תחילת הכיסוי של הארכיון למק"ט הזה
    if days(mkt_first, first_d) > GAP_D:
        evs.append({'d': first_d, 'k': 'new', 'src': 'ob',
                    'note': 'הווריאנט הופיע ברישום (ארכיון אופן באס, תאריך מדויק)'})
    prev = recs[0]
    for r in recs[1:]:
        if days(prev[0], r[0]) > GAP_D:
            evs.append({'d': next_day(prev[0]), 'k': 'removed', 'src': 'ob',
                        'note': 'הווריאנט נעלם מהרישום (ארכיון אופן באס, תאריך מדויק)'})
            evs.append({'d': r[0], 'k': 'new', 'src': 'ob',
                        'note': 'הווריאנט חזר לרישום (ארכיון אופן באס, תאריך מדויק)'})
        else:
            if r[2] != prev[2] and r[2]:
                evs.append({'d': r[0], 'k': 'dest', 'src': 'ob',
                            'note': f"היעד שוּנה: {prev[2][:60]} ← {r[2][:60]}"})
            if r[1] != prev[1] and r[1]:
                evs.append({'d': r[0], 'k': 'renum', 'src': 'ob',
                            'note': f"מספר הקו שוּנה: {prev[1]} ← {r[1]}"})
            if r[3] != prev[3] and r[3] and prev[3]:
                evs.append({'d': r[0], 'k': 'operator', 'src': 'ob',
                            'note': f"המפעיל הוחלף: {prev[3]} ← {r[3]}"})
        prev = r
    # נעלם לפני עידן המעקב היומי — ביטול בתאריך מדויק
    if days(prev[0], TO) > GAP_D:
        evs.append({'d': next_day(prev[0]), 'k': 'removed', 'src': 'ob',
                    'note': 'הווריאנט נעלם מהרישום (ארכיון אופן באס, תאריך מדויק)'})
    return evs

def refinable(lf):
    """מותר להחליף את ההיסטוריה: הכול מהארכיון, בלי רצפים ובלי תיארוך."""
    for v in lf.get('versions', []):
        if v.get('src') != 'ob': return False
        if v.get('stops') or v.get('dated') or v.get('add') or v.get('rem'): return False
    return True

statep = f'{OUTDIR}/backfill-exact-state.json'
state = jload(statep, {})

# ---- רשימת המק"טים: כל מה שמוכר לנו + סריקות גילוי רבעוניות בימי חול ----
if not state.get('mkts'):
    mkts = set()
    idx = jload(f'{OUTDIR}/lines.json', {})
    for e in idx.get('lines', []):
        mkts.add(e['rd'].split('-', 1)[0])
    print('מק"טים מהאינדקס:', len(mkts))
    disc_dates = []
    d = datetime.date(2022, 2, 14)   # יום שני
    while d.isoformat() < TO:
        disc_dates.append(d.isoformat())
        d += datetime.timedelta(days=91)
    for dd in disc_dates:
        offset = 0
        while True:
            rows = api('/gtfs_routes/list', date_from=dd, date_to=dd, limit=1000, offset=offset)
            if not isinstance(rows, list) or not rows: break
            for r in rows:
                m = str(r.get('route_mkt') or '').lstrip('0')
                if m: mkts.add(m)
            if len(rows) < 1000: break
            offset += 1000
        print(f'גילוי {dd}: סה"כ מק"טים {len(mkts)}')
    state['mkts'] = sorted(mkts)
    state['done'] = state.get('done', [])
    json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

done = set(state.get('done', []))
todo = [m for m in state['mkts'] if m not in done]
print(f'מק"טים: {len(state["mkts"])} | טופלו {len(done)} | בתור {len(todo)}')

n_new = n_ref = 0
for mkt in todo:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    rows = mkt_rows(mkt)
    if rows is None:
        print(f'  {mkt}: כשל רשת — יטופל בריצה הבאה'); continue
    byrd = {}
    for r in rows:
        if str(r.get('route_type') or '3') != '3': continue
        m = str(r.get('route_mkt') or '').lstrip('0')
        rd = f"{m}-{r.get('route_direction', '')}-{r.get('route_alternative', '')}"
        d = r.get('date')
        if not d: continue
        byrd.setdefault(rd, []).append((d, r.get('route_short_name') or '',
                                        (r.get('route_long_name') or '')[:120],
                                        r.get('agency_name') or ''))
    if byrd:
        mkt_first = min(rs[0][0] for rs in (sorted(v) for v in byrd.values()))
        for rd, recs in byrd.items():
            recs.sort()
            p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
            lf = jload(p, None)
            if lf is not None and not refinable(lf):
                continue
            evs = build_events(recs, mkt_first)
            if lf is None and not evs:
                continue   # וריאנט שחי לאורך כל התקופה בלי שינויים ובלי קובץ — הקו השקט יטופל בעוגנים
            last = recs[-1]
            out = {'rd': rd, 'line': last[1], 'dest': last[2], 'op': last[3],
                   'ty': (lf or {}).get('ty', ''), 'versions': evs}
            if lf is not None:
                # שומרים גרסאות שאינן מהארכיון (אין כאלה אם refinable, אבל ליתר ביטחון)
                out['ty'] = lf.get('ty', '')
                n_ref += 1
            else:
                n_new += 1
            json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    done.add(mkt)
    if len(done) % 50 == 0:
        state['done'] = sorted(done)
        json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(f'{len(done)}/{len(state["mkts"])} מק"טים | חדשים {n_new} | דויקו {n_ref} | {int((time.time()-T0)/60)} דק׳')

state['done'] = sorted(done)
json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))

# ---- עדכון האינדקס לקבצים חדשים/מדויקים ----
idxp = f'{OUTDIR}/lines.json'
idx = jload(idxp, {})
if idx.get('lines') is not None:
    byrd_idx = {e['rd']: e for e in idx['lines']}
    import glob
    n_idx = 0
    for fn in os.listdir(f'{OUTDIR}/lines'):
        if not fn.endswith('.json'): continue
        lf = jload(f'{OUTDIR}/lines/{fn}', {})
        rd = lf.get('rd')
        if not rd: continue
        vs = lf.get('versions', [])
        e = byrd_idx.get(rd)
        if e is None:
            e = {'rd': rd, 'line': lf.get('line', ''), 'dest': lf.get('dest', '')[:80],
                 'op': lf.get('op', ''), 'ty': lf.get('ty', '')}
            idx['lines'].append(e)
            byrd_idx[rd] = e
            n_idx += 1
        else:
            # תמיד מסנכרנים מהקובץ — דיוק יכול לשנות תאריכים בלי לשנות ספירה
            e['line'] = lf.get('line', e.get('line', ''))
            e['dest'] = (lf.get('dest') or e.get('dest', ''))[:80]
            e['op'] = lf.get('op', e.get('op', ''))
        ks = {v['k'] for v in vs if v['k'] != 'baseline'}
        for v in vs:   # קטגוריות התחנות הנגזרות מההשוואות — לא לדרוס
            if (v.get('src') == 'ob' or v.get('gd')) and v.get('k') != 'removed':
                a, rr = v.get('add'), v.get('rem')
                if a and rr: ks.add('stops')
                elif a: ks.add('stops-add')
                elif rr: ks.add('stops-del')
        ks = sorted(ks)
        e['v'] = len(vs)
        if ks: e['ks'] = ks
        if vs: e['lk'] = vs[-1]['k']; e['ld'] = vs[-1]['d']
    idx['lines'].sort(key=lambda x: (x.get('line', ''), x['rd']))
    json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('רשומות אינדקס חדשות:', n_idx)

print(f'סיום: וריאנטים חדשים {n_new} | הוחלפו לתאריכים מדויקים {n_ref} | נותרו {len(state["mkts"]) - len(done)} מק"טים')
