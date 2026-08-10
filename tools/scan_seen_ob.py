#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מתי כל וריאנט נראה לאחרונה בפיד — תקופת הארכיון של אופן באס, 2022–2026.

mark_archive_removed גוזר את תאריך הביטול מ"נראה לאחרונה", והנתון הזה
נאסף עד היום בסריקת TransitFeeds בלבד — כלומר עד 15.01.2022. מכיוון
שהיעדרות בסוף הטווח עשויה להיות רק סופו של הטווח, יש שם חלון חסד של
חודשיים, וכל מה שנעלם בתוכו נשאר לא מוכרע: 2,697 וריאנטים שאינם ברישום
היום ואינם מסומנים כבוטלים. כך "16015 כיוון 2 חלופה א", שנראה לאחרונה
ב-14.01.2022, מוצג באתר כאילו לא קרה לו דבר.

הסריקה כאן ממשיכה את "נראה לאחרונה" מ-16.01.2022 והלאה, ואז ההיעלמות
של ינואר 2022 כבר אינה בסוף שום טווח. היא קוראת routes.txt בלבד בבקשות
Range, ולא כותבת דבר לקובצי הקווים — כל תפקידה לרשום תאריכים.

FROM/TO · STEP_DAYS · MAX_MIN · DRY=1
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402

S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/ob-seen-state.json'
DRY = os.environ.get('DRY') == '1'
FROM = os.environ.get('FROM', '2022-01-16')
TO = os.environ.get('TO', '2026-07-24')
STEP = int(os.environ.get('STEP_DAYS', '7'))
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))


def jdump(obj, path):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def variants(day):
    """קבוצת ה-route_desc שמופיעים בצילום של יום אחד."""
    y, m, d = day.split('-')
    url = S3.format(y=y, m=m, d=d)
    c, rows = member_rows(url, central_dir(url), 'routes.txt')
    out = set()
    for r in rows:
        rd = (r[c['route_desc']] or '').strip()
        if rd.count('-') >= 2:
            out.add(rd)
    return out


def main():
    import time
    a = datetime.date.fromisoformat(FROM)
    b = datetime.date.fromisoformat(TO)
    days = []
    while a <= b:
        days.append(a.isoformat())
        a += datetime.timedelta(days=STEP)
    if days[-1] != TO:
        days.append(TO)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    done = set(st.get('done') or [])
    seen = dict(st.get('seen') or {})
    missing = set(st.get('missing') or [])
    todo = [d for d in days if d not in done and d not in missing]
    print(f'דגימות: {len(days)} · עובדו: {len(done)} · בריצה זו: {len(todo)}',
          file=sys.stderr)
    if not todo:
        print('הכל עובד — אין דגימות שנותרו', file=sys.stderr)
        return

    def save():
        if not DRY:
            jdump({'done': sorted(done), 'seen': seen,
                   'missing': sorted(missing)}, STATE)

    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    for day in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר', file=sys.stderr)
            break
        try:
            cur = variants(day)
        except BaseException as e:
            print(f'  {day}: דילוג — {type(e).__name__}', file=sys.stderr)
            missing.add(day)
            save()
            continue
        # התאריך נשמר בפורמט הדחוס של הסריקה השנייה, כדי ששני המקורות
        # יתמזגו ב-mark_archive_removed בלי המרה
        ds = day.replace('-', '')
        for rd in cur:
            if seen.get(rd, '') < ds:
                seen[rd] = ds
        done.add(day)
        print(f'  {day}: {len(cur)} וריאנטים', file=sys.stderr)
        save()

    print(f'סה"כ {len(seen)} וריאנטים · נסרקו {len(done)} דגימות',
          file=sys.stderr)


if __name__ == '__main__':
    main()
