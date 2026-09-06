#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בניית נתוני אתר "רשת 2012" מתוך ענף magihim-data (תוצרי הסורק).

קורא את parsed/routes-agency-*.jsonl ואת state.json (שמות חברות) ישירות
מהענף המרוחק (git show), ומפיק:
  magihim-2012/data/index.json — רשימת קווים מקובצת: מספר קו, חברה, יעדים
  magihim-2012/data/l<agency>-<line>.json — קובץ לקו: כל וריאנטי המסלול והתחנות

מריצים שוב אחרי כל checkpoint כדי לרענן את האתר בנתונים העדכניים.
"""
import collections
import json
import math
import pathlib
import re
import subprocess
import sys
import time

REF = 'origin/magihim-data'
# תקרת מק"טים לשם אחד. מעליה ההתאמה רחבה מדי מכדי לומר עליה משהו.
CAP = 6
OUT = pathlib.Path('magihim-2012/data')


def show(path):
    r = subprocess.run(['git', 'show', f'{REF}:{path}'], capture_output=True)
    return r.stdout.decode('utf-8') if r.returncode == 0 else None


# קיצורים נפוצים בשמות של 2012 מול הכתיב של המאגר — מוחל על שני הצדדים
EXPAND = [('ת.מרכזית', 'תחנה מרכזית'), ('ת. מרכזית', 'תחנה מרכזית'),
          ('ת.רכבת', 'תחנת רכבת'), ('ת. רכבת', 'תחנת רכבת'),
          ('שד. ', 'שדרות '), ('שד.', 'שדרות '), ('רח. ', ''), ('רח.', ''),
          ("בי''ס", 'בית ספר'), ('בי"ס', 'בית ספר'),
          ('ביה"ח', 'בית חולים'), ("ביה''ח", 'בית חולים'),
          ('תחנה מרכזית', 'מרכזית')]


# מגיעים קיצר "בני ברק" ל"ברק" בחלק מהרשומות — לפעמים בתוך אותו מסלול
# עצמו ("בן גוריון/ז'בוטינסקי - בני ברק" לצד "מגדלי קונקורד - ברק"). זו
# חוסר עקביות שלהם, ובתצוגה היא נקראת כשם עיר אחר.
# ה"ל" וה"מ" הן תחיליות היעד ("מקרית מלאכי לברק"), והבדיקה על "בני "
# שלפני מונעת מ"בני ברק" תקין להפוך ל"בני בני ברק".
TRUNC = re.compile(r'(?<!בני )(?<![א-ת])([למ]?)ברק(?![א-ת])')


def untrunc(s):
    """השלמת שמות עיר שנקטעו במקור, לתצוגה בלבד."""
    return TRUNC.sub(r'\1בני ברק', s or '')


def norm(s):
    """נרמול שם תחנה להצלבה: קיצורים, גרשיים, מקפים, לוכסנים ורווחים."""
    for a, b in EXPAND:
        s = s.replace(a, b)
    for ch in ('"', "''", "'", '״', '׳'):
        s = s.replace(ch, '')
    s = s.replace(' - ', ' ').replace('-', ' ').replace('/', ' ')
    return ' '.join(s.split())


def sortkey(s):
    """אותן מילים בסדר אחר — אותה תחנה.

    שם של צומת נכתב בשני המקורות בשני הסדרים: "חנה סנש/שד.ירושלים" ב-2012
    מול "שדרות ירושלים/חנה סנש" ברישום היום. השוואה לפי שוויון או רישא
    מפספסת את זה לגמרי, ולכן יש גם מפתח שבו המילים ממוינות.
    """
    return ' '.join(sorted(norm(s).split()))


# שמות ערים שהשתנו או נכתבים אחרת ב-2012. הרישום של היום נרשם גם תחת
# הכתיב של אז, ולא להפך — כך שם עיר ישן לא דורס שם עיר קיים.
CITY_ALIAS = {'בני ברק': ['ברק'], 'נוף הגליל': ['נצרת עילית'],
              'תל אביב יפו': ['תל אביב'], 'מעלות תרשיחא': ['מעלות'],
              'דייר חנא': ['דיר חנא'], 'יהוד מונוסון': ['יהוד']}


def build_stop_lookup():
    """שלושה מפתחות: שם מלא מנורמל, אותו שם במילים ממוינות, ולפי-עיר
    לשמות קטועים. המקורות: המאגר הנוכחי + שמות היסטוריים מהארכיון."""
    lk = collections.defaultdict(set)          # norm(שם עיר) / norm(שם) -> מק"טים
    srt = collections.defaultdict(set)         # sortkey(שם עיר) -> מק"טים
    by_city = collections.defaultdict(list)    # norm(עיר) -> [(norm(שם), מק"ט)]
    cities = set()
    coords = {}                                # מק"ט -> (lat, lon)
    city_of = collections.defaultdict(set)     # מק"ט -> שמות העיר המנורמלים (כולל כינויים)
    # תחנה שנולדה אחרי 2012 לא יכולה להיות התחנה של 2012 כשיש לצידה תחנה
    # ותיקה באותו שם: "מסוף רמז - אשקלון" נפל על המסוף החדש (מק"ט מ-2024)
    # במקום על הישן, שנקרא אז בדיוק "מסוף-רמז" (שלמה 06.09). לכן נשמרים
    # תאריך הלידה של כל מק"ט (אירוע 'new' בארכיון) והשמות שנשאה בעבר.
    born = {}                                  # מק"ט -> תאריך אירוע 'new' המוקדם
    old_named = collections.defaultdict(set)   # norm(שם ישן) -> מק"טים שנשאו אותו
    cur_named = collections.defaultdict(set)   # norm(שם היום) -> מק"טים
    dels = []                                  # (תאריך, norm(שם), (lat, lon)) של תחנות שנמחקו

    def add(n, city, mk):
        nn, nc = norm(n), norm(city)
        lk[norm(f'{n} {city}')].add(mk)
        lk[nn].add(mk)
        # רק עם העיר: בלעדיה "הרצל/ויצמן" מכל הארץ נופל לאותו מפתח
        for c in [city] + CITY_ALIAS.get(nc, []):
            if norm(c):
                lk[norm(f'{n} {c}')].add(mk)
                srt[sortkey(f'{n} {c}')].add(mk)
                cities.add(norm(c))
                by_city[norm(c)].append((nn, mk))
                city_of[mk].add(norm(c))

    try:
        state = json.load(open('line-history/data/stops-state.json', encoding='utf-8'))
        for mk, row in state.items():
            add(row[0], row[3] if len(row) > 3 else '', mk)
            cur_named[norm(row[0])].add(mk)
            if len(row) > 2 and row[1] and row[2]:
                coords[mk] = (row[1], row[2])
    except Exception:
        pass
    try:
        hist = json.load(open('line-history/data/stops-hist.json', encoding='utf-8'))
        for mk, evs in hist.items():
            for e in evs:
                # 'on' הוא השם שהיה לפני שינוי השם — כלומר בדיוק השם שסביר
                # שיופיע ב-2012. בלעדיו נשאר רק השם החדש, וההצלבה מחפשת
                # שם שהתחנה כבר לא נקראת בו.
                for n in (e.get('n'), e.get('nn'), e.get('on')):
                    if n:
                        add(n, e.get('t', ''), mk)
                if e.get('on'):
                    old_named[norm(e['on'])].add(mk)
                if e.get('k') == 'new' and e.get('d'):
                    born[mk] = min(born.get(mk, '9'), e['d'])
                if e.get('k') == 'del' and e.get('d') and e.get('la') and e.get('lo'):
                    dels.append((e['d'], norm(e.get('n') or ''), (e['la'], e['lo'])))
                if mk not in coords and e.get('la') and e.get('lo'):
                    coords[mk] = (e['la'], e['lo'])
    except Exception:
        pass
    # תאומות: שתי תחנות באותו שם משני צידי הכביש (עד 120 מ׳). ההצלבה לפי
    # שם לבדו בוחרת צד אקראי; הצד נקבע אחר כך לפי כיוון הנסיעה (route_stops).
    twins = collections.defaultdict(set)
    try:
        by_nm = collections.defaultdict(list)
        for mk, row in state.items():
            if len(row) > 2 and row[1] and row[2]:
                by_nm[norm(row[0])].append(mk)
        for nm, mks in by_nm.items():
            for a in mks:
                for b in mks:
                    if a < b and abs(coords[a][0] - coords[b][0]) * 111 < .12 and abs(coords[a][1] - coords[b][1]) * 94 < .12:
                        twins[a].add(b)
                        twins[b].add(a)
    except Exception:
        pass
    # אינדקס מילים לכל עיר, להתאמת שם שקיבל או איבד מילה: "שדרות בן
    # גוריון/בן אהרון" של 2012 מול "שדרות דוד בן גוריון/בן אהרון" אצלנו.
    tok_city = collections.defaultdict(list)
    for c, items in by_city.items():
        for nn, mk in set(items):
            tok_city[c].append((frozenset(nn.split()), mk))
    # תחנה "צעירה": נולדה מ-2018 (הארכיון מתחיל ב-2017, אז לידה מאוחרת יותר
    # היא אמיתית) ואין לה קודמת — תחנה שנמחקה עד 60 מ׳ ממנה (או עד 120 מ׳
    # באותו שם) בטווח חצי שנה מהלידה, כלומר מספור מחדש של אותה תחנה. תחנה
    # כזו לא הייתה קיימת ב-2012 ואינה יכולה להיות התחנה של 2012 (שלמה 06.09,
    # "מחלף חולון" — מק"ט 3199 שנולד ב-2026).
    def km_(a, b):
        return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))
    young = set()
    nm_of = {}
    try:
        for mk, row in state.items():
            nm_of[mk] = norm(row[0])
    except Exception:
        pass
    for mk, d in born.items():
        if d < '2018' or mk not in coords:
            continue
        y0, y1 = int(d[:4]) - 1, int(d[:4]) + 1
        pred = False
        for dd, dn, dc in dels:
            if not (str(y0) <= dd[:4] <= str(y1)):
                continue
            if abs((int(dd[:4]) - int(d[:4])) * 365 + (int(dd[5:7]) - int(d[5:7])) * 30 + (int(dd[8:10]) - int(d[8:10]))) > 183:
                continue
            dist = km_(dc, coords[mk])
            if dist <= .06 or (dist <= .12 and dn == nm_of.get(mk)):
                pred = True
                break
        if not pred:
            young.add(mk)
    return lk, srt, by_city, cities, coords, tok_city, city_of, born, old_named, cur_named, twins, young


def main():
    state = json.loads(show('state.json') or '{}')
    ag_names = {a: (m.get('name') or f'חברה {a}')
                for a, m in state.get('agencies', {}).items()}

    listing = subprocess.run(['git', 'ls-tree', '--name-only', REF, 'parsed/'],
                             capture_output=True, text=True).stdout.split()
    routes = {}   # rid -> row (דה-דופליקציה: שומרים את הגרסה העשירה ביותר)
    for f in listing:
        if not re.match(r'parsed/routes-agency-\d+\.jsonl$', f):
            continue
        for ln in (show(f) or '').splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            rid = str(row.get('route'))
            if rid not in routes or len(row.get('stops', [])) > len(routes[rid].get('stops', [])):
                routes[rid] = row

    # מגיעים קיבץ במסד שלו את כל המסלולים הארציים של אותו מספר תחת מזהה
    # קו אחד — "קו 1" מכיל את קרית שמונה, אילת, ירושלים ועוד. מפצלים לפי
    # חתימת הערים שבכותרת של כל מסלול, כדי שכל עיר תקבל שורה משלה.
    def citysig(dest):
        mm = re.match(r'מ(.+?) ל(.+)$', dest or '')
        if mm:
            return ' ↔ '.join(sorted((mm.group(1).strip(), mm.group(2).strip())))
        return (dest or '').strip() or '?'

    lines = collections.defaultdict(list)   # (agency, line_id, citysig) -> [row]
    for row in routes.values():
        title = row.get('title', '')
        dest = title.split(' - ', 1)[1] if ' - ' in title else ''
        lines[(str(row['agency']), str(row.get('line')), citysig(dest))].append(row)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('l*.json'):
        old.unlink()

    lookup, srt, by_city, cities, coords, tok_city, city_of, born, old_named, cur_named, twins, young = build_stop_lookup()
    m_hit = m_tot = 0
    n_side = n_young = 0

    def right_side(out):
        """תחנה שיש לה תאומה מעבר לכביש: בוחרים את הצד הימני ביחס לכיוון
        הנסיעה (מהתחנה הידועה הקודמת לבאה) — בישראל נוסעים בימין והאוטובוס
        עוצר בצד הימני. הצלבה לצד הלא נכון שלחה את מנוע הניווט לפניית פרסה
        במרחק עשרות ק"מ (שלמה 06.09, קווים 180 ו-388)."""
        nonlocal n_side
        def near(i, step):
            j = i + step
            while 0 <= j < len(out):
                if len(out[j]) >= 7:
                    return out[j]
                j += step
            return None
        for i, row in enumerate(out):
            if len(row) < 7 or not row[4] or len(row[4]) != 1:
                continue
            mk = row[4][0]
            tw = twins.get(mk)
            if not tw:
                continue
            a, b = near(i, -1), near(i, 1)
            if a is None and b is None:
                continue
            here = coords[mk]
            src = (a[5], a[6]) if a is not None else here
            dst = (b[5], b[6]) if b is not None else here
            cosl = math.cos(math.radians(here[0]))
            dx, dy = (dst[1] - src[1]) * 111000 * cosl, (dst[0] - src[0]) * 111000
            if math.hypot(dx, dy) < 50:
                continue
            cands = [mk] + sorted(tw)
            my, mx = (sum(coords[c][0] for c in cands) / len(cands), sum(coords[c][1] for c in cands) / len(cands))
            def score(c):
                ox, oy = (coords[c][1] - mx) * 111000 * cosl, (coords[c][0] - my) * 111000
                return ox * dy - oy * dx          # חיובי = מימין לכיוון הנסיעה
            best = max(cands, key=score)
            if best != mk:
                out[i] = row[:4] + [[best]] + list(coords[best])
                n_side += 1

    def prefer_old(name, mks):
        """בין כמה מועמדים: קודם מי שנשא בעבר בדיוק את השם של 2012, ואז מי
        שלא נולד אחרי 2017 (הארכיון מתחיל ב-2017; לידה מ-2018 ואילך היא
        אמיתית). מועמד יחיד נשאר כמו שהוא."""
        if len(mks) <= 1:
            return mks
        street = norm(name.rsplit(' - ', 1)[0] if ' - ' in name else name)
        # "נשא את השם": היום או בעבר. רק העבר הביא "בית ספר אזורי" של באר שבע
        # לתחנה בפרדס חנה שנקראה כך פעם, במקום לזו בנאות חובב שנקראת כך היום
        # (שלמה 06.09). וזה רק שובר שוויון — הגאוגרפיה של המסלול מכריעה קודם.
        carried = [mk for mk in mks if mk in old_named.get(street, ()) or mk in cur_named.get(street, ())]
        if carried and len(carried) < len(mks):
            mks = carried
        old = [mk for mk in mks if born.get(mk, '0') < '2018']
        if old and len(old) < len(mks):
            mks = old
        return mks
    # הצלבות שהוכרעו מחוץ לכלי (צוות סוכנים / אדם): שם תצוגה של 2012 → מק"ט,
    # או null = "אין תחנה כזו היום". גוברות על כל שלב אוטומטי.
    try:
        manual = json.load(open(OUT / 'manual.json', encoding='utf-8'))
    except Exception:
        manual = {}
    manual = {k: (str(v) if v else None) for k, v in manual.items()}
    n_manual = 0
    # חומר להכרעה: לכל שם ייחודי — כמה מסלולים, מה ההצלבה, ורמז מיקום
    # (חציון מיקומי התחנות הידועות הסמוכות לו במסלולים) כדי לבחור תחנה במפה
    xref = collections.defaultdict(lambda: {'c': 0, 'm': None, 'hints': [], 'rs': [], 'nb': None})

    def name_city(name):
        """העיר שבסוף שם של 2012 ("הנביאים - ירושלים"), אם היא עיר מוכרת."""
        parts = name.split(' - ')
        for take in (2, 1):
            if len(parts) > take:
                c = norm(' '.join(parts[-take:]))
                if c in cities:
                    return c
        return None

    def mks_of(name):
        nonlocal m_hit, m_tot
        m_tot += 1
        # העיר שבשם מכריעה: "הנביאים - ירושלים" נפל על "הנביאים/ירושלים" בקרית
        # אתא (צומת של רחוב הנביאים ורחוב ירושלים), כי אחרי הנרמול שני השמות
        # זהים. מק"ט שהעיר שלו ידועה ואינה העיר שבשם — נפסל (שלמה 05.09,
        # קו 1 ירושלים: מסלול של 300 ק"מ דרך קרית אתא).
        city = name_city(name)

        def same_city(mks):
            if not city:
                return mks
            return [mk for mk in mks if not city_of.get(mk) or city in city_of[mk]]

        mks = same_city(sorted(lookup.get(norm(name), [])))
        if 0 < len(mks) <= CAP:
            m_hit += 1
            return mks
        # אותן מילים בסדר הפוך — "חנה סנש/שד.ירושלים" מול "שדרות ירושלים/חנה סנש"
        mks = same_city(sorted(srt.get(sortkey(name), [])))
        if 0 < len(mks) <= CAP:
            m_hit += 1
            return mks
        # שמות קטועים/מקוצרים: מפרקים "שם - עיר", ואז התאמת-רישא בתוך העיר
        parts = name.split(' - ')
        for take in (2, 1):
            if len(parts) <= take:
                continue
            city = norm(' '.join(parts[-take:]))
            if city not in cities:
                continue
            street = norm(' '.join(parts[:-take]))
            if len(street) < 6:
                break
            # גם שם הרישום חייב אורך: "חזון אי'ש/דבורה הנביאה - חזון" נפל על
            # התחנה "חזון" במושב חזון בגליל, כי "חזון..." מתחיל ב"חזון" (שלמה 05.09)
            found = {mk for nn, mk in by_city[city]
                     if nn == street or (len(nn) >= 6 and (nn.startswith(street) or street.startswith(nn)))}
            if 0 < len(found) <= CAP:
                m_hit += 1
                return sorted(found)
            break
        # שם שקיבל או איבד מילה: "שדרות בן גוריון/בן אהרון" מול "שדרות דוד
        # בן גוריון/בן אהרון". שני הצדדים חייבים שלוש מילים לפחות, אחרת
        # "הרצל/ויצמן" היה נבלע בכל שם ארוך שמכיל אותן.
        if len(parts) > 1:
            city = norm(parts[-1])
            street = frozenset(norm(' '.join(parts[:-1])).split())
            if city in tok_city and len(street) >= 3:
                found = {mk for toks, mk in tok_city[city]
                         if len(toks) >= 3 and (street <= toks or toks <= street)}
                if 0 < len(found) <= CAP:
                    m_hit += 1
                    return sorted(found)
        return []

    def weak_mks_of(name):
        """שם זהה בעיר אחרת ברישום: "שדרות בן גוריון/יגאל הורביץ - באר טוביה"
        ב-2012 מול אותה תחנה שרשומה היום תחת קרית מלאכי (שלמה 05.09). מועמדים
        לפי השם בלי העיר — ומתקבלים רק אם הם יושבים ליד תחנות ידועות סמוכות
        במסלול (route_stops), אחרת שם קצר היה נופל שוב על עיר אחרת."""
        parts = name.split(' - ')
        if len(parts) < 2:
            return []
        street = norm(' '.join(parts[:-1]))
        if len(street) < 6:
            return []
        mks = sorted(lookup.get(street, []))
        return mks if 0 < len(mks) <= CAP else []

    n_amb = n_res = n_out = n_weak = 0

    def km(a, b):
        return math.hypot((a[0] - b[0]) * 111,
                          (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))

    def drop_outliers(out):
        """ביטול התאמה שיושבת רחוק משתי שכנותיה במסלול.

        שם קצר כמו "הנביאים" קיים בכמה ערים, ולפעמים ההתאמה נופלת על תחנה
        במרחק מאה קילומטר משתי התחנות שלפניה ואחריה. אין מסלול כזה — עדיף
        להשאיר את התחנה בלי מק"ט מאשר לשייך אותה לעיר אחרת.
        """
        nonlocal n_out
        # השכנות הן התחנות הקרובות ביותר *שיש להן מיקום*, לא רק הסמוכות:
        # כשהתחנה הסמוכה לא הוצלבה, הבדיקה הקודמת ויתרה — וכך נשארה תחנה
        # בקרית אתא באמצע קו ירושלמי. "קפיצה" = רחוק משתי השכנות בעוד
        # שהן קרובות זו לזו יחסית לקפיצה (קו בינעירוני אמיתי מתקדם, לא חוזר).
        def near(i, step):
            j = i + step
            while 0 <= j < len(out):
                if len(out[j]) >= 7:
                    return out[j]
                j += step
            return None
        for i in range(len(out)):
            c = out[i]
            if len(c) < 7:
                continue
            a, b = near(i, -1), near(i, 1)
            if a is None or b is None:
                continue
            da, db = km(c[5:7], a[5:7]), km(c[5:7], b[5:7])
            if da > 25 and db > 25 and km(a[5:7], b[5:7]) < max(5, min(da, db) / 3):
                out[i] = c[:4] + [[]]
                n_out += 1

    def route_stops(r, rkey=None):
        """רצף התחנות של מסלול, אחרי הכרעה בין מועמדים לפי הגאוגרפיה.

        שם כמו "ספריה עירונית/בן גוריון" מתאים לשתי תחנות באותה עיר — שני
        הכיוונים של אותו רחוב. השם לבדו אינו יכול להכריע, אבל המסלול כן:
        התחנה הנכונה היא זו שמתיישבת עם השכנות שלה ברצף.
        """
        nonlocal n_amb, n_res, n_weak, n_manual, n_young

        def not_young(mks):
            nonlocal n_young
            keep = [mk for mk in mks if mk not in young]
            if len(keep) < len(mks):
                n_young += len(mks) - len(keep)
            return keep

        raw = []
        fixed = set()
        for st in (r.get('stops') or []):
            disp = untrunc(st['name'])
            if disp in manual:
                mk = manual[disp]
                raw.append((st, not_young([mk] if mk and mk in coords else [])))
                fixed.add(len(raw) - 1)
                n_manual += 1
            else:
                raw.append((st, not_young(mks_of(st['name']))))
        anchors = [(i, coords[mk[0]]) for i, (st, mk) in enumerate(raw)
                   if len(mk) == 1 and mk[0] in coords]
        out = []
        for i, (st, mks) in enumerate(raw):
            if i in fixed:
                out.append([st['seq'], untrunc(st['name']), st['t'], st['type'], mks]
                           + (list(coords.get(mks[0], ())) if mks else []))
                continue
            if not mks:
                # שם זהה תחת עיר אחרת — מתקבל רק ליד עוגן סמוך (עד 3 ק"מ)
                near = [c for j, c in anchors if 0 < abs(j - i) <= 3]
                cands = [mk for mk in not_young(weak_mks_of(st['name']))
                         if mk in coords and any(km(coords[mk], c) <= 3 for c in near)]
                if cands:
                    mks = [min(cands, key=lambda mk: min(km(coords[mk], c) for c in near))]
                    n_weak += 1
            if len(mks) > 1 and all(mk in coords for mk in mks):
                n_amb += 1
                near = [c for j, c in anchors if 0 < abs(j - i) <= 3]
                if near:
                    def cost(mk):
                        y, x = coords[mk]
                        return sum((y - b) ** 2 + (x - a) ** 2 for b, a in near)
                    best = min(mks, key=cost)
                    # הגאוגרפיה קודם: מועמדים באותו מקום כמו הקרוב ביותר (עד
                    # 300 מ׳); ביניהם — מי שנשא את השם ומי שוותיק יותר
                    close = [mk for mk in mks if km(coords[mk], coords[best]) <= 0.3]
                    mks = [min(prefer_old(st['name'], close), key=cost)]
                    n_res += 1
                else:
                    mks = prefer_old(st['name'], mks)
            elif len(mks) > 1:
                mks = prefer_old(st['name'], mks)
            out.append([st['seq'], untrunc(st['name']), st['t'], st['type'], mks]
                       + (list(coords.get(mks[0], ())) if mks else []))
        drop_outliers(out)
        for i in fixed:   # הצלבה ידנית אינה "חריגה" — היא ההכרעה של אדם
            st, mks = raw[i]
            out[i] = [st['seq'], untrunc(st['name']), st['t'], st['type'], mks] + (list(coords.get(mks[0], ())) if mks else [])
        right_side(out)   # גם על הידניות: ההכרעה היא על המקום, הצד לפי כיוון הנסיעה
        # חומר להכרעה: רמז מיקום מהשכנות הידועות (עד 3 מקומות לכל צד)
        for i, row in enumerate(out):
            e = xref[row[1]]
            e['c'] += 1
            e['m'] = row[4]
            if len(e['rs']) < 4 and rkey:
                e['rs'].append(rkey)
            nbs = [out[j] for j in range(max(0, i - 3), min(len(out), i + 4)) if j != i and len(out[j]) >= 7]
            for nb in nbs:
                if len(e['hints']) < 60:
                    e['hints'].append((nb[5], nb[6]))
            if e['nb'] is None and nbs:
                e['nb'] = [[nb[5], nb[6], nb[1]] for nb in nbs[:6]]
        return out

    by_al = collections.defaultdict(list)    # (agency, line_id) -> [(sig, rows)]
    for (a, lid, sig), rows in lines.items():
        by_al[(a, lid)].append((sig, rows))

    idx = []
    flat = []
    for (a, lid), groups in by_al.items():
        groups.sort(key=lambda g: (-len(g[1]), g[0]))
        for gi, (sig, rows) in enumerate(groups):
            flat.append((a, lid, gi, rows))
    for a, lid, gi, rows in flat:
        rows.sort(key=lambda r: -len(r.get('stops', [])))
        title = rows[0].get('title', '')
        m = re.match(r'קו\s+(\S+)', title)
        no = m.group(1) if m else '?'
        dest = title.split(' - ', 1)[1] if ' - ' in title else ''
        key = f'{a}-{lid}' if gi == 0 else f'{a}-{lid}x{gi}'
        payload = {'a': a, 'an': ag_names.get(a, ''), 'no': no, 'dest': untrunc(dest), 'routes': [
            {'rid': str(r.get('route')), 'n': len(r.get('stops', [])),
             'f': untrunc(r['stops'][0]['name'] if r.get('stops') else ''),
             'l': untrunc(r['stops'][-1]['name'] if r.get('stops') else ''),
             'stops': route_stops(r, f'{key}/{ri}')}
            for ri, r in enumerate(rows)]}
        (OUT / f'l{key}.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        idx.append({'k': key, 'a': a, 'an': ag_names.get(a, ''), 'no': no,
                    'dest': untrunc(dest), 'nr': len(rows),
                    'ns': max((len(r.get('stops', [])) for r in rows), default=0)})

    def sort_key(e):
        m = re.match(r'(\d+)', e['no'])
        return (int(e['a']) if e['a'].isdigit() else 999,
                int(m.group(1)) if m else 9999, e['no'])
    idx.sort(key=sort_key)

    total_lines_known = sum(len(m.get('lines') or []) for m in state.get('agencies', {}).values())
    (OUT / 'index.json').write_text(json.dumps({
        'gen': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
        'partial': True,
        'agencies': ag_names,
        'lines_known': total_lines_known,
        'routes_total': len(routes),
        'lines': idx,
    }, ensure_ascii=False), encoding='utf-8')
    # ---- xref.json: שמות שדורשים הכרעה (חומר לצוות הסוכנים המצליב; בקשת שלמה 05.09) ----
    def median(xs):
        s = sorted(xs)
        return s[len(s) // 2]
    reg_city = {}
    try:
        for mk, row in json.load(open('line-history/data/stops-state.json', encoding='utf-8')).items():
            reg_city[mk] = row[3] if len(row) > 3 else ''
    except Exception:
        pass
    rows_x = []
    cnt = collections.Counter()
    for name, e in xref.items():
        mks = e['m'] or []
        hint = [round(median([h[0] for h in e['hints']]), 5), round(median([h[1] for h in e['hints']]), 5)] if e['hints'] else None
        c12 = name_city(name)
        st = 'none' if not mks else ('amb' if len(mks) > 1 else 'ok')
        flags = []
        if st == 'ok':
            mk = mks[0]
            if c12 and city_of.get(mk) and c12 not in city_of[mk]:
                flags.append('city')
            if hint and mk in coords and km(coords[mk], hint) > 3:
                flags.append('far')
        if name in manual:
            cnt['manual'] += 1
            continue          # הוכרע — לא דורש הכרעה נוספת
        cnt[st] += 1
        for f in flags:
            cnt[f] += 1
        if st == 'ok' and not flags:
            continue
        row = {'n': name, 'c': e['c'], 's': st, 'm': mks, 'rs': e['rs']}
        if hint:
            row['h'] = hint
        if e['nb']:
            row['nb'] = e['nb']
        if c12:
            row['cty'] = c12
        if st == 'ok':
            row['rc'] = reg_city.get(mks[0], '')
        if flags:
            row['f'] = flags
        rows_x.append(row)
    rows_x.sort(key=lambda r: -r['c'])
    (OUT / 'xref.json').write_text(json.dumps({
        'gen': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
        'counts': dict(cnt), 'names': len(xref), 'rows': rows_x,
    }, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'xref: {len(rows_x)} שמות להכרעה מתוך {len(xref)} · {dict(cnt)} · הצלבות ידניות בשימוש: {n_manual}')
    print(f'הכרעת מועמדים לפי המסלול: {n_res} מתוך {n_amb} תחנות רב-משמעיות · '
          f'{n_out} התאמות בוטלו כחריגות גאוגרפיות · {n_weak} התאמות לפי שם בלי עיר, ליד עוגן · '
          f'{n_side} הועברו לצד הימני של הכביש · {n_young} מועמדים נפסלו כתחנות שנולדו אחרי 2017 בלי קודמת')
    print(f'נבנו {len(idx)} קווים | {len(routes)} מסלולים | '
          f'{sum(1 for _ in OUT.glob("l*.json"))} קבצים | '
          f'הצלבת תחנות: {m_hit}/{m_tot} ({m_hit * 100 // max(m_tot, 1)}%)')


if __name__ == '__main__':
    main()
