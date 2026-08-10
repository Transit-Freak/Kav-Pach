#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""יומן ערכים שאיננו מכירים — כדי שדילוג שקט לא יחזור.

ב-05.03.2023 פרסם משרד התחבורה 3,046 קווים עם route_type 707, סוג שלא היה
בטבלה שלנו. הסורק דילג עליהם, ודילוג פירושו שהמצב נשאר על הערך הקודם —
ואחר כך נרשם "שינוי סיווג" שלא קרה. שום דבר בפלט לא אמר שנתקלנו במשהו חדש.

מעכשיו כל ערך לא מוכר נרשם כאן עם מונה, תאריכים ודוגמאות. הצינור מדפיס
אזהרה כשהקובץ אינו ריק, והבדיקה נופלת על ערך שטרם אושר — כך שהוספת סוג
חדש בפיד מגיעה כהתראה ולא כטעות שקטה בנתונים.

ACK: ערכים שכבר בדקנו והוחלט עליהם יושבים ב-unknown-ack.json ואינם מתריעים.
"""
import json
import os

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
PATH = f'{OUTDIR}/unknown-values.json'
_buf = {}


def note(kind, value, day='', ctx=''):
    """רישום ערך לא מוכר. kind = השדה, value = מה שהתקבל."""
    d = _buf.setdefault(kind, {}).setdefault(str(value), {'n': 0, 'ex': []})
    d['n'] += 1
    if day:
        d['first'] = min(d.get('first', day), day)
        d['last'] = max(d.get('last', day), day)
    if ctx and len(d['ex']) < 5 and ctx not in d['ex']:
        d['ex'].append(ctx)


def flush():
    """מיזוג לקובץ. נקרא בסוף ריצה; בלי ערכים חדשים אינו נוגע בקובץ."""
    if not _buf:
        return {}
    old = {}
    if os.path.exists(PATH):
        try:
            old = json.load(open(PATH, encoding='utf-8'))
        except Exception:
            old = {}
    for kind, vals in _buf.items():
        for v, d in vals.items():
            o = old.setdefault(kind, {}).setdefault(v, {'n': 0, 'ex': []})
            o['n'] += d['n']
            if d.get('first'):
                o['first'] = min(o.get('first', d['first']), d['first'])
                o['last'] = max(o.get('last', d['last']), d['last'])
            for x in d['ex']:
                if x not in o['ex'] and len(o['ex']) < 5:
                    o['ex'].append(x)
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump(old, open(PATH, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, sort_keys=True)
    return _buf
