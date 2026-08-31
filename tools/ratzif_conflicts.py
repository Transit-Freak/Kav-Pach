# -*- coding: utf-8 -*-
"""רציף כפול — מערכת חדשה (בקשת שלמה 31.08.2026).

מוצאת מקרים שבהם שני קווים שונים אמורים לצאת מאותו רציף באותה דקה
בדיוק, לפי לוח הזמנים הרשמי (GTFS). נבדקות אך ורק תחנות מוצא —
היציאה הראשונה של כל מסלול — כי שם האוטובוס עומד ברציף, לא חולף.

שני קווים = שני מק"טים שונים או שני כיוונים שונים; חלופות של אותו
קו-כיוון לא נספרות (כמעט תמיד ארטיפקט רישוי, לא התנגשות אמיתית).
התנגשות נספרת רק אם לשתי הנסיעות יש חפיפה בימי הפעילות בלוח.

הפלט: ratzif/data/conflicts.json. רץ לילית מה-GTFS של אתמול בארכיון.
"""
import csv
import datetime
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows, stream_member  # noqa: E402

# בניגוד ל-backfill_geo (שם S3 הוא רק שם השרת), כאן צריך את הנתיב המלא
S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')

OUT = 'ratzif/data/conflicts.json'
DAYS_HE = 'אבגדהוש'


def load_small(url, cd, name):
    c, rows = member_rows(url, cd, name)
    return c, list(rows)


def origin_rows(url, cd):
    """שורות stop_sequence=1 בלבד מ-stop_times הענק — בזרימה, בלי לטעון הכול."""
    out = []
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
            # סינון זול לפני פירוק CSV מלא: רצף התחנות הוא שדה קצר
            r = ln.decode('utf-8', 'replace').split(',')
            try:
                if r[hdr['stop_sequence']].strip() not in ('1', '0'):
                    continue
                out.append((r[hdr['trip_id']], r[hdr['departure_time']][:5],
                            r[hdr['stop_id']]))
            except (IndexError, KeyError):
                continue

    stream_member(url, cd, 'stop_times.txt', feed)
    print(f'יציאות-מוצא: {len(out):,}', flush=True)
    return out


def main():
    # הארכיון של אתמול נבנה במהלך היום — נסוגים אחורה עד יום שקיים
    day, cd, url = None, None, None
    for back in range(1, 7):
        day = datetime.date.today() - datetime.timedelta(days=back)
        url = S3.format(y=day.year, m=f'{day.month:02d}', d=f'{day.day:02d}')
        try:
            cd = central_dir(url)
            break
        except Exception as e:
            print(f'{day}: אין ארכיון ({type(e).__name__}) — צעד אחורה', flush=True)
    if cd is None:
        raise SystemExit('אין אף יום זמין בארכיון בשבוע האחרון')

    c, rows = load_small(url, cd, 'trips.txt')
    trip2 = {r[c['trip_id']]: (r[c['route_id']], r[c['service_id']],
                               r[c['trip_headsign']] if 'trip_headsign' in c else '') for r in rows}

    c, rows = load_small(url, cd, 'routes.txt')
    routes = {}
    for r in rows:
        desc = (r[c['route_desc']] or '').split('-')
        makat, direc = (desc[0], desc[1]) if len(desc) >= 2 else (r[c['route_id']], '')
        routes[r[c['route_id']]] = {'n': r[c['route_short_name']] or '',
                                    'long': r[c['route_long_name']] or '',
                                    'mk': makat, 'dir': direc,
                                    'ag': r[c['agency_id']]}
    c, rows = load_small(url, cd, 'agency.txt')
    ag = {r[c['agency_id']]: r[c['agency_name']] for r in rows}
    # רכבות ורכבלים אינם רציפי אוטובוס — "תחנת" הרכבת ב-GTFS היא כל
    # המתחם, ושתי רכבות באותה דקה זה שגרה, לא התנגשות
    RAIL = {a for a, n in ag.items() if any(w in n for w in ('רכבת', 'רכבל', 'כרמלית'))}

    c, rows = load_small(url, cd, 'calendar.txt')
    svc_days = {}
    dcols = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
    for r in rows:
        m = 0
        for i, d in enumerate(dcols):
            if r[c[d]] == '1':
                m |= 1 << i
        svc_days[r[c['service_id']]] = m

    c, rows = load_small(url, cd, 'stops.txt')
    stops = {}
    for r in rows:
        desc = r[c['stop_desc']] if 'stop_desc' in c else ''
        city = (re.search(r'עיר:\s*([^:]*?)\s*רציף', desc) or [None, ''])[1].strip()
        # "רציף:" ריק נגמר במילה "קומה:" — לתפוס רק ערך אמיתי שביניהן
        plat = (re.search(r'רציף:\s*([^:]*?)\s*(?:קומה|$)', desc) or [None, ''])[1].strip()
        stops[r[c['stop_id']]] = {'code': r[c['stop_code']], 'name': r[c['stop_name']],
                                  'city': city, 'plat': plat}

    # קיבוץ: (רציף, דקה) -> נסיעות
    groups = {}
    for trip, dep, sid in origin_rows(url, cd):
        t = trip2.get(trip)
        if not t or len(dep) < 5:
            continue
        groups.setdefault((sid, dep), []).append(t)

    conflicts = []
    for (sid, dep), ts in groups.items():
        entries = []
        for rid, svc, th in ts:
            ro = routes.get(rid)
            if not ro or ro['ag'] in RAIL:
                continue
            entries.append((rid, svc, th, ro))
        if not entries:
            continue
        # כמויות (הערת יצחק, מודיעין עילית): כל נסיעה ברישוי היא אוטובוס.
        # קו מתוגבר ב-4 נסיעות באותה דקה תופס 4 מקומות — גם לבדו זו
        # התנגשות. סופרים אוטובוסים לכל יום-שבוע ולוקחים את היום העמוס.
        per_day = [0] * 7
        for rid, svc, th, ro in entries:
            m = svc_days.get(svc, 0)
            for i in range(7):
                if m >> i & 1:
                    per_day[i] += 1
        peak = max(per_day)
        if peak < 2:
            continue
        peak_day = per_day.index(peak)
        qdays = [i for i in range(7) if per_day[i] >= 2]
        by_line = {}
        for rid, svc, th, ro in entries:
            key = ro['mk'] + '|' + ro['dir']
            e = by_line.setdefault(key, {'ro': ro, 'th': th, 'cnt': 0})
            if svc_days.get(svc, 0) >> peak_day & 1:
                e['cnt'] += 1
        st = stops.get(sid, {})
        lines_out = []
        for key, e in sorted(by_line.items(), key=lambda x: -x[1]['cnt']):
            if not e['cnt']:
                continue
            ro, th = e['ro'], e['th']
            if th and '_' in th:
                city_, stop_ = th.split('_', 1)
                dest = f'{stop_}, {city_}'
            elif th:
                dest = th
            else:
                dest = ro['long'].split('<->')[-1].split('-')[0] if '<->' in ro['long'] else ''
            lines_out.append([ro['n'], dest, ag.get(ro['ag'], ''), e['cnt']])
        days_txt = ''.join(DAYS_HE[i] for i in qdays)
        conflicts.append({'code': st.get('code', ''), 'name': st.get('name', ''),
                          'city': st.get('city', ''), 'plat': st.get('plat', ''),
                          't': dep, 'days': days_txt, 'lines': lines_out, 'bus': peak})

    conflicts.sort(key=lambda x: (x['city'], x['name'], x['t']))
    from collections import Counter
    per_stop = Counter((x['code'], x['name'], x['city']) for x in conflicts)
    top = [{'code': k[0], 'name': k[1], 'city': k[2], 'n': v}
           for k, v in per_stop.most_common(12)]
    # דחיסה (הקובץ המלא יצא 11MB): תחנות ומפעילים נשמרים פעם אחת,
    # וכל התנגשות היא מערך קצר — העמוד פורש חזרה בטעינה
    st_tbl, op_tbl, st_ix, op_ix = [], [], {}, {}
    comp = []
    for x in conflicts:
        sk = (x['code'], x['name'], x['city'], x['plat'])
        if sk not in st_ix:
            st_ix[sk] = len(st_tbl)
            st_tbl.append(list(sk))
        ls = []
        for n, dest, op, cnt in x['lines']:
            if op not in op_ix:
                op_ix[op] = len(op_tbl)
                op_tbl.append(op)
            ls.append([n, dest, op_ix[op], cnt])
        comp.append([st_ix[sk], x['t'], x['days'], ls, x['bus']])
    out = {'updated': day.isoformat(), 'total': len(conflicts),
           'stations': len(per_stop), 'top': top,
           'st': st_tbl, 'ops': op_tbl, 'c': comp}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f'התנגשויות רציף: {len(conflicts):,} ב-{len(per_stop):,} תחנות מוצא', flush=True)


if __name__ == '__main__':
    sys.exit(main())
