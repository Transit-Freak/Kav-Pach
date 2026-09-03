#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מילוי לאחור של "שינוי שתוכנן ולא נכנס לתוקף" מארכיון אופן באס — 2023 ואילך (בקשת שלמה 03.09).

הסורק היומי (linehistory.py) רושם מהיום: וריאנט או תבנית מסלול שפורסמו
בפיד עם תאריך התחלה עתידי, וירדו מהרישום בלי שנכנסו לתוקף. כאן אותו כלל
בדיוק על הצילומים היומיים של הפיד הארצי בארכיון הסדנא לידע ציבורי:

  · תוכנית = וריאנט (route_desc) שיש לו נסיעות ששירותן מתחיל אחרי יום
    הצילום. סוגה 'new' אם לוריאנט אין נסיעות בתוקף באותו יום, 'route' אם
    יש והרצף המתוכנן שונה מהרצף הפעיל. תבנית עתידית שזהה לפעילה אינה
    תוכנית — כמו בסורק היומי.
  · התוכנית נעקבת מצילום לצילום לפי הווריאנט ורצף התחנות. ביום שבו היא
    נעלמת מהרישום: אם הווריאנט פעיל עם הרצף המתוכנן (או, ב-'new', פעיל
    בכלל) — נכנסה לתוקף, בלי אירוע. אחרת — "תוכנן ולא נכנס לתוקף":
      d  = היום שבו נמצא שהתוכנית ירדה ("בוטל ב-"), וגם pc
      ps = התאריך שבו הייתה אמורה להיכנס לתוקף
      sd = הצילום האחרון שבו עוד נראתה
      pf = הצילום הראשון שבו פורסמה (חסר אם כבר הייתה בצילום הבסיס)
      pstops = רצף התחנות שתוכנן. בכוונה לא 'stops': גרסה עם 'stops' נחשבת
      בכל האתר והכלים למסלול שהקו נסע בו, וזה מסלול שמעולם לא נסע.
  · אמינות (שלמה 03.09): כשבין הצילום האחרון שבו נראתה התוכנית לצילום שבו
    נעלמה יש יותר מ-MAX_GAP ימים, אי אפשר לדעת אם השינוי לא נכנס או נכנס
    ובוטל בינתיים — לא נרשם אירוע, רק רישום ביומן המצב ('unverified').

סדר וכשלים (הביקורת 03.09): הימים מעובדים בסדר עולה בלבד, ולעולם לא יום
שקודם ליום האחרון שעובד. יום שקריאתו נכשלה (רשת, zip פגום, צילום מדולדל)
נרשם ב-'failed' ונחשב מעובד — הוא פשוט מרחיב את הפער לצילום הבא, וכלל
השבוע מטפל בזה. כך גם השרשור נגמר תמיד.

לכל יום נקראים מהצילום calendar, agency, routes, stops, trips, ומ-stop_times
(בזרימה) רק רצפי הנסיעות הנחוצות. הצילום הראשון בריצה הראשונה הוא בסיס
שקט. האירועים והמצב נכתבים אחרי כל יום. RESET=1 מוחק כל תוצר קודם של הכלי
(גרסאות planned-dropped עם src=ob) ואת המצב. כשהארכיון נגמר (remaining=0)
נכתב planned-first.json: תאריך הפרסום הראשון של התוכניות שעדיין פתוחות
ביום האחרון, והסורק היומי קורא אותו (ולא להפך — שני הכלים לא כותבים לאותו
קובץ מצב).

FROM/TO (YYYY-MM-DD) · MAX_DAYS · MAX_MIN · MAX_GAP (ימים, ברירת מחדל 7) ·
DRY=1 ניתוח בלי כתיבה · RESET=1 איפוס
"""
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/backfill-planned-state.json'
FIRSTS = f'{OUTDIR}/planned-first.json'       # נקרא ע"י הסורק היומי
FROM = os.environ.get('FROM', '2023-01-01')
TO = os.environ.get('TO', '2026-09-02')        # יום לפני בסיס הסורק היומי (03.09.2026)
MAX_DAYS = int(os.environ.get('MAX_DAYS', '0') or 0)
MAX_MIN = float(os.environ.get('MAX_MIN', '0') or 0)
MAX_GAP = int(os.environ.get('MAX_GAP', '7') or 7)
DRY = os.environ.get('DRY') == '1'
RESET = os.environ.get('RESET') == '1'
PAUSE = 0.03
SRC = 'ob'
KIND = 'planned-dropped'
DEGENERATE = 0.5     # צילום עם פחות ממחצית הווריאנטים הפעילים של הצילום הקודם — פגום, לא נמדד
# route_type: כמו בסורק היומי — כל טווח ה-70x הוא אוטובוס, 715 לפי דרישה
BUSX = {'700', '701', '702', '703', '704', '705', '706', '707', '708', '709',
        '710', '711', '712', '713', '714', '716'}
TT = {'2': 'rail', '8': 'taxi', '0': 'lightrail', '5': 'cable', '715': 'demand'}


# ---- גישה לארכיון (על בסיס backfill_freq_daily.py — שם המודול רץ בטעינה ואין לייבא ממנו) ----
def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (planned scan; polite)'})
            if rng:
                req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
                time.sleep(PAUSE)
                return data, r.headers
        except Exception as e:
            print(f'  retry {attempt + 1}: {e}', file=sys.stderr)
            time.sleep(6 * (attempt + 1))
    raise SystemExit(f'HTTP failed: {url}')


def central_dir(url):
    """{שם קובץ: (היסט הכותרת המקומית, גודל דחוס, שיטה)} מתוך ספריית ה-zip.

    Zip64 (הביקורת 03.09): בארכיון הזה כל הגדלים בכותרת הם 0xFFFFFFFF והערכים
    האמיתיים יושבים בשדה ההרחבה 0x0001. בלי לקרוא אותו, כל קובץ קטן הוריד
    את ה-zip כולו (פי שישה תעבורה ליום)."""
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
        csize, usize = struct.unpack('<II', cd[p + 20:p + 28])
        nlen, xlen, clen = struct.unpack('<HHH', cd[p + 28:p + 34])
        lho, = struct.unpack('<I', cd[p + 42:p + 46])
        extra = cd[p + 46 + nlen:p + 46 + nlen + xlen]
        q = 0
        while q + 4 <= len(extra):
            hid, hsz = struct.unpack('<HH', extra[q:q + 4])
            body = extra[q + 4:q + 4 + hsz]
            if hid == 1:
                r = 0
                if usize == 0xFFFFFFFF and r + 8 <= len(body):
                    usize, = struct.unpack('<Q', body[r:r + 8]); r += 8
                if csize == 0xFFFFFFFF and r + 8 <= len(body):
                    csize, = struct.unpack('<Q', body[r:r + 8]); r += 8
                if lho == 0xFFFFFFFF and r + 8 <= len(body):
                    lho, = struct.unpack('<Q', body[r:r + 8]); r += 8
                break
            q += 4 + hsz
        members[cd[p + 46:p + 46 + nlen].decode()] = (lho, csize, method)
        p += 46 + nlen + xlen + clen
    return members


def _data_offset(url, lho):
    lh, _ = http(url, f'bytes={lho}-{lho + 29}')
    n2, x2 = struct.unpack('<HH', lh[26:30])
    return lho + 30 + n2 + x2


def member_bytes(url, members, name):
    lho, csize, method = members[name]
    off = _data_offset(url, lho)
    raw, _ = http(url, f'bytes={off}-{off + csize - 1}')
    return zlib.decompressobj(-15).decompress(raw) if method == 8 else raw


def stream_member(url, members, name, cb):
    lho, csize, method = members[name]
    off = _data_offset(url, lho)
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (planned scan; polite)',
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


def list_dates(frm, to):
    dates = []
    ym = datetime.date.fromisoformat(frm[:7] + '-01')
    while ym.isoformat()[:7] <= to[:7]:
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ym.year}/{ym.month:02d}/')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if frm <= ds <= to:
                dates.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(dates))


# ---- עזרים ----
def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def jdump(obj, p):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def _fmtd(d):
    return f'{d[8:10]}.{d[5:7]}.{d[:4]}' if d and len(d) == 10 else (d or '')


def note_for(old, ds):
    what = 'הווריאנט' if old.get('kind') == 'new' else 'המסלול החדש'
    s = f"שינוי שתוכנן ל-{_fmtd(old.get('start'))} לא נכנס לתוקף: {what} בוטל ב-{_fmtd(ds)}, ירד מהרישום לפני שהתחיל"
    if old.get('last') and days_between(old['last'], ds) > 1:
        s += f" (נראה לאחרונה בצילום {_fmtd(old['last'])})"
    if old.get('first'):
        s += f" · פורסם לראשונה ב-{_fmtd(old['first'])}"
    return s + ' (מארכיון אופן באס)'


# ---- קריאת צילום אחד ----
def day_snapshot(ds, watch):
    """מחזיר (active, planned) ליום אחד.

    active:  rd -> {'codes': רצף הנציג הפעיל (None אם לא נקרא), 'alts': קבוצת רצפי כל התבניות הפעילות שנקראו}
             וריאנט פעיל שאינו מתוכנן ואינו במעקב מופיע בקיום בלבד.
    planned: rd -> תוכנית {'kind','start','codes','stopinfo','line','long','op','tt'}
    watch:   הווריאנטים שתוכניתם פתוחה — עבורם נקראות כל התבניות הפעילות (לבדיקת "נכנס לתוקף").
    """
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    members = central_dir(url)
    dsc = ds.replace('-', '')
    # לוח השירות: חלון התוקף בלבד, בלי דגלי ימי השבוע — כמו הסורק היומי
    c, rows = csvdict(url, members, 'calendar.txt')
    active_svc, future = set(), {}
    for row in rows:
        try:
            sd = row[c['start_date']].strip() or '00000000'
            ed = row[c['end_date']].strip() or '99999999'
            if sd <= dsc <= ed:
                active_svc.add(row[c['service_id']])
            elif sd > dsc:
                future[row[c['service_id']]] = f'{sd[:4]}-{sd[4:6]}-{sd[6:]}'
        except IndexError:
            continue
    ag = {}
    try:
        c, rows = csvdict(url, members, 'agency.txt')
        for row in rows:
            try:
                ag[row[c['agency_id']]] = row[c['agency_name']]
            except IndexError:
                continue
    except KeyError:
        pass
    c, rows = csvdict(url, members, 'routes.txt')
    routes = {}
    for row in rows:
        try:
            rt = (row[c['route_type']].strip() if 'route_type' in c else '') or '3'
            if rt in BUSX:
                rt = '3'
            if rt != '3' and rt not in TT:
                continue
            rd = row[c['route_desc']].strip()
            if not rd:
                continue
            routes[row[c['route_id']]] = {'rd': rd, 'line': row[c['route_short_name']], 'long': row[c['route_long_name']],
                                          'ag': row[c['agency_id']] if 'agency_id' in c else '', 'tt': TT.get(rt)}
        except IndexError:
            continue
    # נסיעות: תבניות פעילות ותבניות עתידיות, לכל route_id
    c, rows = csvdict(url, members, 'trips.txt')
    acnt, afirst, fcnt, ffirst, fstart = {}, {}, {}, {}, {}
    for row in rows:
        try:
            rid = row[c['route_id']]
            if rid not in routes:
                continue
            svc = row[c['service_id']]
            sh = row[c['shape_id']].strip() if 'shape_id' in c else ''
            t = row[c['trip_id']]
        except IndexError:
            continue
        if not sh:
            continue          # נציג חייב שרטוט — כמו בסורק היומי
        if svc in active_svc:
            d = acnt.setdefault(rid, {})
            d[sh] = d.get(sh, 0) + 1
            if (rid, sh) not in afirst or t < afirst[(rid, sh)]:
                afirst[(rid, sh)] = t
        elif svc in future:
            d = fcnt.setdefault(rid, {})
            d[sh] = d.get(sh, 0) + 1
            if (rid, sh) not in ffirst or t < ffirst[(rid, sh)]:
                ffirst[(rid, sh)] = t
            fs = future[svc]
            if rid not in fstart or fs < fstart[rid]:
                fstart[rid] = fs
    # הנציג: התבנית שרוב הנסיעות רצות בה, ובתוכה מזהה הנסיעה הקטן ביותר (כמו בסורק היומי).
    # וריאנט יכול להופיע בכמה route_id (רישוי מחודש): הרצף הפעיל של הווריאנט הוא של
    # ה-route_id שרוב הנסיעות הפעילות שלו (הביקורת 03.09, סעיף 4).
    rep = {rid: min(shs, key=lambda x: (-shs[x], x)) for rid, shs in acnt.items()}
    frep = {rid: min(shs, key=lambda x: (-shs[x], x)) for rid, shs in fcnt.items()}
    main_rid = {}
    for rid, shs in acnt.items():
        rd = routes[rid]['rd']
        tot = sum(shs.values())
        if rd not in main_rid or tot > main_rid[rd][0]:
            main_rid[rd] = (tot, rid)
    rds_f = {routes[rid]['rd'] for rid in fcnt}
    want = set()
    for rid in fcnt:
        want.add(ffirst[(rid, frep[rid])])
    for rid, shs in acnt.items():
        rd = routes[rid]['rd']
        if rd in rds_f:
            want.add(afirst[(rid, rep[rid])])
        if rd in watch:
            for sh in shs:
                want.add(afirst[(rid, sh)])
    c, rows = csvdict(url, members, 'stops.txt')
    stops = {}
    for row in rows:
        try:
            stops[row[c['stop_id']]] = [(row[c['stop_code']] or '').strip() or row[c['stop_id']],
                                        ' '.join(row[c['stop_name']].split()),
                                        round(float(row[c['stop_lat']]), 5), round(float(row[c['stop_lon']]), 5)]
        except (IndexError, ValueError):
            continue
    # רצפי התחנות — רק לנסיעות הנחוצות, בזרימה על stop_times
    wantb = {t.encode() for t in want}
    seqs = {}
    buf = [b'']
    hdr = {}

    def on_chunk(data):
        buf[0] += data
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not hdr:
                for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr[h.strip()] = i
                hdr['_t'], hdr['_s'], hdr['_q'] = hdr['trip_id'], hdr['stop_id'], hdr['stop_sequence']
                continue
            f = ln.split(b',')
            try:
                t = f[hdr['_t']].strip()
                if t not in wantb:
                    continue
                seqs.setdefault(t, []).append((int(f[hdr['_q']]), f[hdr['_s']].strip().decode()))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    if wantb:
        stream_member(url, members, 'stop_times.txt', on_chunk)
        if buf[0].strip():
            on_chunk(b'\n')          # שורה אחרונה בלי סיום שורה
        if not seqs:
            raise ValueError('stop_times ריק — צילום פגום')

    def stopinfo_of(t):
        return [stops[s] for _, s in sorted(seqs.get(t.encode(), [])) if s in stops]

    active, planned = {}, {}
    for rid, shs in acnt.items():
        rd = routes[rid]['rd']
        a = active.setdefault(rd, {'codes': None, 'alts': set()})
        for sh in shs:
            t = afirst[(rid, sh)]
            if t not in want:
                continue
            cl = tuple(x[0] for x in stopinfo_of(t))
            if len(cl) < 2:
                continue
            a['alts'].add(cl)
            if sh == rep.get(rid) and main_rid[rd][1] == rid:
                a['codes'] = list(cl)
    for rid in sorted(fcnt, key=lambda r: sum(fcnt[r].values())):   # הגדול אחרון = קובע
        info = routes[rid]
        rd = info['rd']
        si = stopinfo_of(ffirst[(rid, frep[rid])])
        cl = [x[0] for x in si]
        if len(cl) < 2:
            continue
        a = active.get(rd)
        if a is None:
            kind = 'new'
        elif a['codes'] is None or cl == a['codes']:
            continue      # תבנית עתידית זהה לפעילה — אינה שינוי
        else:
            kind = 'route'
        planned[rd] = {'kind': kind, 'start': fstart.get(rid, ''), 'codes': cl, 'stopinfo': si,
                       'line': info['line'], 'long': info['long'], 'op': ag.get(info['ag'], ''), 'tt': info['tt']}
    return active, planned


# ---- כתיבה ----
def write_events(events):
    """events: [(ds, rd, plan)] — גרסה בקובץ הקו ושורה בפיד החודשי. אידמפוטנטי.
    מפתח הכפילות (d, k) כמו בסורק היומי: תוכנית אחת לווריאנט ליום."""
    by_month = {}
    for ds, rd, old in events:
        p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
        lf = materialize(jload(p, None))
        if lf is None:
            lf = {'rd': rd, 'line': old.get('line', ''), 'dest': old.get('long', ''), 'op': old.get('op', ''), 'ty': '', 'versions': []}
            if old.get('tt'):
                lf['tt'] = old['tt']
        vs = [v for v in (lf.get('versions') or []) if not (v.get('k') == KIND and v.get('d') == ds)]
        v = {'d': ds, 'k': KIND, 'src': SRC, 'ps': old.get('start', ''), 'pc': ds,
             'pstops': old.get('stopinfo') or [], 'note': note_for(old, ds)}
        if old.get('last'):
            v['sd'] = old['last']
        if old.get('first'):
            v['pf'] = old['first']
        vs.append(v)
        vs.sort(key=lambda x: x['d'])
        lf['versions'] = vs
        jdump(compact(lf), p)
        row = {'d': ds, 'rd': rd, 'line': old.get('line', ''), 'op': old.get('op', ''),
               'k': KIND, 'src': SRC, 'ps': old.get('start', ''), 'pc': ds}
        if old.get('last'):
            row['sd'] = old['last']
        by_month.setdefault(ds[:7], []).append(row)
    for month, chs in by_month.items():
        p = f'{OUTDIR}/changes/{month}.json'
        m = jload(p, {'month': month, 'changes': []})
        keys = {(x['rd'], x['d']) for x in chs}
        m['changes'] = [x for x in m['changes'] if not (x.get('k') == KIND and (x.get('rd'), x.get('d')) in keys)] + chs
        m['changes'].sort(key=lambda x: x.get('d', ''))
        jdump(m, p)


def reset_previous():
    """מחיקת כל תוצר קודם של הכלי: גרסאות planned-dropped עם src=ob בקווים ובפיד החודשי, המצב, וקובץ התאריכים."""
    n_l = n_f = 0
    ld = f'{OUTDIR}/lines'
    for f in os.listdir(ld):
        if not f.endswith('.json'):
            continue
        p = f'{ld}/{f}'
        lf = materialize(jload(p, None))
        if not lf:
            continue
        vs = lf.get('versions') or []
        keep = [v for v in vs if not (v.get('k') == KIND and v.get('src') == SRC)]
        if len(keep) == len(vs):
            continue
        n_l += len(vs) - len(keep)
        if keep:
            lf['versions'] = keep
            jdump(compact(lf), p)
        else:
            os.remove(p)      # קובץ שנוצר רק בשביל התוכנית שלא התממשה
            n_f += 1
    n_m = 0
    for f in os.listdir(f'{OUTDIR}/changes'):
        p = f'{OUTDIR}/changes/{f}'
        m = jload(p, None)
        if not m or 'changes' not in m:
            continue
        before = len(m['changes'])
        m['changes'] = [x for x in m['changes'] if not (x.get('k') == KIND and x.get('src') == SRC)]
        if len(m['changes']) != before:
            n_m += before - len(m['changes'])
            jdump(m, p)
    for p in (STATE, FIRSTS):
        if os.path.exists(p):
            os.remove(p)
    print(f'איפוס: נמחקו {n_l} גרסאות קו ({n_f} קבצים שנותרו ריקים), {n_m} שורות חודשיות', file=sys.stderr)


def write_firsts(plans, final_day):
    """התוכניות שעדיין פתוחות ביום האחרון של הארכיון קיימות גם במצב הסורק היומי
    (שנפתח ב-03.09.2026 בלי לדעת מתי פורסמו). כאן נכתב קובץ צד עם תאריך הפרסום
    הראשון שלהן; הסורק קורא אותו ומאמץ את התאריך כשרצף התחנות זהה. רק בסוף
    הארכיון — תוכנית שפתוחה באמצע 2023 אינה בהכרח אותה תוכנית של 2026."""
    out = {rd: {'codes': P.get('codes'), 'first': P.get('first')} for rd, P in plans.items()
           if P.get('first') and P.get('last') == final_day}
    jdump({'archive_end': final_day, 'plans': out}, FIRSTS)
    return len(out)


def main():
    if RESET and not DRY:
        reset_previous()
    st = jload(STATE, {'done': [], 'failed': [], 'plans': {}, 'unverified': [], 'n_started': 0, 'n_dropped': 0, 'n_unverified': 0})
    done = set(st['done'])
    plans = st.get('plans') or {}
    dates = list_dates(FROM, TO)
    last_ds = max(done) if done else None
    # לעולם לא אחורה: יום שלא עובד ונמצא לפני היום האחרון שעובד — נחשב כמעובד (אבוד)
    late = [d for d in dates if d not in done and (last_ds is None or d > last_ds)]
    stale = [d for d in dates if d not in done and last_ds is not None and d <= last_ds]
    for d in stale:
        st.setdefault('failed', []).append({'d': d, 'err': 'קודם ליום האחרון שעובד — לא מעובד'})
        done.add(d)
    todo = late[:MAX_DAYS] if MAX_DAYS else late
    print(f'צילומים בטווח: {len(dates)} · כבר עובדו: {len(done)} · בריצה זו: {len(todo)}'
          + (f' · דולגו כי קודמים ליום האחרון: {len(stale)}' if stale else ''), file=sys.stderr)

    def save():
        st['done'] = sorted(done)
        st['plans'] = plans
        st['remaining'] = len([d for d in dates if d not in done])
        st['updated'] = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
        jdump(st, STATE)

    if not todo:
        if not DRY:
            save()
            if st['remaining'] == 0 and dates and plans:
                print(f'תאריכי פרסום ראשון לסורק היומי: {write_firsts(plans, max(done))}', file=sys.stderr)
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return
    baseline = not plans and not done
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    n_ev = 0
    for ds in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר — נעצר בין צילומים', file=sys.stderr)
            break
        t0 = time.monotonic()
        err = None
        try:
            active, planned = day_snapshot(ds, set(plans))
            prev_n = st.get('prev_active') or 0
            if prev_n and len(active) < DEGENERATE * prev_n:
                err = f'צילום מדולדל: {len(active)} וריאנטים פעילים מול {prev_n} בצילום הקודם'
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            err = f'{type(e).__name__}: {str(e)[:80]}'
        if err:
            # יום אבוד: נרשם, נחשב מעובד, והפער לצילום הבא גדל — כלל השבוע מטפל בזה
            print(f'  {ds}: דילוג — {err}', file=sys.stderr)
            st.setdefault('failed', []).append({'d': ds, 'err': err})
            done.add(ds)
            if not DRY:
                save()
            continue
        events = []
        n_started = n_unv = 0
        if baseline:
            plans = {rd: {**P, 'first': None, 'last': ds} for rd, P in planned.items()}
            baseline = False
        else:
            gap = days_between(last_ds, ds) if last_ds else None
            for rd, old in list(plans.items()):
                if rd in planned:
                    continue
                a = active.get(rd)
                took = a is not None and (old.get('kind') == 'new' or old.get('codes') == a['codes']
                                          or tuple(old.get('codes') or ()) in a['alts'])
                if took:
                    n_started += 1
                elif gap is not None and gap > MAX_GAP:
                    n_unv += 1
                    st['unverified'] = (st.get('unverified') or [])[-300:] + [
                        {'rd': rd, 'line': old.get('line', ''), 'ps': old.get('start', ''), 'last': old.get('last'), 'd': ds, 'gap': gap}]
                else:
                    events.append((ds, rd, old))
                plans.pop(rd)
            for rd, P in planned.items():
                old = plans.get(rd)
                same = old is not None and old.get('codes') == P['codes']
                plans[rd] = {**P, 'first': (old.get('first') if same else ds), 'last': ds}
        done.add(ds)
        last_ds = ds
        st['prev_active'] = len(active)
        n_ev += len(events)
        st['n_started'] = st.get('n_started', 0) + n_started
        st['n_dropped'] = st.get('n_dropped', 0) + len(events)
        st['n_unverified'] = st.get('n_unverified', 0) + n_unv
        print(f'  {ds}: פעילים {len(active)} · תוכניות פתוחות {len(plans)} · נכנסו לתוקף {n_started} · לא נכנסו {len(events)}'
              f' · לא ניתן לאמת {n_unv} · {time.monotonic() - t0:.0f} שנ׳', file=sys.stderr)
        if DRY:
            for ds_, rd, old in events[:8]:
                print('     ', rd, old.get('line'), old.get('kind'), old.get('start'), '←', old.get('first'), old.get('last'), file=sys.stderr)
            continue
        if events:
            write_events(events)
        save()
    if not DRY:
        save()
        if st['remaining'] == 0 and plans:
            print(f'הארכיון נגמר — תאריכי פרסום ראשון לסורק היומי: {write_firsts(plans, max(done))}', file=sys.stderr)
    print(f'סיכום הריצה: {n_ev} אירועים "תוכנן ולא נכנס לתוקף" · נותרו {len([d for d in dates if d not in done])} צילומים'
          + (' (DRY)' if DRY else ''), file=sys.stderr)


if __name__ == '__main__':
    main()
