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

    try:
        state = json.load(open('line-history/data/stops-state.json', encoding='utf-8'))
        for mk, row in state.items():
            add(row[0], row[3] if len(row) > 3 else '', mk)
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
                if mk not in coords and e.get('la') and e.get('lo'):
                    coords[mk] = (e['la'], e['lo'])
    except Exception:
        pass
    # אינדקס מילים לכל עיר, להתאמת שם שקיבל או איבד מילה: "שדרות בן
    # גוריון/בן אהרון" של 2012 מול "שדרות דוד בן גוריון/בן אהרון" אצלנו.
    tok_city = collections.defaultdict(list)
    for c, items in by_city.items():
        for nn, mk in set(items):
            tok_city[c].append((frozenset(nn.split()), mk))
    return lk, srt, by_city, cities, coords, tok_city


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

    lookup, srt, by_city, cities, coords, tok_city = build_stop_lookup()
    m_hit = m_tot = 0

    def mks_of(name):
        nonlocal m_hit, m_tot
        m_tot += 1
        mks = sorted(lookup.get(norm(name), []))
        if 0 < len(mks) <= CAP:
            m_hit += 1
            return mks
        # אותן מילים בסדר הפוך — "חנה סנש/שד.ירושלים" מול "שדרות ירושלים/חנה סנש"
        mks = sorted(srt.get(sortkey(name), []))
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
            found = {mk for nn, mk in by_city[city]
                     if nn == street or nn.startswith(street) or street.startswith(nn)}
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

    n_amb = n_res = n_out = 0

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
        for i in range(1, len(out) - 1):
            c, a, b = out[i], out[i - 1], out[i + 1]
            if len(c) < 7 or len(a) < 7 or len(b) < 7:
                continue
            da, db = km(c[5:7], a[5:7]), km(c[5:7], b[5:7])
            if da > 25 and db > 25 and km(a[5:7], b[5:7]) < 5:
                out[i] = c[:4] + [[]]
                n_out += 1

    def route_stops(r):
        """רצף התחנות של מסלול, אחרי הכרעה בין מועמדים לפי הגאוגרפיה.

        שם כמו "ספריה עירונית/בן גוריון" מתאים לשתי תחנות באותה עיר — שני
        הכיוונים של אותו רחוב. השם לבדו אינו יכול להכריע, אבל המסלול כן:
        התחנה הנכונה היא זו שמתיישבת עם השכנות שלה ברצף.
        """
        nonlocal n_amb, n_res
        raw = [(st, mks_of(st['name'])) for st in (r.get('stops') or [])]
        anchors = [(i, coords[mk[0]]) for i, (st, mk) in enumerate(raw)
                   if len(mk) == 1 and mk[0] in coords]
        out = []
        for i, (st, mks) in enumerate(raw):
            if len(mks) > 1 and all(mk in coords for mk in mks):
                n_amb += 1
                near = [c for j, c in anchors if 0 < abs(j - i) <= 3]
                if near:
                    def cost(mk):
                        y, x = coords[mk]
                        return sum((y - b) ** 2 + (x - a) ** 2 for b, a in near)
                    mks = [min(mks, key=cost)]
                    n_res += 1
            out.append([st['seq'], untrunc(st['name']), st['t'], st['type'], mks]
                       + (list(coords.get(mks[0], ())) if mks else []))
        drop_outliers(out)
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
             'stops': route_stops(r)}
            for r in rows]}
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
    print(f'הכרעת מועמדים לפי המסלול: {n_res} מתוך {n_amb} תחנות רב-משמעיות · '
          f'{n_out} התאמות בוטלו כחריגות גאוגרפיות')
    print(f'נבנו {len(idx)} קווים | {len(routes)} מסלולים | '
          f'{sum(1 for _ in OUT.glob("l*.json"))} קבצים | '
          f'הצלבת תחנות: {m_hit}/{m_tot} ({m_hit * 100 // max(m_tot, 1)}%)')


if __name__ == '__main__':
    main()
