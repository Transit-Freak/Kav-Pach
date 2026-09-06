#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""השוואה חד-פעמית: המדדים שלנו מול הקבצים של משרד התחבורה ב-data.gov.il (שלמה 06.09).
כותב רק ל-docs/compare — לא נוגע ב-bus/data וב-rail/data.

אוטובוסים: "תכנון מול ביצוע ברמת נסיעה בודדת" (bitzua_bus_trip) ליום נתון — לכל
נסיעה: מק"ט, כיוון, חלופה, רכב, שעת יציאה מתוכננת, התחלה וסיום בפועל (GPS) —
מול הפלט של tools/bus_reliability.py --dump-rides לאותו יום.
רכבת: "רכבת לו"ז" (train_station: לכל תחנה ולכל חודש — בזמן/איחור/הקדמה) ו"רכבת
תכנון מול ביצוע" (train_trip) מול rail/data/index.json.

    python3 tools/compare_mot.py --day 2026-05-12 --rides /tmp/cmp/rides.json --out docs/compare
"""
import argparse
import collections
import datetime
import json
import os
import statistics
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
UA = {'User-Agent': 'kav-bochan-compare/1.0', 'Referer': 'https://data.gov.il/'}


def log(*a):
    print(*a, flush=True)


def ckan(url, timeout=300):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def resource_for_year(package, year):
    pkg = ckan(f'{CKAN}/package_show?id={package}')['result']
    for r in pkg.get('resources', []):
        if (r.get('format') or '').upper() == 'CSV' and str(year) in (r.get('name') or '') and r.get('datastore_active'):
            return r['id'], r.get('last_modified')
    return None, None


def fetch_all(rid, filters=None, fields=None, limit=32000):
    rows, offset = [], 0
    q = f'{CKAN}/datastore_search?resource_id={rid}&limit={limit}'
    if filters:
        q += '&filters=' + urllib.parse.quote(json.dumps(filters))
    if fields:
        q += '&fields=' + ','.join(fields)
    while True:
        res = ckan(f'{q}&offset={offset}')['result']
        recs = res.get('records', [])
        rows.extend(recs)
        if len(recs) < limit:
            break
        offset += limit
    return rows


def hhmm(sec):
    return f'{int(sec) // 3600 % 24:02d}:{int(sec) % 3600 // 60:02d}'


def pct(a, b):
    return f'{100 * a / b:.1f}%' if b else '—'


def alt_norm(a):
    a = str(a or '').strip()
    return '0' if a in ('', '#', '0') else a


# ---------------------------------------------------------------- אוטובוסים
def compare_bus(day, rides_path, out_dir):
    rd = json.load(open(rides_path, encoding='utf-8'))
    rid, updated = resource_for_year('bitzua_bus_trip', day[:4])
    if not rid:
        log('אין משאב ביצוע לשנה הזו')
        return None
    rows = fetch_all(rid, filters={'trip_dt': day},
                     fields=['OperatorId', 'operator_nm', 'OfficeLineId', 'Direction', 'LineAlternative', 'Viechle_num', 'TripId', 'trip_time', 'bitzua_history_start_dt', 'bitzua_history_end_dt', 'erua_hachraga_ind'])
    log(f'משרד: {len(rows):,} שורות ל-{day} (הקובץ עודכן {updated})')
    if not rows:
        return {'day': day, 'mot_rows': 0, 'note': 'אין שורות בקובץ המשרד ליום הזה'}
    # מפתח: (מק"ט, כיוון, חלופה מנורמלת, HH:MM)
    mot = {}
    dup = 0
    for r in rows:
        key = (str(r.get('OfficeLineId')), str(r.get('Direction')), alt_norm(r.get('LineAlternative')), str(r.get('trip_time') or '')[:5])
        if key in mot:
            dup += 1
        mot[key] = r
    ours = {}
    for x in rd['rides']:
        mkt, d, alt, trip, sched, od, ld, lk, n, veh, dep, last = x
        ours[(str(mkt), str(d), alt_norm(alt), hhmm(sched))] = x
    sched_keys = {(str(mkt), str(d), alt_norm(alt), hhmm(s)) for mkt, d, alt, trip, s in rd['sched_trips']}
    both = [k for k in ours if k in mot]
    mot_only = [k for k in mot if k not in ours]
    ours_only = [k for k in ours if k not in mot]
    mot_perf = [k for k, r in mot.items() if r.get('bitzua_history_start_dt')]
    log(f'לו"ז שלנו {len(sched_keys):,} · נצפו אצלנו {len(ours):,} · שורות משרד {len(mot):,} (כפולים {dup:,}) · בוצעו לפי המשרד {len(mot_perf):,} · בשניהם {len(both):,} · רק משרד {len(mot_only):,} · רק אצלנו {len(ours_only):,}')

    def mot_delay(r):
        st = r.get('bitzua_history_start_dt')
        if not st:
            return None
        try:
            t = datetime.datetime.fromisoformat(str(st).replace('T', ' ')[:19])
            hh, mm = map(int, str(r.get('trip_time'))[:5].split(':'))
            planned = t.replace(hour=hh % 24, minute=mm, second=0)
            if hh >= 24:
                planned += datetime.timedelta(days=1)
            dlt = (t - planned).total_seconds() / 60
            if dlt < -12 * 60:
                dlt += 24 * 60
            if dlt > 12 * 60:
                dlt -= 24 * 60
            return dlt
        except Exception:  # noqa: BLE001
            return None

    diffs, pairs = [], []
    veh_eq = veh_n = 0
    per_op = collections.defaultdict(lambda: {'n': 0, 'mot_on': 0, 'our_on': 0, 'diffs': [], 'veh_eq': 0, 'veh_n': 0})
    hist = collections.Counter()
    for k in both:
        r, x = mot[k], ours[k]
        md = mot_delay(r)
        od = x[5] / 60 if x[5] is not None else None
        op = r.get('operator_nm') or '?'
        p = per_op[op]
        if str(r.get('Viechle_num') or '').strip() and x[9]:
            veh_n += 1
            p['veh_n'] += 1
            if str(r['Viechle_num']).strip().lstrip('0') == str(x[9]).strip().lstrip('0'):
                veh_eq += 1
                p['veh_eq'] += 1
        if md is None or od is None:
            continue
        d = od - md
        diffs.append(d)
        pairs.append((md, od))
        p['n'] += 1
        p['diffs'].append(d)
        p['mot_on'] += 1 if -2 <= md <= 5 else 0
        p['our_on'] += 1 if -2 <= od <= 5 else 0
        hist[max(-15, min(15, int(round(d))))] += 1
    mot_on = sum(1 for md, od in pairs if -2 <= md <= 5)
    our_on = sum(1 for md, od in pairs if -2 <= od <= 5)
    agree = sum(1 for md, od in pairs if (-2 <= md <= 5) == (-2 <= od <= 5))
    res = {
        'day': day, 'mot_file_updated': updated, 'mot_rows': len(rows), 'mot_dup_keys': dup, 'mot_performed': len(mot_perf),
        'our_sched': len(sched_keys), 'our_observed': len(ours), 'both': len(both), 'mot_only': len(mot_only), 'ours_only': len(ours_only),
        'origin_pairs': len(pairs),
        'mot_on_time': mot_on, 'our_on_time': our_on, 'agree_on_time': agree,
        'diff_median': round(statistics.median(diffs), 2) if diffs else None,
        'diff_mean': round(statistics.mean(diffs), 2) if diffs else None,
        'diff_within_1': sum(1 for d in diffs if abs(d) <= 1), 'diff_within_2': sum(1 for d in diffs if abs(d) <= 2), 'diff_within_5': sum(1 for d in diffs if abs(d) <= 5),
        'mot_delay_median': round(statistics.median([m for m, o in pairs]), 2) if pairs else None,
        'our_delay_median': round(statistics.median([o for m, o in pairs]), 2) if pairs else None,
        'hist_minutes': dict(sorted(hist.items())),
        'vehicle_same': veh_eq, 'vehicle_compared': veh_n,
        'hachraga': sum(1 for r in rows if str(r.get('erua_hachraga_ind') or '') not in ('', '0', 'None', 'False')),
        'per_operator': sorted([[op, p['n'], p['mot_on'], p['our_on'], round(statistics.median(p['diffs']), 2) if p['diffs'] else None, p['veh_eq'], p['veh_n']] for op, p in per_op.items()], key=lambda x: -x[1]),
        'mot_only_sample': [list(k) for k in mot_only[:10]], 'ours_only_sample': [list(k) for k in ours_only[:10]],
    }
    json.dump(res, open(f'{out_dir}/mot-bus-{day}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    md = [f'# מדד דיוק האוטובוסים מול קובץ הביצוע של משרד התחבורה — {day}', '',
          f'קובץ המשרד ("תכנון מול ביצוע ברמת נסיעה בודדת", עודכן {updated}): {len(rows):,} שורות ליום, מהן {len(mot_perf):,} עם זמן התחלה בפועל.',
          f'הלו"ז שלנו (GTFS של אותו יום): {len(sched_keys):,} נסיעות; נצפו אצלנו: {len(ours):,}.', '',
          '## כיסוי', f'- בשני המקורות: {len(both):,}', f'- רק אצל המשרד: {len(mot_only):,}', f'- רק אצלנו: {len(ours_only):,}', '',
          '## יציאה מהמוצא (נסיעות שבשניהן יש מדידה במוצא)', f'- זוגות: {len(pairs):,}',
          f'- חציון האיחור במוצא: משרד {res["mot_delay_median"]} דק׳ · אנחנו {res["our_delay_median"]} דק׳',
          f'- הפרש (אנחנו פחות משרד): חציון {res["diff_median"]} דק׳ · ממוצע {res["diff_mean"]} דק׳ · בתוך דקה {pct(res["diff_within_1"], len(pairs))} · בתוך 2 דק׳ {pct(res["diff_within_2"], len(pairs))} · בתוך 5 דק׳ {pct(res["diff_within_5"], len(pairs))}',
          f'- "יצאה בזמן" (בין 2- ל-5 דק׳): משרד {pct(mot_on, len(pairs))} · אנחנו {pct(our_on, len(pairs))} · הסכמה נסיעה-נסיעה {pct(agree, len(pairs))}',
          f'- מספר הרכב זהה: {pct(veh_eq, veh_n)} מתוך {veh_n:,}', f'- נסיעות עם "אירוע החרגה" אצל המשרד: {res["hachraga"]:,}', '',
          '## לפי מפעיל', '| מפעיל | זוגות | בזמן לפי המשרד | בזמן לפי המדד | חציון ההפרש | רכב זהה |', '|---|---|---|---|---|---|']
    for op, n, mo, oo, dm, ve, vn in res['per_operator'][:25]:
        md.append(f'| {op} | {n:,} | {pct(mo, n)} | {pct(oo, n)} | {dm} | {pct(ve, vn)} |')
    md += ['', '## התפלגות ההפרש בדקות (אנחנו פחות משרד)', ' '.join(f'{k:+d}:{v}' for k, v in sorted(hist.items()))]
    open(f'{out_dir}/mot-bus-{day}.md', 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    log('\n'.join(md[:20]))
    return res


# ---------------------------------------------------------------- רכבת
def compare_rail(out_dir, rail_index='rail/data/index.json', stations_path='rail/data/stations.json'):
    pkg = ckan(f'{CKAN}/package_show?id=train_station')['result']
    rid = next((r['id'] for r in pkg['resources'] if r.get('datastore_active')), None)
    rows = fetch_all(rid)
    log(f'רכבת לו"ז: {len(rows):,} שורות')
    by_month = collections.defaultdict(collections.Counter)
    by_station = collections.defaultdict(collections.Counter)
    for r in rows:
        ym = (int(r.get('shana') or 0), int(r.get('hodesh') or 0))
        st = str(r.get('station_status_nm') or '')
        n = int(r.get('status_count') or 0)
        by_month[ym][st] += n
        by_station[(ym, str(r.get('train_station_nm') or ''))][st] += n
    months = sorted(by_month)
    last = months[-1] if months else None
    statuses = sorted({s for c in by_month.values() for s in c})
    series = []
    for ym in months[-24:]:
        c = by_month[ym]
        tot = sum(c.values())
        on = c.get('בזמן', 0)
        series.append({'ym': f'{ym[0]}-{ym[1]:02d}', 'total': tot, 'on': on, 'on_share': round(on / tot, 4) if tot else None, **{s: c.get(s, 0) for s in statuses}})
    # ביצוע נסיעות (train_trip): אחוז ביצוע לפי חודש
    try:
        pkg2 = ckan(f'{CKAN}/package_show?id=train_trip')['result']
        rid2 = next((r['id'] for r in pkg2['resources'] if r.get('datastore_active')), None)
        rows2 = fetch_all(rid2)
        bm = collections.defaultdict(lambda: [0, 0, 0])
        for r in rows2:
            ym = (int(r.get('shana') or 0), int(r.get('hodesh') or 0))
            bm[ym][0] += int(r.get('rishui_all') or 0)
            bm[ym][1] += int(r.get('rishui_only') or 0)
            bm[ym][2] += int(r.get('bitzua_only') or 0)
        perf = [{'ym': f'{ym[0]}-{ym[1]:02d}', 'rishui_all': v[0], 'rishui_only': v[1], 'bitzua_only': v[2], 'performed_share': round(1 - v[1] / v[0], 4) if v[0] else None} for ym, v in sorted(bm.items())[-24:]]
    except Exception as e:  # noqa: BLE001
        perf = [{'error': str(e)}]
    # שלנו: לפי תחנה על פני כל התקופה, ולפי חודש
    idx = json.load(open(rail_index, encoding='utf-8'))
    st_names = json.load(open(stations_path, encoding='utf-8')) if os.path.exists(stations_path) else {}
    our_st = collections.defaultdict(lambda: [0, 0])
    our_days = [d for d in idx['days'] if d.get('rides')]
    our_tot = [0, 0]
    for d in our_days:
        for code, s in (d.get('stations') or {}).items():
            if s.get('n'):
                our_st[code][0] += s['n']
                our_st[code][1] += s['b'][0]
                our_tot[0] += s['n']
                our_tot[1] += s['b'][0]
    name_of = lambda c: (st_names.get(c) or [c])[0]  # noqa: E731
    last_st = {}
    if last:
        for (ym, nm), c in by_station.items():
            if ym == last:
                tot = sum(c.values())
                last_st[nm] = {'total': tot, 'on': c.get('בזמן', 0), 'on_share': round(c.get('בזמן', 0) / tot, 4) if tot else None}
    ours_by_name = {}
    for code, (n, on) in our_st.items():
        nm = name_of(code)
        o = ours_by_name.setdefault(nm, [0, 0])
        o[0] += n
        o[1] += on
    table = []
    for nm, m in sorted(last_st.items(), key=lambda kv: -kv[1]['total']):
        o = ours_by_name.get(nm) or next((v for k, v in ours_by_name.items() if nm and (nm in k or k in nm)), None)
        table.append({'station': nm, 'mot_total': m['total'], 'mot_on_share': m['on_share'], 'our_n': o[0] if o else None, 'our_on_share': round(o[1] / o[0], 4) if o and o[0] else None})
    res = {'mot_statuses': statuses, 'mot_last_month': f'{last[0]}-{last[1]:02d}' if last else None, 'mot_months': len(months),
           'mot_monthly': series, 'mot_performance_monthly': perf,
           'our_period': [our_days[0]['d'], our_days[-1]['d']] if our_days else None, 'our_days': len(our_days),
           'our_stop_arrivals': our_tot[0], 'our_on_share': round(our_tot[1] / our_tot[0], 4) if our_tot[0] else None,
           'stations_last_month_vs_ours': table}
    json.dump(res, open(f'{out_dir}/mot-rail.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    md = ['# מדד אמינות הרכבת מול קובצי הרכבת של משרד התחבורה', '',
          f'קובץ "רכבת לו"ז" (לכל תחנה ולכל חודש): {len(months)} חודשים, האחרון {res["mot_last_month"]}. סטטוסים במקור: {", ".join(statuses)}.',
          f'המדד שלנו: {res["our_days"]} ימים ({res["our_period"]}), {our_tot[0]:,} הגעות לתחנות, {pct(our_tot[1], our_tot[0])} בזמן (עד 5 דק׳).', '',
          '## המשרד, לפי חודש (24 האחרונים)', '| חודש | הגעות | בזמן | ' + ' | '.join(statuses) + ' |', '|---|---|---|' + '---|' * len(statuses)]
    for s in series:
        md.append(f'| {s["ym"]} | {s["total"]:,} | {pct(s["on"], s["total"])} | ' + ' | '.join(f'{s.get(st, 0):,}' for st in statuses) + ' |')
    md += ['', '## ביצוע נסיעות לפי המשרד (train_trip), 24 חודשים אחרונים', '| חודש | נסיעות ברישוי | לא בוצעו | בוצעו בלי רישוי | אחוז ביצוע |', '|---|---|---|---|---|']
    for p in perf:
        if 'ym' in p:
            md.append(f'| {p["ym"]} | {p["rishui_all"]:,} | {p["rishui_only"]:,} | {p["bitzua_only"]:,} | {pct(p["rishui_all"] - p["rishui_only"], p["rishui_all"])} |')
    md += ['', f'## לפי תחנה: החודש האחרון אצל המשרד ({res["mot_last_month"]}) מול כל התקופה שלנו', '| תחנה | הגעות (משרד) | בזמן (משרד) | הגעות (שלנו) | בזמן (שלנו) |', '|---|---|---|---|---|']
    for t in table[:70]:
        md.append(f'| {t["station"]} | {t["mot_total"]:,} | {pct(t["mot_on_share"] or 0, 1) if t["mot_on_share"] is not None else "—"} | {t["our_n"] if t["our_n"] is not None else "—"} | {pct(t["our_on_share"] or 0, 1) if t["our_on_share"] is not None else "—"} |')
    md += ['', 'הערה: התקופות שונות, וההגדרות שונות — "בזמן" אצל המשרד לפי הסף שלהם (איחור מעל 6 דקות נספר כאיחור), אצלנו עד 5 דקות.']
    open(f'{out_dir}/mot-rail.md', 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    log('\n'.join(md[:12]))
    return res


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default='')
    ap.add_argument('--rides', default='')
    ap.add_argument('--out', default='docs/compare')
    ap.add_argument('--skip-rail', action='store_true')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if a.day and a.rides and os.path.exists(a.rides):
        compare_bus(a.day, a.rides, a.out)
    else:
        log('בלי השוואת אוטובוסים (חסר --day/--rides)')
    if not a.skip_rail:
        compare_rail(a.out)
