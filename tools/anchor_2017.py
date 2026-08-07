#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""עוגני 2017 — מתוך ארכיון TransitFeeds/OpenMobilityData (הפיד הארצי של משרד התחבורה).

ארכיון הסדנא מתחיל ב-16.1.2022; הארכיון הזה מחזיק צילומים מ-2017 ואילך, ומכסה
בדיוק את החור שלפני כן. כאן נשאבת שכבה דקה בלבד — routes.txt של כל צילום 2017 —
שממנה נבנה "עוגן": מה היה קיים ב-2017, תחת איזה שם, ובאילו תאריכים נצפה.

הקובץ נפרד מקבצי הקווים בכוונה: הוא לא מתנגש בסריקות הרקע שכותבות אליהם.

פלט: line-history/data/anchor-2017.json
"""
import concurrent.futures
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, http, member_rows  # noqa: E402

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
YEAR = int(os.environ.get('YEAR', '2017'))


def snapshot_days(year):
    """הימים שקיימים בארכיון — הבאקט אינו מאפשר רשימה, אז בדיקה יום-יום.

    365 בדיקות בטור נמשכות זמן רב מדי; הן נעשות במקביל בכמות מרוסנת,
    כדי לא להעמיס על שרת שאינו שלנו.
    """
    dates = []
    d = datetime.date(year, 1, 1)
    while d.year == year:
        dates.append(d.strftime('%Y%m%d'))
        d += datetime.timedelta(days=1)

    def exists(ds):
        try:
            http(f'{BASE}/{ds}/gtfs.zip', rng='bytes=0-1', tries=1)
            return ds
        except SystemExit:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        found = [x for x in ex.map(exists, dates) if x]
    return sorted(found)


def terminals(long_name):
    """'מוצא-עיר<->יעד-עיר-1#' → ('מוצא-עיר', 'יעד-עיר'). הסיומת אינה חלק מהיעד."""
    if '<->' not in long_name:
        return long_name.strip(), ''
    a, b = long_name.split('<->', 1)
    b = b.rsplit('-', 1)[0] if b.rsplit('-', 1)[-1][:1] in '0123456789' else b
    return a.strip(), b.strip()


def main():
    days = snapshot_days(YEAR)
    print(f'צילומי {YEAR} בארכיון: {len(days)}', file=sys.stderr)
    if not days:
        raise SystemExit('לא נמצאו צילומים')

    anchors = {}
    for ds in days:
        url = f'{BASE}/{ds}/gtfs.zip'
        members = central_dir(url)
        idx, rdr = member_rows(url, members, 'routes.txt')
        iso = f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'
        n = 0
        for row in rdr:
            rd = row[idx['route_desc']].strip()
            if not rd:
                continue
            n += 1
            f, l = terminals(row[idx['route_long_name']])
            a = anchors.get(rd)
            if a is None:
                anchors[rd] = {'f': f, 'l': l, 'no': row[idx['route_short_name']].strip(),
                               'first': iso, 'last': iso, 'seen': 1}
            else:
                a['last'] = iso
                a['seen'] += 1
                # מספר הקו חסר בחלק מקבצי 2017 — מאמצים את הראשון שנמצא
                if not a['no'] and row[idx['route_short_name']].strip():
                    a['no'] = row[idx['route_short_name']].strip()
        print(f'  {iso}: {n} מסלולים (מצטבר {len(anchors)})', file=sys.stderr)

    out = {'gen': datetime.date.today().isoformat(), 'year': YEAR,
           'days': days, 'anchors': anchors}
    p = f'{OUTDIR}/anchor-{YEAR}.json'
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False,
              separators=(',', ':'))
    print(f'נכתב {p}: {len(anchors)} מסלולים · {os.path.getsize(p)//1024} KB',
          file=sys.stderr)


if __name__ == '__main__':
    main()
