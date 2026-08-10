#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מתי קו בוטל — לפי ההיעלמות שלו מהארכיון, לא לפי יום הריצה.

המנוע הראשי משווה את מה שקיים בכל צילום, ולכן קו שנעלם פשוט מפסיק
להופיע — ההיעלמות שקופה לו. הסורק הקל, שקורא את routes.txt של כל צילום,
זוכר מתי כל וריאנט נראה לאחרונה, וממנו נגזר תאריך הביטול.

זה מה שמבדיל בין "בוטל" אמיתי לבין הסימון השגוי שהוסר קודם: שם התאריך
היה יום הריצה, כלומר שגוי בשנים. כאן הוא הצילום האחרון שבו הקו עוד היה.

לא מסומן קו שעדיין ברישום של היום (state-routes.json), ולא קו שנראה סמוך
לסוף טווח הארכיון — שם ההיעדרות עשויה להיות פשוט סופו של הטווח.

GRACE  ימים מסוף הטווח שבהם לא מסיקים ביטול (ברירת מחדל 60)
DRY=1  דיווח בלבד. הכלי אידמפוטנטי.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import fsafe  # noqa: E402
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
GRACE = int(os.environ.get('GRACE', '60'))


def iso(ds):
    return f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'


def main():
    st = json.load(open(f'{OUTDIR}/tf-mode-state.json', encoding='utf-8'))
    seen = dict(st.get('seen') or {})
    if not seen:
        raise SystemExit('אין נתוני "נראה לאחרונה" — יש להריץ קודם את backfill_mode')
    days = sorted(st['done'])
    if not days:
        raise SystemExit('לא נסרקו צילומים')

    # "נראה לאחרונה" של תקופת אופן באס, אם נסרקה. בלעדיו הטווח נגמר
    # ב-15.01.2022, וכל מה שנעלם בחודשיים שלפניו נופל בחלון החסד ונשאר
    # לא מוכרע — 2,697 וריאנטים שאינם ברישום היום ואינם מסומנים כבוטלים.
    try:
        ob = json.load(open(f'{OUTDIR}/ob-seen-state.json', encoding='utf-8'))
    except Exception:
        ob = {}
    for rd, last in (ob.get('seen') or {}).items():
        if seen.get(rd, '') < last:
            seen[rd] = last
    days = sorted(set(days) | {d.replace('-', '') for d in (ob.get('done') or [])})
    end = datetime.date.fromisoformat(iso(days[-1]))
    cutoff = end - datetime.timedelta(days=GRACE)

    try:
        alive = set(json.load(open(f'{OUTDIR}/state-routes.json', encoding='utf-8')))
    except Exception:
        alive = set()

    # הצילום שאחרי ההיעלמות: הגבול העליון של חלון הביטול
    nxt = {}
    for i, d in enumerate(days[:-1]):
        nxt[d] = days[i + 1]

    marked = skipped = still = 0
    for rd, last in seen.items():
        if rd in alive:
            still += 1                 # עדיין ברישום היום — לא בוטל
            continue
        ld = datetime.date.fromisoformat(iso(last))
        if ld > cutoff:
            skipped += 1               # נעלם סמוך לסוף הטווח — ייתכן שרק הטווח נגמר
            continue
        p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
        if not os.path.exists(p):
            continue
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = lf.get('versions') or []
        gone = iso(nxt.get(last, last))
        if not vs or vs[-1].get('k') == 'removed' or vs[-1]['d'] > gone:
            continue
        if not DRY:
            v = {'d': gone, 'k': 'removed', 'src': 'tf', 'shp': '', 'stops': [],
                 'note': f'הקו נעלם מהפיד הארצי — נראה לאחרונה ב-{iso(last)}'}
            if iso(last) != gone:
                v['sd'] = iso(last)    # דיוק התאריך לפי המרווח בין הצילומים
            vs.append(v)
            lf['versions'] = vs
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
        marked += 1

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {marked} קווים סומנו כבוטלו לפי מועד ההיעלמות · '
          f'{still} עדיין ברישום · {skipped} נעלמו סמוך לסוף הטווח ולא הוכרעו',
          file=sys.stderr)


if __name__ == '__main__':
    main()
