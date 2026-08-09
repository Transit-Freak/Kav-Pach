#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סימון שינויי תחנות שהתבטלו מיד — תנודה בפרסום, לא שינוי במסלול.

בקו 548 נרשם ב-14.01.2022 ש"ירדו" ארבע תחנות, בעוד הקו עוצר בשתיים מהן עד
היום. במבט על הרצף רואים מה קרה באמת: אותן ארבע תחנות נוספו ב-6.1, ירדו
ב-9.1, נוספו שוב ב-13.1 וירדו ב-14.1. הפיד התנדנד שמונה ימים, והמסלול לא
השתנה.

זה נפוץ: 8,635 מקרים שבהם רצף התחנות השתנה וחזר תוך שלושה ימים.

האירועים נשארים — הם באמת פורסמו, וזה מידע על הפרסום — אבל מקבלים סימון
שאומר את האמת: השינוי הזה לא החזיק. rv הוא מספר הימים עד שהרצף חזר,
ו-rvb מסמן את האירוע המחזיר.

מחיקה הייתה מסתירה גם את התנודה עצמה, שהיא ממצא ולא רעש טכני.

DAYS  חלון החזרה (ברירת מחדל 14) · DRY=1 מדווח בלבד
"""
import datetime
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
DAYS = int(os.environ.get('DAYS', '14'))


def gap(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def main():
    n_pairs = n_files = 0
    hist = {}
    for p in glob.glob(f'{OUTDIR}/lines/*.json'):
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = [v for v in (lf.get('versions') or []) if v.get('stops')]
        codes = [[s[0] for s in v['stops']] for v in vs]
        ch = False
        for i in range(len(vs) - 2):
            a, b, c = vs[i], vs[i + 1], vs[i + 2]
            if codes[i] != codes[i + 2] or codes[i] == codes[i + 1]:
                continue
            g = gap(b['d'], c['d'])
            if g > DAYS:
                continue
            n_pairs += 1
            hist.setdefault(g, 0)
            hist[g] += 1
            if b.get('rv') != g or not c.get('rvb'):
                b['rv'] = g
                c['rvb'] = 1
                ch = True
        if ch and not DRY:
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            n_files += 1

    mode = 'סימולציה' if DRY else 'בוצע'
    quick = sum(n for g, n in hist.items() if g <= 3)
    print(f'{mode}: {n_pairs} שינויים שחזרו תוך {DAYS} יום ({quick} מהם תוך שלושה) · '
          f'{n_files} קבצים עודכנו', file=sys.stderr)


if __name__ == '__main__':
    main()
