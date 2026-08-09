#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""היסטוריית תחנות מארכיון TransitFeeds — 2017 עד 2022.

היסטוריית התחנות באתר נבנתה על ארכיון הסדנא ולכן מתחילה ב-2022, בעוד
היסטוריית הקווים כבר מגיעה ל-2017. הפער אינו בנתונים אלא בשימוש בהם:
stops.txt יושב בכל אחד מ-799 צילומי הארכיון ואיש לא נגע בו.

הקובץ קל בהרבה מרצפי התחנות (מגות בודדים מול עשרות), ולכן הסריקה כאן
מהירה ורצה לצד המילוי הראשי.

ארבעת סוגי האירועים זהים לאלה שהאתר כבר מכיר: תחנה חדשה, תחנה שבוטלה,
שינוי שם והזזת מיקום.

FROM/TO · MAX_MIN תקציב זמן · DRY=1 ניתוח בלבד
"""
import json
import math
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402
from backfill_tf import BASE, iso  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/tf-stops-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
FROM = os.environ.get('FROM', '20170316')
TO = os.environ.get('TO', '20220115')

# סף הזזה. מתחתיו מדובר בריענון קואורדינטות ולא בהזזה של תחנה בשטח —
# בלי סף כזה כל עדכון מדידה היה נרשם כאירוע.
MOVE_M = 35
# ימים שההיעדרות חייבת להחזיק כדי להיחשב ביטול ולא רעש בפיד
SETTLE_D = 45
TOWN = re.compile(r'עיר:\s*(.*?)\s*רציף:')


def gapd(a, b):
    import datetime
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def dist_m(a, b, c, d):
    dy = (a - c) * 111320
    dx = (b - d) * 111320 * math.cos(math.radians((a + c) / 2))
    return math.hypot(dx, dy)


def snap_stops(ds):
    """{מק"ט: [שם, עיר, lat, lon]} מצילום יחיד."""
    url = f'{BASE}/{ds}/gtfs.zip'
    c, rows = member_rows(url, central_dir(url), 'stops.txt')
    out = {}
    for r in rows:
        code = (r[c['stop_code']] or '').strip()
        if not code:
            continue
        m = TOWN.search(r[c['stop_desc']] if 'stop_desc' in c else '')
        try:
            out[code] = [r[c['stop_name']].strip(), m.group(1) if m else '',
                         round(float(r[c['stop_lat']]), 5),
                         round(float(r[c['stop_lon']]), 5)]
        except (ValueError, IndexError):
            continue
    return out


def main():
    src = (f'{OUTDIR}/tf-days.txt' if os.path.exists(f'{OUTDIR}/tf-days.txt')
           else '/tmp/hits.txt')
    days = [l.strip() for l in open(src) if l.strip() and FROM <= l.strip() <= TO]
    st = json.load(open(STATE)) if os.path.exists(STATE) else {'done': [], 'stops': {}}
    done, prev = set(st['done']), dict(st.get('stops') or {})
    ever = dict(st.get('ever') or {})    # מק"טים שנראו אי-פעם — מונע "חדשה" לחוזרת
    gone = {k: tuple(v) for k, v in (st.get('gone') or {}).items()}   # היעדרות פתוחה
    todo = [d for d in days if d not in done]
    print(f'צילומים: {len(days)} · עובדו: {len(done)} · בריצה זו: {len(todo)}',
          file=sys.stderr)
    if not todo:
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return

    hist = json.load(open(f'{OUTDIR}/stops-hist.json', encoding='utf-8')) \
        if os.path.exists(f'{OUTDIR}/stops-hist.json') else {}
    months = {}
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    tally = {}

    for ds in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר', file=sys.stderr)
            break
        try:
            cur = snap_stops(ds)
        except BaseException as e:
            print(f'  {iso(ds)}: דילוג — {type(e).__name__}', file=sys.stderr)
            continue
        d = iso(ds)
        evs = []
        if prev:
            for code, s in cur.items():
                gone.pop(code, None)      # חזרה מהיעדרות — לא היה ביטול
                if code not in ever:
                    ever[code] = d
                    evs.append({'d': d, 'c': code, 'k': 'new', 'n': s[0],
                                't': s[1], 'la': s[2], 'lo': s[3]})
                    continue
                o = prev.get(code)
                if o is None:
                    continue              # חזרה של תחנה מוכרת — לא "חדשה"
                if o[0] != s[0]:
                    # 'on'/'nn' ולא 'was': אלה השדות שהממשק קורא לשם הישן
                    # והחדש, ובשמות אחרים החץ מופיע ריק משני צדדיו.
                    evs.append({'d': d, 'c': code, 'k': 'renamed', 'n': s[0],
                                't': s[1], 'la': s[2], 'lo': s[3],
                                'on': o[0], 'nn': s[0]})
                elif dist_m(o[2], o[3], s[2], s[3]) >= MOVE_M:
                    evs.append({'d': d, 'c': code, 'k': 'moved', 'n': s[0],
                                't': s[1], 'la': s[2], 'lo': s[3],
                                'm': round(dist_m(o[2], o[3], s[2], s[3]))})
            for code in prev:
                if code not in cur and code not in gone:
                    gone[code] = [d, prev[code]]   # תחילת היעדרות, לא ביטול
            # ביטול אינו נקבע כאן בכוונה. תחנה שנעלמה וחזרה — ולו אחרי
            # חודשים — לא בוטלה מעולם, ורק סריקה עד סוף הטווח יכולה לדעת
            # זאת. ההכרעה נעשית בסוף, על מי שלא חזר כלל.
        else:
            for code in cur:
                ever.setdefault(code, d)
        prev = cur
        for e in evs:
            tally[e['k']] = tally.get(e['k'], 0) + 1
            months.setdefault(d[:7], []).append(e)
            h = hist.setdefault(e['c'], [])
            if not any(x.get('d') == e['d'] and x.get('k') == e['k'] for x in h):
                h.append({k: v for k, v in e.items() if k != 'c'})
        if evs:
            print(f'  {d}: {len(evs)} שינויי תחנות', file=sys.stderr)
        done.add(ds)      # גם בסימולציה, אחרת הכרעת הביטולים לא נבדקת כלל
        if not DRY:
            json.dump({'done': sorted(done), 'stops': prev, 'ever': ever,
                       'gone': {k: list(v) for k, v in gone.items()}}, open(STATE, 'w'))

    # הכרעת הביטולים — רק כשכל הטווח נסרק. תחנה נחשבת מבוטלת רק אם נעלמה
    # מהרישום ולא חזרה עד סוף הטווח, וגם אינה ברישום של היום. שתי הבדיקות
    # נחוצות: הטווח נגמר בינואר 2022, ומשם ואילך הצינור היומי הוא הסמכות.
    if not [x for x in days if x not in done]:
        try:
            alive = set(json.load(open(f'{OUTDIR}/stops-state.json', encoding='utf-8')))
        except Exception:
            alive = set()
        end = iso(max(done))
        n_del = held = 0
        for code, (since, o) in list(gone.items()):
            if code in alive:
                held += 1                 # קיימת היום — לא בוטלה
                continue
            if gapd(since, end) < SETTLE_D:
                held += 1                 # נעלמה ממש בסוף הטווח — לא מוכרע
                continue
            e = {'d': since, 'c': code, 'k': 'del', 'n': o[0], 't': o[1],
                 'la': o[2], 'lo': o[3]}
            tally['del'] = tally.get('del', 0) + 1
            months.setdefault(since[:7], []).append(e)
            h = hist.setdefault(code, [])
            if not any(x.get('d') == since and x.get('k') == 'del' for x in h):
                h.append({k: v for k, v in e.items() if k != 'c'})
            n_del += 1
        print(f'הכרעת ביטולים: {n_del} תחנות שלא חזרו · {held} חזרו או קיימות היום',
              file=sys.stderr)

    if not DRY and months:
        os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
        for mo, evs in months.items():
            p = f'{OUTDIR}/changes/stops-{mo}.json'
            old = json.load(open(p, encoding='utf-8'))['changes'] \
                if os.path.exists(p) else []
            seen = {(x['d'], x['c'], x['k']) for x in old}
            old += [e for e in evs if (e['d'], e['c'], e['k']) not in seen]
            old.sort(key=lambda x: (x['d'], x['c']))
            json.dump({'month': mo, 'changes': old}, open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
        for h in hist.values():
            h.sort(key=lambda x: x['d'])
        json.dump(hist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        # months.json הוא מה שמזין את בוחר החודשים בממשק; חודש שאינו רשום
        # בו פשוט לא קיים למשתמש, גם אם הקובץ שלו על הדיסק.
        mp = f'{OUTDIR}/months.json'
        mj = json.load(open(mp, encoding='utf-8')) if os.path.exists(mp) else {}
        mj['stopMonths'] = sorted(set(mj.get('stopMonths') or []) | set(months))
        json.dump(mj, open(mp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))

    brk = ' · '.join(f'{k}:{v}' for k, v in sorted(tally.items(), key=lambda x: -x[1]))
    print(f'סה"כ {sum(tally.values())} אירועי תחנות — {brk}', file=sys.stderr)


if __name__ == '__main__':
    main()
