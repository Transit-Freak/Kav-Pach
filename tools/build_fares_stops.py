# -*- coding: utf-8 -*-
# המחירון — אינדקס תחנות ארצי לחיפוש-לפי-תחנה: סורק את כל קבצי הקווים
# הפעילים ב-line-history (אוטובוס, קווי דרישה, רכבת ורק"ל) ובונה מפה אחת
# stop_id -> [שם,עיר,lat,lon]. רץ פעם בשבוע (אותו קצב כמו רענון שמות
# התחנות הארצי) כי מיקומי תחנות משתנים לעיתים רחוקות מאוד.
import glob
import json
import os

OUT = os.environ.get('OUTDIR', 'fares/data')
LH = 'line-history/data/lines'
# מוניות שירות וכבלים לא בטבלת התעריפים הזאת בכלל — נשארים בחוץ
INCLUDE_TT = {None, 'demand', 'rail', 'lightrail'}


def main():
    # next-station/stops-names.json נבנה מחדש כל יום ישירות מ-stops.txt
    # הטרי של משרד התחבורה (ראו update-weekly.yml) — זה השם הכי עדכני
    # שיש. ה-pool של line-history הוא הרבה פעמים תמונת-מצב ישנה יותר
    # שלא בהכרח מתעדכנת בכל סריקה, ולכן שם משם משמש רק כגיבוי לתחנות
    # שעדיין לא הגיעו לסנאפשוט הארצי.
    try:
        snap = json.load(open('next-station/stops-names.json', encoding='utf-8'))
    except Exception:
        snap = {}
    # תיקונים ידניים לתחנות ספציפיות שגם המקור הטרי טועה בהן (נדיר) —
    # ראו tools/fares-stop-overrides.json
    try:
        overrides = json.load(open('tools/fares-stop-overrides.json', encoding='utf-8'))
    except Exception:
        overrides = {}

    stops = {}
    n_files = n_active = 0
    for path in glob.glob(f'{LH}/*.json'):
        n_files += 1
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if d.get('tt') not in INCLUDE_TT or d.get('lk') == 'removed':
            continue
        pool = d.get('pool') or []
        if len(pool) < 2:
            continue
        n_active += 1
        for p in pool:
            if len(p) < 4:
                continue
            sid, name, la, lo = p[0], p[1], p[2], p[3]
            if sid not in stops:
                fresh = snap.get(sid)
                stops[sid] = [fresh[0] if fresh else name, fresh[1] if fresh else '', la, lo]

    for sid, ov in overrides.items():
        if sid in stops:
            stops[sid][0] = ov['name']

    os.makedirs(OUT, exist_ok=True)
    json.dump({'gen': os.environ.get('GEN_DATE', ''), 'stops': stops},
              open(f'{OUT}/stops.json', 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'{n_files:,} קבצי קווים נסרקו | {n_active:,} וריאנטים פעילים | {len(stops):,} תחנות ייחודיות')


if __name__ == '__main__':
    main()
