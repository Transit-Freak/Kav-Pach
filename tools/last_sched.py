#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הלו"ז האחרון לקווים שבוטלו — שאיבה אוטומטית מהארכיון.

קו שבוטל ואין לו שום אירוע לו"ז (sched/freq) נשאר בלי זכר לשעות שבהן פעל.
הכלי משלים: לכל וריאנט שביטולו מלאה לו שנה (ועודו מבוטל), נקרא יום-הארכיון
האחרון שבו היה פעיל — היום הזמין האחרון שלפני תאריך הביטול, ספציפית לכל
קו — ונשלף ממנו לוח-הזמנים השבועי המלא (שעות יציאה מהתחנה הראשונה, לפי
ימי שבוע). התוצאה נרשמת בקובץ הווריאנט כגרסה k='times' עם טבלת tb.

סף השנה (בקשת המשתמש): ביטול טרי עשוי עוד לחזור; אחרי שנה הקו מת סופית,
והמנגנון "יודע לשאוב לבד" — הצעד היומי בצינור המאוחד מזהה קווים שחצו את
השנה ומשלים אותם, בלי יד אדם.

קיבוץ לפי יום-ארכיון: כל הקווים שבוטלו סביב אותו תאריך נקראים בהורדה
אחת (~70MB ליום). MAX_DAYS מגביל קבוצות-יום לריצה (לצעד היומי); MAX_MIN
מגביל זמן (לריצת השלמה ארוכה).

מצב: line-history/data/last-sched-skip.json — רק כשלים קבועים (קו שלא
נמצא בארכיון); הצלחות מסומנות בגרסת ה-times בקובץ הקו עצמו (אידמפוטנטי).
"""
import datetime
import json
import os
import re
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import S3, central_dir, fsafe, http, member_rows, stream_member


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
MAX_DAYS = int(os.environ.get('MAX_DAYS', '0'))      # 0 = בלי מגבלה
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))      # 0 = בלי מגבלה
TEST_RD = os.environ.get('TEST_RD', '')              # ריצה יבשה על וריאנט אחד
YEAR_D = int(os.environ.get('YEAR_D', '365'))
T0 = time.time()

DAY_ORDER = 'אבגדהוש'
DAY_NAME = {'א': 'ראשון', 'ב': 'שני', 'ג': 'שלישי', 'ד': 'רביעי',
            'ה': 'חמישי', 'ו': 'שישי', 'ש': 'שבת'}
WD_LETTER = {6: 'א', 0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש'}
COL_LETTER = {'sunday': 'א', 'monday': 'ב', 'tuesday': 'ג', 'wednesday': 'ד',
              'thursday': 'ה', 'friday': 'ו', 'saturday': 'ש'}


def list_archive_days(lo, hi):
    """ימי הארכיון הזמינים בטווח [lo, hi] (יש חורים)."""
    days = []
    ym = datetime.date.fromisoformat(lo[:7] + '-01')
    while ym.isoformat()[:7] <= hi[:7]:
        xml, _ = http(f'{S3}/?list-type=2&max-keys=1000&prefix=gtfs_archive/{ym.year}/{ym.month:02d}/')
        for m in re.finditer(rb'<Key>gtfs_archive/(\d{4})/(\d{2})/(\d{2})/israel-public-transportation\.zip</Key>', xml):
            ds = b'-'.join(m.groups()).decode()
            if lo <= ds <= hi:
                days.append(ds)
        ym = (ym.replace(day=28) + datetime.timedelta(days=5)).replace(day=1)
    return sorted(set(days))


def pending_variants(today):
    """וריאנטים מבוטלים סופית, בלי שום לו"ז, שביטולם לפני שנה ומעלה."""
    skip = jload(f'{OUTDIR}/last-sched-skip.json', {})
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=YEAR_D)).isoformat()
    out = []
    for fn in os.listdir(f'{OUTDIR}/lines'):
        if not fn.endswith('.json'):
            continue
        lf = jload(f'{OUTDIR}/lines/{fn}', None)
        if not lf or not lf.get('versions'):
            continue
        rd = lf.get('rd') or fn[:-5].replace('H', '#')
        if TEST_RD and rd != TEST_RD:
            continue
        vs = lf['versions']
        ks = [v.get('k') for v in vs]
        if any(k in ('sched', 'freq', 'times') for k in ks):
            continue
        # מבוטל סופית = אירוע removed אחרון שאין אחריו לידה מחדש
        last_rem = last_new = ''
        for v in vs:
            if v.get('k') == 'removed':
                last_rem = max(last_rem, v['d'])
            elif v.get('k') in ('new', 'baseline'):
                last_new = max(last_new, v['d'])
        if not last_rem or last_new > last_rem:
            continue
        if last_rem > cutoff:
            continue          # טרם מלאה שנה — הצעד היומי יתפוס אותו בבוא היום
        if skip.get(rd):
            continue
        out.append((rd, last_rem))
    return out


def weekly_times(ds, rds):
    """הלו"ז השבועי המלא של הווריאנטים ביום-ארכיון: rd -> {אות-יום: [שעות]}.

    בניגוד ל-day_departures (שעות של יום בודד), כאן נלקח כל שבוע-הטיפוס
    מה-calendar: לכל שירות בתוקף ביום ds — אילו ימי שבוע הוא מקיף.
    חריגי calendar_dates (חגים) מדולגים בכוונה — מבוקש הלו"ז הרגיל.
    """
    url = f"{S3}/gtfs_archive/{ds[:4]}/{ds[5:7]}/{ds[8:10]}/israel-public-transportation.zip"
    members = central_dir(url)
    dsc = ds.replace('-', '')

    c, rows = member_rows(url, members, 'routes.txt')
    rid2rd = {}
    for row in rows:
        try:
            parts = row[c['route_desc']].strip().split('-')
            mkt = parts[0].lstrip('0') if parts else ''
            if len(parts) >= 3 and mkt:
                rd = f"{mkt}-{parts[1]}-{parts[2]}"
                if rd in rds:
                    rid2rd[row[c['route_id']]] = rd
        except IndexError:
            continue
    if not rid2rd:
        return {}

    c, rows = member_rows(url, members, 'calendar.txt')
    svc_days = {}
    for row in rows:
        try:
            if not (row[c['start_date']] <= dsc <= row[c['end_date']]):
                continue
            letters = ''.join(l for col, l in COL_LETTER.items() if row[c[col]].strip() == '1')
            if letters:
                svc_days[row[c['service_id']]] = letters
        except IndexError:
            continue

    c, rows = member_rows(url, members, 'trips.txt')
    trip2 = {}
    for row in rows:
        try:
            rd = rid2rd.get(row[c['route_id']])
            days = svc_days.get(row[c['service_id']])
            if rd and days:
                trip2[row[c['trip_id']].encode()] = (rd, days)
        except IndexError:
            continue

    out = {}
    buf = [b'']
    hdr = {}

    def on_chunk(data):
        buf[0] += data
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not hdr:
                for i, hname in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr[hname.strip()] = i
                hdr['_t'], hdr['_d'], hdr['_s'] = hdr['trip_id'], hdr['departure_time'], hdr['stop_sequence']
                continue
            f = ln.split(b',')
            try:
                if f[hdr['_s']].strip() != b'1':
                    continue
                hit = trip2.get(f[hdr['_t']].strip())
                if hit is None:
                    continue
                rd, days = hit
                t = f[hdr['_d']][:5].decode()
                for l in days:
                    out.setdefault(rd, {}).setdefault(l, set()).add(t)
            except (IndexError, UnicodeDecodeError):
                continue

    stream_member(url, members, 'stop_times.txt', on_chunk)
    return {rd: {l: sorted(ts) for l, ts in d.items()} for rd, d in out.items()}


def collapse_buckets(day2times):
    """קיבוץ ימים עם לו"ז זהה לשורה אחת: [['ימי חול (א׳–ה׳)', 'ת1,ת2'], …]"""
    groups = []   # [(אותיות, times)]
    for l in DAY_ORDER:
        ts = day2times.get(l)
        if not ts:
            continue
        for g in groups:
            if g[1] == ts:
                g[0] += l
                break
        else:
            groups.append([l, ts])
    rows = []
    for letters, ts in groups:
        if letters == 'אבגדה':
            label = 'ימי חול (א׳–ה׳)'
        elif letters == 'אבגדהו':
            label = 'ימים א׳–ו׳'
        elif letters == 'אבגדהוש':
            label = 'כל ימות השבוע'
        elif len(letters) == 1:
            label = 'שבת' if letters == 'ש' else f'ימי {DAY_NAME[letters]}'
        else:
            label = 'ימי ' + ', '.join(f'{l}׳' for l in letters)
        rows.append([label, ','.join(ts)])
    return rows


def main():
    today = datetime.date.today().isoformat()
    pend = pending_variants(today)
    if not pend:
        print('אין קווים ממתינים — הכל הושלם')
        return
    arc_lo = '2022-01-16'
    avail = list_archive_days(arc_lo, today)

    # קיבוץ לפי יום-הארכיון האחרון שלפני הביטול — ספציפי לכל קו
    by_day = {}
    skip = jload(f'{OUTDIR}/last-sched-skip.json', {})
    for rd, rem in pend:
        prev_days = [d for d in avail if d < rem]
        if not prev_days:
            skip[rd] = 'לפני תחילת הארכיון'
            continue
        by_day.setdefault(prev_days[-1], []).append(rd)
    print(f'{len(pend)} קווים ממתינים ב-{len(by_day)} קבוצות-יום')

    done_days = 0
    n_written = 0
    for ds in sorted(by_day, reverse=True):   # מהחדש לישן — הטרי קודם
        if MAX_DAYS and done_days >= MAX_DAYS:
            print(f'מכסת ימים לריצה ({MAX_DAYS}) — ההמשך בריצה הבאה')
            break
        if MAX_MIN and (time.time() - T0) / 60 > MAX_MIN:
            print(f'מכסת זמן לריצה ({MAX_MIN} דק\') — ההמשך בריצה הבאה')
            break
        rds = set(by_day[ds])
        try:
            wt = weekly_times(ds, rds)
        except (ValueError, KeyError, zlib.error) as e:
            print(ds, '— קובץ בעייתי:', e)
            done_days += 1
            continue
        for rd in sorted(rds):
            d2t = wt.get(rd)
            if not d2t:
                # הקו לא בקובץ יומו האחרון — ננסה פעם אחת יום זמין אחד אחורה
                prevs = [d for d in avail if d < ds]
                got = False
                if prevs:
                    try:
                        wt2 = weekly_times(prevs[-1], {rd})
                        if wt2.get(rd):
                            d2t, ds_eff, got = wt2[rd], prevs[-1], True
                    except (ValueError, KeyError, zlib.error):
                        pass
                if not got:
                    skip[rd] = f'לא נמצא בארכיון ({ds})'
                    print(f'  {rd}: לא נמצא — דילוג קבוע')
                    continue
            else:
                ds_eff = ds
            tb = collapse_buckets(d2t)
            if not tb:
                skip[rd] = f'בלי נסיעות ({ds_eff})'
                continue
            n_tot = sum(len(r[1].split(',')) for r in tb)
            if TEST_RD:
                print(f'--- {rd} (בוטל, יום אחרון בארכיון {ds_eff}):')
                for label, ts in tb:
                    print(f'   {label}: {ts}')
                continue
            p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
            lf = jload(p, None)
            if lf is None or any(v.get('k') == 'times' for v in lf['versions']):
                continue
            lf['versions'].append({
                'd': ds_eff, 'k': 'times', 'shp': '', 'stops': [], 'src': 'ob',
                'note': f'הלו"ז האחרון לפני הביטול — צילום מהארכיון ({n_tot} יציאות בשבוע)',
                'tb': tb,
            })
            lf['versions'].sort(key=lambda v: v['d'])
            json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
            n_written += 1
            print(f'  {rd}: נכתב לו"ז ({ds_eff}, {n_tot} יציאות)')
        done_days += 1

    if not TEST_RD:
        json.dump(skip, open(f'{OUTDIR}/last-sched-skip.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
    remaining = len(pend) - n_written - 0
    print(f'סיכום: נכתבו {n_written} | קבוצות-יום שעובדו {done_days}/{len(by_day)}')
    if done_days >= len(by_day):
        print('נותרו 0 קבוצות')


if __name__ == '__main__':
    main()
