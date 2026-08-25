# -*- coding: utf-8 -*-
"""הקו בזמן — השלמת "הקטע ששונה" מהארכיון (בקשת שלמה, 25.08.2026).

לכל גרסת שינוי גיאומטרי (מסלול/שרטוט/הארכה/קיצור/קצה/תחנות) שחסר לה
שרטוט מדויק באחד הצדדים: שולפים מהארכיון את שרטוט המסלול מהיום שלפני
השינוי ומיום השינוי, מחשבים את הקטעים ששונו בלבד, ושומרים רק אותם —
v['sg'] = {'o': [קטעים שירדו], 'n': [קטעים חדשים]} — ולא את השרטוט
המלא, כדי לא להעמיס על האתר. שינויי לו"ז/תדירות מחוץ לתחום.

מקורות לפי תאריך: אופן באס S3 (מ-2022-01-16), TransitFeeds (לפני).
state: segs-state.json — צדדים ממתינים, כשלים, וסימוני סיום.
הרצה במחזורים: MAX_MIN מגביל את משך הריצה; ריצה שמסיימת בלי עבודה
יוצאת מיד. אחרי כתיבה קובץ הקו נדחס מחדש (compact).
"""
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, enc_polyline, http, member_rows, stream_member  # noqa: E402
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/segs-state.json'
OB = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
TF = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
      '/public/feeds/ministry-of-transport-and-road-safety/820/{ds}/gtfs.zip')
OB_LO, OB_HI = '2022-01-16', '2026-07-24'
GEO_KINDS = {'route', 'redraw', 'extend', 'shorten', 'terminal',
             'stops', 'stops-add', 'stops-del'}
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
MAX_DATES = int(os.environ.get('MAX_DATES', '0'))
ONLY = os.environ.get('ONLY', '')          # לבדיקות: שם קובץ קו יחיד
MAX_PTS = 240                              # תקרת נקודות לצד — "לא להעמיס"
T0 = time.time()

_tf_days = []
try:
    _tf_days = sorted(open(f'{OUTDIR}/tf-days.txt').read().split())
except OSError:
    pass


def _budget_left():
    return MAX_MIN <= 0 or (time.time() - T0) < MAX_MIN * 60


def day_url(iso_d):
    """כתובת הארכיון ליום נתון, או None כשאין ארכיון לתקופה."""
    if iso_d >= OB_LO:
        if iso_d > OB_HI:
            return None
        y, m, d = iso_d.split('-')
        return OB.format(y=y, m=m, d=d)
    ds = iso_d.replace('-', '')
    cand = [t for t in _tf_days if t <= ds]
    return TF.format(ds=cand[-1]) if cand else None


def dec_polyline(s):
    pts, i, la, lo = [], 0, 0, 0
    while i < len(s):
        for w in (0, 1):
            b, sh, r = 0x20, 0, 0
            while b >= 0x20:
                b = ord(s[i]) - 63
                i += 1
                r |= (b & 0x1f) << sh
                sh += 5
            d = ~(r >> 1) if (r & 1) else (r >> 1)
            if w == 0:
                la += d
            else:
                lo += d
        pts.append((la / 1e5, lo / 1e5))
    return pts


def _thin(run, cap):
    if len(run) <= cap:
        return run
    step = (len(run) - 1) / (cap - 1)
    return [run[round(i * step)] for i in range(cap)]


def seg_diff(old_pts, new_pts):
    """הקטעים ששונו: רצפים בכל צד שאינם קרובים (עד ~15מ') לאף נקודה בצד
    השני, מורחבים בנקודת-עיגון אחת מכל כיוון. מוחזר (o_runs, n_runs)."""
    def grid(pts):
        g = set()
        for la, lo in pts:
            g.add((round(la * 4000), round(lo * 4000)))
        return g

    def runs(pts, other_g):
        out, cur = [], []
        for p in pts:
            key = (round(p[0] * 4000), round(p[1] * 4000))
            near = any((key[0] + dy, key[1] + dx) in other_g
                       for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            if near:
                if len(cur) >= 2:
                    out.append(cur)
                cur = []
            else:
                cur.append(p)
        if len(cur) >= 2:
            out.append(cur)
        return out

    def anchored(pts, rs):
        idx = {id(p): i for i, p in enumerate(pts)}
        out = []
        for r in rs:
            i0, i1 = idx[id(r[0])], idx[id(r[-1])]
            a = pts[max(0, i0 - 1):min(len(pts), i1 + 2)]
            out.append([(round(la, 5), round(lo, 5)) for la, lo in a])
        return out

    og, ng = grid(old_pts), grid(new_pts)
    o_runs = anchored(old_pts, runs(old_pts, ng))
    n_runs = anchored(new_pts, runs(new_pts, og))

    def cap_side(rs):
        total = sum(len(r) for r in rs)
        if total <= MAX_PTS:
            return rs
        per = max(6, int(MAX_PTS * 0.9 / max(1, len(rs))))
        return [_thin(r, per) for r in rs]
    return cap_side(o_runs), cap_side(n_runs)


def build_worklist():
    """entries: dict מפתח 'file|vi' → פרטי הצדדים החסרים."""
    entries = {}
    files = sorted(os.listdir(f'{OUTDIR}/lines'))
    if ONLY:
        files = [f for f in files if f == ONLY]
    for f in files:
        try:
            lf = materialize(json.load(open(f'{OUTDIR}/lines/{f}', encoding='utf-8')))
        except Exception:
            continue
        vs = lf.get('versions') or []
        rd = lf.get('rd') or f.rsplit('.', 1)[0]
        for i, v in enumerate(vs):
            if i == 0 or v.get('k') not in GEO_KINDS or v.get('sg') is not None:
                continue
            pv = vs[i - 1]
            has_new = bool(v.get('shp'))
            has_old = bool(pv.get('shp'))
            if has_new and has_old:
                continue   # האתר מחשב את ההפרש המדויק בעצמו
            d_new = str(v.get('d', ''))[:10]
            try:
                d_old = (datetime.date.fromisoformat(d_new)
                         - datetime.timedelta(days=1)).isoformat()
            except ValueError:
                continue
            entries[f'{f}|{i}'] = {
                'f': f, 'vi': i, 'rd': rd, 'dn': d_new, 'do': d_old,
                'need': {**({} if has_new else {'n': d_new}),
                         **({} if has_old else {'o': d_old})},
                'have': {**({'n': v['shp']} if has_new else {}),
                         **({'o': pv['shp']} if has_old else {})},
            }
    return entries


def fetch_day(iso_d, rds):
    """{rd: encoded_shape} מיום ארכיון אחד, רק לוריאנטים המבוקשים."""
    url = day_url(iso_d)
    if not url:
        return None
    try:
        members = central_dir(url)
    except SystemExit:
        return None
    except Exception:
        return None
    want = set(rds)
    c, rows = member_rows(url, members, 'routes.txt')
    rid2rd = {}
    for row in rows:
        try:
            parts = row[c['route_desc']].split('-')
            mkt = parts[0].lstrip('0') if parts else ''
            if len(parts) >= 3 and mkt:
                rd2 = f'{mkt}-{parts[1]}-{parts[2]}'
                if rd2 in want:
                    rid2rd[row[c['route_id']]] = rd2
        except IndexError:
            continue
    if not rid2rd:
        return {}
    c, rows = member_rows(url, members, 'trips.txt')
    rd2sid = {}
    for row in rows:
        try:
            rd2 = rid2rd.get(row[c['route_id']])
            if rd2 and rd2 not in rd2sid and 'shape_id' in c and row[c['shape_id']]:
                rd2sid[rd2] = row[c['shape_id']]
        except IndexError:
            continue
    if not rd2sid:
        return {}
    sid2rds = {}
    for rd2, sid in rd2sid.items():
        sid2rds.setdefault(sid.encode(), []).append(rd2)
    pts = {}
    buf, hdr = [b''], {}

    def on_shp(data):
        buf[0] += data
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not hdr:
                for j, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr[h.strip()] = j
                continue
            fl = ln.split(b',')
            try:
                sid = fl[hdr['shape_id']]
                if sid in sid2rds:
                    pts.setdefault(sid, []).append(
                        (int(fl[hdr['shape_pt_sequence']]),
                         float(fl[hdr['shape_pt_lat']]), float(fl[hdr['shape_pt_lon']])))
            except (IndexError, ValueError):
                continue

    try:
        stream_member(url, members, 'shapes.txt', on_shp)
    except (KeyError, ValueError):
        return {}
    out = {}
    for sid, lst in pts.items():
        lst.sort()
        coords = [(la, lo) for _, la, lo in lst]
        if len(coords) < 2:
            continue
        enc = enc_polyline(coords)
        for rd2 in sid2rds.get(sid, []):
            out[rd2] = enc
    return out


def write_sg(entry, old_enc, new_enc):
    p = f"{OUTDIR}/lines/{entry['f']}"
    lf = materialize(json.load(open(p, encoding='utf-8')))
    v = lf['versions'][entry['vi']]
    o_runs, n_runs = seg_diff(dec_polyline(old_enc), dec_polyline(new_enc))
    v['sg'] = {'o': [enc_polyline(r) for r in o_runs],
               'n': [enc_polyline(r) for r in n_runs], 'src': 'arc'}
    out = json.dumps(compact(lf), ensure_ascii=False, separators=(',', ':'))
    open(p, 'w', encoding='utf-8').write(out)


def main():
    try:
        state = json.load(open(STATE, encoding='utf-8'))
    except Exception:
        state = {'pend': {}, 'skip': {}}
    entries = build_worklist()
    # מסננים את מה שכבר סומן ככישלון קבוע (הווריאנט לא נמצא בארכיון)
    entries = {k: e for k, e in entries.items() if k not in state['skip']}
    print('worklist:', len(entries), flush=True)
    if not entries:
        print('nothing to do')
        return

    # תאריך → אילו (entry, side) צריכים אותו; ממלאים גם מצדדים שכבר בהמתנה
    for k, e in entries.items():
        for side, d in list(e['need'].items()):
            pk = f'{d}|{e["rd"]}'
            if pk in state['pend']:
                e['have'][side] = state['pend'][pk]
                del e['need'][side]

    by_date = {}
    for k, e in entries.items():
        for side, d in e['need'].items():
            by_date.setdefault(d, []).append((k, side))
    order = sorted(by_date, key=lambda d: -len(by_date[d]))
    if MAX_DATES:
        order = order[:MAX_DATES]

    done = fails = 0
    for d in order:
        if not _budget_left():
            print('time budget reached')
            break
        needs = [x for x in by_date[d] if x[0] in entries]
        rds = sorted({entries[k]['rd'] for k, _ in needs})
        if not rds:
            continue
        print(f'== {d}: {len(rds)} variants', flush=True)
        got = fetch_day(d, rds)
        if got is None:
            print('  no archive for date — marking skips', flush=True)
            for k, side in needs:
                state['skip'][k] = f'no-archive:{d}'
            continue
        for k, side in needs:
            e = entries.get(k)
            if not e:
                continue
            enc = got.get(e['rd'])
            if not enc:
                state['skip'][k] = f'variant-missing:{d}'
                fails += 1
                continue
            e['have'][side] = enc
            e['need'].pop(side, None)
            if not e['need']:
                try:
                    write_sg(e, e['have']['o'], e['have']['n'])
                    done += 1
                except Exception as ex:
                    state['skip'][k] = f'write-fail:{ex}'
                del entries[k]
            else:
                state['pend'][f'{d}|{e["rd"]}'] = enc
    # בהמתנה נשארים רק צדדים של רשומות שעדיין פתוחות (לפי שני התאריכים
    # הדטרמיניסטיים של כל רשומה) — השאר נוקה כדי שה-state לא יתנפח
    ref = set()
    for e in entries.values():
        ref.add(f'{e["dn"]}|{e["rd"]}')
        ref.add(f'{e["do"]}|{e["rd"]}')
    state['pend'] = {k: v for k, v in state['pend'].items() if k in ref}
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'completed: {done} | variant-missing: {fails} | remaining: {len(entries)}')


if __name__ == '__main__':
    main()
