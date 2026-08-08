#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""האם הארכיון מחזיק צילומים מלפני מרץ 2017?

הבאקט אינו מאפשר רשימת קבצים, ולכן הדרך היחידה לדעת היא לבקש כל יום
ולראות אם הוא עונה. נבדקות רק שתי בתים ראשונות מכל קובץ — לא הורדה.

הקצב מרוסן בכוונה: זה שרת שאינו שלנו, ובמקביל רצה עליו כבר משיכת
הארכיון המלאה.

פלט: /tmp/pre2017.txt
"""
import concurrent.futures
import datetime
import os
import sys
import urllib.request

# בדיקת קיום, לא הורדה: בקשת שני בתים ראשונים. הבאקט עונה 403 על קובץ
# שאינו קיים (אין הרשאת רשימה), ולכן "אין" ו"נכשל" נראים אותו דבר —
# מה שמצדיק בקשה נקייה בלי לוגיקת ניסיונות חוזרים. פונקציית http של
# הכלים האחרים ישנה שש שניות אחרי כל כישלון, וכאן רוב הימים הם כישלון.
def exists(url, timeout=20):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'kav-bochan/line-history (archive depth probe; polite)'})
    req.add_header('Range', 'bytes=0-1')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in (200, 206)
    except Exception:
        return False

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
FROM = os.environ.get('FROM', '20130101')
TO = os.environ.get('TO', '20170315')
OUT = os.environ.get('OUT', '/tmp/pre2017.txt')


def main():
    d = datetime.date(int(FROM[:4]), int(FROM[4:6]), int(FROM[6:]))
    end = datetime.date(int(TO[:4]), int(TO[4:6]), int(TO[6:]))
    days = []
    while d <= end:
        days.append(d.strftime('%Y%m%d'))
        d += datetime.timedelta(days=1)
    print(f'נבדקים {len(days)} ימים, {FROM}–{TO}', file=sys.stderr)

    def check(ds):
        return ds if exists(f'{BASE}/{ds}/gtfs.zip') else None

    hits = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(check, days), 1):
            if r:
                hits.append(r)
                print(f'  נמצא {r}', file=sys.stderr)
            if i % 200 == 0:
                print(f'  ...{i}/{len(days)} · {len(hits)} עד כה', file=sys.stderr)

    open(OUT, 'w').write('\n'.join(hits))
    from collections import Counter
    print(f'סה"כ {len(hits)} צילומים לפני {TO}', file=sys.stderr)
    print(dict(Counter(h[:4] for h in hits)), file=sys.stderr)


if __name__ == '__main__':
    main()
