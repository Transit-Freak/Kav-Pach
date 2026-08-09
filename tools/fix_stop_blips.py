#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ניקוי תחנות שהופיעו ונעלמו בתוך זמן קצר — תקלת פרסום, לא תחנות.

ב-2.9.2021 קפץ קובץ התחנות של הפיד הארצי מ-27,836 ל-41,029 רשומות, וב-13.9
ירד ל-31,681. שלושה עשר אלף תחנות לא נבנו בין לילה ולא פורקו אחרי אחת עשרה
יום — זו הייתה תקלת פרסום.

הכלל של "נעלם ולא חזר" הגן על צד הביטול בלבד. תחנה שהופיעה ונעלמה מיד
קיבלה בכל זאת אירוע "חדשה", ואחר כך "בוטלה" — שני אירועים על משהו שלא קרה.
הכלל כאן סימטרי: תחנה שכל חייה קצרים מהסף לא נוספה מעולם, ושני האירועים
שלה יורדים.

תחנה שנוספה ועדיין קיימת אינה נוגעת — ההסרה חלה רק על זוג סגור.

DAYS  אורך חיים מרבי להסרה (ברירת מחדל 45) · DRY=1 מדווח בלבד
"""
import datetime
import json
import os
import sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
DAYS = int(os.environ.get('DAYS', '45'))


def gap(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def main():
    hp = f'{OUTDIR}/stops-hist.json'
    hist = json.load(open(hp, encoding='utf-8'))
    drop = set()          # (code, date, kind) להסרה
    n_pairs = 0
    for code, evs in hist.items():
        evs.sort(key=lambda e: e['d'])
        open_new = None
        for e in evs:
            if e['k'] == 'new':
                open_new = e
            elif e['k'] == 'del' and open_new is not None:
                if gap(open_new['d'], e['d']) <= DAYS:
                    drop.add((code, open_new['d'], 'new'))
                    drop.add((code, e['d'], 'del'))
                    n_pairs += 1
                open_new = None

    if not n_pairs:
        print('לא נמצאו זוגות קצרים', file=sys.stderr)
        return

    if not DRY:
        for code, evs in hist.items():
            hist[code] = [e for e in evs if (code, e['d'], e['k']) not in drop]
        hist = {k: v for k, v in hist.items() if v}
        json.dump(hist, open(hp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))

        for fn in sorted(os.listdir(f'{OUTDIR}/changes')):
            if not fn.startswith('stops-') or not fn.endswith('.json'):
                continue
            p = f'{OUTDIR}/changes/{fn}'
            d = json.load(open(p, encoding='utf-8'))
            keep = [c for c in d['changes']
                    if (c['c'], c['d'], c['k']) not in drop]
            if len(keep) != len(d['changes']):
                json.dump({'month': d['month'], 'changes': keep},
                          open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_pairs} תחנות חיו פחות מ-{DAYS} יום · '
          f'{len(drop)} אירועים הוסרו', file=sys.stderr)


if __name__ == '__main__':
    main()
