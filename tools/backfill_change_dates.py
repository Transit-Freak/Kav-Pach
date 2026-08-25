# -*- coding: utf-8 -*-
"""תיארוך שינויי-מסלול חסרי-תאריך מצילומי הארכיון (כל הקווים בארץ).

פער = שתי גרסאות סמוכות עם רצפי תחנות שונים, כשלמאוחרת אין רשימות
➕/➖: השינוי קרה מתישהו בין לבין, והאתר ייחס אותו לתאריך הצילום במקום
לתאריך האמיתי (דרישת שלמה, קו 80: הורדת מעון-עולים קרתה ב-26.10.2022
בדיוק — יום ביטול התחנה — ולא בשום תאריך אחר).

לכל פער שנחתך עם עידן ארכיון אופן באס: חיפוש בינארי על רצף קודי-התחנות
(נסיעות בתוקף באותו יום בלבד, תבנית הרוב — כמו הסורק) עד היום הראשון
שבו הרצף שונה מנקודת הפתיחה; שם נכתב אירוע עם המסלול המלא, ➕/➖
ומק"טים מדויקים מול יום-לפני. הימים המבוקשים מקובצים — כל צילום נשלף
פעם אחת עבור כל הפערים שתלויים בו.

checkpoint: cd-state.json (done/dead + lo/hi לכל פער) — ריצה חוזרת
ממשיכה מאותה נקודה. פער רב-שלבי מתכנס באיטרציות: כל סבב מוצא את המעבר
הראשון, והסריקה הבאה מזהה את הפער שנותר. MAX_MIN תקציב דקות, DRY=1.
"""
import collections
import datetime
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402
from backfill_geo import (S3, central_dir, member_rows, stream_member,  # noqa: E402
                          list_available_days, nearest_available)
from backfill_new_routes import day_full_cal  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/cd-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
PAUSE = float(os.environ.get('PAUSE', '0.4'))
OB0, OB1 = '2022-01-16', '2026-07-24'
T0 = time.time()
NOTE = 'השינוי אותר ותוארך בהשוואת צילומי הארכיון יום-מול-יום'


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def day_sigs_cal(ds, rds):
    """rd -> טאפל קודי-תחנות של תבנית הרוב שבתוקף באותו יום (None=לא קיים)."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    want = set(rds)
    out = {rd: None for rd in rds}
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
        active = None
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
    trip2rd = {}
    for rd2, shapes in cnt.items():
        sh = min(shapes, key=lambda x: (-shapes[x], x))
        trip2rd[first[(rd2, sh)].encode()] = rd2
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
    code_of = {}
    for r in rows:
        if r[c['stop_id']] in need:
            code_of[r[c['stop_id']]] = r[c['stop_code']] or r[c['stop_id']]
    for rd2, lst in seqs.items():
        lst.sort()
        out[rd2] = tuple(str(code_of.get(sid, sid)) for _, sid in lst)
    return out


def build_cases(done, dead):
    cases = {}
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        d = materialize(jload(p, None) or {})
        rd = d.get('rd')
        vs = sorted([v for v in d.get('versions') or [] if v.get('stops')],
                    key=lambda v: v['d'])
        for a, b in zip(vs, vs[1:]):
            if b.get('add') or b.get('rem'):
                continue
            ca = tuple(str(s[0]) for s in a['stops'])
            cb = tuple(str(s[0]) for s in b['stops'])
            if ca == cb:
                continue
            if b['d'] < OB0 or a['d'] > OB1:
                continue                    # מחוץ לעידן הארכיון — עידן TF בנפרד
            cid = f"{rd}|{a['d']}|{b['d']}"
            if cid in done or cid in dead:
                continue
            cases[cid] = {'rd': rd, 'p': p, 'a_d': a['d'], 'b_d': b['d'],
                          'a': ca, 'b': cb}
    return cases


def main():
    st = jload(STATE, {'done': [], 'dead': [], 'pos': {}})
    done = set(st.get('done') or [])
    dead = set(st.get('dead') or [])
    pos = st.get('pos') or {}
    cases = build_cases(done, dead)
    if not cases:
        print('אין פערים חסרי-תאריך בעידן הארכיון — סיימנו')
        return
    print(f'{len(cases)} פערים לתיארוך')
    avail = list_available_days()
    ai = {d: i for i, d in enumerate(avail)}

    def save():
        st['done'] = sorted(done)
        st['dead'] = sorted(dead)
        st['pos'] = pos
        if not DRY:
            json.dump(st, open(STATE, 'w', encoding='utf-8'))

    # אתחול תחום החיפוש לכל פער
    import bisect
    for cid, c in cases.items():
        if cid in pos:
            continue
        lo_i = bisect.bisect_left(avail, max(c['a_d'], OB0))
        hi_i = bisect.bisect_right(avail, min(c['b_d'], OB1)) - 1
        if lo_i >= len(avail) or hi_i < 0 or lo_i >= hi_i:
            dead.add(cid)
            continue
        pos[cid] = {'lo': lo_i, 'hi': hi_i, 'skip': [], 'lo_ok': False}
    resolved = []
    active = [cid for cid in cases if cid in pos and cid not in done and cid not in dead]
    rounds = 0
    while active and (time.time() - T0) / 60 < MAX_MIN:
        rounds += 1
        # כל פער מבקש את יום-האמצע שלו; הימים המשותפים נשלפים פעם אחת
        want = collections.defaultdict(set)   # day -> {cid}
        for cid in active:
            pp = pos[cid]
            if pp['hi'] - pp['lo'] <= 1:
                resolved.append(cid)
                continue
            mid = (pp['lo'] + pp['hi']) // 2
            while mid in pp['skip'] and mid > pp['lo'] + 1:
                mid -= 1
            if mid <= pp['lo'] or mid >= pp['hi']:
                resolved.append(cid)
                continue
            want[avail[mid]].add(cid)
        for cid in resolved:
            if cid in active:
                active.remove(cid)
        if not want:
            break
        for ds in sorted(want, key=lambda d: -len(want[d])):
            if (time.time() - T0) / 60 > MAX_MIN:
                break
            cids = [c for c in want[ds] if c in active]
            if not cids:
                continue
            rds = sorted({cases[c]['rd'] for c in cids})
            try:
                sigs = day_sigs_cal(ds, rds)
            except (Exception, SystemExit) as e:
                print(f'{ds}: {type(e).__name__} — דילוג סבב', file=sys.stderr)
                for cid in cids:
                    pos[cid]['skip'].append(ai[ds])
                time.sleep(8)
                continue
            for cid in cids:
                c = cases[cid]
                pp = pos[cid]
                sig = sigs.get(c['rd'])
                if sig is None:
                    pp['skip'].append(ai[ds])
                elif sig == c['a']:
                    pp['lo'] = ai[ds]
                    pp['lo_ok'] = True
                else:
                    pp['hi'] = ai[ds]
            time.sleep(PAUSE)
        save()
        print(f'סבב {rounds}: {len(active)} פערים פעילים, {len(resolved)} הוכרעו')
    # כתיבת האירועים לפערים שהוכרעו — מקובץ לפי יום המעבר
    by_day = collections.defaultdict(list)
    for cid in resolved:
        pp = pos[cid]
        # כשהפער מתחיל לפני תחילת הארכיון, העוגן "עדיין המסלול הישן" חייב
        # להיות מוכח בדגימה — אחרת ייתכן שהמעבר קרה לפני שהארכיון מתחיל
        if not pp.get('lo_ok') and cases[cid]['a_d'] < OB0:
            dead.add(cid)
            continue
        by_day[avail[pp['hi']]].append(cid)
    n_written = 0
    for ds in sorted(by_day, reverse=True):
        if (time.time() - T0) / 60 > MAX_MIN + 10:
            break
        cids = by_day[ds]
        rds = sorted({cases[c]['rd'] for c in cids})
        try:
            got = day_full_cal(ds, rds)
        except (Exception, SystemExit) as e:
            print(f'{ds}: שליפת יום-המעבר נכשלה ({type(e).__name__})', file=sys.stderr)
            continue
        for cid in cids:
            c = cases[cid]
            g = got.get(c['rd'])
            if not g or not g.get('stops'):
                dead.add(cid)
                continue
            lf = materialize(jload(c['p'], None) or {})
            vs = lf.get('versions') or []
            if any(v['d'] == ds for v in vs):
                done.add(cid)
                continue
            names = {}
            for v in vs:
                for s in v.get('stops') or []:
                    names.setdefault(str(s[0]), s)
            cc = {str(s[0]) for s in g['stops']}
            aset = set(c['a'])
            add = [s for s in g['stops'] if str(s[0]) not in aset]
            rem = []
            for code in c['a']:
                if code not in cc:
                    k = names.get(code)
                    rem.append([code, k[1] if k else code])
            kind = 'stops-del' if rem and not add else ('stops-add' if add and not rem else 'route')
            v = {'d': ds, 'k': kind, 'shp': g.get('shp') or '', 'stops': g['stops'],
                 'src': 'ob', 'note': NOTE}
            if add:
                v['add'] = [s[1] for s in add][:15]
                v['ac'] = [str(s[0]) for s in add][:15]
            if rem:
                v['rem'] = [s[1] for s in rem][:15]
                v['rc'] = [str(s[0]) for s in rem][:15]
            vs.append(v)
            vs.sort(key=lambda x: x['d'])
            lf['versions'] = vs
            if not DRY:
                json.dump(compact(lf), open(c['p'], 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
                mp = f'{OUTDIR}/changes/{ds[:7]}.json'
                mm = jload(mp, {'changes': []})
                mm['changes'] = [x for x in mm['changes']
                                 if not (x.get('rd') == c['rd'] and x.get('d') == ds)]
                ch = {'d': ds, 'rd': c['rd'], 'line': lf.get('line', ''), 'k': kind}
                if add:
                    ch['add'] = v['add']
                if rem:
                    ch['rem'] = v['rem']
                mm['changes'].append(ch)
                json.dump(mm, open(mp, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
            done.add(cid)
            pos.pop(cid, None)
            n_written += 1
            print(f"  תוארך: {c['rd']} — האירוע נכתב ב-{ds} (➕{len(add)} ➖{len(rem)})")
        time.sleep(PAUSE)
    save()
    print(f'סיכום: {n_written} אירועים תוארכו ונכתבו · {len(active)} פערים ממשיכים בריצה הבאה'
          f' · {len(dead)} ללא הכרעה')


if __name__ == '__main__':
    main()
