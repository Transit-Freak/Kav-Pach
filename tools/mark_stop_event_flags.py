#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סימון האירועים שהממשק מסתיר, כדי שלא יצטרך את כל ההיסטוריה כדי לדעת.

טאב התחנות מציג חודש אחד — קובץ של כמה עשרות קילובייט — אבל כדי להחליט
מה להציג בו הוא הוריד את stops-hist.json במלואו: 4.5 מגה. שני כללי תצוגה
דרשו זאת:

  "תחנה חדשה" מוצגת רק אם זה הרישום הראשון אי-פעם של התחנה. הופעה חוזרת
  אחרי היעדרות אינה לידה.
  "תחנה בוטלה" אינה מוצגת אם התחנה חזרה אחר כך, או אם היא ברישום היום.

שתי השאלות נענות מראש כאן ונשמרות על האירוע עצמו: k1 — זה הרישום הראשון,
xb — הביטול הזה לא בתוקף. כלל השנה נשאר בצד הלקוח, כי הוא תלוי בתאריך של
היום ולא בנתונים.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי ומחושב מחדש בכל ריצה.
"""
import glob
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def main():
    hist = json.load(open(f'{OUTDIR}/stops-hist.json', encoding='utf-8'))
    first_new, dead = {}, {}
    for code, evs in hist.items():
        evs = sorted(evs, key=lambda e: e['d'])
        if evs and evs[0]['k'] == 'new':
            first_new[code] = evs[0]['d']
        last = evs[-1] if evs else None
        still = bool(last and last['k'] == 'del' and last.get('now'))
        # ביטול שאחריו יש רישום מחדש, או תחנה שקיימת היום — לא ביטול בתוקף
        dead[code] = ({e['d'] for e in evs if e['k'] == 'del'
                       if still or any(x['d'] > e['d'] and x['k'] == 'new' for x in evs)})

    n1 = nx = 0
    for p in glob.glob(f'{OUTDIR}/changes/stops-*.json'):
        d = json.load(open(p, encoding='utf-8'))
        ch = False
        for c in d['changes']:
            if c['k'] == 'new':
                want = first_new.get(c['c']) == c['d']
                if want:
                    n1 += 1
                if want != bool(c.get('k1')):
                    ch = True
                    c['k1'] = 1 if want else c.pop('k1', None)
            elif c['k'] == 'del':
                want = c['d'] in dead.get(c['c'], ())
                if want:
                    nx += 1
                if want != bool(c.get('xb')):
                    ch = True
                    c['xb'] = 1 if want else c.pop('xb', None)
        if ch and not DRY:
            json.dump(d, open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n1} רישומים ראשונים סומנו · {nx} ביטולים שאינם בתוקף',
          file=sys.stderr)


if __name__ == '__main__':
    main()
