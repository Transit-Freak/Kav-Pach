# -*- coding: utf-8 -*-
# המחירון — אינדקס תחנות ארצי לחיפוש-לפי-תחנה: סורק את כל קבצי הקווים
# הפעילים ב-line-history (אוטובוס, קווי דרישה, רכבת ורק"ל) ובונה מפה אחת
# stop_id -> [שם,עיר,lat,lon]. רץ פעם בשבוע (אותו קצב כמו רענון שמות
# התחנות הארצי) כי מיקומי תחנות משתנים לעיתים רחוקות מאוד.
import csv
import datetime
import glob
import json
import os
import re

OUT = os.environ.get('OUTDIR', 'fares/data')
LH = 'line-history/data/lines'
# מוניות שירות וכבלים לא בטבלת התעריפים הזאת בכלל — נשארים בחוץ
INCLUDE_TT = {None, 'demand', 'rail', 'lightrail'}


def route_state():
    # לא ניחוש לפי תאריך אירוע אחרון (lk/ld יכולים להישאר תקועים בלי
    # אירוע ביטול רשמי) — routes-daily-state.json של הקו בזמן עצמו הוא
    # המקור הסופי. seen שומר כל קו שנראה אי-פעם עם תאריך last, אז
    # מחזירים שני סטים: כל מי שהסריקה מכירה, ומי שנראה ב-30 הימים
    # האחרונים שלה (סולח לקו של שישי/שבת, זורק וריאנטים שנעלמו מזמן).
    # קו שהסריקה לא מכירה בכלל (רק"ל/רכבת/דרישה, או אוטובוס חדש) נשפט
    # לפי versions שלו — הסריקה עוקבת רק אחרי אוטובוסים.
    try:
        st = json.load(open('line-history/data/routes-daily-state.json', encoding='utf-8'))
        last = datetime.date.fromisoformat(st['last_date'])
        seen = st.get('seen') or {}
        cur = {rd for rd, e in seen.items()
               if e.get('last') and (last - datetime.date.fromisoformat(e['last'])).days <= 30}
        return set(seen), cur
    except Exception:
        return None, None


def current_seq(d):
    # ה-pool הוא איחוד היסטורי של כל תחנה שהקו עצר בה אי-פעם — הרצף
    # הנוכחי הוא הגרסה האחרונה שיש לה רשימת תחנות. גרסה טרייה עלולה
    # להישמר עם תחנות "פתוחות" (מערכים מלאים) עד שהדחיסה היומית תהפוך
    # אותן לאינדקסים — תומכים בשני המצבים
    pool = d.get('pool') or []
    for v in reversed(d.get('versions') or []):
        st = v.get('stops')
        if not st:
            continue
        seq = [pool[i] if isinstance(i, int) else i for i in st
               if not isinstance(i, int) or i < len(pool)]
        seq = [p for p in seq if isinstance(p, list) and len(p) >= 4]
        if len(seq) > 1:
            return seq
    return None


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
    # המפתח חייב להיות stop_code — זה המספר שעל השלט, וזה מה שה-pool של
    # line-history שומר. stop_id הוא מספר רץ פנימי אחר לגמרי, ומיפתוח
    # לפיו מחזיר שם ועיר של תחנה לא קשורה בכל התנגשות מספרים
    need = ('stop_code', 'stop_name', 'stop_desc')
    if not all(k in ix for k in need):
        return {}
    sc, sn, sd = ix['stop_code'], ix['stop_name'], ix['stop_desc']
    out = {}
    for r in rows[1:]:
        if len(r) <= max(sc, sn, sd):
            continue
        code = r[sc].strip()
        if code:
            out[code] = [r[sn].strip(), city_from_desc(r[sd])]
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

    seen_all, current = route_state()

    stops = {}
    n_files = n_active = 0
    for path in glob.glob(f'{LH}/*.json'):
        n_files += 1
        try:
            d = json.load(open(path, encoding='utf-8'))
        except Exception:
            continue
        rd = d.get('rd')
        vs = d.get('versions') or []
        not_removed = bool(vs) and vs[-1].get('k') != 'removed'
        if current is not None and seen_all and rd in seen_all:
            is_current = rd in current
        else:
            is_current = not_removed
        if d.get('tt') not in INCLUDE_TT or not is_current:
            continue
        seq = current_seq(d)
        if not seq:
            continue
        n_active += 1
        for p in seq:
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
