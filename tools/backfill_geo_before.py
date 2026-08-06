# -*- coding: utf-8 -*-
# "הקו בזמן" — שלב ב' של השלמת המסלולים: צילום "המסלול שלפני" לכל אירוע
# שינוי יעד (dest) שאין לו גרסה עם מסלול לפני האירוע. המשתמשים רואים
# "היעד שוּנה: X ← Y" אבל אין להם את המסלול הישן על המפה — כאן הוא נשלף
# מהארכיון מיום שקדם לשינוי ונכתב כגרסת 'snapshot' מתוארכת לאותו יום.
#
# קיבוץ: יום היעד מוצמד לתחילת החודש שלפני האירוע (המסלול הישן פעיל עד יום
# השינוי עצמו) — מכווץ ~1,150 ימים לכ-60 ימי-ארכיון. אם לוריאנט היה אירוע
# קודם באותו חלון, מתקדמים אליו כדי לא לצלם מצב מוקדם מדי.
# checkpoint: geo2-state.json — אותו דפוס מחזורים כמו הסבבים הקודמים.
import datetime
import json
import os
import sys
import time
import zlib
from compact_lines import materialize

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import (S3, OUTDIR, MAX_MIN, MAX_DAYS_ENV, ARC_LO, ARC_HI, T0,
                          central_dir, member_rows, stream_member, enc_polyline,
                          fsafe, list_available_days, nearest_available, thin)


def build_targets(avail):
    """יום-ארכיון -> {rd: תאריך האירוע} עבור אירועי dest בלי מסלול-לפני."""
    targets = {}
    dd = f'{OUTDIR}/lines'
    for fn in os.listdir(dd):
        if not fn.endswith('.json'):
            continue
        lf = materialize(json.load(open(f'{dd}/{fn}', encoding='utf-8')))
        vs = lf.get('versions', [])
        rd = lf.get('rd')
        if not vs or not rd:
            continue
        for i, v in enumerate(vs):
            if v.get('k') != 'dest':
                continue
            ev = v['d']
            if ev <= ARC_LO:
                continue
            if any(u.get('shp') and u['d'] < ev for u in vs):
                continue          # יש כבר מסלול מתועד לפני האירוע
            prev = (datetime.date.fromisoformat(ev) - datetime.timedelta(days=1)).isoformat()
            snap = prev[:8] + '01'
            # לא לחצות אירוע קודם של אותו וריאנט (שינוי בתוך אותו חודש)
            for u in vs[:i]:
                if snap < u['d'] <= prev:
                    snap = u['d']
            snap = max(snap, ARC_LO)
            t = nearest_available(min(snap, prev), avail)
            if t >= ev:
                continue          # אין יום ארכיון לפני האירוע
            targets.setdefault(t, {})[rd] = ev
            break                 # אירוע dest אחד לוריאנט מספיק — הראשון בלי עבר
    return targets


def process_day(ds, rdmap):
    """שולף מהיום ds תחנות+שרטוט לוריאנטים שברשימה וכותב 'המסלול שלפני'."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    want = set(rdmap)
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
        picked = {}
        for row in rows:
            try:
                rd2 = rid2rd.get(row[c['route_id']])
                if rd2 and rd2 not in picked:
                    picked[rd2] = (row[c['trip_id']], row[c['shape_id']] if 'shape_id' in c else '')
            except IndexError:
                continue
        if not picked:
            return 0
        trip2rd = {v[0].encode(): k for k, v in picked.items()}

        seqs = {}
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

        shp_wanted = {v[1].encode() for v in picked.values() if v[1]}
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
            pts = shp_pts.get(sid_.encode() if isinstance(sid_, str) else sid_)
            if pts:
                pts.sort()
                shp = enc_polyline(thin([(p[1], p[2]) for p in pts]))
            p = f'{OUTDIR}/lines/{fsafe(rd2)}.json'
            lf = materialize(json.load(open(p, encoding='utf-8')))
            ev = rdmap[rd2]
            vs = lf['versions']
            if any(u.get('shp') and u['d'] < ev for u in vs) or any(u['d'] == ds and u.get('k') == 'snapshot' for u in vs):
                continue
            note = f'המסלול והתחנות כפי שהיו לפני השינוי של {ev} (צילום מהארכיון)'
            after = next((u for u in vs if u.get('shp') and u['d'] >= ev), None)
            if after and shp and after.get('shp') == shp:
                note = f'צילום מלפני השינוי של {ev} — המסלול עצמו לא השתנה, רק שם היעד'
            vs.append({'d': ds, 'k': 'snapshot', 'shp': shp, 'stops': stops, 'src': 'ob', 'note': note})
            vs.sort(key=lambda x: x['d'])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            done += 1
        return done
    except (ValueError, KeyError, zlib.error) as e:
        print(ds, '— קובץ בעייתי:', e)
        return 0


def main():
    statep = f'{OUTDIR}/geo2-state.json'
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
