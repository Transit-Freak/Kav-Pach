# -*- coding: utf-8 -*-
"""ארכיאולוגיית מוניות שירות (בקשת שלמה 23.08): סריקת כל ארכיון TransitFeeds
(2017–2022) דרך קריאות-טווח זעירות — אילו תאגידי מוניות היו בפיד הארצי,
אילו קווים הפעילו ומתי, ומה מהם חסר בארכיון הקו בזמן. דיווח בלבד (שלב א')."""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows, fsafe  # noqa: E402

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
LINESDIR = 'line-history/data/lines'

# מועמדים: 1 ו-15 בכל חודש, 2017-03 עד 2022-01 (טווח הארכיון)
dates = []
d = datetime.date(2017, 3, 1)
while d <= datetime.date(2022, 1, 15):
    dates.append(d.strftime('%Y%m%d'))
    d = (d + datetime.timedelta(days=17)).replace(day=1 if d.day == 15 else 15)

import urllib.request


def exists(url):
    # S3 מחזיר 403 גם על מפתח שלא קיים; HEAD זול מונע 4 ניסיונות-שווא
    # של http() (שמסיים ב-SystemExit) על כל תאריך חסר
    req = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


ops = {}      # op -> {rd: {'line','dest','ty','first','last'}}
snaps_ok = 0
for ds in dates:
    url = f'{BASE}/{ds}/gtfs.zip'
    if not exists(url):
        continue
    try:
        members = central_dir(url)
        c2, arows = member_rows(url, members, 'agency.txt')
        agency = {r[c2['agency_id']]: r[c2['agency_name']].strip() for r in arows}
        taxi_ag = {aid: nm for aid, nm in agency.items() if 'מוני' in nm or 'טקסי' in nm}
        c, rows = member_rows(url, members, 'routes.txt')
    except BaseException:  # noqa: BLE001 — גם SystemExit של http()
        continue
    snaps_ok += 1
    if not taxi_ag:
        continue
    for r in rows:
        aid = r[c['agency_id']].strip()
        if aid not in taxi_ag:
            continue
        rd = r[c['route_desc']].strip()
        key = rd if rd else f'noRD:{r[c["route_id"]]}'
        op = taxi_ag[aid]
        rec = ops.setdefault(op, {}).setdefault(key, {
            'line': r[c['route_short_name']].strip(),
            'dest': r[c['route_long_name']].strip()[:70],
            'ty': r[c['route_type']].strip(), 'first': ds, 'last': ds})
        rec['last'] = ds
print(f'צילומים שנקראו בהצלחה: {snaps_ok} מתוך {len(dates)}')
print(f'תאגידי מוניות שנמצאו אי-פעם: {len(ops)}')
missing_total = 0
for op, routes in sorted(ops.items()):
    have = sum(1 for rd in routes if os.path.exists(f'{LINESDIR}/{fsafe(rd)}.json'))
    missing = {rd: m for rd, m in routes.items()
               if not os.path.exists(f'{LINESDIR}/{fsafe(rd)}.json')}
    missing_total += len(missing)
    print(f'\n== {op}: {len(routes)} קווים בארכיון · {have} כבר באתר · {len(missing)} חסרים ==')
    for rd, m in sorted(missing.items()):
        print(f"  חסר: קו {m['line']} · {m['dest']} · rd={rd} · type={m['ty']} · {m['first']}→{m['last']}")
print(f'\nRESULT: סה"כ {missing_total} קווי מוניות חסרים באתר')
json.dump(ops, open('/tmp/taxi_ops.json', 'w', encoding='utf-8'), ensure_ascii=False)
