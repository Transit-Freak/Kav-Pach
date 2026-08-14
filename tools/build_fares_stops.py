# -*- coding: utf-8 -*-
# המחירון — אינדקס תחנות ארצי לחיפוש-לפי-תחנה: סורק את כל קבצי הקווים
# הפעילים ב-line-history (אוטובוס בלבד) ובונה מפה אחת stop_id -> [שם,עיר,lat,lon].
# רץ פעם בשבוע (אותו קצב כמו רענון שמות התחנות הארצי) כי מיקומי תחנות
# משתנים לעיתים רחוקות מאוד.
import glob
import json
import os

OUT = os.environ.get('OUTDIR', 'fares/data')
LH = 'line-history/data/lines'


def main():
    try:
        cities = {sid: v[1] for sid, v in
                  json.load(open('next-station/stops-names.json', encoding='utf-8')).items()}
    except Exception:
        cities = {}

    stops = {}
    n_files = n_active = 0
    for path in glob.glob(f'{LH}/*.json'):
        n_files += 1
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        if d.get('tt') or d.get('lk') == 'removed':
            continue  # רק קווי אוטובוס פעילים כרגע
        pool = d.get('pool') or []
        if len(pool) < 2:
            continue
        n_active += 1
        for p in pool:
            if len(p) < 4:
                continue
            sid, name, la, lo = p[0], p[1], p[2], p[3]
            if sid not in stops:
                stops[sid] = [name, cities.get(sid, ''), la, lo]

    os.makedirs(OUT, exist_ok=True)
    json.dump({'gen': os.environ.get('GEN_DATE', ''), 'stops': stops},
              open(f'{OUT}/stops.json', 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'{n_files:,} קבצי קווים נסרקו | {n_active:,} וריאנטים פעילים | {len(stops):,} תחנות ייחודיות')


if __name__ == '__main__':
    main()
