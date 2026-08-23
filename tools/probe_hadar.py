# -*- coding: utf-8 -*-
"""המבחן להשערת שלמה: אולי מוניות הדר לוד רשומה כאוטובוס? לכל צילום קיים:
מזהה כל agency עם 'הדר' בשם, ומדפיס את כל שורות הקווים שמצביעות עליו —
בלי שום סינון לפי סוג. גם סופר קווים 'יתומים' (agency_id בלי רשומת מפעיל)."""
import datetime
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')


def exists(url):
    req = urllib.request.Request(url, method='HEAD')
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


dates = []
d = datetime.date(2017, 3, 1)
while d <= datetime.date(2022, 1, 15):
    dates.append(d.strftime('%Y%m%d'))
    d = (d + datetime.timedelta(days=17)).replace(day=1 if d.day == 15 else 15)

seen_any = False
for ds in dates:
    url = f'{BASE}/{ds}/gtfs.zip'
    if not exists(url):
        continue
    try:
        members = central_dir(url)
        c2, arows = member_rows(url, members, 'agency.txt')
        agency = {r[c2['agency_id']]: r[c2['agency_name']].strip() for r in arows}
        hadar = {aid: nm for aid, nm in agency.items() if 'הדר' in nm}
        if not hadar:
            continue
        c, rows = member_rows(url, members, 'routes.txt')
        cnt = 0
        for r in rows:
            if r[c['agency_id']].strip() in hadar:
                cnt += 1
                if cnt <= 6:
                    print(f"  {ds}: קו {r[c['route_short_name']]} · {r[c['route_long_name']][:60]} · rd={r[c['route_desc']]} · type={r[c['route_type']]}")
        print(f'{ds}: {list(hadar.values())} (id={list(hadar)}) · {cnt} קווים')
        seen_any = True
    except BaseException:  # noqa: BLE001
        continue
if not seen_any:
    print('RESULT: "הדר" לא הופיעה כמפעיל באף צילום שנסרק')
