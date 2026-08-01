# -*- coding: utf-8 -*-
# "הקו בזמן" — סריקה יומית מלאה של פעילות הקווים מארכיון ה-GTFS הגולמי.
#
# הסריקה ההיסטורית (backfill_routes.py) דגמה את ה-API פעם בשבוע: תאריכים
# מדויקים עד שבוע, וריאנטים קצרי-חיים פוספסו, ו-2022 ריקה (ה-API ריק שם).
# כאן עוברים יום-יום על הארכיון ובונים את האמת המלאה בדיוק של יום.
#
# סמנטיקה: "קיים" = יש לו נסיעות מתוכננות באותו יום (calendar+trips), כמו
# ב-API — לא "מופיע בקטלוג" (הקטלוג מכיל ~פי 2.5 שורות, כולל עתידיות).
# קו שלא פעיל בשבת/חג לא "בוטל": היעלמות שמסתיימת בחזרה תוך עד 35 יום
# נבלעת בשקט (אותה מדיניות כמו הסריקה השבועית, בקשת המשתמש). היעלמות
# ארוכה מזה נרשמת כביטול בתאריך היום הראשון שבו הקו כבר לא פעל.
#
# התאמה לאירועים קיימים: אירוע שבועי (src=ob) עד 8 ימים אחרי היום האמיתי
# מקבל את התאריך המדויק במקום להיווצר כפול. אירועי הצינור היומי לא זזים.
#
# checkpoint: routes-daily-state.json. אחרי הריצה: rebuild_lines_index.py
# ו-build_line_changes.py לרענון האינדקס והפיד.
import json, os, re, struct, sys, time, datetime, zlib, io, csv
import urllib.request

S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
FROM = os.environ.get('FROM', '2022-01-16')
TO = os.environ.get('TO', '2026-07-24')   # משם ואילך מכסה התיעוד היומי
MAX_MIN = float(os.environ.get('MAX_MIN', '340'))
PAUSE = float(os.environ.get('PAUSE', '0.03'))
MATCH_WIN = 8    # אירוע שבועי עד 8 ימים אחרי היום האמיתי = אותו אירוע
GAP_OK = 35      # נעלם וחזר תוך עד ~חודש = הפסקה — לא נרשם
T0 = time.time()

def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (daily routes scan; polite)'})
            if rng: req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                time.sleep(PAUSE)
                return data, r.headers
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(6 * (attempt + 1))
    raise SystemExit(f'HTTP failed: {url}')

def member(url, want):
    tail, h = http(url, 'bytes=-66000')
    total = int((h.get('Content-Range') or '/0').rsplit('/', 1)[-1])
    i = tail.rfind(b'PK\x05\x06')
    if i < 0: raise ValueError('EOCD not found')
    cd_size, cd_off = struct.unpack('<II', tail[i+12:i+20])
    if cd_off == 0xFFFFFFFF:
        j = tail.rfind(b'PK\x06\x06')
        cd_size, cd_off = struct.unpack('<QQ', tail[j+40:j+56])
    base = total - len(tail)
    cd = tail[cd_off-base:cd_off-base+cd_size] if base <= cd_off else http(url, f'bytes={cd_off}-{cd_off+cd_size-1}')[0]
    p = 0
    while p + 46 <= len(cd):
        if cd[p:p+4] != b'PK\x01\x02': break
        method, = struct.unpack('<H', cd[p+10:p+12])
        csize, = struct.unpack('<I', cd[p+20:p+24])
        nlen, xlen, clen = struct.unpack('<HHH', cd[p+28:p+34])
        lho, = struct.unpack('<I', cd[p+42:p+46])
        name = cd[p+46:p+46+nlen]
        if name.endswith(want):
            lh, _ = http(url, f'bytes={lho}-{lho+29}')
            n2, x2 = struct.unpack('<HH', lh[26:30])
            off = lho + 30 + n2 + x2
            raw, _ = http(url, f'bytes={off}-{off+csize-1}')
            return zlib.decompressobj(-15).decompress(raw) if method == 8 else raw
        p += 46 + nlen + xlen + clen
    raise ValueError(f'{want} missing')

def csvdict(url, want):
    rd_ = csv.reader(io.StringIO(member(url, want).decode('utf-8-sig')))
    hdr = next(rd_)
    c = {h.strip(): i for i, h in enumerate(hdr)}
    return c, rd_

def list_dates():
    dates = []
    ym = datetime.date.fromisoformat(FROM[:7] + '-01')
    while ym.isoformat()[:7] <= TO[:7]:
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ym.year}/{ym.month:02d}/')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if FROM <= ds <= TO: dates.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(dates))

def active_routes(ds):
    """rd -> {'line','dest','op'} רק לקווים עם נסיעות מתוכננות ביום ds."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    try:
        wd = datetime.date.fromisoformat(ds).weekday()   # שני=0..ראשון=6
        col = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][wd]
        dsc = ds.replace('-', '')
        c, rows = csvdict(url, b'calendar.txt')
        svc = set()
        for row in rows:
            try:
                if row[c[col]].strip() == '1' and row[c['start_date']] <= dsc <= row[c['end_date']]:
                    svc.add(row[c['service_id']])
            except IndexError: continue
        try:   # חריגים: הוספה/הסרה נקודתית של שירות
            c, rows = csvdict(url, b'calendar_dates.txt')
            for row in rows:
                try:
                    if row[c['date']] != dsc: continue
                    if row[c['exception_type']].strip() == '1': svc.add(row[c['service_id']])
                    else: svc.discard(row[c['service_id']])
                except IndexError: continue
        except ValueError: pass
        c, rows = csvdict(url, b'trips.txt')
        active_rids = set()
        for row in rows:
            try:
                if row[c['service_id']] in svc: active_rids.add(row[c['route_id']])
            except IndexError: continue
        ag = {}
        c, rows = csvdict(url, b'agency.txt')
        for row in rows:
            try: ag[row[c['agency_id']]] = row[c['agency_name']].strip()
            except IndexError: continue
        out = {}
        c, rows = csvdict(url, b'routes.txt')
        for row in rows:
            try:
                if row[c['route_id']] not in active_rids: continue
                if row[c['route_type']].strip() != '3': continue
                parts = row[c['route_desc']].strip().split('-')
                if len(parts) < 3: continue
                mkt = parts[0].lstrip('0')
                if not mkt: continue
                out[f"{mkt}-{parts[1]}-{parts[2]}"] = {
                    'line': row[c['route_short_name']].strip(),
                    'dest': (row[c['route_long_name']] or '').strip()[:120],
                    'op': ag.get(row[c['agency_id']], '')}
            except IndexError: continue
        return out
    except (ValueError, KeyError) as e:
        print(ds, '— קובץ בעייתי:', e); return None

def fsafe(rd): return rd.replace('#', 'H').replace('/', '_')
def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days

NOTES = {'new': 'הווריאנט הופיע ברישום (ארכיון אופן באס, תאריך מדויק)',
         'removed': 'הווריאנט נעלם מהרישום (ארכיון אופן באס, תאריך מדויק)'}

n_sharp = n_add = n_blip = 0
def apply_event(rd2, ds, kind, info, note_extra=''):
    """מחדד אירוע שבועי תואם או מוסיף אירוע חדש — בלי כפילויות."""
    global n_sharp, n_add
    p = f'{OUTDIR}/lines/{fsafe(rd2)}.json'
    lf = jload(p, None)
    if lf is None:
        lf = {'rd': rd2, 'line': info['line'], 'dest': info['dest'], 'op': info['op'],
              'ty': '', 'versions': []}
    for v in lf['versions']:
        if v.get('k') != kind: continue
        gap = days_between(ds, v['d'])
        if gap == 0: return
        if v.get('src') != 'ob': continue   # אירועי הצינור היומי לא זזים
        if 0 < gap <= MATCH_WIN and 'תאריך מדויק' not in (v.get('note') or ''):
            v['d'] = ds
            v['note'] = ((v.get('note') or '').replace('(ארכיון אופן באס)', '(ארכיון אופן באס, תאריך מדויק)')
                         or NOTES.get(kind, ''))
            if 'תאריך מדויק' not in v['note']:
                v['note'] = (v['note'] + ' · תאריך מדויק מהסריקה היומית').strip(' ·')
            lf['versions'].sort(key=lambda x: x['d'])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            n_sharp += 1
            return
    # מדיניות ההפסקות: 'new' שמגיע אחרי removed קרוב (עד 35 יום) מוחק אותו בשקט
    if kind == 'new':
        before = [v for v in lf['versions'] if v['d'] < ds]
        if before and before[-1].get('k') == 'removed' and before[-1].get('src') == 'ob' \
           and 0 <= days_between(before[-1]['d'], ds) <= GAP_OK:
            global n_blip
            lf['versions'].remove(before[-1])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            n_blip += 1
            return
    v = {'d': ds, 'k': kind, 'shp': '', 'stops': [], 'src': 'ob'}
    if kind in NOTES: v['note'] = NOTES[kind]
    elif note_extra: v['note'] = note_extra
    lf['versions'].append(v)
    lf['versions'].sort(key=lambda x: x['d'])
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n_add += 1

statep = f'{OUTDIR}/routes-daily-state.json'
state = jload(statep, {})
dates = [d for d in list_dates() if d > (state.get('last_date') or '')]
if state.get('last_date'): print('ממשיך מ-', state['last_date'])
print(len(dates), 'ימים לסריקה')

# seen: rd -> {'info': ..., 'last': תאריך פעילות אחרון}
# absent: rd -> תאריך ההיעלמות (היום הראשון בלי נסיעות) — ממתין להכרעה
seen = state.get('seen') or {}
absent = state.get('absent') or {}
first_anchor = not seen
chain_start = state.get('chain_start') or (dates[0] if dates else FROM)

for di, ds in enumerate(dates):
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    cur = active_routes(ds)
    if cur is None:
        continue
    if seen and len(cur) < 300:
        print(ds, f'— קובץ חשוד ({len(cur)} פעילים), מדלג'); continue
    for rd2, info in cur.items():
        old = seen.get(rd2)
        if rd2 in absent:
            gap = days_between(absent[rd2], ds)
            if gap > GAP_OK:   # היעלמות אמיתית שהסתיימה בחזרה — שני אירועים
                apply_event(rd2, absent[rd2], 'removed', seen[rd2]['info'])
                apply_event(rd2, ds, 'new', info)
            del absent[rd2]    # עד 35 יום — הפסקה, נבלע בשקט
        elif old is None and not first_anchor:
            # התחממות: וריאנט שפשוט לא פעל ביום העיגון (קו של שישי בלבד,
            # קו תלמידים בחופשה) אינו "חדש" — 35 הימים הראשונים נבלעים
            if days_between(chain_start, ds) > GAP_OK:
                apply_event(rd2, ds, 'new', info)
        if old is not None:
            ov = old['info']
            if ov['dest'] != info['dest']:
                apply_event(rd2, ds, 'dest', info, f"היעד שוּנה: {ov['dest'][:60]} ← {info['dest'][:60]}")
            if ov['line'] != info['line']:
                apply_event(rd2, ds, 'renum', info, f"מספר הקו שוּנה: {ov['line']} ← {info['line']}")
            if ov.get('op') and ov['op'] != info['op']:
                apply_event(rd2, ds, 'operator', info, f"המפעיל הוחלף: {ov['op']} ← {info['op']}")
        seen[rd2] = {'info': info, 'last': ds}
    for rd2, st in seen.items():
        if rd2 not in cur and rd2 not in absent and st['last'] < ds:
            absent[rd2] = ds   # מהיום הזה אין נסיעות — ממתין להכרעה
    if first_anchor:
        print(ds, '— נקודת עיגון ראשונה:', len(cur), 'וריאנטים פעילים')
        first_anchor = False
    state = {'last_date': ds, 'seen': seen, 'absent': absent, 'chain_start': chain_start}
    if di % 40 == 0:
        json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        print(ds, f'| {len(cur)} פעילים | חודדו {n_sharp} · נוספו {n_add} · הפסקות שנבלעו {n_blip}')

# הכרעת היעלמויות שנשארו פתוחות בסוף הטווח: מעל 35 יום = ביטול אמיתי;
# פחות מזה נשאר פתוח — הסריקה השבועית/היומית שאחרי TO כבר כיסתה אותו
if state.get('last_date') == (dates[-1] if dates else None):
    for rd2, d0 in list(absent.items()):
        if days_between(d0, TO) > GAP_OK:
            apply_event(rd2, d0, 'removed', seen[rd2]['info'])
            del absent[rd2]
    state = {'last_date': state['last_date'], 'seen': seen, 'absent': absent, 'chain_start': chain_start}

json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'סיום: חודדו {n_sharp} · נוספו {n_add} · הפסקות שנבלעו {n_blip} | נדגם עד', state.get('last_date'))
