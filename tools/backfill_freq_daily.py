# -*- coding: utf-8 -*-
# "הקו בזמן" — סריקת תדירות ולוח זמנים מארכיון ה-GTFS: כמה יציאות מתוכננות
# יש לכל וריאנט בכל יום ובאילו שעות, וזיהוי שינויים לאורך זמן.
#
# לכל יום נשלפות שעות היציאה (departure_time של התחנה הראשונה) לכל וריאנט.
# ההשוואה נעשית בתוך "דלי" לכל יום בשבוע בנפרד (בישראל לחמישי ולשישי יש
# בדרך כלל לוח משלהם) — יום ראשון מושווה רק ליום ראשון קודם וכן הלאה.
#
# מדיניות רעש: שינוי נרשם רק אם החזיק מעמד 14 יום לפחות (וב-2 תצפיות
# לפחות באותו דלי). ככה חגים, חול המועד וימים חריגים נבלעים בשקט —
# אותה רוח כמו מדיניות ההפסקות של סריקת הקווים (GAP_OK). שינוי אמיתי
# משנה כמה ימי שבוע בבת אחת — חלון איחוד של 12 יום מקבץ אותם לאירוע אחד.
#
# סוגי אירוע חדשים בקובצי הווריאנטים:
#   freq  — מספר היציאות השתנה   sched — אותן כמויות, שעות אחרות
#
# checkpoint: freq-state.json. אחרי הריצה: build_line_changes.py לפיד.
import csv
import datetime
import io
import json
import os
import re
import struct
import sys
import time
import urllib.request
import zlib

S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
FROM = os.environ.get('FROM', '2022-01-16')
TO = os.environ.get('TO', '2026-07-24')   # משם ואילך ימשיך הצינור היומי
MAX_MIN = float(os.environ.get('MAX_MIN', '330'))
PAUSE = float(os.environ.get('PAUSE', '0.03'))
PERSIST_DAYS = 14   # שינוי חייב להחזיק שבועיים כדי להירשם
PERSIST_OBS = 2     # ובלפחות שתי תצפיות באותו דלי
T0 = time.time()

MERGE_WIN = 12   # אירועים מאותו סוג בתוך החלון = אותו שינוי (ימי שבוע שונים)
DAY_HE = {6: 'א', 0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש'}


def bucket_of(ds):
    return DAY_HE[datetime.date.fromisoformat(ds).weekday()]


def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (freq scan; polite)'})
            if rng:
                req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
                time.sleep(PAUSE)
                return data, r.headers
        except Exception as e:
            print(f'  retry {attempt+1}: {e}', file=sys.stderr)
            time.sleep(6 * (attempt + 1))
    raise SystemExit(f'HTTP failed: {url}')


def central_dir(url):
    tail, h = http(url, 'bytes=-66000')
    total = int((h.get('Content-Range') or '/0').rsplit('/', 1)[-1])
    i = tail.rfind(b'PK\x05\x06')
    if i < 0:
        raise ValueError('EOCD not found')
    cd_size, cd_off = struct.unpack('<II', tail[i + 12:i + 20])
    if cd_off == 0xFFFFFFFF:
        j = tail.rfind(b'PK\x06\x06')
        cd_size, cd_off = struct.unpack('<QQ', tail[j + 40:j + 56])
    base = total - len(tail)
    cd = tail[cd_off - base:cd_off - base + cd_size] if base <= cd_off else http(url, f'bytes={cd_off}-{cd_off + cd_size - 1}')[0]
    members = {}
    p = 0
    while p + 46 <= len(cd):
        if cd[p:p + 4] != b'PK\x01\x02':
            break
        method, = struct.unpack('<H', cd[p + 10:p + 12])
        csize, = struct.unpack('<I', cd[p + 20:p + 24])
        nlen, xlen, clen = struct.unpack('<HHH', cd[p + 28:p + 34])
        lho, = struct.unpack('<I', cd[p + 42:p + 46])
        members[cd[p + 46:p + 46 + nlen].decode()] = (lho, csize, method)
        p += 46 + nlen + xlen + clen
    return members


def member_bytes(url, members, name):
    lho, csize, method = members[name]
    lh, _ = http(url, f'bytes={lho}-{lho + 29}')
    n2, x2 = struct.unpack('<HH', lh[26:30])
    off = lho + 30 + n2 + x2
    raw, _ = http(url, f'bytes={off}-{off + csize - 1}')
    return zlib.decompressobj(-15).decompress(raw) if method == 8 else raw


def stream_member(url, members, name, cb):
    lho, csize, method = members[name]
    lh, _ = http(url, f'bytes={lho}-{lho + 29}')
    n2, x2 = struct.unpack('<HH', lh[26:30])
    off = lho + 30 + n2 + x2
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (freq scan; polite)',
                                              'Range': f'bytes={off}-{off + csize - 1}'})
    d = zlib.decompressobj(-15)
    with urllib.request.urlopen(req, timeout=300) as r:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            cb(d.decompress(b))
    cb(d.flush())


def csvdict(url, members, name):
    rd_ = csv.reader(io.StringIO(member_bytes(url, members, name).decode('utf-8-sig')))
    hdr = next(rd_)
    return {h.strip(): i for i, h in enumerate(hdr)}, rd_


def list_dates():
    dates = []
    ym = datetime.date.fromisoformat(FROM[:7] + '-01')
    while ym.isoformat()[:7] <= TO[:7]:
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ym.year}/{ym.month:02d}/')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if FROM <= ds <= TO:
                dates.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(dates))


def day_departures(ds):
    """rd -> רשימת שעות יציאה (HH:MM, ממוינות) של כל היציאות המתוכננות ביום."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    try:
        members = central_dir(url)
        wd = datetime.date.fromisoformat(ds).weekday()
        col = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][wd]
        dsc = ds.replace('-', '')
        c, rows = csvdict(url, members, 'calendar.txt')
        svc = set()
        for row in rows:
            try:
                if row[c[col]].strip() == '1' and row[c['start_date']] <= dsc <= row[c['end_date']]:
                    svc.add(row[c['service_id']])
            except IndexError:
                continue
        try:
            c, rows = csvdict(url, members, 'calendar_dates.txt')
            for row in rows:
                try:
                    if row[c['date']] != dsc:
                        continue
                    if row[c['exception_type']].strip() == '1':
                        svc.add(row[c['service_id']])
                    else:
                        svc.discard(row[c['service_id']])
                except IndexError:
                    continue
        except (KeyError, ValueError):
            pass
        c, rows = csvdict(url, members, 'routes.txt')
        rid2rd = {}
        for row in rows:
            try:
                parts = row[c['route_desc']].strip().split('-')
                mkt = parts[0].lstrip('0') if parts else ''
                if len(parts) >= 3 and mkt:
                    rid2rd[row[c['route_id']]] = f"{mkt}-{parts[1]}-{parts[2]}"
            except IndexError:
                continue
        c, rows = csvdict(url, members, 'trips.txt')
        trip2rd = {}
        for row in rows:
            try:
                if row[c['service_id']] in svc:
                    rd2 = rid2rd.get(row[c['route_id']])
                    if rd2:
                        trip2rd[row[c['trip_id']].encode()] = rd2
            except IndexError:
                continue

        deps = {}
        buf = [b'']
        hdr = {}

        def on_chunk(data):
            buf[0] += data
            *lines, buf[0] = buf[0].split(b'\n')
            for ln in lines:
                if not hdr:
                    for i, hname in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                        hdr[hname.strip()] = i
                    hdr['_t'], hdr['_d'], hdr['_s'] = hdr['trip_id'], hdr['departure_time'], hdr['stop_sequence']
                    continue
                f = ln.split(b',')
                try:
                    if f[hdr['_s']].strip() != b'1':
                        continue
                    rd2 = trip2rd.get(f[hdr['_t']].strip())
                    if rd2 is None:
                        continue
                    deps.setdefault(rd2, []).append(f[hdr['_d']][:5].decode())
                except (IndexError, UnicodeDecodeError):
                    continue

        stream_member(url, members, 'stop_times.txt', on_chunk)
        return {rd2: sorted(ts) for rd2, ts in deps.items()}
    except (ValueError, KeyError, zlib.error) as e:
        print(ds, '— קובץ בעייתי:', e)
        return None


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def fmt_times(ts, cap=5):
    out = ', '.join(ts[:cap])
    if len(ts) > cap:
        out += f' ועוד {len(ts) - cap}'
    return out


n_ev = 0


def write_event(rd2, ds, kind, note):
    """מוסיף אירוע לקובץ הווריאנט. שינוי אמיתי נוגע בכמה ימי שבוע —
    אירוע מאותו סוג בתוך חלון האיחוד מייצג את כולם, ולא נכפל."""
    global n_ev
    p = f'{OUTDIR}/lines/{fsafe(rd2)}.json'
    lf = jload(p, None)
    if lf is None:
        return False   # וריאנט בלי קובץ (לא בסריקה הראשית) — לא יוצרים חלקי
    for v in lf['versions']:
        if v.get('k') == kind and abs(days_between(v['d'], ds)) <= MERGE_WIN:
            return False
    lf['versions'].append({'d': ds, 'k': kind, 'shp': '', 'stops': [], 'src': 'ob', 'note': note})
    lf['versions'].sort(key=lambda x: x['d'])
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n_ev += 1
    return True


BUCKET_HE = {'א': 'ימי ראשון', 'ב': 'ימי שני', 'ג': 'ימי שלישי', 'ד': 'ימי רביעי',
             'ה': 'ימי חמישי', 'ו': 'ימי שישי', 'ש': 'שבת'}


def diff_note(bucket, old_ts, new_ts):
    """בונה את טקסט האירוע ומחזיר (kind, note)."""
    bh = BUCKET_HE[bucket]
    if len(old_ts) != len(new_ts):
        note = f'מספר היציאות ({bh}) השתנה מ-{len(old_ts)} ל-{len(new_ts)}'
        added = sorted(set(new_ts) - set(old_ts))
        removed = sorted(set(old_ts) - set(new_ts))
        if added:
            note += f' · נוספו: {fmt_times(added)}'
        if removed:
            note += f' · ירדו: {fmt_times(removed)}'
        return 'freq', note
    added = sorted(set(new_ts) - set(old_ts))
    removed = sorted(set(old_ts) - set(new_ts))
    note = f'לוח הזמנים ({bh}, {len(new_ts)} יציאות) השתנה'
    if added and removed:
        note += f' · שעות חדשות: {fmt_times(added)} · במקום: {fmt_times(removed)}'
    return 'sched', note


statep = f'{OUTDIR}/freq-state.json'
state = jload(statep, {})
committed = state.get('committed') or {}   # rd -> {bucket: "05:20,06:10,..."}
pending = state.get('pending') or {}       # rd -> {bucket: {d, sig, n}}
dates = [d for d in list_dates() if d > (state.get('last_date') or '')]
if state.get('last_date'):
    print('ממשיך מ-', state['last_date'])
print(len(dates), 'ימים לסריקה')


def save_state(last_ds):
    state.update({'last_date': last_ds, 'committed': committed, 'pending': pending})
    json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


done = 0
for ds in dates:
    if (time.time() - T0) / 60 > MAX_MIN:
        print('הגעתי למגבלת הזמן — checkpoint ויציאה')
        break
    deps = day_departures(ds)
    if deps is None:
        save_state(ds)
        continue
    b = bucket_of(ds)
    for rd2, ts in deps.items():
        sig = ','.join(ts)
        cm = committed.setdefault(rd2, {})
        if b not in cm:
            cm[b] = sig                      # תצפית ראשונה — בסיס שקט
            pending.get(rd2, {}).pop(b, None)
            continue
        if sig == cm[b]:                     # חזרה למוכר — שינוי זמני נבלע
            pending.get(rd2, {}).pop(b, None)
            continue
        pd = pending.setdefault(rd2, {}).get(b)
        if pd is None or pd['sig'] != sig:
            pending[rd2][b] = {'d': ds, 'sig': sig, 'n': 1}
            continue
        pd['n'] += 1
        if pd['n'] >= PERSIST_OBS and days_between(pd['d'], ds) >= PERSIST_DAYS:
            old_ts = cm[b].split(',') if cm[b] else []
            kind, note = diff_note(b, old_ts, sig.split(','))
            write_event(rd2, pd['d'], kind, note)
            cm[b] = sig
            pending[rd2].pop(b, None)
    done += 1
    save_state(ds)
    if done % 20 == 0:
        el = (time.time() - T0) / 60
        print(f'{ds} | {done}/{len(dates)} ימים | {n_ev} אירועים | {el:.0f} דק')

print(f'סיום: {done} ימים, {n_ev} אירועים נכתבו')
