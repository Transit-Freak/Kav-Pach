# -*- coding: utf-8 -*-
# "הקו בזמן" — איתור תאריך שינוי-המסלול האמיתי (סבב geo3).
#
# הרקע (קו 3 קרית מלאכי): שינוי שם ברישום נרשם חודשים אחרי שהמסלול הפיזי
# כבר הוחלף, ולכן "צילום מלפני שינוי השם" הראה את המסלול החדש. לכל מקרה
# שבו צילום-הלפני זהה למסלול שאחרי (חשד לשם-בלבד) עושים חיפוש בינארי
# בארכיון על רצף קודי-התחנות, ומאתרים מתי המסלול באמת הוחלף:
#   - אם המסלול זהה לכל אורך הארכיון — זה באמת שינוי-שם בלבד, מעדכנים כיתוב.
#   - אם נמצא מעבר — כותבים אירוע 'route' בתאריך האמיתי (עם המסלול החדש,
#     שכבר בידינו מהצילום) + צילום המסלול הישן מהיום שלפני המעבר.
#
# הבדיקות מקובצות לפי יום ארכיון: בכל סבב, כל המקרים הפעילים מבקשים יום
# אחד (אמצע הטווח שלהם) והימים המשותפים נשלפים פעם אחת. checkpoint:
# geo3-state.json. TEST_RD=<rd> מריץ מקרה בודד בפירוט מלא, בלי כתיבה.
import collections
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import (S3, OUTDIR, MAX_MIN, T0, central_dir, member_rows,
                          stream_member, enc_polyline, fsafe,
                          list_available_days, nearest_available, thin)

TEST_RD = os.environ.get('TEST_RD', '')


def day_sigs(ds, rds):
    """rd -> רצף קודי-תחנות (טאפל) עבור היום ds. rd שלא קיים באותו יום — None."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    want = set(rds)
    out = {rd: None for rd in rds}
    try:
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
        if not rid2rd:
            return out
        c, rows = member_rows(url, members, 'trips.txt')
        picked = {}
        for r in rows:
            rd2 = rid2rd.get(r[c['route_id']])
            if rd2 and rd2 not in picked:
                picked[rd2] = r[c['trip_id']]
        trip2rd = {v.encode(): k for k, v in picked.items()}
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
        code = {}
        for r in rows:
            if r[c['stop_id']] in need:
                code[r[c['stop_id']]] = r[c['stop_code']] or r[c['stop_id']]
        for rd2, lst in seqs.items():
            lst.sort()
            out[rd2] = tuple(code.get(sid, sid) for _, sid in lst)
    except Exception as e:
        print(f'{ds}: שגיאת שליפה — {e}', file=sys.stderr)
    return out


def day_full(ds, rds):
    """rd -> {'stops': [[code,name,lat,lon]...], 'shp': encoded} — שליפה מלאה."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    want = set(rds)
    out = {}
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
    c, rows = member_rows(url, members, 'trips.txt')
    picked = {}
    for r in rows:
        rd2 = rid2rd.get(r[c['route_id']])
        if rd2 and rd2 not in picked:
            picked[rd2] = (r[c['trip_id']], r[c['shape_id']] if 'shape_id' in c else '')
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
                sinfo[r[c['stop_id']]] = [r[c['stop_code']] or r[c['stop_id']], r[c['stop_name']].strip(),
                                          round(float(r[c['stop_lat']]), 5), round(float(r[c['stop_lon']]), 5)]
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
                                             float(f[hdr2['shape_pt_lat']]), float(f[hdr2['shape_pt_lon']])))
                except (IndexError, ValueError):
                    continue

        try:
            stream_member(url, members, 'shapes.txt', on_shp)
        except (KeyError, ValueError):
            pass
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


def build_cases():
    """כל צילום-לפני שזהה לגרסה שאחריו: rd -> {ev, d0, target}."""
    cases = {}
    dd = f'{OUTDIR}/lines'
    for fn in os.listdir(dd):
        if not fn.endswith('.json'):
            continue
        lf = json.load(open(f'{dd}/{fn}', encoding='utf-8'))
        vs = lf.get('versions', [])
        rd = lf.get('rd')
        if not rd or (TEST_RD and rd != TEST_RD):
            continue
        for i, v in enumerate(vs):
            if v.get('k') != 'snapshot':
                continue
            m = re.search(r'השינוי של (\d{4}-\d{2}-\d{2})', v.get('note') or '')
            if not m or not v.get('stops'):
                continue
            after = next((u for u in vs[i + 1:] if u.get('stops')), None)
            if not after:
                continue
            codes = tuple(s[0] for s in v['stops'])
            if codes != tuple(s[0] for s in after['stops']):
                continue          # המסלול באמת שונה — הצילום תקין, לא נוגעים
            cases[rd] = {'ev': m.group(1), 'd0': v['d'], 'target': list(codes)}
            break
    return cases


def main():
    statep = f'{OUTDIR}/geo3-state.json'
    try:
        state = json.load(open(statep, encoding='utf-8'))
    except Exception:
        state = {}
    avail = list_available_days()
    aidx = {d: i for i, d in enumerate(avail)}
    if 'cases' not in state:
        found = build_cases()
        state['cases'] = {rd: {'ev': c['ev'], 'd0': c['d0'], 'target': c['target'],
                               'lo': 0, 'hi': aidx.get(nearest_available(c['d0'], avail), 0),
                               'st': 'first'} for rd, c in found.items()}
        print(f'{len(found)} מקרים לאיתור תאריך-שינוי אמיתי')
    cases = state['cases']

    def save():
        if not TEST_RD:
            json.dump(state, open(statep, 'w', encoding='utf-8'), ensure_ascii=False)

    def out_of_time():
        return (time.time() - T0) / 60 > MAX_MIN

    # ---- סבבי חיפוש בינארי, מקובצים לפי יום ----
    while not out_of_time():
        want = collections.defaultdict(list)   # day -> [rd]
        for rd, c in cases.items():
            if c['st'] == 'first':
                want[avail[0]].append(rd)
            elif c['st'] == 'bisect' and c['hi'] - c['lo'] > 1:
                want[avail[(c['lo'] + c['hi']) // 2]].append(rd)
            elif c['st'] == 'bisect':
                c['st'] = 'ready'
        pend = {d: rds for d, rds in want.items()}
        if not pend:
            break
        # היום שמשרת הכי הרבה מקרים — קודם
        for ds, rds in sorted(pend.items(), key=lambda kv: -len(kv[1])):
            if out_of_time():
                break
            sigs = day_sigs(ds, rds)
            for rd in rds:
                c = cases[rd]
                is_target = (sigs.get(rd) is not None and list(sigs[rd]) == c['target'])
                if c['st'] == 'first':
                    if is_target:
                        c['st'] = 'never'       # זהה כבר מתחילת הארכיון
                    else:
                        c['st'] = 'bisect'
                        c['old_at0'] = True
                elif c['st'] == 'bisect':
                    mid = (c['lo'] + c['hi']) // 2
                    if is_target:
                        c['hi'] = mid
                    else:
                        c['lo'] = mid
            n_done = sum(1 for c in cases.values() if c['st'] in ('never', 'ready', 'done'))
            print(f'{ds}: {len(rds)} מקרים נבדקו | הוכרעו עד כה {n_done}/{len(cases)}')
            save()

    # ---- כתיבת התוצאות (מקובץ לפי יום-המסלול-הישן) ----
    old_want = collections.defaultdict(list)
    for rd, c in cases.items():
        if c['st'] == 'ready':
            old_want[avail[c['lo']]].append(rd)
    n_written = 0
    for ds, rds in sorted(old_want.items(), key=lambda kv: -len(kv[1])):
        if out_of_time():
            break
        full = day_full(ds, rds)
        for rd in rds:
            c = cases[rd]
            info = full.get(rd)
            t_old, t_new = avail[c['lo']], avail[c['hi']]
            if TEST_RD:
                print(f'--- {rd}: מעבר בין {t_old} ל-{t_new}')
                if info:
                    print('   מסלול ישן:', ' | '.join(s[1] for s in info['stops']))
                continue
            if not info or len(info['stops']) < 2 or [s[0] for s in info['stops']] == c['target']:
                c['st'] = 'done'   # לא הצלחנו לחלץ מסלול ישן שונה — לא כותבים דבר שגוי
                continue
            p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
            lf = json.load(open(p, encoding='utf-8'))
            vs = lf['versions']
            # הצילום המטעה הופך לאירוע שינוי-מסלול בתאריך האמיתי
            for v in vs:
                if v.get('k') == 'snapshot' and f"השינוי של {c['ev']}" in (v.get('note') or ''):
                    v['k'] = 'route'
                    v['d'] = t_new
                    v['note'] = (f'שינוי מסלול שאותר בהשוואת ארכיון: המסלול הוחלף בין {t_old} ל-{t_new} '
                                 f'(שם היעד ברישום עודכן רק ב-{c["ev"]})')
                    break
            if not any(u.get('d') == t_old and u.get('k') == 'snapshot' for u in vs):
                vs.append({'d': t_old, 'k': 'snapshot', 'shp': info['shp'], 'stops': info['stops'],
                           'src': 'ob', 'note': f'המסלול הישן — כפי שהיה עד {t_old} (אותר בהשוואת ארכיון)'})
            vs.sort(key=lambda x: x['d'])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            c['st'] = 'done'
            n_written += 1
        save()
        print(f'{ds}: נכתבו {sum(1 for r in rds if cases[r]["st"]=="done")} מסלולים ישנים')

    # ---- מקרים שבהם המסלול באמת לא השתנה מעולם ----
    n_never = 0
    if not TEST_RD:
        for rd, c in cases.items():
            if c['st'] != 'never':
                continue
            p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
            try:
                lf = json.load(open(p, encoding='utf-8'))
            except Exception:
                continue
            for v in lf['versions']:
                if v.get('k') == 'snapshot' and f"השינוי של {c['ev']}" in (v.get('note') or ''):
                    v['note'] = (f'צילום מהארכיון — המסלול זהה לאורך כל התקופה המתועדת (מ-2022); '
                                 f'שינוי היעד של {c["ev"]} היה שינוי שם ברישום בלבד')
                    n_never += 1
                    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
                    break
            c['st'] = 'done'
        save()

    left = sum(1 for c in cases.values() if c['st'] not in ('done',))
    print(f'סיכום ריצה: {n_written} שינויי-מסלול אמיתיים נכתבו | {n_never} אומתו כשם-בלבד | נותרו {left} מקרים')
    if left == 0:
        print('נותרו 0 מקרים')


if __name__ == '__main__':
    main()
