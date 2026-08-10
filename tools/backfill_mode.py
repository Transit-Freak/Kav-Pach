#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מתי סוג הקו שוּנה — סריקת הסיווג לאורך כל הארכיון.

route_type קובע אם הקו הוא אוטובוס, רכבת, מונית שירות או "שירות לפי
דרישה". שינוי בו אינו נוגע בתחנות ולא בשרטוט, ולכן מנוע ההשוואה הרגיל
אינו רואה אותו כלל — אף שמבחינת הנוסע ההבדל בין קו שיוצא בשעה קבועה לקו
שמחייב הזמנה מראש גדול משינוי תחנה.

הסריקה כאן קלה בהרבה מהמילוי המלא: היא קוראת רק את routes.txt מכל צילום
(מגה בודד) ולא את רצפי התחנות (עשרות מגה), ולכן היא עוברת את כל הארכיון
בשבריר מהזמן ורצה במקביל בלי להפריע.

FROM/TO  טווח תאריכים · MAX_MIN תקציב זמן לחוליה · DRY=1 ניתוח בלבד
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, fsafe, member_rows  # noqa: E402
from backfill_tf import BASE, TT, iso  # noqa: E402
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/tf-mode-state.json'
SRC = 'tf'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
FROM = os.environ.get('FROM', '20170316')
TO = os.environ.get('TO', '20220115')

LBL = {'rail': 'רכבת', 'taxi': 'מונית שירות', 'lightrail': 'רכבת קלה',
       'cable': 'רכבל/כרמלית', 'demand': 'שירות לפי דרישה',
       None: 'קו אוטובוס רגיל'}


# route_type בפיד הארצי אינו רק 0-7: במרץ 2023 פורסמו 3,046 קווים כ-707
# ("אוטובוס לצרכים מיוחדים" בתקן המורחב), ואחר כך הם חזרו ל-3. סוג שלא
# הכרנו נדלג עליו — ואז מצב הקו נתקע על הערך הישן, וכשהוא חזר ל-3 נרשם
# "שינוי סיווג" שלא היה. כל טווח ה-70x הוא אוטובוס, מלבד 715 שהוא שירות
# לפי דרישה.
BUSX = {'700', '701', '702', '703', '704', '705', '706', '707', '708', '709',
        '710', '711', '712', '713', '714', '716'}


def modes(ds):
    """{rd: סוג התחבורה} מצילום יחיד — routes.txt בלבד."""
    url = f'{BASE}/{ds}/gtfs.zip'
    c, rows = member_rows(url, central_dir(url), 'routes.txt')
    out = {}
    for r in rows:
        rd = r[c['route_desc']].strip()
        if rd.count('-') < 2:
            continue
        rt = r[c['route_type']].strip()
        if rt in BUSX:
            rt = '3'
        # סוג שאיננו מכירים — לא מנחשים, ולא רושמים עליו אירוע
        if rt != '3' and rt not in TT:
            continue
        out.setdefault(rd, TT.get(rt) if rt != '3' else None)
    return out


def write_mode(rd, ds, old, new):
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    if not os.path.exists(p):
        return False
    lf = materialize(json.load(open(p, encoding='utf-8')))
    vs = lf.get('versions') or []
    d = iso(ds)
    if any(v.get('d') == d and v.get('k') == 'mode' and v.get('src') == SRC
           for v in vs):
        return False
    vs.append({'d': d, 'k': 'mode', 'src': SRC, 'shp': '', 'stops': [],
               'note': f'סוג הקו שוּנה: {LBL.get(old, old)} ← {LBL.get(new, new)} '
                       f'(לפי סיווג route_type בפיד הארצי)'})
    vs.sort(key=lambda x: (x['d'], x.get('k') or ''))
    lf['versions'] = vs
    if new:
        lf['tt'] = new
    elif 'tt' in lf:
        del lf['tt']
    json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    return True


def main():
    src = (f'{OUTDIR}/tf-days.txt' if os.path.exists(f'{OUTDIR}/tf-days.txt')
           else '/tmp/hits.txt')
    days = [l.strip() for l in open(src) if l.strip() and FROM <= l.strip() <= TO]
    st = json.load(open(STATE)) if os.path.exists(STATE) else {'done': [], 'tt': {}}
    done, prev = set(st['done']), dict(st.get('tt') or {})
    # 'seen' = הצילום האחרון שבו הווריאנט עוד היה בפיד. זה מה שמאפשר לומר
    # מתי קו בוטל: המנוע הראשי רואה רק את מה שקיים בצילום ולכן היעלמות
    # שקופה לו לגמרי.
    seen = dict(st.get('seen') or {})
    # מצב שנוצר לפני שהשדה הזה קיים אינו יודע מתי קווים נעלמו, ובלי זה אי
    # אפשר לקבוע תאריך ביטול. הסריקה קלה (routes.txt בלבד), ולכן עדיף
    # לסרוק מחדש מאשר להסיק תאריכים ממידע חלקי. האירועים אידמפוטנטיים.
    if done and not seen:
        print('חסר מידע "נראה לאחרונה" — סורק מחדש מההתחלה', file=sys.stderr)
        done, prev = set(), {}
    todo = [d for d in days if d not in done]
    print(f'צילומים בטווח: {len(days)} · עובדו: {len(done)} · בריצה זו: {len(todo)}',
          file=sys.stderr)
    if not todo:
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return

    # המצב נשמר בקובץ ולא בזיכרון בלבד: כך חוליה חדשה יודעת מה היה הסיווג
    # הקודם בלי לקרוא מחדש את כל הארכיון.
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    total = 0
    for ds in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר', file=sys.stderr)
            break
        try:
            cur = modes(ds)
        except BaseException as e:
            print(f'  {iso(ds)}: דילוג — {type(e).__name__}', file=sys.stderr)
            continue
        n = 0
        for rd, tt in cur.items():
            if rd in prev and prev[rd] != tt:
                if DRY or write_mode(rd, ds, prev[rd], tt):
                    n += 1
            prev[rd] = tt
            seen[rd] = ds
        if n:
            print(f'  {iso(ds)}: {n} שינויי סיווג', file=sys.stderr)
        total += n
        if not DRY:
            done.add(ds)
            json.dump({'done': sorted(done), 'tt': prev, 'seen': seen}, open(STATE, 'w'))
    print(f'סה"כ {total} שינויי סיווג', file=sys.stderr)


if __name__ == '__main__':
    main()
