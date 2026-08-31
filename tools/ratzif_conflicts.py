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
    trip2 = {r[c['trip_id']]: (r[c['route_id']], r[c['service_id']]) for r in rows}

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
        plat = (re.search(r'רציף:\s*(\S+)', desc) or [None, ''])[1].strip()
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
        if len(ts) < 2:
            continue
        # זהות קו = מק"ט+כיוון; חלופות של אותו קו-כיוון מאוחדות
        by_line = {}
        for rid, svc in ts:
            ro = routes.get(rid)
            if not ro or ro['ag'] in RAIL:
                continue
            key = ro['mk'] + '|' + ro['dir']
            by_line.setdefault(key, []).append((rid, svc))
        if len(by_line) < 2:
            continue
        # חפיפת ימים בין שני קווים שונים לפחות
        lines_out, seen_pairs_mask = [], 0
        keys = list(by_line)
        pair_mask = 0
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                for _, s1 in by_line[keys[i]]:
                    for _, s2 in by_line[keys[j]]:
                        pair_mask |= svc_days.get(s1, 0) & svc_days.get(s2, 0)
        if not pair_mask:
            continue
        st = stops.get(sid, {})
        for key in keys:
            rid, svc = by_line[key][0]
            ro = routes[rid]
            dest = ro['long'].split('<->')[-1].split('-')[0] if '<->' in ro['long'] else ''
            lines_out.append({'n': ro['n'], 'mk': ro['mk'], 'dest': dest,
                              'op': ag.get(ro['ag'], ''),
                              'days': ''.join(DAYS_HE[i] for i in range(7)
                                              if svc_days.get(svc, 0) >> i & 1)})
        days_txt = ''.join(DAYS_HE[i] for i in range(7) if pair_mask >> i & 1)
        conflicts.append({'code': st.get('code', ''), 'name': st.get('name', ''),
                          'city': st.get('city', ''), 'plat': st.get('plat', ''),
                          't': dep, 'days': days_txt, 'lines': lines_out})

    conflicts.sort(key=lambda x: (x['city'], x['name'], x['t']))
    # תחנה עם הכי הרבה התנגשויות — לסיכום בעמוד
    from collections import Counter
    per_stop = Counter((x['code'], x['name'], x['city']) for x in conflicts)
    top = [{'code': k[0], 'name': k[1], 'city': k[2], 'n': v}
           for k, v in per_stop.most_common(12)]
    out = {'updated': day.isoformat(), 'total': len(conflicts),
           'stations': len(per_stop), 'top': top, 'conflicts': conflicts}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f'התנגשויות רציף: {len(conflicts):,} ב-{len(per_stop):,} תחנות מוצא', flush=True)


if __name__ == '__main__':
    sys.exit(main())
