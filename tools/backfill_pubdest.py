# -*- coding: utf-8 -*-
"""סריקה היסטורית של תחנות היעד לפרסום (בקשת שלמה 31.08.2026).

עוברת על ארכיון הסדנא (16.01.2022 → 24.07.2026) בדגימה דו-שבועית,
מחשבת לכל דגימה את קבוצת תחנות-היעד (התחנה האחרונה של כל מסלול פעיל,
לפי מק"ט — אותה הגדרה כמו המעקב היומי), ורושמת אירוע על כל תחנה
שהפכה או חדלה להיות יעד — עם התאריך ההיסטורי האמיתי.

רצה בנתחים: כל נתח מעבד כמה דגימות ונדחף מיד — המונים באתר עולים
תוך כדי הסריקה, לא בסופה. בטוחה להרצה חוזרת (אירועים לא מוכפלים).

מצב: line-history/data/pubdest-hist-state.json
"""
import csv
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows, stream_member  # noqa: E402

S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/pubdest-hist-state.json'
ARC0 = datetime.date(2022, 1, 16)
ARC1 = datetime.date.today() - datetime.timedelta(days=1)
STEP_DAYS = 14
MAX_SAMPLES = int(os.environ.get('MAX_SAMPLES', '4'))
MAX_MIN = float(os.environ.get('MAX_MIN', '30'))


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def day_dest_map(day):
    """{מק"ט תחנה אחרונה: (קווים, שם, עיר, la, lo)} ליום ארכיון אחד."""
    url = S3.format(y=day.year, m=f'{day.month:02d}', d=f'{day.day:02d}')
    cd = central_dir(url)

    c, rows = member_rows(url, cd, 'routes.txt')
    short = {r[c['route_id']]: (r[c['route_short_name']] or '') for r in rows}

    c, rows = member_rows(url, cd, 'trips.txt')
    rep = {}
    for r in rows:
        rid = r[c['route_id']]
        if rid not in rep:
            rep[rid] = r[c['trip_id']]
    trip2rid = {t: rid for rid, t in rep.items()}

    # התחנה האחרונה של כל נסיעת-נציג — סריקת stop_times בזרימה
    last = {}
    buf = [b'']
    hdr = {}

    def feed(chunk):
        buf[0] += chunk
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not ln.strip():
                continue
            if not hdr:
                for i, h in enumerate(next(csv.reader([ln.decode('utf-8-sig')]))):
                    hdr[h.strip()] = i
                continue
            r = ln.decode('utf-8', 'replace').split(',')
            try:
                t = r[hdr['trip_id']]
                if t not in trip2rid:
                    continue
                seq = int(r[hdr['stop_sequence']])
                cur = last.get(t)
                if cur is None or seq > cur[0]:
                    last[t] = (seq, r[hdr['stop_id']])
            except (IndexError, KeyError, ValueError):
                continue

    stream_member(url, cd, 'stop_times.txt', feed)

    c, rows = member_rows(url, cd, 'stops.txt')
    stops = {}
    for r in rows:
        desc = r[c['stop_desc']] if 'stop_desc' in c else ''
        m = re.search(r'עיר:\s*(.*?)\s*רציף:', desc or '')
        city = m.group(1).strip() if m else ''
        stops[r[c['stop_id']]] = (r[c['stop_code']], r[c['stop_name']],
                                  float(r[c['stop_lat']] or 0), float(r[c['stop_lon']] or 0), city)

    dest = {}
    for t, (seq, sid) in last.items():
        st = stops.get(sid)
        if not st:
            continue
        code, name, la, lo, city = st
        ln = short.get(trip2rid[t], '')
        e = dest.setdefault(str(code), [set(), name, city, la, lo])
        if ln:
            e[0].add(ln)
    return {k: (sorted(v[0])[:12], v[1], v[2], v[3], v[4]) for k, v in dest.items()}


def _exists(url):
    """בדיקת קיום מהירה (HEAD) — בלי ניסיונות ההורדה האיטיים של העוזר."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False


def next_existing(day):
    """היום הקיים הראשון בחלון הדגימה, או None (חור בארכיון / קצה)."""
    for back in range(STEP_DAYS):
        d = day + datetime.timedelta(days=back)
        if d > ARC1:
            return None
        if _exists(S3.format(y=d.year, m=f'{d.month:02d}', d=f'{d.day:02d}')):
            return d
    return None


def add_event(shist, months, code, ev):
    day = ev['d']
    hc = shist.setdefault(code, [])
    if any(e.get('d') == day and e.get('k') == 'pubdest' and e.get('st') == ev['st'] for e in hc):
        return False
    hc.append(ev)
    hc.sort(key=lambda e: e.get('d', ''))
    mon = day[:7]
    mp = f'{OUTDIR}/changes/stops-{mon}.json'
    mm = months.setdefault(mon, jload(mp, {'month': mon, 'changes': []}))
    if not any(x.get('c') == code and x.get('d') == day and x.get('k') == 'pubdest'
               and x.get('st') == ev['st'] for x in mm['changes']):
        mm['changes'].append({'c': code, **ev})
    return True


def main():
    t0 = time.monotonic()
    st = jload(STATE, {'ptr': ARC0.isoformat(), 'prev': None, 'prev_day': None, 'done': False})
    if st.get('done'):
        print('הסריקה ההיסטורית הושלמה כבר — אין מה לעשות')
        return
    shist = jload(f'{OUTDIR}/stops-hist.json', {})
    months = {}
    n_ev = n_smp = 0
    while n_smp < MAX_SAMPLES and (time.monotonic() - t0) / 60 < MAX_MIN:
        ptr = datetime.date.fromisoformat(st['ptr'])
        if ptr > ARC1:
            st['done'] = True
            print('הגענו לקצה הארכיון — הסריקה ההיסטורית הושלמה')
            break
        day = next_existing(ptr)
        if day is None:
            if ptr + datetime.timedelta(days=STEP_DAYS) > ARC1:
                st['done'] = True
                print('הגענו לקצה הארכיון — הסריקה ההיסטורית הושלמה')
                break
            # חור בארכיון (כמו תחילת יולי 2022) — מדלגים חלון ולא מוותרים
            print(f'{ptr}: חור בארכיון — דילוג חלון', flush=True)
            st['ptr'] = (ptr + datetime.timedelta(days=STEP_DAYS)).isoformat()
            continue
        try:
            dest = day_dest_map(day)
        except (Exception, SystemExit) as e:
            # קובץ קיים אך שבור/קטוע — מנסים את היום הבא בחלון במקום ליפול
            print(f'{day}: כשל בקריאה ({e}) — ממשיכים ליום הבא', flush=True)
            st['ptr'] = (day + datetime.timedelta(days=1)).isoformat()
            continue
        prev = st.get('prev')
        if prev is not None:
            for code in dest.keys() - prev.keys():
                lns, name, city, la, lo = dest[code]
                if add_event(shist, months, code,
                             {'d': day.isoformat(), 'k': 'pubdest', 'st': 'in',
                              'n': name, 't': city, 'la': la, 'lo': lo, 'ln': lns[:8]}):
                    n_ev += 1
            for code in prev.keys() - dest.keys():
                pl = prev[code]
                if add_event(shist, months, code,
                             {'d': day.isoformat(), 'k': 'pubdest', 'st': 'out',
                              'n': pl[1], 't': pl[2], 'la': pl[3], 'lo': pl[4],
                              'ln': (pl[0] or [])[:8]}):
                    n_ev += 1
        st['prev'] = {k: list(v) for k, v in dest.items()}
        st['prev_day'] = day.isoformat()
        st['ptr'] = (day + datetime.timedelta(days=STEP_DAYS)).isoformat()
        n_smp += 1
        print(f'{day}: {len(dest)} תחנות יעד · אירועים עד כה: {n_ev}', flush=True)

    json.dump(shist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    for mon, mm in months.items():
        json.dump(mm, open(f'{OUTDIR}/changes/stops-{mon}.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
    if months:
        # חודש חדש נראה בעמוד רק אם הוא רשום ב-months.json — מרעננים מיד
        mj = jload(f'{OUTDIR}/months.json', {})
        mj['stopMonths'] = sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes')
                                   if f.startswith('stops-')}, reverse=True)
        json.dump(mj, open(f'{OUTDIR}/months.json', 'w', encoding='utf-8'), ensure_ascii=False)
    json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'נתח הסתיים: {n_smp} דגימות · {n_ev} אירועים חדשים · מצביע: {st["ptr"]}')


if __name__ == '__main__':
    main()
