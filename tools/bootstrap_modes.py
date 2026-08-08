#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""יצירת קבצי קו לסוגי תחבורה שאינם אוטובוס, מצילום ארכיון יחיד.

מילוי הארכיון עובר על הצילומים לפי סדר ולכן מגיע לסוג תחבורה רק בתאריך
שבו הוא נכנס לפיד — מוניות השירות, למשל, נכנסו רק ב-2020. אין סיבה
שהקטגוריה שלהן תעמוד ריקה באתר עד שהמילוי יזחל לשם.

כאן נקרא צילום אחד מאוחר ונוצרים ממנו הקווים החסרים בלבד. קובץ המצב של
המילוי אינו נוגע — השרשרת תעבור על אותם תאריכים כרגיל ותוסיף להם את
ההיסטוריה, ויצירה כפולה אינה אפשרית כי קובץ קיים לא נדרס.

DAY   תאריך הצילום (YYYYMMDD), ברירת מחדל 20220114
DRY=1 דיווח בלבד
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backfill_tf as bf  # noqa: E402

DAY = os.environ.get('DAY', '20220114')
DRY = os.environ.get('DRY') == '1'


def main():
    print(f'קורא צילום {bf.iso(DAY)}...', file=sys.stderr)
    cur = bf.snapshot(DAY)
    if not cur:
        raise SystemExit('הצילום ריק — ייתכן שהתאריך אינו בארכיון')

    made, existing = {}, {}
    for rd, (stops, shp) in cur.items():
        m = bf.SNAP_META.get(rd) or {}
        tt = m.get('tt')
        if not tt:
            continue                      # אוטובוסים — לא בטיפול הזה
        p = f'{bf.OUTDIR}/lines/{bf.fsafe(rd)}.json'
        if os.path.exists(p):
            existing[tt] = existing.get(tt, 0) + 1
            continue
        if not DRY and bf.ensure_line(rd, DAY, stops, shp):
            made[tt] = made.get(tt, 0) + 1
        elif DRY:
            made[tt] = made.get(tt, 0) + 1

    mode = 'סימולציה' if DRY else 'בוצע'
    fmt = lambda d: ' · '.join(f'{k}:{v}' for k, v in sorted(d.items())) or 'אין'
    print(f'{mode} · נוצרו — {fmt(made)}', file=sys.stderr)
    print(f'       כבר היו — {fmt(existing)}', file=sys.stderr)


if __name__ == '__main__':
    main()
