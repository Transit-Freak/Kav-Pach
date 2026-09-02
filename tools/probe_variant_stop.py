# -*- coding: utf-8 -*-
"""בדיקה מול המקור (ארכיון אופן באס, Stride): האם תחנה מסוימת הייתה ברצף התחנות
של וריאנט בתאריכים נתונים. שאלת שלמה 02.09 על 391-2-א וקריית מחקר גרעינית (10345):
ירדה ב-07.2025, אבל האם חזרה במהלך קיץ 2025 ואז ירדה שוב ב-2026? הקבצים שלנו
אינם מתעדים חזרה, אבל קיץ 2025 היה לפני המעקב היומי — אז שואלים את הארכיון.

אותה שרשרת כמו backfill_stops.seq_for: route → ride → ride_stops (עם פרטי התחנה).

    RD=10391-2-א STOP=10345 DATES=2025-07-01,2025-07-15,... python3 tools/probe_variant_stop.py
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

API = 'https://open-bus-stride-api.hasadna.org.il'
RD = os.environ['RD']
STOP = os.environ.get('STOP', '10345')
DATES = [d for d in os.environ.get('DATES', '').split(',') if d]
OUT = pathlib.Path('docs/probes') / f"variant-stop-{RD.replace('#', 'H').replace('/', '_')}-{STOP}.json"


def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (probe; polite)'})
            with urllib.request.urlopen(req, timeout=90) as r:
                time.sleep(0.4)
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(6 * (attempt + 1))
    print(f'  api failed: {url} :: {last}', file=sys.stderr)
    return None


def seq_for(rd, d):
    mkt, dr, alt = rd.split('-', 2)
    routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt, route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes:
        routes = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mkt.zfill(5), route_direction=dr, route_alternative=alt, limit=5)
    if not isinstance(routes, list) or not routes:
        return None, 'הווריאנט לא רשום ביום הזה'
    rid = routes[0]['id']
    rides = api('/gtfs_rides/list', gtfs_route_id=rid, limit=1, start_time_from=f'{d}T00:00:00+02:00', start_time_to=f'{d}T23:59:00+02:00')
    if not isinstance(rides, list) or not rides:
        return None, 'רשום, אבל בלי נסיעות ביום הזה'
    if rides[0].get('gtfs_route_id') != rid:
        return None, 'הסינון לפי route לא כובד'
    rs = api('/gtfs_ride_stops/list', gtfs_ride_ids=rides[0]['id'], limit=300)
    if not isinstance(rs, list) or len(rs) < 2:
        return None, 'אין רצף תחנות לנסיעה'
    rs = [r for r in rs if r.get('gtfs_ride_id') == rides[0]['id']]
    rs.sort(key=lambda r: r.get('stop_sequence') or 0)
    return [[str(r.get('gtfs_stop__code') or ''), r.get('gtfs_stop__name') or ''] for r in rs], ''


def main():
    out = {'rd': RD, 'stop': STOP, 'checked': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime('%d.%m.%Y %H:%M'), 'days': []}
    for d in DATES:
        seq, why = seq_for(RD, d)
        if seq is None:
            out['days'].append({'d': d, 'status': why})
            print(f'{d}: {why}')
            continue
        present = any(s[0] == STOP for s in seq)
        out['days'].append({'d': d, 'status': 'רשום', 'n_stops': len(seq), 'stop_present': present})
        print(f"{d}: {len(seq)} תחנות · {STOP} {'בפנים' if present else 'לא בפנים'}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('נכתב', OUT)


if __name__ == '__main__':
    main()
