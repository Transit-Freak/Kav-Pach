#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""פיד "שינויים לפי יום" לשנים שהגיעו מהארכיון.

אירועי הארכיון נכתבו לתוך קבצי הקווים, ולכן מי שנכנס לקו רואה את 2017.
אבל הפיד הכרונולוגי נבנה בנפרד — קובץ לכל חודש — והוא מעולם לא נבנה
לשנים האלה. התוצאה: הנתונים קיימים ואי אפשר לדפדף אליהם.

הכלי נגזר מקבצי הקווים עצמם, שהם מקור האמת, ולכן הרצה חוזרת מעדכנת
במקום לשכפל. חודשים שכבר קיימים מהצינור היומי אינם נדרסים — נוספים אליהם
רק אירועים שאינם בהם.

DRY=1 מדווח בלבד.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
# הכלי משלים לפיד כל אירוע שיושב בקובץ קו ואינו שם — מכל מקור. הוא
# התחיל כמשלים של ארכיון tf בלבד, ואז כל מקור שנוסף (ob, v10, הצינור
# החי) היה צריך להיזכר בו בנפרד — ופיצול הקו האדום במלחמת מרץ 2026 ישב
# בקובצי הקווים בלי להופיע בשום חודש. ביקורת מלאה מצאה 490 אירועים
# כאלה מארבעה מקורות שונים. הכפילות נמנעת ממילא — ההוספה בודקת
# (d, rd, k) מול תוכן החודש הקיים.
SRCS = None   # None = כל המקורות


def main():
    months = {}
    for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
        if not fn.endswith('.json'):
            continue
        try:
            lf = materialize(json.load(open(f'{OUTDIR}/lines/{fn}', encoding='utf-8')))
        except Exception:
            continue
        rd, line = lf.get('rd'), lf.get('line', '')
        for v in lf.get('versions') or []:
            if SRCS is not None and v.get('src') not in SRCS:
                continue
            # תיעוד-מצב אינו שינוי: baseline הוא תחילת התיעוד, times הוא
            # צילום הלו"ז האחרון, ו-snapshot של ob הוא השלמת-גאומטריה
            # שנוספה בדיעבד. צילומי tf17 (מצב 2017) כבר בפיד מאז ומתמיד
            # ונשארים בו דרך הדדופ.
            if v.get('k') in ('baseline', 'times'):
                continue
            if v.get('src') == 'ob' and v.get('k') == 'snapshot':
                continue
            c = {'d': v['d'], 'rd': rd, 'line': line, 'k': v['k']}
            if v.get('note'):
                c['note'] = v['note']
            if v.get('sd'):
                c['sd'] = v['sd']      # דיוק התאריך — הממשק מציג לפיו חודש בלבד
            for f in ('add', 'rem'):
                if v.get(f):
                    c[f] = v[f][:15]
            months.setdefault(v['d'][:7], []).append(c)

    if not months:
        print('אין אירועי ארכיון', file=sys.stderr)
        return

    n_new = n_upd = total = 0
    for mo, evs in sorted(months.items()):
        p = f'{OUTDIR}/changes/{mo}.json'
        old = json.load(open(p, encoding='utf-8'))['changes'] if os.path.exists(p) else []
        seen = {(x['d'], x['rd'], x['k']) for x in old}
        add = [e for e in evs if (e['d'], e['rd'], e['k']) not in seen]
        total += len(add)
        if not add:
            continue
        if os.path.exists(p):
            n_upd += 1
        else:
            n_new += 1
        if not DRY:
            out = old + add
            out.sort(key=lambda x: (x['d'], x.get('line') or '', x['rd']))
            os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
            json.dump({'month': mo, 'changes': out}, open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))

    if not DRY:
        # בלי הרישום ב-months.json החודש אינו קיים למשתמש, גם אם הקובץ שלו
        # יושב על הדיסק — זה בדיוק הפער שהכלי הזה בא לסגור.
        mp = f'{OUTDIR}/months.json'
        mj = json.load(open(mp, encoding='utf-8')) if os.path.exists(mp) else {}
        mj['months'] = sorted(set(mj.get('months') or []) | set(months))
        json.dump(mj, open(mp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {total} אירועים · {n_new} חודשים חדשים · {n_upd} חודשים עודכנו',
          file=sys.stderr)


if __name__ == '__main__':
    main()
