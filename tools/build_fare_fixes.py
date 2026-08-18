# -*- coding: utf-8 -*-
# המחירון — קובץ תיקוני-מחיר מהטבלה הרשמית (fares/data/fixes.json):
# נוסחת "מרחק אווירי -> אזור" נכונה ב-99.85% מזוגות התחנות, אבל יש לה
# שלושה עיוורונים שהטבלה הרשמית (fare_rules) יודעת לתקן במדויק:
#   pairs — זוגות תחנות שמשרד התחבורה סיווג לאזור אחר מהנוסחה (רובם
#           צמודים לגבולות 15/40/120/225, חלקם סחף קואורדינטות אצל המשרד)
#           + כל זוג רשמי שקרוב לגבול אזור, כחגורת ביטחון לרעשי קואורדינטות
#   flat  — קווים בתעריף אחיד רשמי לכל הקו (יותר מחצי מהקווים! שאטלים,
#           עירוניים ארוכים) שאינם בטבלת המרחקים בכלל
#   rail  — הרכבת מתומחרת רשמית לפי זוג תחנות, לא לפי קו אווירי — המחירון
#           המלא קטן ונכנס כולו
# רץ בריצת update-weekly אחרי הורדת ה-GTFS. קלט (env):
#   FARE_RULES, FARE_ATTRS, STOPS_TXT, ROUTES_TXT, GEN_DATE, OUT
import csv
import json
import math
import os
import sys

FARE_RULES = os.environ.get('FARE_RULES', 'fare_rules.txt')
FARE_ATTRS = os.environ.get('FARE_ATTRS', 'fare_attributes.txt')
STOPS_TXT = os.environ.get('STOPS_TXT', 'stops.txt')
ROUTES_TXT = os.environ.get('ROUTES_TXT', 'routes.txt')
OUT = os.environ.get('OUT', 'fares/data/fixes.json')
GEN_DATE = os.environ.get('GEN_DATE', '')
# אינדקס תחנה->קווים למצב "לפי תחנות": אילו קווים עוצרים בשתי התחנות
# שנבחרו — ובפרט האם ביניהן נוסע קו בתעריף אחיד (שאז המרחק לא קובע)
LH_DIR = os.environ.get('LH_DIR', 'line-history/data/lines')
CURRENT_JSON = os.environ.get('CURRENT_JSON', 'fares/data/current.json')

# גבולות האזורים, כמו ב-ZONES של fares/index.html
BOUNDS = [15.0, 40.0, 75.0, 120.0, 225.0]
# כמה קרוב לגבול נחשב "על הקצה" ונכנס לקובץ גם כשהנוסחה צודקת — הגנה
# מהפרשי קואורדינטות זעירים בין מקורות התחנות השונים באתר
EDGE_KM = 0.25

# מחלקות המחיר: ספרת המאות אומרת סדרה (2xx אוטובוס ארצי, 21x רכבת,
# 22x אילת פטור-מע"מ), ספרת היחידות ממופה לאינדקס אזור בטבלת האתר
UNIT_TO_ZONE = {1: 0, 2: 1, 4: 2, 5: 4, 6: 5}


def dist_wgs84(lat1, lon1, lat2, lon2):
    """מרחב אווירי על אליפסואיד WGS84 (קירוב Andoyer-Lambert).
    חייב להיות זהה 1:1 ל-hav() שבאתר: כדור R=6371 מנפח מרחקים
    צפון-דרום בכ-0.3% — מספיק כדי להעביר אזור לזוגות שעל הגבול."""
    a, f = 6378.137, 1 / 298.257223563
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    b1, b2 = math.atan((1 - f) * math.tan(p1)), math.atan((1 - f) * math.tan(p2))
    s = math.acos(min(1, max(-1, math.sin(b1) * math.sin(b2) + math.cos(b1) * math.cos(b2) * math.cos(dl))))
    if s == 0:
        return 0.0
    P, Q = (b2 + b1) / 2, (b2 - b1) / 2
    X = (s - math.sin(s)) * (math.sin(P) ** 2 * math.cos(Q) ** 2) / math.cos(s / 2) ** 2
    Y = (s + math.sin(s)) * (math.cos(P) ** 2 * math.sin(Q) ** 2) / math.sin(s / 2) ** 2
    return a * (s - f / 2 * (X + Y))


def zone_for(km):
    for i, m in enumerate(BOUNDS):
        if km <= m:
            return i
    return 5


def rows(path):
    rd = csv.reader(open(path, encoding='utf-8-sig'))
    head = {h.strip(): i for i, h in enumerate(next(rd))}
    for r in rd:
        yield head, r


# המחירים שטבלת ZONES שב-fares/index.html מציגה — אם המשרד מעדכן תעריף,
# הריצה השבועית תצעק ותזכיר לעדכן את הטבלה ידנית
EXPECTED = {'201': 8.0, '202': 14.5, '204': 19.0, '205': 30.5, '206': 87.32,
            '211': 11.5, '212': 21.0, '213': 27.0, '214': 30.5, '215': 52.5}


def main():
    # fare_id -> (אינדקס אזור, סדרת אילת?) לפי מבנה המחלקות הרשמי
    fare_zone, fare_price = {}, {}
    for h, r in rows(FARE_ATTRS):
        fid = r[h['fare_id']].strip()
        fare_price[fid] = float(r[h['price']])
        if fid in EXPECTED and abs(fare_price[fid] - EXPECTED[fid]) > 0.001:
            print(f'::warning::תעריף השתנה! fare_id {fid}: {fare_price[fid]} במקום '
                  f'{EXPECTED[fid]} — יש לעדכן את טבלת ZONES ב-fares/index.html', file=sys.stderr)
        if len(fid) == 3 and fid[0] == '2' and int(fid[2]) in UNIT_TO_ZONE:
            fare_zone[fid] = (UNIT_TO_ZONE[int(fid[2])], fid[1] == '2')

    # stops.txt: zone_id -> תחנות + קואורדינטות (המיפוי כמעט 1:1).
    # תחנות רכבת חריגות: ה-zone_id שלהן ריק, וכללי הרכבת ב-fare_rules
    # מזהים אותן לפי קוד התחנה עצמו — נופלים לזה כשאין אזור תואם
    zone_stops, by_code = {}, {}
    for h, r in rows(STOPS_TXT):
        code = r[h['stop_code']].strip()
        try:
            lat, lon = float(r[h['stop_lat']]), float(r[h['stop_lon']])
        except ValueError:
            continue
        if code and code not in by_code:
            by_code[code] = [(code, lat, lon)]
        z = r[h['zone_id']].strip()
        if z:
            zone_stops.setdefault(z, []).append((code, lat, lon))

    # routes.txt: route_id -> route_desc ("12345-1-#" — ה-rd של האתר)
    route_rd = {}
    for h, r in rows(ROUTES_TXT):
        route_rd[r[h['route_id']].strip()] = r[h['route_desc']].strip()

    pairs, rail, flat = {}, {}, {}
    n_od = n_mm = n_edge = n_conflict = 0
    for h, r in rows(FARE_RULES):
        fid = r[h['fare_id']].strip()
        rid = r[h['route_id']].strip() if 'route_id' in h else ''
        if rid:
            # כלל לכל הקו — תעריף אחיד, גובר על טבלת המרחקים
            rd = route_rd.get(rid)
            if rd and fid in fare_price:
                flat[rd] = fare_price[fid]
            continue
        o, d = r[h['origin_id']].strip(), r[h['destination_id']].strip()
        if not o or not d or fid not in fare_zone:
            continue
        n_od += 1
        so = zone_stops.get(o) or by_code.get(o)
        sd = zone_stops.get(d) or by_code.get(d)
        if not so or not sd:
            continue
        oz, eilat = fare_zone[fid]
        if fid[1] == '1':
            # רכבת: המחירון הרשמי המלא לפי זוג תחנות — נכנס כולו
            for co, la1, lo1 in so:
                for cd, la2, lo2 in sd:
                    key = '|'.join(sorted((co, cd), key=lambda x: (len(x), x)))
                    prev = rail.get(key)
                    if prev is not None and prev != fare_price[fid]:
                        n_conflict += 1
                        continue
                    rail[key] = fare_price[fid]
            continue
        for co, la1, lo1 in so:
            for cd, la2, lo2 in sd:
                km = dist_wgs84(la1, lo1, la2, lo2)
                pz = zone_for(km)
                # מחלקת ה-19 ₪ פרושה על תכלת+כחול — שני האזורים "נכונים"
                same = (pz == oz) or (oz == 2 and pz == 3)
                edge = min(abs(km - b) for b in BOUNDS) <= EDGE_KM
                # זוגות אילת נכנסים תמיד: בלי הדגל האתר יציג את המחיר
                # הארצי המלא במקום מחיר הפטור ממע"מ שנגבה בפועל.
                # ובכיוון ההפוך — זוג במחיר ארצי מלא שאחד מקצותיו דרומי
                # לקו רוחב 29.72 (מחנות צבא, עובדה): בלעדיו העוגן הגאוגרפי
                # של האתר היה מעניק לו הנחת אילת שלא קיימת רשמית
                south = la1 <= 29.72 or la2 <= 29.72
                if same and not edge and not eilat and not south:
                    continue
                if not same:
                    n_mm += 1
                elif edge:
                    n_edge += 1
                # באזור המשותף של מחלקת 19 בוחרים את האזור לפי המרחק,
                # כדי שעמודות הרכבת/יומי/חודשי של השורה יהיו הסבירות
                z = (2 if km <= 75 else 3) if oz == 2 else oz
                val = z + (8 if eilat else 0)
                key = '|'.join(sorted((co, cd), key=lambda x: (len(x), x)))
                prev = pairs.get(key)
                if prev is not None and prev != val:
                    n_conflict += 1
                    continue
                pairs[key] = val

    # האינדקס: lines = [[מספר קו, מחיר אחיד או null], ...] לפי הקווים
    # הפעילים השבוע; serve = {קוד תחנה: [אינדקסים לתוך lines]}. הרצף
    # הנוכחי של כל קו נקרא כמו שהאתר עצמו קורא אותו (הגרסה האחרונה
    # שיש לה רשימת תחנות, אינדקסים לתוך ה-pool).
    # ההצלבה באתר היא לפי הרישוי בלבד: קו נחשב עוצר בתחנה רק אם היא
    # מופיעה ברצף התחנות הרשמי שלו. ברישוי כל כיוון רשום כרשומה נפרדת
    # (מקט-כיוון-חלופה), ולכן שני הכיוונים של אותו רישיון מאוחדים כאן
    # לרשומה אחת — בלעדיו קו שעוצר בתחנה א' בהלוך ובתחנה ב' בחזור לא
    # היה נחשב עובר בין שתיהן. חלופות (10 מול 10א) נשארות נפרדות —
    # מספרי קו שונים עם רצפי תחנות שונים.
    serve, ln_tab = {}, []
    try:
        rds = json.load(open(CURRENT_JSON, encoding='utf-8')).get('rds') or []
    except Exception:
        rds = []
    groups = {}   # מקט-חלופה -> [מספר קו, מחירים אחידים, קודי תחנות]
    for rd in rds:
        fp = os.path.join(LH_DIR, rd.replace('#', 'H').replace('/', '_') + '.json')
        try:
            d2 = json.load(open(fp, encoding='utf-8'))
        except Exception:
            continue
        pool = d2.get('pool') or []
        seq = None
        for v in reversed(d2.get('versions') or []):
            st = v.get('stops')
            if not st or len(st) < 2:
                continue
            s = [pool[x] if isinstance(x, int) and x < len(pool) else x for x in st]
            s = [p for p in s if isinstance(p, list) and len(p) >= 4]
            if len(s) > 1:
                seq = s
                break
        if not seq:
            continue
        p = rd.split('-')
        gk = p[0] + '-' + (p[2] if len(p) >= 3 else '')
        g = groups.setdefault(gk, [d2.get('line') or '', [], {}])
        fl = flat.get(rd)
        if fl is not None:
            g[1].append(fl)
        for q in seq:
            g[2][str(q[0])] = 1    # dict כסט שומר-סדר — פלט דטרמיניסטי
    for line, fls, codes in groups.values():
        idx = len(ln_tab)
        # תעריף אחיד אם רשום לפחות לכיוון אחד: במקרים הבודדים שכיוון
        # אחד חסר בטבלה (3 מתוך 3,258) זו השמטה בנתוני המשרד — מחיר
        # אחיד סותר בין כיוונים לא קיים בנתונים בכלל
        ln_tab.append([line, min(fls) if fls else None])
        for c in codes:
            serve.setdefault(c, []).append(idx)

    out = {'gen': GEN_DATE, 'pairs': pairs, 'rail': rail, 'flat': flat,
           'lines': ln_tab, 'serve': serve}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'fixes.json: {len(pairs)} pairs ({n_mm} mismatch + {n_edge} edge-band), '
          f'{len(rail)} rail pairs, {len(flat)} flat routes, '
          f'{len(ln_tab)} lines indexed over {len(serve)} stops, '
          f'{n_conflict} conflicts skipped, {n_od} od rules read', file=sys.stderr)


if __name__ == '__main__':
    main()
