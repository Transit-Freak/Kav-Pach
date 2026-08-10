#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""תיקון דיוק התאריכים של אירועי הסריקה השבועית לקווים שאינם אוטובוס.

הסריקה שהשלימה את 2022–2026 לרכבת, לרכבת הקלה ולמוניות השירות דוגמת
פעם בשבוע (יום שלישי), אבל ירשה מהצינור היומי את נוסח ההערה "תאריך
מדויק". ההצלבה מול הארכיון הראתה את הפער: חלופה א של הרכבת הקלה
בירושלים נעלמה בפועל ב-02.03.2022, ונרשם "נעלמה ב-08.03.2022 — תאריך
מדויק".

התיקון: מוחקים את "תאריך מדויק" מההערה ומוסיפים 'sd' — הדגימה הקודמת,
שבועיים לכל היותר לפני האירוע — כמו בכל אירוע אחר מהארכיון. האתר כבר
יודע להציג את אי-הוודאות הזו.

מזוהים לפי: קובץ עם 'tt' (אינו אוטובוס) · src=ob · אחד מחמשת סוגי
האירועים של סריקת הרישום · בטווח הארכיון. אירועי mode (סריקה נפרדת)
כבר נושאים sd ואינם נוגעים.

DRY=1 מדווח בלבד. הכלי אידמפוטנטי (אירוע עם sd לא נוגעים בו שוב).
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
LO, HI = '2022-01-16', '2026-07-24'
KINDS = {'new', 'removed', 'dest', 'renum', 'operator'}


def main():
    n_ev = n_f = 0
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        if not lf.get('tt'):
            continue
        dirty = False
        for v in lf.get('versions') or []:
            if v.get('src') != 'ob' or v.get('k') not in KINDS:
                continue
            if not (LO <= v['d'] <= HI) or v.get('sd'):
                continue
            note = v.get('note') or ''
            v['note'] = note.replace(', תאריך מדויק', '').replace(' תאריך מדויק', '')
            sd = (datetime.date.fromisoformat(v['d']) - datetime.timedelta(days=7)).isoformat()
            v['sd'] = max(sd, LO)
            n_ev += 1
            dirty = True
        if dirty:
            n_f += 1
            if not DRY:
                json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_ev} אירועים ב-{n_f} קווים קיבלו sd ואיבדו את "תאריך מדויק"',
          file=sys.stderr)


if __name__ == '__main__':
    main()
