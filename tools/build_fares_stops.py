# -*- coding: utf-8 -*-
# המחירון — אינדקס תחנות ארצי לחיפוש-לפי-תחנה: סורק את כל קבצי הקווים
# הפעילים ב-line-history (אוטובוס, קווי דרישה, רכבת ורק"ל) ובונה מפה אחת
# stop_id -> [שם,עיר,lat,lon]. רץ פעם בשבוע (אותו קצב כמו רענון שמות
# התחנות הארצי) כי מיקומי תחנות משתנים לעיתים רחוקות מאוד.
import csv
import glob
import json
import os
import re

OUT = os.environ.get('OUTDIR', 'fares/data')
LH = 'line-history/data/lines'
# מוניות שירות וכבלים לא בטבלת התעריפים הזאת בכלל — נשארים בחוץ
INCLUDE_TT = {None, 'demand', 'rail', 'lightrail'}


def city_from_desc(desc):
    # אותו regex בדיוק כמו ב-classify.py — GTFS-IL כותב לכל תחנה
    # stop_desc בפורמט "רחוב: X עיר: Y רציף: Z", תמיד עם עיר
    m = re.search(r'עיר:\s*(.*?)\s*רציף:', desc or '')
    return m.group(1).strip() if m else ''


def fresh_names_from_gtfs(path):
    # stops.txt גולמי, אם זמין (מורד כבר באותה ריצה של update-weekly
    # בשביל classify.py) — עדיף על הסנאפשוט הארצי כי הוא לא מסונן רק
    # לתחנות "פעילות היום": כל תחנה אמיתית כותבת עיר ב-stop_desc שלה,
    # בלי קשר אם עברה בה נסיעה בתאריך הספציפי שבו רץ classify.py
    try:
        rows = list(csv.reader(open(path, encoding='utf-8-sig')))
    except Exception:
        return {}
    ix = {h: i for i, h in enumerate(rows[0])}
    need = ('stop_id', 'stop_name', 'stop_desc')
    if not all(k in ix for k in need):
        return {}
    si, sn, sd = ix['stop_id'], ix['stop_name'], ix['stop_desc']
    out = {}
    for r in rows[1:]:
        if len(r) <= sd:
            continue
        out[r[si]] = [r[sn].strip(), city_from_desc(r[sd])]
    return out


def main():
    fresh = fresh_names_from_gtfs(os.environ.get('STOPS_TXT', ''))
    # גיבוי: הסנאפשוט הארצי (stops-names.json) — נבנה גם הוא מ-stops.txt
    # אבל מסונן רק לתחנות פעילות אותו יום; משמש רק כשאין stops.txt גולמי
    if not fresh:
        try:
            fresh = json.load(open('next-station/stops-names.json', encoding='utf-8'))
        except Exception:
            fresh = {}
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
                fn = fresh.get(sid)
                stops[sid] = [fn[0] if fn else name, fn[1] if fn else '', la, lo]

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
