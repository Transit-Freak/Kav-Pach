# -*- coding: utf-8 -*-
"""סריקה ארצית יום-מול-יום של כל הארכיון: אף שינוי לא נשאר בלי תאריך.

דרישת שלמה (קו 26 שדרות): לא בדיקה נקודתית — כל הקווים, כל התקופה.
המנועים הקודמים תיארכו פערים בין גרסאות שמורות; כאן משווים את רצף
התחנות של כל וריאנט בין כל שני צילומי ארכיון עוקבים (2022-2026,
מהחדש לישן), כך שגם שינוי שהתהפך בחזרה — ולכן לא הותיר עקבה בין
הגרסאות השמורות — מתגלה ונכתב ביומו.

- מושווים רק ימים שבהם הווריאנט פעיל בשני הצדדים (נסיעות בתוקף,
  תבנית הרוב) — היעלמות/חזרה מכוסות ברשומות הקיום ואינן אירוע כאן.
- אירוע נכתב רק אם אין כבר רשומת-מסלול בטווח ±2 ימים.
- ההערה פותחת ב"שוחזר בדיעבד" — זוג שמתהפך תוך 35 יום נבלע אוטומטית
  בניקוי היומי (collapse_wobbles), לפי המדיניות הקיימת.

checkpoint: aa-state.json (מצביע היום + טביעות רצף לכל וריאנט).
MAX_MIN תקציב דקות · DRY=1 גילוי בלבד, בלי כתיבה.
"""
import collections
import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402
from backfill_geo import S3, central_dir, member_rows, stream_member, list_available_days  # noqa: E402
from backfill_new_routes import day_full_cal  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/aa-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
PAUSE = float(os.environ.get('PAUSE', '0.4'))
T0 = time.time()
NOTE = 'שוחזר בדיעבד מסריקת הארכיון יום-מול-יום'
ROUTEINFO = {'new', 'removed', 'baseline', 'snapshot'}


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def day_sigs_all(ds):
    """rd -> sha1 קצר של רצף קודי-התחנות (תבנית הרוב, נסיעות בתוקף) — לכל הרישום."""
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    members = central_dir(url)
    c, rows = member_rows(url, members, 'routes.txt')
    rid2rd = {}
    for r in rows:
        p = r[c['route_desc']].strip().split('-')
        mkt = p[0].lstrip('0') if p else ''
        if len(p) >= 3 and mkt:
            rid2rd[r[c['route_id']]] = f"{mkt}-{p[1]}-{p[2]}"
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
                seqs[rd2].append((int(f[hdr['stop_sequence']]), f[hdr['stop_id']]))
            except (IndexError, ValueError):
                continue

    stream_member(url, members, 'stop_times.txt', on_st)
    out = {}
    for rd2, lst in seqs.items():
        lst.sort()
        out[rd2] = hashlib.sha1(b','.join(sid for _, sid in lst)).hexdigest()[:10]
    return out


def has_route_record(rd, ds):
    """יש כבר רשומת-מסלול בטווח ±2 ימים? (אירוע/קיום — לא לו"ז)."""
    import datetime
    lf = jload(f'{OUTDIR}/lines/{fsafe(rd)}.json', None)
    if not lf:
        return True   # וריאנט בלי קובץ — לא נוגעים
    d0 = datetime.date.fromisoformat(ds)
    for v in materialize(lf).get('versions') or []:
        try:
            dd = datetime.date.fromisoformat(v['d'])
        except Exception:
            continue
        if abs((dd - d0).days) <= 2 and (v.get('stops') or v.get('add') or v.get('rem')
                                         or v.get('k') in ROUTEINFO):
            return True
    return False


def write_events(young, old, rds):
    """כתיבת אירוע לכל וריאנט שרצפו השתנה בין old ל-young — ביום young."""
    n = 0
    try:
        got_y = day_full_cal(young, rds)
        got_o = day_full_cal(old, rds)
    except (Exception, SystemExit) as e:
        print(f'{young}: שליפת פרטי המעבר נכשלה ({type(e).__name__})', file=sys.stderr)
        return 0
    for rd in rds:
        gy, go = got_y.get(rd), got_o.get(rd)
        if not (gy and gy.get('stops') and go and go.get('stops')):
            continue
        p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
        lf = materialize(jload(p, None))
        if not lf:
            continue
        yc = {str(s[0]) for s in gy['stops']}
        oc = {str(s[0]) for s in go['stops']}
        add = [s for s in gy['stops'] if str(s[0]) not in oc]
        rem = [s for s in go['stops'] if str(s[0]) not in yc]
        if not add and not rem:
            continue   # שינוי סדר בלבד — לא נרשם כאן
        kind = 'stops-del' if rem and not add else ('stops-add' if add and not rem else 'route')
        v = {'d': young, 'k': kind, 'shp': gy.get('shp') or '', 'stops': gy['stops'],
             'src': 'ob', 'note': f'{NOTE} ({old} ← {young})'}
        if add:
            v['add'] = [s[1] for s in add][:15]
            v['ac'] = [str(s[0]) for s in add][:15]
        if rem:
            v['rem'] = [s[1] for s in rem][:15]
            v['rc'] = [str(s[0]) for s in rem][:15]
        vs = [x for x in lf['versions'] if x['d'] != young or x.get('k') != kind]
        vs.append(v)
        vs.sort(key=lambda x: x['d'])
        lf['versions'] = vs
        if not DRY:
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            mp = f'{OUTDIR}/changes/{young[:7]}.json'
            mm = jload(mp, {'changes': []})
            mm['changes'] = [x for x in mm['changes']
                             if not (x.get('rd') == rd and x.get('d') == young)]
            ch = {'d': young, 'rd': rd, 'line': lf.get('line', ''), 'k': kind}
            if add:
                ch['add'] = v['add']
            if rem:
                ch['rem'] = v['rem']
            mm['changes'].append(ch)
            json.dump(mm, open(mp, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
        n += 1
        print(f"  נכתב: {rd} — {kind} ב-{young} (➕{len(add)} ➖{len(rem)})")
    return n


def main():
    st = jload(STATE, {})
    avail = list_available_days()
    if not st.get('young'):
        young = avail[-1]
        print(f'אתחול: טביעות היום {young}')
        st = {'young': young, 'sigs': day_sigs_all(young), 'done_pairs': 0, 'written': 0}
        if not DRY:
            json.dump(st, open(STATE, 'w', encoding='utf-8'))
    idx = {d: i for i, d in enumerate(avail)}
    while (time.time() - T0) / 60 < MAX_MIN:
        yi = idx.get(st['young'])
        if yi is None or yi == 0:
            if st.get('pass', 1) < 2:
                # מעבר אימות שני מההתחלה (דרישת שלמה: "הכל לבדוק מחדש") —
                # הכתיבה מדלגת על מה שכבר מתועד, אז מעבר נקי אמור לכתוב אפס
                young = avail[-1]
                print(f'מעבר 1 הושלם — מתחיל מעבר אימות שני מ-{young}')
                st = {'young': young, 'sigs': day_sigs_all(young), 'pass': 2,
                      'done_pairs': st.get('done_pairs', 0), 'written': st.get('written', 0)}
                if not DRY:
                    json.dump(st, open(STATE, 'w', encoding='utf-8'))
                continue
            print('שני המעברים הושלמו — הסריקה נגמרה')
            break
        old = avail[yi - 1]
        try:
            sigs_o = day_sigs_all(old)
        except (Exception, SystemExit) as e:
            print(f'{old}: {type(e).__name__} — מדלגים על היום', file=sys.stderr)
            st['young'] = old   # ממשיכים אחורה; הזוג הבא יגשר מעל החור
            time.sleep(8)
            continue
        sy = st['sigs']
        changed = [rd for rd, h in sigs_o.items()
                   if rd in sy and sy[rd] != h]
        pend = [rd for rd in changed if not has_route_record(rd, st['young'])]
        if pend:
            print(f'{old} ← {st["young"]}: {len(changed)} שינויים, {len(pend)} בלי תיעוד')
            st['written'] = st.get('written', 0) + write_events(st['young'], old, pend)
        st['young'] = old
        st['sigs'] = sigs_o
        st['done_pairs'] = st.get('done_pairs', 0) + 1
        if not DRY:
            json.dump(st, open(STATE, 'w', encoding='utf-8'))
        time.sleep(PAUSE)
    print(f"מצב: הגענו עד {st.get('young')} · זוגות שנבדקו: {st.get('done_pairs', 0)}"
          f" · אירועים שנכתבו: {st.get('written', 0)}")


if __name__ == '__main__':
    main()
