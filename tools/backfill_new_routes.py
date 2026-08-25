# -*- coding: utf-8 -*-
"""השלמת מסלול לרשומות "וריאנט חדש" של סריקת-הקיום מהארכיון.

סריקת ארכיון אופן באס (scan_seen_ob) רשמה מתי וריאנט הופיע ברישום —
קיום בלבד, בלי מסלול ובלי תחנות. התוצאה באתר (דיווח שלמה, קו 80 כפר
חב"ד): כרטיס "וריאנט חדש" שמציג את המסלול המתועד הסמוך במקום את מה
שבאמת נסע אז, והשינוי הבא בתור נראה כאילו הוא ממציא תחנות שכבר קיימות.

לכל תאריך עם רשומות כאלה שולפים מצילום הארכיון של אותו יום בדיוק את
המסלול והתחנות של כל הווריאנטים הרלוונטיים בבת אחת, וכותבים אותם על
הרשומה עצמה. וריאנט שרשום בלי נסיעות באותו צילום נשאר קיום-בלבד.

checkpoint: nr-state.json (done/skip) — ריצה חוזרת ממשיכה מאיפה שעצרה.
התאריכים מטופלים מהחדש לישן: הכרטיסים שהמשתמשים רואים קודם נפתרים קודם.

MAX_MIN  תקציב זמן בדקות (ברירת מחדל 45)
DRY=1    ניתוח בלבד, בלי כתיבה
"""
import collections
import glob
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402
from backfill_geo import (S3, central_dir, member_rows, stream_member,  # noqa: E402
                          enc_polyline, thin)

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/nr-state.json'
DRY = os.environ.get('DRY') == '1'
REDO = os.environ.get('REDO') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
PAUSE = float(os.environ.get('PAUSE', '0.6'))
ARC_FROM, ARC_TO = '2022-01-16', '2026-07-24'   # טווח צילומי gtfs_archive
T0 = time.time()
FILLED_MARK = 'הושלמו מצילום הארכיון'


def day_url(ds):
    return f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"


def probe(url):
    """קוד ה-HTTP של היום בארכיון — להבחין בין יום חסר לתקלה זמנית."""
    try:
        req = urllib.request.Request(url, headers={'Range': 'bytes=0-0'})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def day_full_cal(ds, rds):
    """rd -> {'stops': [[code,name,lat,lon]...], 'shp': encoded}.

    כמו day_full של backfill_geo_truth, בשני הבדלים מהותיים: נספרות רק
    נסיעות שבתוקף באותו יום (calendar.txt), והתבנית הנבחרת היא זו שרוב
    הנסיעות רצות בה — אותו כלל בחירה כמו הסורק היומי. בלי הסינון, רשומת
    10.04 של קו 80 קיבלה תבנית-נייר עתידית במקום את המסלול שרץ בפועל."""
    url = day_url(ds)
    want = set(rds)
    members = central_dir(url)
    c, rows = member_rows(url, members, 'routes.txt')
    rid2rd = {}
    for r in rows:
        p = r[c['route_desc']].strip().split('-')
        mkt = p[0].lstrip('0') if p else ''
        if len(p) >= 3 and mkt:
            rd2 = f"{mkt}-{p[1]}-{p[2]}"
            if rd2 in want:
                rid2rd[r[c['route_id']]] = rd2
    ymd = ds.replace('-', '')
    active = None
    try:
        c, rows = member_rows(url, members, 'calendar.txt')
        active = set()
        for r in rows:
            sd = r[c['start_date']] if 'start_date' in c else ''
            ed = r[c['end_date']] if 'end_date' in c else ''
            if (sd or '00000000') <= ymd <= (ed or '99999999'):
                active.add(r[c['service_id']])
    except Exception:
        active = None            # אין לוח שנה בצילום — בלי סינון
    c, rows = member_rows(url, members, 'trips.txt')
    cnt = {}
    first = {}
    for r in rows:
        rd2 = rid2rd.get(r[c['route_id']])
        if not rd2:
            continue
        if active is not None and 'service_id' in c and r[c['service_id']] not in active:
            continue
        sh = r[c['shape_id']] if 'shape_id' in c else ''
        t = r[c['trip_id']]
        d0 = cnt.setdefault(rd2, {})
        d0[sh] = d0.get(sh, 0) + 1
        if (rd2, sh) not in first or t < first[(rd2, sh)]:
            first[(rd2, sh)] = t
    picked = {}
    for rd2, shapes in cnt.items():
        sh = min(shapes, key=lambda x: (-shapes[x], x))
        picked[rd2] = (first[(rd2, sh)], sh)
    trip2rd = {v[0].encode(): k for k, v in picked.items()}
    seqs = collections.defaultdict(list)
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
                seqs[rd2].append((int(f[hdr['stop_sequence']]), f[hdr['stop_id']].decode()))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    stream_member(url, members, 'stop_times.txt', on_st)
    need = {sid for lst in seqs.values() for _, sid in lst}
    c, rows = member_rows(url, members, 'stops.txt')
    sinfo = {}
    for r in rows:
        if r[c['stop_id']] in need:
            try:
                sinfo[r[c['stop_id']]] = [r[c['stop_code']] or r[c['stop_id']],
                                          r[c['stop_name']].strip(),
                                          round(float(r[c['stop_lat']]), 5),
                                          round(float(r[c['stop_lon']]), 5)]
            except (ValueError, IndexError):
                continue
    shp_wanted = {v[1].encode() for v in picked.values() if v[1]}
    shp_pts = collections.defaultdict(list)
    if shp_wanted:
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
                        shp_pts[sid].append((int(f[hdr2['shape_pt_sequence']]),
                                             float(f[hdr2['shape_pt_lat']]),
                                             float(f[hdr2['shape_pt_lon']])))
                except (IndexError, ValueError):
                    continue

        try:
            stream_member(url, members, 'shapes.txt', on_shp)
        except (KeyError, ValueError):
            pass
    out = {}
    for rd2, lst in seqs.items():
        lst.sort()
        stops = [sinfo[sid] for _, sid in lst if sid in sinfo]
        shp = ''
        sid_ = picked[rd2][1]
        pts = shp_pts.get(sid_.encode() if isinstance(sid_, str) else sid_)
        if pts:
            pts.sort()
            shp = enc_polyline(thin([(p[1], p[2]) for p in pts]))
        out[rd2] = {'stops': stops, 'shp': shp}
    return out


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def refillable(v):
    """רשומה שממלאים: ריקה, או (במצב REDO) כזו שמולאה עם הבורר הלא-מסונן."""
    if v.get('k') != 'new' or v.get('src') != 'ob':
        return False
    if not (v.get('stops') or v.get('shp')):
        return True
    return REDO and FILLED_MARK in (v.get('note') or '')


def build_worklist():
    """date -> [(path, rd)] — רשומות 'וריאנט חדש' מהארכיון בלי מסלול."""
    by = collections.defaultdict(list)
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        d = jload(p, None)
        if not d:
            continue
        for v in d.get('versions') or []:
            if refillable(v):
                by[v['d']].append((p, d.get('rd')))
    return by


def save_state(st, done, skip):
    st['done'] = sorted(done)
    st['skip'] = sorted(skip)
    if not DRY:
        json.dump(st, open(STATE, 'w', encoding='utf-8'))


def main():
    st = jload(STATE, {'done': [], 'skip': []})
    done = set(st.get('done') or [])
    skip = set(st.get('skip') or [])
    by = build_worklist()
    dates = [d for d in sorted(by, reverse=True)
             if (REDO or (d not in done and d not in skip)) and ARC_FROM <= d <= ARC_TO]
    out_range = [d for d in by if not (ARC_FROM <= d <= ARC_TO)]
    total = sum(len(v) for v in by.values())
    print(f'{total} רשומות ב-{len(by)} תאריכים · {len(dates)} תאריכים נותרו לטיפול'
          + (f' · {len(out_range)} מחוץ לטווח הארכיון' if out_range else '')
          + (' · REDO' if REDO else ''))
    n_fix = n_miss = 0
    for i, ds in enumerate(dates):
        if (time.time() - T0) / 60 > MAX_MIN:
            print('נגמר תקציב הזמן — ההמשך בריצה הבאה')
            break
        rds = sorted({rd for _, rd in by[ds] if rd})
        print(f'{ds}: {len(rds)} וריאנטים')
        try:
            got = day_full_cal(ds, rds)
        except (Exception, SystemExit) as e:
            # ה-http של backfill_geo זורק SystemExit אחרי כל הניסיונות —
            # בלי לתפוס אותו יום חסר אחד בארכיון הפיל את כל הריצה (17.08.2024)
            code = probe(day_url(ds))
            if code in (403, 404):
                print(f'{ds}: אין צילום בארכיון ({code}) — נרשם דילוג קבוע', file=sys.stderr)
                skip.add(ds)
                save_state(st, done, skip)
            else:
                print(f'{ds}: {type(e).__name__}: {e} — דילוג זמני', file=sys.stderr)
                time.sleep(10)
            continue
        for p, rd in by[ds]:
            g = got.get(rd)
            lf = materialize(jload(p, None))
            if not lf:
                continue
            dirty = False
            for v in lf.get('versions') or []:
                if v.get('d') == ds and refillable(v):
                    if g and g.get('stops'):
                        v['stops'] = g['stops']
                        v['shp'] = g.get('shp') or ''
                        v['note'] = ('הווריאנט הופיע ברישום (ארכיון אופן באס, תאריך מדויק)'
                                     ' · המסלול והתחנות הושלמו מצילום הארכיון של אותו יום')
                        dirty = True
                        n_fix += 1
                    elif not (v.get('stops') or v.get('shp')):
                        n_miss += 1   # רשום בלי נסיעות בתוקף בצילום — נשאר קיום-בלבד
            if dirty and not DRY:
                json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
        done.add(ds)
        if i % 8 == 0:
            save_state(st, done, skip)
        time.sleep(PAUSE)
    save_state(st, done, skip)
    print(f'סיכום הריצה: {n_fix} רשומות קיבלו מסלול ותחנות · {n_miss} לא פעלו בצילום היום שלהן')


if __name__ == '__main__':
    main()
