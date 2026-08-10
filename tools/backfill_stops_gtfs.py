# -*- coding: utf-8 -*-
# "הקו בזמן" — היסטוריית רישום התחנות של 2022 מקובצי ה-GTFS הגולמיים ב-S3
# של אופן באס. ה-API של Stride ריק לכל 2022 (אומת בלוג הריצה מ-26.07.2026),
# אבל קובצי הארכיון היומיים כן קיימים ב-gtfs_archive/YYYY/MM/DD/. הסקריפט
# מושך מכל zip את stops.txt בלבד בבקשות Range (בלי להוריד 118MB ליום),
# ומזהה בין יום ליום: תחנה חדשה / בוטלה / שינוי שם / הזזה — באותו פורמט
# בדיוק של backfill_stops_registry.py, כך שהאתר קורא את התוצאה כמו שהיא.
#
# הטווח נגמר ב-2023-01-07 — נקודת העיגון שממנה מתחילה השרשרת של ה-API —
# כדי ששתי השרשראות ישתלבו בלי תפר כפול.
#
# checkpoint: stops-gtfs2022-state.json (נפרד מזה של ה-API — אין דריסה).
import csv, io, json, math, os, re, struct, sys, time, datetime, zlib
import urllib.request, urllib.error

S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
FROM = os.environ.get('FROM', '2022-01-16')   # הקובץ הראשון בארכיון
TO = os.environ.get('TO', '2023-01-07')       # נקודת העיגון של שרשרת ה-API
MAX_MIN = float(os.environ.get('MAX_MIN', '110'))
PAUSE = float(os.environ.get('PAUSE', '0.05'))
MOVE_M = 25
T0 = time.time()

def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (2022 stops backfill; polite)'})
            if rng: req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                time.sleep(PAUSE)
                return data, r.headers
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f'HTTP failed repeatedly: {url} {rng}')

def list_archive_dates():
    """כל התאריכים עם israel-public-transportation.zip בטווח המבוקש."""
    d0, d1 = FROM[:7], TO[:7]
    dates = []
    ym = datetime.date.fromisoformat(FROM[:7] + '-01')
    while ym.isoformat()[:7] <= d1:
        pfx = f'gtfs_archive/{ym.year}/{ym.month:02d}/'
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix={pfx}')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if FROM <= ds <= TO: dates.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(dates))

def fetch_stops_txt(ds):
    """מחלץ את stops.txt מה-zip של התאריך בבקשות Range בלבד."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    tail, hdrs = http(url, rng='bytes=-66000')
    total = int((hdrs.get('Content-Range') or '/0').rsplit('/', 1)[-1])
    i = tail.rfind(b'PK\x05\x06')
    if i < 0: raise ValueError('EOCD not found')
    cd_size, cd_off = struct.unpack('<II', tail[i+12:i+20])
    if cd_off == 0xFFFFFFFF:   # zip64
        j = tail.rfind(b'PK\x06\x06')
        if j < 0: raise ValueError('zip64 EOCD not found')
        cd_size, cd_off = struct.unpack('<QQ', tail[j+40:j+56])
    base = total - len(tail)
    if base <= cd_off and cd_off + cd_size <= total:
        cd = tail[cd_off - base: cd_off - base + cd_size]
    else:
        cd, _ = http(url, rng=f'bytes={cd_off}-{cd_off+cd_size-1}')
    # סריקת רשומות המרכזייה עד stops.txt
    p = 0
    while p + 46 <= len(cd):
        if cd[p:p+4] != b'PK\x01\x02': break
        method, = struct.unpack('<H', cd[p+10:p+12])
        csize, usize = struct.unpack('<II', cd[p+20:p+28])
        nlen, xlen, clen = struct.unpack('<HHH', cd[p+28:p+34])
        lho, = struct.unpack('<I', cd[p+42:p+46])
        name = cd[p+46:p+46+nlen]
        if csize == 0xFFFFFFFF or lho == 0xFFFFFFFF:   # zip64 extra
            x = cd[p+46+nlen:p+46+nlen+xlen]; q = 0
            while q + 4 <= len(x):
                hid, hsz = struct.unpack('<HH', x[q:q+4])
                if hid == 1:
                    vals = list(struct.unpack(f'<{hsz//8}Q', x[q+4:q+4+hsz]))
                    if usize == 0xFFFFFFFF: usize = vals.pop(0)
                    if csize == 0xFFFFFFFF: csize = vals.pop(0)
                    if lho == 0xFFFFFFFF: lho = vals.pop(0)
                q += 4 + hsz
        if name.endswith(b'stops.txt'):
            lh, _ = http(url, rng=f'bytes={lho}-{lho+29}')
            n2, x2 = struct.unpack('<HH', lh[26:30])
            off = lho + 30 + n2 + x2
            raw, _ = http(url, rng=f'bytes={off}-{off+csize-1}')
            if method == 8: raw = zlib.decompressobj(-15).decompress(raw)
            elif method != 0: raise ValueError(f'unsupported method {method}')
            return raw
        p += 46 + nlen + xlen + clen
    raise ValueError('stops.txt not in archive')

def snapshot(ds):
    """מילון code -> [שם, lat, lon, עיר] — אותם עיגולים ונרמולים כמו ב-API."""
    try:
        raw = fetch_stops_txt(ds)
    except (ValueError, SystemExit) as e:
        print(ds, '— קובץ בעייתי:', e); return None
    txt = raw.decode('utf-8-sig', errors='replace')
    rd = csv.reader(io.StringIO(txt))
    try: hdr = next(rd)
    except StopIteration: return None
    col = {h.strip(): i for i, h in enumerate(hdr)}
    need = ['stop_code', 'stop_name', 'stop_lat', 'stop_lon']
    if any(c not in col for c in need):
        print(ds, '— כותרות חסרות:', hdr); return None
    ic, iname = col['stop_code'], col['stop_name']
    ila, ilo, idesc = col['stop_lat'], col['stop_lon'], col.get('stop_desc')
    out = {}
    for row in rd:
        try:
            c = row[ic].strip()
            if not c or c == '0': continue
            city = ''
            if idesc is not None and idesc < len(row):
                m = re.search(r'עיר:\s*(.*?)\s*(?:רציף:|קומה:|$)', row[idesc])
                if m: city = ' '.join(m.group(1).split())
            out[c] = [' '.join(row[iname].split()),
                      round(float(row[ila]), 5), round(float(row[ilo]), 5), city]
        except (IndexError, ValueError):
            continue
    return out

def dist_m(a_la, a_lo, b_la, b_lo):
    cl = math.cos(math.radians((a_la + b_la) / 2))
    return math.hypot((a_la - b_la) * 110540, (a_lo - b_lo) * 111320 * cl)

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

statep = f'{OUTDIR}/stops-gtfs2022-state.json'
state = jload(statep, {})
shist = jload(f'{OUTDIR}/stops-hist.json', {})
months = {}

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
    """נעלמה וחזרה תוך עד ~חודש = חור בארכיון — מוחקים את הביטול בשקט.
    רק אירועים מהשרשרת הזו (מוקדמים מ-ds): לתחנות יש כבר אירועי 2023+
    בקובץ, וגם ביטול עתידי-לכאורה אסור שיימחק כאן (gap שלילי נפסל)."""
    evs = shist.get(code) or []
    if not (evs and evs[-1].get('k') == 'del'):
        return False
    gap = days_between(evs[-1]['d'], ds)
    if not (0 <= gap <= max_d):
        return False
    dd = evs[-1]['d']
    shist[code] = evs[:-1]
    if not shist[code]: shist.pop(code)
    mm = mload(month_of(dd))
    mm['changes'] = [x for x in mm['changes'] if not (x.get('c') == code and x.get('k') == 'del' and x.get('d') == dd)]
    return True

def jdump(obj, path):
    """כתיבה אטומית. ריצה ארוכה נקטעת באמצע (תקרת זמן, kill, מכולה שנסגרת),
    ואם היא נקטעת בדיוק בתוך json.dump נשאר קובץ חתוך — קרה ל-state של
    הסריקה הזו, וכל ההתקדמות ירדה לטמיון כי אי אפשר היה לטעון אותו."""
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def flush():
    os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
    cur_reg = jload(f'{OUTDIR}/stops-state.json', {})
    for c, evs in shist.items():
        evs.sort(key=lambda e: e['d'])
        if evs and evs[-1].get('k') == 'del':
            if c in cur_reg: evs[-1]['now'] = 1
            else: evs[-1].pop('now', None)
    for m, chm in months.items():
        chm['changes'].sort(key=lambda e: e['d'])
        jdump(chm, f'{OUTDIR}/changes/stops-{m}.json')
    jdump(shist, f'{OUTDIR}/stops-hist.json')
    jdump(state, statep)
    jdump({'months': sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$', f)}, reverse=True),
           'stopMonths': sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')}, reverse=True)},
          f'{OUTDIR}/months.json')

dates = [d for d in list_archive_dates() if d > (state.get('last_date') or '')]
if state.get('last_date'): print('ממשיך מ-', state['last_date'])
print(len(dates), 'תאריכים לדגימה')

prev = state.get('stops') or {}
n_ev = 0
t_flush = time.time()
for ds in dates:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('תקרת זמן — ממשיכים בריצה הבאה'); break
    cur = snapshot(ds)
    if not cur:
        continue
    # קובץ חלקי (קרה בארכיון, למשל 16.09.2023 בקווים) יוליד אלפי ביטולי-סרק
    if prev and (len(cur) < 0.6 * len(prev) or len(cur) < 10000):
        print(ds, f'— קובץ חשוד ({len(cur)} מול {len(prev)} אתמול), מדלג')
        continue
    if prev:
        for c, v in cur.items():
            pv = prev.get(c)
            if pv is None:
                if drop_recent_del(c, ds):
                    continue
                sev(ds, c, {'k': 'new', 'n': v[0], 't': v[3], 'la': v[1], 'lo': v[2]}); n_ev += 1
                continue
            if pv[0] != v[0] and v[0]:
                sev(ds, c, {'k': 'renamed', 'on': pv[0], 'nn': v[0], 't': v[3], 'la': v[1], 'lo': v[2]}); n_ev += 1
            dm = dist_m(pv[1], pv[2], v[1], v[2])
            if dm > MOVE_M:
                sev(ds, c, {'k': 'moved', 'n': v[0], 't': v[3], 'dist': round(dm), 'ola': pv[1], 'olo': pv[2], 'la': v[1], 'lo': v[2]}); n_ev += 1
        for c, pv in prev.items():
            if c not in cur:
                sev(ds, c, {'k': 'del', 'n': pv[0], 't': pv[3], 'la': pv[1], 'lo': pv[2], 'lines': []}); n_ev += 1
    else:
        print(ds, '— נקודת עיגון ראשונה:', len(cur), 'תחנות')
    print(ds, '|', len(cur), 'תחנות | אירועים עד כה:', n_ev)
    prev = cur
    state = {'last_date': ds, 'stops': prev}
    # שמירה לפי שעון ולא לפי מונה אירועים: התנאי הקודם (n_ev % 2000 < 50)
    # יכול לדלג על החלון כולו כשיום אחד מוסיף מאות אירועים, ואז ריצה של
    # שעות נשמרת רק בסוף.
    if time.time() - t_flush > 300:
        flush(); t_flush = time.time()

flush()
print('סיום ריצה:', n_ev, 'אירועי תחנות | נדגם עד', state.get('last_date'))
