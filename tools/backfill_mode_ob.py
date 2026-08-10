#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""שינויי סיווג (route_type) בתקופת ארכיון אופן באס — 2022 עד 2026.

סריקת הסיווגים נכתבה לארכיון TransitFeeds (2017–2022), והסורק היומי מזהה
אותם מיולי 2026 והלאה. בין שני אלה יש ארבע שנים וחצי שבהן איש לא בדק את
route_type, וכל קו שסיווגו השתנה שם נשאר אצלנו עם הסיווג הישן.

כך קו 15 של אגד ברחובות מוצג כ"שירות לפי דרישה" בעוד הפיד של היום מסווג
אותו כאוטובוס רגיל. 22 וריאנטים במצב הזה.

הקריאה היא של routes.txt בלבד, בבקשות Range מתוך ה-zip היומי — כמה מאות
קילובייט ליום במקום 120 מגה. הדגימה שבועית, ולכן תאריך השינוי מדויק עד
שבוע; הפער נרשם ב-'sd' כמו בכל אירוע אחר מהארכיון.

FROM/TO · STEP_DAYS · MAX_MIN · DRY=1
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402
from backfill_mode import LBL  # noqa: E402
from compact_lines import compact, materialize  # noqa: E402

S3 = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
      '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/ob-mode-state.json'
SRC = 'ob'
DRY = os.environ.get('DRY') == '1'
FROM = os.environ.get('FROM', '2022-01-16')
TO = os.environ.get('TO', '2026-07-24')
STEP = int(os.environ.get('STEP_DAYS', '7'))
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
# route_type בפיד הארצי אינו רק 0-7: במרץ 2023 פורסמו 3,046 קווים כ-707
# ("אוטובוס לצרכים מיוחדים" בתקן המורחב), ואחר כך הם חזרו ל-3. סוג שלא
# הכרנו נדלג עליו — ואז מצב הקו נתקע על הערך הישן, וכשהוא חזר ל-3 נרשם
# "שינוי סיווג" שלא היה. כל טווח ה-70x הוא אוטובוס, מלבד 715 שהוא שירות
# לפי דרישה.
BUSX = {'700', '701', '702', '703', '704', '705', '706', '707', '708', '709',
        '710', '711', '712', '713', '714', '716'}
TT = {'2': 'rail', '8': 'taxi', '0': 'lightrail', '5': 'cable', '715': 'demand'}


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def modes(day):
    """{rd: סוג} מיום אחד. סוג None = אוטובוס."""
    y, m, d = day.split('-')
    url = S3.format(y=y, m=m, d=d)
    c, rows = member_rows(url, central_dir(url), 'routes.txt')
    out = {}
    for r in rows:
        rd = (r[c['route_desc']] or '').strip()
        if rd.count('-') < 2:
            continue
        rt = (r[c['route_type']] or '3').strip()
        if rt in BUSX:
            rt = '3'
        if rt != '3' and rt not in TT:
            continue                     # סוג שאיננו מכירים — לא מנחשים
        out[rd] = TT.get(rt)
    return out


def write_mode(rd, day, old, new, since):
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    if not os.path.exists(p):
        return False
    lf = materialize(json.load(open(p, encoding='utf-8')))
    vs = lf.get('versions') or []
    if any(v.get('d') == day and v.get('k') == 'mode' for v in vs):
        return False
    v = {'d': day, 'k': 'mode', 'src': SRC, 'shp': '', 'stops': [],
         'note': f'סוג הקו שוּנה: {LBL.get(old, old)} ← {LBL.get(new, new)} '
                 f'(לפי סיווג route_type בפיד הארצי)'}
    if since and since != day:
        v['sd'] = since
    vs.append(v)
    vs.sort(key=lambda x: (x['d'], x.get('k') or ''))
    lf['versions'] = vs
    if new:
        lf['tt'] = new
    elif 'tt' in lf:
        del lf['tt']
    if not DRY:
        json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
    return True


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

    st = json.load(open(STATE)) if os.path.exists(STATE) else {'done': [], 'tt': {}}
    done, prev = set(st['done']), dict(st.get('tt') or {})
    todo = [d for d in days if d not in done]
    print(f'דגימות: {len(days)} · עובדו: {len(done)} · בריצה זו: {len(todo)}',
          file=sys.stderr)
    if not todo:
        print('הכל עובד — אין דגימות שנותרו', file=sys.stderr)
        return

    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    last = max(done) if done else None
    total = 0
    for day in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר', file=sys.stderr)
            break
        try:
            cur = modes(day)
        except BaseException as e:
            print(f'  {day}: דילוג — {type(e).__name__}', file=sys.stderr)
            continue
        n = 0
        for rd, tt in cur.items():
            if rd in prev and prev[rd] != tt and write_mode(rd, day, prev[rd], tt, last):
                n += 1
            prev[rd] = tt
        if n:
            print(f'  {day}: {n} שינויי סיווג', file=sys.stderr)
        total += n
        last = day
        done.add(day)
        if not DRY:
            json.dump({'done': sorted(done), 'tt': prev}, open(STATE, 'w'))
    print(f'סה"כ {total} שינויי סיווג', file=sys.stderr)


if __name__ == '__main__':
    main()
