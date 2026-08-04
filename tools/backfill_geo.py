# -*- coding: utf-8 -*-
# "הקו בזמן" — השלמת מסלולים ותחנות לוריאנטים בלי גאומטריה (בעיקר קווים
# שבוטלו לפני שהרישום השוטף התחיל): לכל וריאנט נשלף מהארכיון צילום מהיום
# הסמוך לפעילותו האחרונה — רצף התחנות + שרטוט המסלול — ונכתב כגרסת
# 'snapshot' בקובץ הווריאנט.
#
# אופטימיזציה: יום היעד מוצמד לתחילת החודש (אם הווריאנט כבר פעל אז) —
# מקבץ אלפי וריאנטים לכ-100 ימי-ארכיון במקום מאות.
#
# checkpoint: geo-state.json (ימים שהושלמו). ריצה מקומית במחזורים, כמו
# סריקת התדירות. אחרי הסיום: rebuild_lines_index.py (קטגוריות ks).
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
MAX_MIN = float(os.environ.get('MAX_MIN', '8'))
MAX_DAYS_ENV = int(os.environ.get('MAX_DAYS', '0'))
ARC_LO, ARC_HI = '2022-01-16', '2026-07-24'
T0 = time.time()


def http(url, rng=None, tries=4):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (geo completion; polite)'})
            if rng:
                req.add_header('Range', rng)
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read(), r.headers
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


def stream_member(url, members, name, cb):
    lho, csize, method = members[name]
    lh, _ = http(url, f'bytes={lho}-{lho + 29}')
    n2, x2 = struct.unpack('<HH', lh[26:30])
    off = lho + 30 + n2 + x2
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (geo completion; polite)',
                                              'Range': f'bytes={off}-{off + csize - 1}'})
    d = zlib.decompressobj(-15)
    with urllib.request.urlopen(req, timeout=300) as r:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            cb(d.decompress(b))
    cb(d.flush())


def member_rows(url, members, name):
    buf = io.BytesIO()
    stream_member(url, members, name, buf.write)
    rd_ = csv.reader(io.StringIO(buf.getvalue().decode('utf-8-sig')))
    hdr = next(rd_)
    return {h.strip(): i for i, h in enumerate(hdr)}, rd_


def enc_polyline(coords):
    """קידוד פוליליין (precision 5) — הפורמט שהאתר קורא."""
    out = []
    plat = plon = 0
    for la, lo in coords:
        ila, ilo = round(la * 1e5), round(lo * 1e5)
        for v in (ila - plat, ilo - plon):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plon = ila, ilo
    return ''.join(out)


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def list_available_days():
    """הימים שבאמת קיימים בארכיון (יש בו חורים) — דרך רשימת ה-S3."""
    days = []
    ym = datetime.date.fromisoformat(ARC_LO[:7] + '-01')
    while ym.isoformat()[:7] <= ARC_HI[:7]:
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ym.year}/{ym.month:02d}/')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if ARC_LO <= ds <= ARC_HI:
                days.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(days))


def nearest_available(t, avail):
    """היום הזמין הקרוב ביותר עד t (ואם אין — הראשון אחריו)."""
    import bisect
    i = bisect.bisect_right(avail, t)
    return avail[i - 1] if i else avail[0]


def thin(coords, min_m=12):
    if len(coords) < 3:
        return coords
    out = [coords[0]]
    for c in coords[1:-1]:
        dy = (c[0] - out[-1][0]) * 111000
        dx = (c[1] - out[-1][1]) * 89000
        if dy * dy + dx * dx >= min_m * min_m:
            out.append(c)
    out.append(coords[-1])
    return out


# ---- אילו וריאנטים חסרים ומה יום היעד של כל אחד ----
def build_targets(avail):
    targets = {}   # יום -> [rd, ...]
    dd = f'{OUTDIR}/lines'
    for fn in os.listdir(dd):
        if not fn.endswith('.json'):
            continue
        lf = json.load(open(f'{dd}/{fn}', encoding='utf-8'))
        vs = lf.get('versions', [])
        if not vs or any(v.get('shp') for v in vs):
            continue
        rd = lf.get('rd')
        if not rd:
            continue
        t = ARC_HI
        if vs[-1].get('k') == 'removed':
            t = (datetime.date.fromisoformat(vs[-1]['d']) - datetime.timedelta(days=1)).isoformat()
        t = max(min(t, ARC_HI), ARC_LO)
        first = vs[0].get('d') or ARC_LO
        snap = t[:8] + '01'          # הצמדה לתחילת החודש — מקבץ ימים
        if snap >= first and snap >= ARC_LO:
            t = snap
        t = nearest_available(t, avail)   # בארכיון יש חורים — היום הקיים הקרוב
        targets.setdefault(t, []).append(rd)
    return targets


def process_day(ds, rds):
    """שולף מהיום המבוקש תחנות+שרטוט לכל הוריאנטים שברשימה. מחזיר כמה הושלמו."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    want = set(rds)
    try:
        members = central_dir(url)
        c, rows = member_rows(url, members, 'routes.txt')
        rid2rd = {}
        for row in rows:
            try:
                parts = row[c['route_desc']].strip().split('-')
                mkt = parts[0].lstrip('0') if parts else ''
                if len(parts) >= 3 and mkt:
                    rd2 = f"{mkt}-{parts[1]}-{parts[2]}"
                    if rd2 in want:
                        rid2rd[row[c['route_id']]] = rd2
            except IndexError:
                continue
        if not rid2rd:
            return 0
        c, rows = member_rows(url, members, 'trips.txt')
        picked = {}   # rd -> (trip_id, shape_id)
        for row in rows:
            try:
                rd2 = rid2rd.get(row[c['route_id']])
                if rd2 and rd2 not in picked:
                    sid = row[c['shape_id']] if 'shape_id' in c else ''
                    picked[rd2] = (row[c['trip_id']], sid)
            except IndexError:
                continue
        if not picked:
            return 0
        trip2rd = {v[0].encode(): k for k, v in picked.items()}
        shape2rd = {}
        for k, v in picked.items():
            if v[1]:
                shape2rd.setdefault(v[1].encode(), []).append(k)

        # stop_times: רצף התחנות של הנסיעות שנבחרו
        seqs = {}   # rd -> [(seq, stop_id)]
        buf = [b'']
        hdr = {}

        def on_st(data):
            buf[0] += data
            *lines, buf[0] = buf[0].split(b'\n')
            for ln in lines:
                if not hdr:
                    for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                        hdr[h.strip()] = i
                    continue
                f = ln.split(b',')
                try:
                    rd2 = trip2rd.get(f[hdr['trip_id']].strip())
                    if rd2 is None:
                        continue
                    seqs.setdefault(rd2, []).append((int(f[hdr['stop_sequence']]), f[hdr['stop_id']].decode()))
                except (IndexError, ValueError, UnicodeDecodeError):
                    continue

        stream_member(url, members, 'stop_times.txt', on_st)

        # stops: פרטי התחנות הדרושות
        need_stops = {sid for lst in seqs.values() for _, sid in lst}
        c, rows = member_rows(url, members, 'stops.txt')
        sinfo = {}
        for row in rows:
            try:
                sid = row[c['stop_id']]
                if sid in need_stops:
                    sinfo[sid] = [row[c['stop_code']] or sid, row[c['stop_name']].strip(),
                                  round(float(row[c['stop_lat']]), 5), round(float(row[c['stop_lon']]), 5)]
            except (IndexError, ValueError):
                continue

        # shapes: השרטוטים הדרושים
        shp_pts = {}
        buf2 = [b'']
        hdr2 = {}

        def on_shp(data):
            buf2[0] += data
            *lines, buf2[0] = buf2[0].split(b'\n')
            for ln in lines:
                if not hdr2:
                    for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                        hdr2[h.strip()] = i
                    continue
                f = ln.split(b',')
                try:
                    sid = f[hdr2['shape_id']]
                    if sid in shp_wanted:
                        shp_pts.setdefault(sid, []).append((int(f[hdr2['shape_pt_sequence']]),
                                                            float(f[hdr2['shape_pt_lat']]), float(f[hdr2['shape_pt_lon']])))
                except (IndexError, ValueError):
                    continue

        shp_wanted = {k for k in (v[1].encode() if False else v[1] for v in picked.values()) if k}
        shp_wanted = {s.encode() if isinstance(s, str) else s for s in shp_wanted}
        # ההשוואה נעשית על bytes — ממירים
        shp_wanted = {s for s in shp_wanted}
        if shp_wanted:
            try:
                stream_member(url, members, 'shapes.txt', on_shp)
            except (KeyError, ValueError):
                pass

        done = 0
        for rd2, lst in seqs.items():
            lst.sort()
            stops = []
            for _, sid in lst:
                si = sinfo.get(sid)
                if si:
                    stops.append(si)
            if len(stops) < 2:
                continue
            shp = ''
            sid_ = picked[rd2][1]
            pts = shp_pts.get(sid_.encode() if isinstance(sid_, str) else sid_) or shp_pts.get(sid_)
            if pts:
                pts.sort()
                shp = enc_polyline(thin([(p[1], p[2]) for p in pts]))
            p = f'{OUTDIR}/lines/{fsafe(rd2)}.json'
            lf = json.load(open(p, encoding='utf-8'))
            if any(v.get('shp') for v in lf['versions']):
                continue
            lf['versions'].append({'d': ds, 'k': 'snapshot', 'shp': shp, 'stops': stops, 'src': 'ob',
                                   'note': 'המסלול והתחנות הושלמו מהארכיון (צילום סמוך ליום הפעילות האחרון)'})
            lf['versions'].sort(key=lambda x: x['d'])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            done += 1
        return done
    except (ValueError, KeyError, zlib.error) as e:
        print(ds, '— קובץ בעייתי:', e)
        return 0


def main():
    statep = f'{OUTDIR}/geo-state.json'
    try:
        state = json.load(open(statep, encoding='utf-8'))
    except Exception:
        state = {'done_days': []}
    done_days = set(state.get('done_days') or [])
    avail = list_available_days()
    print(f'{len(avail)} ימים זמינים בארכיון')
    targets = build_targets(avail)
    todo = sorted(d for d in targets if d not in done_days)
    print(f'{sum(len(v) for v in targets.values())} וריאנטים ב-{len(targets)} ימים | נותרו {len(todo)} ימים')
    n_done = n_days = 0
    for ds in todo:
        if (time.time() - T0) / 60 > MAX_MIN:
            print('מגבלת זמן — checkpoint ויציאה')
            break
        if MAX_DAYS_ENV and n_days >= MAX_DAYS_ENV:
            break
        got = process_day(ds, targets[ds])
        n_done += got
        n_days += 1
        done_days.add(ds)
        state['done_days'] = sorted(done_days)
        json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'{ds}: {got}/{len(targets[ds])} הושלמו | סה"כ {n_done}')
    print(f'סיום ריצה: {n_days} ימים, {n_done} וריאנטים הושלמו')


if __name__ == '__main__':
    main()
