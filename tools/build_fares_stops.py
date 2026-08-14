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
# route_type -> סוג: אוטובוס (כולל תתי-הסוגים 700+), רק"ל, דרישה
BUSX = {'700', '701', '702', '703', '704', '705', '706', '707', '708', '709',
        '710', '711', '712', '3'}
SCHED_TYPES = BUSX | {'0', '715'}


def sched_rds():
    """הרשימה הסופית של "קו שקיים ויש לו לוז": קווים עם נסיעה מתוכננת
    ב-7 הימים הקרובים, ישירות מה-GTFS הטרי של היום. שני מסלולים:
    SCHED_JSON = רשימה מחושבת מראש; או ROUTES_TXT+TRIPS_TXT+CAL_TXT
    מתוך ה-zip שריצת update-weekly כבר מורידה ממילא."""
    p = os.environ.get('SCHED_JSON')
    if p:
        try:
            return set(json.load(open(p, encoding='utf-8')))
        except Exception:
            return None
    routes_p, trips_p, cal_p = (os.environ.get(k) for k in ('ROUTES_TXT', 'TRIPS_TXT', 'CAL_TXT'))
    if not (routes_p and trips_p and cal_p):
        return None
    try:
        today = datetime.date.today()
        win = [today + datetime.timedelta(days=i) for i in range(7)]
        win_s = {d.strftime('%Y%m%d') for d in win}
        daycol = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        svc = set()
        rd_ = csv.reader(open(cal_p, encoding='utf-8-sig'))
        c = {h.strip(): i for i, h in enumerate(next(rd_))}
        for r in rd_:
            try:
                s, e = r[c['start_date']], r[c['end_date']]
                for d in win:
                    if s <= d.strftime('%Y%m%d') <= e and r[c[daycol[d.weekday()]]].strip() == '1':
                        svc.add(r[c['service_id']])
                        break
            except IndexError:
                continue
        cald_p = os.environ.get('CALD_TXT')
        if cald_p and os.path.exists(cald_p):
            rd_ = csv.reader(open(cald_p, encoding='utf-8-sig'))
            c = {h.strip(): i for i, h in enumerate(next(rd_))}
            for r in rd_:
                try:
                    if r[c['date']] in win_s and r[c['exception_type']].strip() == '1':
                        svc.add(r[c['service_id']])
                except IndexError:
                    continue
        active_rids = set()
        rd_ = csv.reader(open(trips_p, encoding='utf-8-sig'))
        c = {h.strip(): i for i, h in enumerate(next(rd_))}
        for r in rd_:
            try:
                if r[c['service_id']] in svc:
                    active_rids.add(r[c['route_id']])
            except IndexError:
                continue
        out = set()
        rd_ = csv.reader(open(routes_p, encoding='utf-8-sig'))
        c = {h.strip(): i for i, h in enumerate(next(rd_))}
        for r in rd_:
            try:
                if r[c['route_id']] not in active_rids:
                    continue
                if r[c['route_type']].strip() not in SCHED_TYPES:
                    continue
                parts = r[c['route_desc']].strip().split('-')
                if len(parts) < 3:
                    continue
                mkt = parts[0].lstrip('0')
                if mkt:
                    out.add(f'{mkt}-{parts[1]}-{parts[2]}')
            except IndexError:
                continue
        print(f'לוז מה-GTFS הטרי: {len(out):,} קווים עם נסיעות בשבוע הקרוב')
        return out
    except Exception as e:
        print('חישוב הלוז נכשל — נופלים לסריקות:', e)
        return None


def route_state():
    # לא ניחוש לפי תאריך אירוע אחרון (lk/ld יכולים להישאר תקועים בלי
    # אירוע ביטול רשמי) — שתי הסריקות היומיות של הקו בזמן הן המקור
    # הסופי: routes-daily-state (אוטובוסים) + routes-tt-2026-state
    # (רק"ל/דרישה/מוניות/כבלים). seen שומר כל קו שנראה אי-פעם עם תאריך
    # last, אז מחזירים שני סטים: כל מי שאיזושהי סריקה מכירה, ומי שנראה
    # ב-30 הימים שלפני הסריקה האחרונה (סולח לקו של שישי/שבת בלבד).
    seen_all, cur = set(), set()
    found = False
    for name in ('routes-daily-state.json', 'routes-tt-2026-state.json'):
        try:
            st = json.load(open(f'line-history/data/{name}', encoding='utf-8'))
            last = datetime.date.fromisoformat(st['last_date'])
        except Exception:
            continue
        found = True
        for rd, e in (st.get('seen') or {}).items():
            seen_all.add(rd)
            if e.get('last') and (last - datetime.date.fromisoformat(e['last'])).days <= 30:
                cur.add(rd)
    return (seen_all, cur) if found else (None, None)


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

    # מקור העדיפות הראשונה: לוז אמיתי מה-GTFS הטרי (נכתב גם לאתר,
    # שישתמש בו כמבחן הקיום היחיד). נפילה: שתי הסריקות היומיות.
    os.makedirs(OUT, exist_ok=True)
    sched = sched_rds()
    if sched:
        json.dump({'gen': os.environ.get('GEN_DATE', ''), 'rds': sorted(sched)},
                  open(f'{OUT}/current.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
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
        if sched is not None:
            is_current = rd in sched
        elif current is None:
            is_current = not_removed
        elif rd in seen_all:
            is_current = rd in current
        else:
            # קו שאף סריקה לא מכירה — רק אם האירוע האחרון שלו טרי (קו
            # חדש באמת), לא וריאנט-רפאים שנשאר "לא מבוטל" משנת 2023
            try:
                age = (datetime.date.today() - datetime.date.fromisoformat(vs[-1]['d'])).days
            except Exception:
                age = 999
            is_current = not_removed and age <= 60
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
