# -*- coding: utf-8 -*-
# "הקו בזמן" — השלמת "קווים שעצרו בה אז" לאירועי תחנות שנשארו בלי רשימה.
#
# enrich_stop_lines.py ממלא את הרשימות מרצפי הקווים שנאספו, אבל הכיסוי
# שלהם דליל לפני 2025 — כמחצית מהאירועים (וכל 2022) נשארו בלי קווים.
# כאן ממלאים את החסר מהמקור הגולמי: קובצי ה-GTFS היומיים בארכיון אופן
# באס. לכל תאריך-עוגן (חצי-שנתי) בונים מיפוי מלא תחנה→קווים מתוך
# stop_times+trips+routes+stops של אותו יום, ולכל אירוע חסר-קווים לוקחים
# את העוגן הקרוב ביותר בזמן שבו התחנה בכלל מופיעה.
#
# המיפויים נשמרים ב-stops-lines-snap.json כדי שהרצה חוזרת (עם עוגנים
# נוספים) לא תוריד שוב את מה שכבר חולץ. ריצה חד-פעמית; האירועים החדשים
# מקבלים קווים מהרצפים של הצינור היומי.
import csv, io, json, os, re, struct, sys, time, datetime, zlib
import urllib.request

S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
SNAPS = os.environ.get('SNAPS', '2022-02-06,2022-07-01,2023-01-07,2023-07-01,'
                       '2024-01-05,2024-07-01,2025-01-05,2025-07-01,2026-01-05').split(',')
CAP = 15   # אותה תקרה כמו enrich_stop_lines.py

def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (stop-lines snapshots; polite)'})
            if rng: req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read(), r.headers
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(8 * (attempt + 1))
    raise SystemExit(f'HTTP failed: {url}')

def member(url, want):
    """חילוץ קובץ בודד מה-zip בבקשות Range (כמו backfill_stops_gtfs)."""
    tail, h = http(url, 'bytes=-66000')
    total = int((h.get('Content-Range') or '/0').rsplit('/', 1)[-1])
    i = tail.rfind(b'PK\x05\x06')
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
        csize, usize = struct.unpack('<II', cd[p+20:p+28])
        nlen, xlen, clen = struct.unpack('<HHH', cd[p+28:p+34])
        lho, = struct.unpack('<I', cd[p+42:p+46])
        name = cd[p+46:p+46+nlen]
        if csize == 0xFFFFFFFF or lho == 0xFFFFFFFF:
            x = cd[p+46+nlen:p+46+nlen+xlen]; q = 0
            while q + 4 <= len(x):
                hid, hsz = struct.unpack('<HH', x[q:q+4])
                if hid == 1:
                    vals = list(struct.unpack(f'<{hsz//8}Q', x[q+4:q+4+hsz]))
                    if usize == 0xFFFFFFFF: usize = vals.pop(0)
                    if csize == 0xFFFFFFFF: csize = vals.pop(0)
                    if lho == 0xFFFFFFFF: lho = vals.pop(0)
                q += 4 + hsz
        if name.endswith(want):
            lh, _ = http(url, f'bytes={lho}-{lho+29}')
            n2, x2 = struct.unpack('<HH', lh[26:30])
            off = lho + 30 + n2 + x2
            raw, _ = http(url, f'bytes={off}-{off+csize-1}')
            return zlib.decompressobj(-15).decompress(raw) if method == 8 else raw
        p += 46 + nlen + xlen + clen
    raise SystemExit(f'{want} not in {url}')

def member_lines(url, want):
    """כמו member, אבל מפוענח במנות ומחזיר שורות-בייטים אחת-אחת —
    stop_times.txt פרוס הוא ~800MB ואי-אפשר להחזיק אותו בזיכרון."""
    tail, h = http(url, 'bytes=-66000')
    total = int((h.get('Content-Range') or '/0').rsplit('/', 1)[-1])
    i = tail.rfind(b'PK\x05\x06')
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
            dec = zlib.decompressobj(-15) if method == 8 else None
            buf = b''
            CHUNK = 4 << 20
            for k in range(0, len(raw), CHUNK):
                part = dec.decompress(raw[k:k+CHUNK]) if dec else raw[k:k+CHUNK]
                buf += part
                *full, buf = buf.split(b'\n')
                yield from full
            if dec: buf += dec.flush()
            if buf: yield buf
            return
        p += 46 + nlen + xlen + clen
    raise SystemExit(f'{want} not in {url}')

def avail_date(ds):
    """התאריך המבוקש, או היום הזמין הראשון אחריו באותו חודש."""
    xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ds[:4]}/{ds[5:7]}/')
    days = sorted(set(re.findall(rb'/(\d{2})/israel-public-transportation\.zip', xml)))
    days = [d.decode() for d in days]
    for d in days:
        if d >= ds[8:10]: return f'{ds[:8]}{d}'
    return f'{ds[:8]}{days[-1]}' if days else None

def snap_lines(ds):
    """מיפוי קוד-תחנה → רשימת מספרי קווים ליום נתון, מתוך ה-GTFS המלא."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    routes = {}
    rd = csv.reader(io.StringIO(member(url, b'routes.txt').decode('utf-8-sig')))
    hdr = next(rd); c = {h: i for i, h in enumerate(hdr)}
    for row in rd:
        try: routes[row[c['route_id']]] = row[c['route_short_name']].strip()
        except IndexError: continue
    trip2r = {}
    rd = csv.reader(io.StringIO(member(url, b'trips.txt').decode('utf-8-sig')))
    hdr = next(rd); c = {h: i for i, h in enumerate(hdr)}
    for row in rd:
        try: trip2r[row[c['trip_id']]] = row[c['route_id']]
        except IndexError: continue
    sid2code = {}
    rd = csv.reader(io.StringIO(member(url, b'stops.txt').decode('utf-8-sig')))
    hdr = next(rd); c = {h: i for i, h in enumerate(hdr)}
    for row in rd:
        try:
            if row[c['stop_code']].strip(): sid2code[row[c['stop_id']]] = row[c['stop_code']].strip()
        except IndexError: continue
    print(f'  {ds}: {len(routes)} מסלולים, {len(trip2r)} נסיעות — מוריד stop_times…')
    stop_routes = {}
    it = isid = None
    for ln in member_lines(url, b'stop_times.txt'):
        parts = ln.rstrip(b'\r').split(b',')
        if it is None:   # שורת הכותרת
            hdr = [x.decode('utf-8-sig').strip() for x in parts]
            it, isid = hdr.index('trip_id'), hdr.index('stop_id')
            continue
        try:
            rid = trip2r.get(parts[it].decode())
            if rid: stop_routes.setdefault(parts[isid].decode(), set()).add(rid)
        except (IndexError, UnicodeDecodeError): continue
    out = {}
    for sid, rids in stop_routes.items():
        code = sid2code.get(sid)
        if not code: continue
        nums = {routes.get(r, '') for r in rids} - {''}
        if nums: out[code] = sorted(nums, key=lambda x: (int(''.join(ch for ch in x if ch.isdigit()) or 10**9), x))[:CAP]
    print(f'  {ds}: {len(out)} תחנות עם קווים')
    return out

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

# ---- בניית/טעינת העוגנים ----
snapp = f'{OUTDIR}/stops-lines-snap.json'
snaps = jload(snapp, {})
for want in SNAPS:
    if any(d[:7] == want[:7] for d in snaps): continue
    ds = avail_date(want)
    if not ds:
        print(want, '— אין קובץ בארכיון, מדלג'); continue
    snaps[ds] = snap_lines(ds)
    json.dump(snaps, open(snapp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
sdates = sorted(snaps)
print('עוגנים:', sdates)

# ---- השלמת האירועים ----
shist = jload(f'{OUTDIR}/stops-hist.json', {})
months = {}
def mload(m):
    if m not in months: months[m] = jload(f'{OUTDIR}/changes/stops-{m}.json', None)
    return months[m]

def days(a, b):
    return abs((datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days)

filled = 0
for code, evs in shist.items():
    for e in evs:
        if e['k'] not in ('del', 'moved', 'renamed', 'new') or e.get('lines'): continue
        best = None
        for ds in sdates:
            lns = snaps[ds].get(code)
            if not lns: continue
            d = days(ds, e['d'])
            # תחנה חדשה לא קיימת בעוגנים שלפניה — עדיפות לעוגן שאחרי הפתיחה
            if e['k'] == 'new' and ds < e['d']: d += 100000
            if best is None or d < best[0]: best = (d, lns)
        if not best: continue
        e['lines'] = best[1]
        filled += 1
        mm = mload(e['d'][:7])
        if mm:
            for x in mm['changes']:
                if x.get('c') == code and x.get('k') == e['k'] and x.get('d') == e['d']:
                    x['lines'] = best[1]

json.dump(shist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
for m, mm in months.items():
    if mm: json.dump(mm, open(f'{OUTDIR}/changes/stops-{m}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('הושלמו רשימות קווים ל-', filled, 'אירועים')
