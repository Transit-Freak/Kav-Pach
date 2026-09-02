# -*- coding: utf-8 -*-
"""נתוני הדו"ח של איריס — מחושבים מהנתונים החיים, בלי מספרים מוקלדים.

קורא את parks/data (האינדקס וקובצי האזורים), מדדי השירות של משרד התחבורה,
האשכולות החברתיים-כלכליים ושכבת משרד התחבורה (תיוג מגזר), ומחשב לקובץ אחד
את כל מה שהדו"ח מציג: תמונת מצב ארצית, קבוצות (מרכז/פריפריה, צפון/מרכז/
דרום, מגזר, אשכול) עם שלושת מדדי הפער של איריס, עשירייה כפולה, פערים בתוך
רשות, חריגים, ומקורות עם תאריכים. מצייר גם את התרשימים (עוגות ועמודות).

    python3 tools/report_data.py            # → parks/report/data.json + img/

המפרט: parks/REPORT-SPEC.md. הנוסחה: גרסת 02.09 (טבלה ומשקלים מ-tools/parks.py).
"""
import collections
import datetime
import zoneinfo
import json
import math
import os
import pathlib
import re
import statistics

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / 'parks' / 'data'
OUT = ROOT / 'parks' / 'report'
IMG = OUT / 'img'
IMG.mkdir(parents=True, exist_ok=True)

# ── הנוסחה (זהה ל-tools/parks.py; מועתקת כי ייבוא מריץ את כל הצינור) ──────
IRIS_HEADWAY = [(5, 100), (10, 90), (15, 80), (21, 70), (30, 65), (40, 55), (60, 40), (90, 15)]
IRIS_WALK = [(2, 100), (7, 90), (10, 80), (12, 75), (15, 65), (20, 55)]
IRIS_W = {'bl': .40, 'far': .30, 'uf': .20, 'near': .10}
# סרגל הצבעים של איריס (02.09 10:16): ירוק רק מ-90, 70 צהוב, 50–60 כתום, מטה — אדום עד שחור
SCALE = [(100, '#14b03d'), (90, '#8cc63f'), (80, '#cfd41f'), (70, '#f8d420'), (60, '#f5a11a'),
         (50, '#ee7a16'), (40, '#e63c14'), (30, '#c00d18'), (20, '#8e0b1e'), (10, '#3f0a18'), (0, '#050505')]
# קבוצות "רמזור" לעוגות — ארבע פרוסות, לפי הסרגל: ירוק ≥90 · צהוב 70–89 · כתום 50–69 · אדום <50
TL = [('ירוק (90 ומעלה)', lambda s: s >= 90, '#14b03d'), ('צהוב (70–89)', lambda s: 70 <= s < 90, '#f8d420'),
      ('כתום (50–69)', lambda s: 50 <= s < 70, '#ee7a16'), ('אדום (מתחת ל-50)', lambda s: s < 50, '#c00d18')]

# גאוגרפיה — הגדרות מתועדות (סעיף 3 בדו"ח)
CENTER_KM = 45                 # "מרכז" = עד 45 ק"מ מתל אביב (כמו באתר)
NORTH_LAT, SOUTH_LAT = 32.40, 31.85   # צפון: מחדרה וצפונה · דרום: מאשדוד/קריית מלאכי ודרומה
BRAND = '#32318e'              # אינדיגו המותג — גוון יחיד לעמודות


def color_of(score):
    if score is None:
        return '#94a3b8'
    for t, c in SCALE:
        if score >= t:
            return c
    return '#050505'


def load():
    P = [p for p in json.load(open(DATA / 'parks.json', encoding='utf-8')) if p.get('score') is not None]
    zones = {}
    for p in P:
        try:
            zones[p['f']] = json.load(open(DATA / p['f'], encoding='utf-8'))
        except Exception:
            zones[p['f']] = {}
    return P, zones


def d_tlv(p):
    return math.hypot((p['la'] - 32.08) * 110.5, (p['lo'] - 34.78) * 94.2)


def region3(p):
    if p['la'] >= NORTH_LAT:
        return 'צפון'
    if p['la'] < SOUTH_LAT:
        return 'דרום'
    return 'מרכז'


def _in_poly(la, lo, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        if (a[1] > lo) != (b[1] > lo):
            x = a[0] + (lo - a[1]) * (b[0] - a[0]) / ((b[1] - a[1]) or 1e-12)
            if la < x:
                inside = not inside
    return inside


def load_districts():
    """המחוז הרשמי של כל אזור משכבת משרד התחבורה (mot-zones.json), לפי מיקום מרכז
    האזור בתוך פוליגון השכבה — לא לפי שם, כי הצינור משנה שמות. שבעת המחוזות
    מקובצים לארבעה: צפון (צפון+חיפה) · מרכז (מרכז+תל אביב) · ירושלים ויו"ש · דרום."""
    f = ROOT / 'parks' / 'osm-check' / 'mot-zones.json'
    if not f.exists():
        return None
    zs = json.load(open(f, encoding='utf-8')).get('zones') or []
    GROUP = {'צפון': 'צפון', 'חיפה': 'צפון', 'מרכז': 'מרכז', 'תל אביב': 'מרכז',
             'ירושלים': 'ירושלים ויו"ש', 'יו"ש': 'ירושלים ויו"ש', 'דרום': 'דרום'}
    def norm_min(v):
        """תיוג המגזר בשכבה, עם שתי שגיאות כתיב שבמקור: 'בדאוים' ו'כללים'."""
        v = (v or '').strip().replace('בדאוים', 'בדואים').replace('כללים', 'כללי').replace('מעוטים כלילם', 'מיעוטים כללי')
        return v or None
    def find(p):
        """(קבוצת מחוז, תיוג מגזר) לאזור — לפי מרכזו בתוך פוליגון השכבה."""
        best, bd = None, 9e9
        for z in zs:
            for ring in z.get('polys') or []:
                if ring and _in_poly(p['la'], p['lo'], ring):
                    return GROUP.get(z.get('district'), z.get('district')), norm_min(z.get('minority'))
            # גיבוי: המרכז הקרוב ביותר עד 2 ק"מ
            pts = [q for r in z.get('polys') or [] for q in r]
            if pts:
                cla = sum(q[0] for q in pts) / len(pts); clo = sum(q[1] for q in pts) / len(pts)
                d = math.hypot((p['la'] - cla) * 110.5, (p['lo'] - clo) * 94.2)
                if d < bd:
                    best, bd = z, d
        if bd <= 2.0 and best:
            return GROUP.get(best.get('district'), best.get('district')), norm_min(best.get('minority'))
        return None, None
    return find


def hw(pkd, minutes):
    return (minutes / pkd) if pkd else None


def mean(v):
    v = [x for x in v if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def median(v):
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 1) if v else None


def pct(a, n):
    return round(100 * a / n) if n else 0


def group_stats(G):
    """שלושת מדדי הפער של איריס (02.09) + הציון, ציון המשרד וספירות."""
    sc = [p['score'] for p in G]
    return {
        'n': len(G),
        'score_mean': mean(sc), 'score_median': median(sc),
        'pct_green': pct(sum(1 for s in sc if s >= 90), len(G)),
        'pct_ge70': pct(sum(1 for s in sc if s >= 70), len(G)),
        'pct_lt50': pct(sum(1 for s in sc if s < 50), len(G)),
        # (א) נגישות כלל האזור: הליכה מהנקודה הרחוקה לתחנה — דקות, ממוצע וחציון
        'far_mean': mean([p.get('ww') for p in G]), 'far_median': median([p.get('ww') for p in G]),
        'pct_far_over20': pct(sum(1 for p in G if p.get('ww') is None or p['ww'] > 20), len(G)),
        # (ב) תדירות שיא ממוצעת לכיוון — מרווח בדקות (420 דק׳ שיא / יציאות)
        'uf_headway_median': median([hw(p.get('pkd'), 420) for p in G if p.get('pkd')]),
        'pct_no_peak': pct(sum(1 for p in G if not p.get('pkd')), len(G)),
        # (ג) הקו החזק לכיוון בשיא הבוקר — מרווח בדקות
        'bl_headway_median': median([hw(p.get('bl1'), 180) for p in G if p.get('bl1')]),
        'pct_bl_le15': pct(sum(1 for p in G if p.get('bl1') and 180 / p['bl1'] <= 15), len(G)),
        'pct_bl_ge60': pct(sum(1 for p in G if not p.get('bl1') or 180 / p['bl1'] >= 60), len(G)),
        # מבחוץ: ציון משרד התחבורה
        'mot_mean': mean([p.get('sf') for p in G]), 'mot_n': sum(1 for p in G if p.get('sf') is not None),
        'walk_near_median': median([p.get('nearw') for p in G]),
    }


def load_sector():
    """תיוג מגזר משכבת משרד התחבורה (אם קיים). מחזיר {שם אזור מנורמל: ערך} או None."""
    f = ROOT / 'parks' / 'osm-check' / 'mot-zones.json'
    if not f.exists():
        return None, None
    d = json.load(open(f, encoding='utf-8'))
    items = d if isinstance(d, list) else (d.get('zones') or d.get('features') or [])
    key = None
    for it in items:
        props = it.get('properties', it) if isinstance(it, dict) else {}
        for k in props:
            if 'minor' in k.lower() or 'מגזר' in k or 'sector' in k.lower():
                key = k
                break
        if key:
            break
    if not key:
        return None, None
    out = {}
    for it in items:
        props = it.get('properties', it) if isinstance(it, dict) else {}
        nm = (props.get('name') or props.get('NAME') or props.get('shem') or '')
        if nm:
            out[norm(nm)] = props.get(key)
    return out, key


def norm(s):
    return (s or '').replace('"', '').replace("'", '').replace('״', '').replace('׳', '') \
        .replace('אזור תעשייה', '').replace('אזור תעשיה', '').replace('א"ת', '').replace('פארק', '').strip()


def build():
    P, Z = load()
    n = len(P)
    today = datetime.date.today().isoformat()
    # ── תמונת מצב ארצית ────────────────────────────────────────────────────
    sc = [p['score'] for p in P]
    bands = collections.OrderedDict((f'{t}', 0) for t, _ in SCALE)
    for s in sc:
        for t, _ in SCALE:
            if s >= t:
                bands[f'{t}'] += 1
                break
    tl = [{'label': lbl, 'n': sum(1 for s in sc if f(s)), 'color': c} for lbl, f, c in TL]
    for x in tl:
        x['pct'] = pct(x['n'], n)
    pk_all = sorted((p.get('pkd') or 0 for p in P), reverse=True)
    tot_pk = sum(pk_all) or 1
    no_line = sum(1 for p in P if not (p.get('lines') or 0))
    national = {
        'n': n, 'mean': mean(sc), 'median': median(sc),
        'bands': bands, 'traffic': tl,
        'no_line_n': no_line, 'no_line_pct': pct(no_line, n),
        'no_peak_n': sum(1 for p in P if not p.get('pkd')),
        'top10_share': pct(sum(pk_all[:round(n * .10)]), tot_pk),
        'top5_share': pct(sum(pk_all[:round(n * .05)]), tot_pk),
        'median_peak_departures': median([p.get('pkd') or 0 for p in P]),
        'stats': group_stats(P),
    }
    # ── קבוצות ─────────────────────────────────────────────────────────────
    C = [p for p in P if d_tlv(p) <= CENTER_KM]
    R = [p for p in P if d_tlv(p) > CENTER_KM]
    # מחוז רשמי (שכבת משרד התחבורה) לכל אזור; קו רוחב רק כגיבוי למי שלא נמצא
    find_d = load_districts()
    n_official = 0
    for p in P:
        d, mn = find_d(p) if find_d else (None, None)
        if d:
            n_official += 1
        p['_reg'] = d or {'צפון': 'צפון', 'מרכז': 'מרכז', 'דרום': 'דרום'}[region3(p)]
        p['_min'] = mn
    ORDER = ['צפון', 'מרכז', 'ירושלים ויו"ש', 'דרום']
    reg4 = {k: [p for p in P if p['_reg'] == k] for k in ORDER}
    reg4 = {k: v for k, v in reg4.items() if v}
    regions = {
        'center_periphery': {'מרכז': group_stats(C), 'פריפריה': group_stats(R)},
        'north_center_south': {k: group_stats(v) for k, v in reg4.items()},
        # הצלבה שאיריס ביקשה: פריפריה בצפון מול פריפריה בדרום
        'periphery_by_region': {k: group_stats([p for p in R if p['_reg'] == k]) for k in ('צפון', 'דרום') if any(p['_reg'] == k for p in R)},
        'defs': {'center_km': CENTER_KM, 'district_source': 'שכבת "תחום אזורי תעשיה תעסוקה" של משרד התחבורה — שדה המחוז',
                 'district_matched': n_official, 'fallback_lat': {'north': NORTH_LAT, 'south': SOUTH_LAT},
                 'groups': 'צפון = מחוזות צפון וחיפה · מרכז = מחוזות מרכז ותל אביב · ירושלים ויו"ש · דרום'},
    }
    # ── מגזר — עמודת MINORITY בשכבה הרשמית של משרד התחבורה ────────────────
    sector = None
    M = [p for p in P if p.get('_min')]
    if M:
        O = [p for p in P if not p.get('_min')]
        subs = collections.OrderedDict()
        for lbl, match in (('בדואים (צפון ודרום)', lambda v: 'בדואים' in v), ('דרוזים (כולל רמת הגולן)', lambda v: 'דרוזים' in v),
                           ('מיעוטים כללי', lambda v: v == 'מיעוטים כללי'), ('רשות מעורבת', lambda v: v == 'רשות מעורבת'),
                           ("צ'רקסים", lambda v: 'צרקסים' in v.replace("'", ''))):
            G = [p for p in M if match(p['_min'])]
            if G:
                subs[lbl] = group_stats(G)
        sector = {'source_field': 'MINORITY — שכבת "תחום אזורי תעשיה תעסוקה", משרד התחבורה',
                  'minority': group_stats(M), 'other': group_stats(O), 'subgroups': subs,
                  'values': dict(collections.Counter(p['_min'] for p in M))}
    # ── אשכול חברתי-כלכלי ──────────────────────────────────────────────────
    socio = None
    grp = {}
    try:
        S = json.load(open(DATA / 'socio.json', encoding='utf-8'))
        bc = S.get('by_city') or {}
        def cl(p):
            e = bc.get(p.get('city') or '')
            return e.get('c') if isinstance(e, dict) else None
        grp = {'אשכולות 1–3 (חלש)': [p for p in P if (cl(p) or 0) in (1, 2, 3)],
               'אשכולות 4–7 (בינוני)': [p for p in P if (cl(p) or 0) in (4, 5, 6, 7)],
               'אשכולות 8–10 (חזק)': [p for p in P if (cl(p) or 0) in (8, 9, 10)]}
        socio = {'year': S.get('year'), 'source': S.get('source'),
                 'groups': {k: group_stats(v) for k, v in grp.items() if v},
                 'unmatched': sum(1 for p in P if cl(p) is None)}
    except Exception:
        pass
    # ── עשירייה כפולה (סעיף 8) ─────────────────────────────────────────────
    def row(p):
        return {'name': p['name'], 'city': p.get('city') or '—', 'score': p['score'],
                'mot': (round(p['sf']) if p.get('sf') is not None else None),
                'motw': (round(p['sfw']) if p.get('sfw') is not None else None),   # הסובב — להקשר
                'bl_headway': (round(180 / p['bl1']) if p.get('bl1') else None),
                'far': (round(p['ww']) if p.get('ww') is not None else None), 'area': p.get('area'),
                'sparts': p.get('sparts')}
    big = [p for p in P if (p.get('area') or 0) >= 0.3]   # אזורים זעירים מסלפים (אלון שבות: 0.01 קמ"ר)
    top10 = [row(p) for p in sorted(big, key=lambda p: (-p['score'], -(p.get('pkd') or 0)))[:10]]
    # שוויון בין אזורי אפס נשבר לפי שטח — האזורים הריקים הגדולים קודם
    bottom10 = [row(p) for p in sorted(big, key=lambda p: (p['score'], -(p.get('area') or 0)))[:10]]
    # ── פערים בתוך אותה רשות (סעיף 9) ─────────────────────────────────────
    by_city = collections.defaultdict(list)
    for p in P:
        if p.get('city'):
            by_city[p['city']].append(p)
    gaps = []
    for city, zs in by_city.items():
        if len(zs) < 2:
            continue
        hi = max(zs, key=lambda p: p['score']); lo = min(zs, key=lambda p: p['score'])
        if hi['score'] - lo['score'] < 20:
            continue
        # הסבר: איזה רכיב פותח את הפער
        sh, sl = hi.get('sparts') or {}, lo.get('sparts') or {}
        diffs = {k: (sh.get(k, 0) - sl.get(k, 0)) * IRIS_W[k] for k in IRIS_W}
        main = max(diffs, key=diffs.get)
        why = {'bl': 'הקו החזק: ' + (f"כל ~{round(180/hi['bl1'])} דק׳" if hi.get('bl1') else 'אין') + ' מול ' + (f"כל ~{round(180/lo['bl1'])} דק׳" if lo.get('bl1') else 'אין קו בשיא'),
               'uf': 'התדירות הממוצעת בשיא: ' + (f"כל ~{round(420/hi['pkd'])} דק׳" if hi.get('pkd') else 'אין') + ' מול ' + (f"כל ~{round(420/lo['pkd'])} דק׳" if lo.get('pkd') else 'אין'),
               'far': 'הליכת העובד המרוחק: ' + (f"{round(hi['ww'])} דק׳" if hi.get('ww') is not None else '—') + ' מול ' + (f"{round(lo['ww'])} דק׳" if lo.get('ww') is not None else 'אין תחנות בטווח'),
               'near': 'הליכה ממרכז האזור: ' + (f"{round(hi['nearw'])} דק׳" if hi.get('nearw') is not None else '—') + ' מול ' + (f"{round(lo['nearw'])} דק׳" if lo.get('nearw') is not None else '—')}[main]
        gaps.append({'city': city, 'n': len(zs), 'hi': row(hi), 'lo': row(lo), 'gap': hi['score'] - lo['score'], 'why': why})
    gaps.sort(key=lambda g: -g['gap'])
    # בדיקת המבנים (OSM) — משמשת לרשימות ולסינון הדוגמאות
    try:
        bst = {z['name']: z for z in json.load(open(ROOT / 'parks/checks/built-status.json', encoding='utf-8'))['zones']}
    except Exception:
        bst = {}
    # ── דוגמאות (בקשת איריס 02.09, נקודות 8–11): שתי דוגמאות מכל סוג ─────────
    # הגרועים ביותר · המצטיינים · המצטיינים מחוץ למרכזי הערים (= הפריפריה, מעל
    # 45 ק"מ מתל אביב). אתרי פסולת ומחצבות אינם דוגמה ל"אזור תעשייה בלי שירות".
    NOT_EXAMPLE = re.compile(r'פסולת|מטמנ|מחצב|זיקוק')
    def enrich(p, kind, text):
        z = Z.get(p['f']) or {}
        st = z.get('stops') or []
        inside = []
        for s in st:
            if s.get('t') == 'in' and s.get('n') and s['n'] not in inside:
                inside.append(s['n'])
        return {**row(p), 'f': p['f'], 'la': p['la'], 'lo': p['lo'], 'kind': kind, 'text': text,
                'polys': z.get('polys'), 'stops': [{'la': s['la'], 'lo': s['lo'], 't': s.get('t'), 'n': s.get('n')} for s in st],
                'nearw': p.get('nearw'), 'ww': p.get('ww'), 'lines': p.get('lines'),
                'streets': inside[:4], 'region': p.get('_reg'), 'periphery': d_tlv(p) > CENTER_KM}
    def describe(p):
        bl = f"הקו החזק כל ~{round(180 / p['bl1'])} דק׳" if p.get('bl1') else 'אין אף קו בשיא הבוקר'
        far = f"העובד המרוחק הולך {round(p['ww'])} דק׳" if p.get('ww') is not None else 'אין תחנה בטווח 20 דקות הליכה'
        near = f"ממרכז האזור לתחנה {round(p['nearw'])} דק׳" if p.get('nearw') is not None else ''
        return f"{p.get('area')} קמ״ר, {p.get('lines') or 0} קווים. {bl}; {far}" + (f"; {near}" if near else '') + '.'
    cand = [p for p in big if not NOT_EXAMPLE.search(p['name'])]
    # "הגרועים ביותר" רק מאזורים שבדיקת המבנים מסמנת כבנויים בוודאות — כדי שלא להציג
    # כדוגמה אזור שאולי טרם אוכלס או שמיפויו חלקי (איריס 02.09: "בניכוי אלה שלא רלוונטיים")
    surely_built = lambda p: (bst.get(p['name']) or {}).get('st') == 'built'
    worst = sorted([p for p in cand if surely_built(p)], key=lambda p: (p['score'], -(p.get('area') or 0)))[:2]
    best = sorted(cand, key=lambda p: (-p['score'], -(p.get('pkd') or 0)))[:2]
    # "מחוץ למרכזי הערים": יותר מ-15 ק"מ מכל אחד מארבעת מרכזי המטרופולין
    # (15 ולא 12: הקריות של חיפה נמצאות 12–13 ק"מ ממרכז חיפה והן לב המטרופולין)
    CORES = [(32.08, 34.78, 'תל אביב'), (32.79, 34.99, 'חיפה'), (31.78, 35.22, 'ירושלים'), (31.25, 34.79, 'באר שבע')]
    def outside_cores(p):
        return all(math.hypot((p['la'] - la) * 110.5, (p['lo'] - lo) * 94.2) > 15 for la, lo, _ in CORES)
    best_out = sorted([p for p in cand if outside_cores(p) and p['f'] not in {q['f'] for q in best}],
                      key=lambda p: (-p['score'], -(p.get('pkd') or 0)))[:2]
    examples = [enrich(p, 'הגרועים ביותר', describe(p)) for p in worst] + \
               [enrich(p, 'המצטיינים', describe(p)) for p in best] + \
               [enrich(p, 'המצטיינים מחוץ למרכזי הערים', describe(p)) for p in best_out]
    outliers = []   # הוחלף בדוגמאות (איריס 02.09); נשאר כמפתח ריק לתאימות
    # ── רשימות מלאות (איריס 02.09, נקודה 2): בלי תחנה בטווח / בלי יציאה בשיא / הוצאו ─
    def lst(p):
        b = bst.get(p['name']) or {}
        return {'name': p['name'], 'city': p.get('city') or '—', 'area': p.get('area'), 'region': p.get('_reg'), 'score': p['score'],
                'lines': p.get('lines') or 0, 'far': (round(p['ww']) if p.get('ww') is not None else None),
                'buildings': b.get('bld'), 'stops_near': len((Z.get(p['f']) or {}).get('stops') or [])}
    no_stop_zones = [lst(p) for p in sorted(P, key=lambda p: -(p.get('area') or 0)) if p.get('ww') is None]
    no_peak_zones = [lst(p) for p in sorted(P, key=lambda p: -(p.get('area') or 0)) if not p.get('pkd')]
    excluded = {'manual': [], 'auto_n': 0, 'auto': []}
    try:
        excluded['manual'] = json.load(open(ROOT / 'parks/exclusions.json', encoding='utf-8')).get('zones') or []
    except Exception:
        pass
    # אוטומטית מוחרגים רק "טרם נבנה"; "בנוי חלקית" נשאר בדירוג (מיפוי חלקי ב-OSM, לא סטטוס בנייה)
    auto = [z for z in bst.values() if z.get('st') == 'planned']
    excluded['auto_n'] = len(auto)
    excluded['auto'] = [{'name': z['name'], 'city': z.get('city') or '—', 'area': z.get('area'), 'st': z['st'], 'bld': z.get('bld')}
                        for z in sorted(auto, key=lambda z: -(z.get('area') or 0))]
    partial = [z for z in bst.values() if z.get('st') == 'partial']
    excluded['partial_n'] = len(partial)
    excluded['partial_names'] = [z['name'] for z in sorted(partial, key=lambda z: -(z.get('area') or 0))]
    # ── פירוק הפער לרכיבים (שאלת איריס 02.09, נקודה 3: למה הפערים קטנים) ────
    def decomp(G):
        if not G:
            return None
        m = {k: mean([(p.get('sparts') or {}).get(k) for p in G]) for k in IRIS_W}
        return {'n': len(G), 'score_mean': mean([p['score'] for p in G]), 'comp': m,
                'weighted': {k: round((m[k] or 0) * IRIS_W[k], 1) for k in IRIS_W},
                'area_median': median([p.get('area') for p in G]),
                'pct_small': pct(sum(1 for p in G if (p.get('area') or 0) <= 0.3), len(G)),
                'bl_headway_median': median([hw(p.get('bl1'), 180) for p in G if p.get('bl1')]),
                'far_median': median([p.get('ww') for p in G]),
                'pct_no_bl': pct(sum(1 for p in G if not p.get('bl1')), len(G))}
    decomposition = collections.OrderedDict()
    decomposition['מרכז (עד 45 ק"מ)'] = decomp(C)
    decomposition['פריפריה'] = decomp(R)
    for k, v in reg4.items():
        decomposition[f'מחוז: {k}'] = decomp(v)
    if M:
        decomposition['ללא תיוג מגזרי'] = decomp([p for p in P if not p.get('_min')])
        bed = [p for p in M if 'בדואים' in (p['_min'] or '')]
        if bed:
            decomposition['בדואים'] = decomp(bed)
        gm = [p for p in M if p['_min'] == 'מיעוטים כללי']
        if gm:
            decomposition['מיעוטים כללי'] = decomp(gm)
    # ── התפלגויות לתרשימי העובדות המשלימות (איריס 02.09: "גם בגרפים") ──────
    def band_count(vals, bands, none_label):
        out = collections.OrderedDict((lbl, 0) for lbl, _ in bands)
        out[none_label] = 0
        for v in vals:
            if v is None:
                out[none_label] += 1
                continue
            for lbl, f in bands:
                if f(v):
                    out[lbl] += 1
                    break
        return out
    dist = {
        'far': band_count([p.get('ww') for p in P],
                          [('עד 5 דק׳', lambda v: v <= 5), ('5–10 דק׳', lambda v: v <= 10), ('10–15 דק׳', lambda v: v <= 15),
                           ('15–20 דק׳', lambda v: v <= 20), ('מעל 20 דק׳', lambda v: True)], 'אין תחנה בטווח'),
        'bl': band_count([hw(p.get('bl1'), 180) if p.get('bl1') else None for p in P],
                         [('עד 10 דק׳', lambda v: v <= 10), ('10–15', lambda v: v <= 15), ('15–21', lambda v: v <= 21), ('21–30', lambda v: v <= 30),
                          ('30–60', lambda v: v <= 60), ('60–90', lambda v: v <= 90), ('מעל 90', lambda v: True)], 'אין קו בשיא'),
        'concentration': [],
    }
    dec = max(1, round(n / 10))
    for i in range(10):
        chunk = pk_all[i * dec:(i + 1) * dec] if i < 9 else pk_all[9 * dec:]
        dist['concentration'].append({'label': f'עשירון {i + 1}', 'pct': pct(sum(chunk), tot_pk)})
    # ── פערים מול ציון משרד התחבורה (איריס 02.09, נקודה 12) ───────────────
    MOTF = collections.OrderedDict((('av', 'זמינות'), ('ac', 'נגישות'), ('co', 'תחרותיות'), ('re', 'אמינות')))
    def mot_row(p):
        sv = (Z.get(p['f']) or {}).get('svc') or {}
        sp_ = p.get('sparts') or {}
        return {**row(p), 'f': p['f'], 'gap': round(p['score'] - p['sf']), 'sub': {MOTF[k]: sv.get(k) for k in MOTF},
                'strong': [k for k in ('bl', 'uf', 'far', 'near') if (sp_.get(k) or 0) >= 80],
                'weak_mot': [MOTF[k] for k in MOTF if sv.get(k) is not None and sv[k] < 40]}
    # השוואה רק כשאזור סטטיסטי של המשרד יושב בתוך האזור (החלטת שלמה 02.09); לשאר יש רק "סובב" להקשר
    withmot = [p for p in P if p.get('sf') is not None]
    def named_row(p):
        r = mot_row(p) if p.get('sf') is not None else {**row(p), 'f': p['f'], 'gap': None, 'sub': {}, 'strong': [], 'weak_mot': []}
        r['direct'] = p.get('sf') is not None
        return r
    mot_gaps = {'fields': MOTF, 'rule': f'אזור סטטיסטי שלפחות {int(0.5 * 100)}% משטחו בתוך אזור התעשייה',
                'ours_high': [mot_row(p) for p in sorted(withmot, key=lambda p: -(p['score'] - p['sf']))[:8]],
                'mot_high': [mot_row(p) for p in sorted(withmot, key=lambda p: (p['score'] - p['sf']))[:8]],
                'named': [named_row(p) for p in P if any(k in p['name'] for k in ('צומת הקריות', 'גב ים', 'צור שלום'))],
                'n': len(withmot), 'n_wide_only': sum(1 for p in P if p.get('sf') is None and p.get('sfw') is not None), 'corr': None}
    try:
        mot_gaps['corr'] = round(statistics.correlation([p['score'] for p in withmot], [p['sf'] for p in withmot]), 2)
    except Exception:
        pass
    # ── פרק ציון משרד התחבורה (בקשת איריס 02.09): אותו ניתוח קבוצות, לפי המדד של המשרד ─
    # שני ערכים לכל אזור: "ישיר" — אזור סטטיסטי שיושב בתוך האזור (מעטים); "סובב" —
    # האזור הסטטיסטי שהאזור נמצא בו או חופף לו (כמעט לכולם). הניתוח הקבוצתי על הסובב,
    # כי זה מה שהמשרד אומר על השירות במקום; הישיר מוצג לידו.
    def mot_vals(p):
        sv = (Z.get(p['f']) or {}).get('svc') or {}
        if sv.get('mode') is None:                      # נתונים מלפני כלל ההשוואה הישירה
            return None, (sv if sv.get('fs') is not None else None)
        strict = sv if sv.get('mode') == 'inside' and sv.get('fs') is not None else None
        return strict, sv.get('wide')
    def mot_stats(G):
        vals = [mot_vals(p) for p in G]
        st = [s for s, _ in vals if s]
        wd = [w for _, w in vals if w and w.get('fs') is not None]
        return {'n': len(G), 'score_mean': mean([p['score'] for p in G]),
                'direct_n': len(st), 'direct_mean': mean([s['fs'] for s in st]),
                'wide_n': len(wd), 'wide_mean': mean([w['fs'] for w in wd]), 'wide_median': median([w['fs'] for w in wd]),
                'wide_lt30': pct(sum(1 for w in wd if w['fs'] < 30), len(wd)),
                'wide_ge60': pct(sum(1 for w in wd if w['fs'] >= 60), len(wd)),
                **{f'sub_{k}': mean([w.get(k) for w in wd]) for k in MOTF}}
    mot_groups = collections.OrderedDict()
    mot_groups['מרכז מול פריפריה'] = collections.OrderedDict([('מרכז', mot_stats(C)), ('פריפריה', mot_stats(R))])
    mot_groups['צפון, מרכז, ירושלים ויו"ש, דרום'] = collections.OrderedDict((k, mot_stats(v)) for k, v in reg4.items())
    per = collections.OrderedDict((k, mot_stats([p for p in R if p['_reg'] == k])) for k in ('צפון', 'דרום') if any(p['_reg'] == k for p in R))
    if len(per) >= 2:
        mot_groups['הפריפריה בצפון מול הפריפריה בדרום'] = per
    if M:
        mot_groups['החברה היהודית מול החברה הערבית והבדואית'] = collections.OrderedDict(
            [('מגזר מיעוטים (תיוג רשמי)', mot_stats(M)), ('כל שאר האזורים', mot_stats([p for p in P if not p.get('_min')]))])
        subs2 = collections.OrderedDict()
        for lbl, match in (('בדואים (צפון ודרום)', lambda v: 'בדואים' in v), ('דרוזים (כולל רמת הגולן)', lambda v: 'דרוזים' in v),
                           ('מיעוטים כללי', lambda v: v == 'מיעוטים כללי'), ('רשות מעורבת', lambda v: v == 'רשות מעורבת')):
            G = [p for p in M if match(p['_min'])]
            if G:
                subs2[lbl] = mot_stats(G)
        if subs2:
            mot_groups['בתוך המגזר המתויג'] = subs2
    if grp:
        mot_groups['לפי האשכול החברתי-כלכלי של הרשות'] = collections.OrderedDict((k, mot_stats(v)) for k, v in grp.items() if v)
    mot_chapter = {'groups': mot_groups, 'fields': MOTF,
                   'n_direct': sum(1 for p in P if mot_vals(p)[0]), 'n_wide': sum(1 for p in P if (mot_vals(p)[1] or {}).get('fs') is not None),
                   'national_wide_mean': mean([mot_vals(p)[1]['fs'] for p in P if (mot_vals(p)[1] or {}).get('fs') is not None])}
    # ── מקורות ותאריכים (סעיף 2) ───────────────────────────────────────────
    gen = next((Z[p['f']].get('gen') for p in P if Z.get(p['f'], {}).get('gen')), today)
    svc = json.load(open(ROOT / 'parks/checks/service-indices.json', encoding='utf-8'))
    def jdate(path, key):
        try:
            return json.load(open(ROOT / path, encoding='utf-8')).get(key)
        except Exception:
            return None
    sources = [
        {'what': 'מסלולי הקווים, התחנות ולוחות הזמנים', 'src': 'קובץ ה-GTFS הרשמי של משרד התחבורה והבטיחות בדרכים (gtfs.mot.gov.il)', 'date': gen, 'note': 'יום חול רגיל; קווי תלמידים ולילה מוחרגים'},
        {'what': 'גבולות אזורי התעשייה — הרשימה הרשמית', 'src': 'שכבת "תחום אזורי תעשיה תעסוקה", משרד התחבורה, data.gov.il', 'date': gen, 'note': 'נמשך מחדש בכל בנייה שבועית'},
        {'what': 'מפעלים, שטחים ומחוז', 'src': '"רשימת איזורי תעשייה", משרד הכלכלה והתעשייה, data.gov.il', 'date': gen, 'note': '29 אזורים מוצמדים'},
        {'what': 'ציון השירות של משרד התחבורה', 'src': svc.get('src'), 'date': svc.get('updated'), 'note': f"{len(svc.get('areas') or [])} אזורים סטטיסטיים; להשוואה נלקח רק אזור סטטיסטי שלפחות מחציתו בתוך אזור התעשייה — {len(withmot)} אזורים"},
        {'what': 'אימות קיום, מבנים וחלק מהגבולות', 'src': 'OpenStreetMap (ODbL)', 'date': jdate('parks/osm-check/osm-approved.json', 'generated'), 'note': 'פאנל אימות; 129 אזורים מאומתים'},
        {'what': 'זמני הליכה אמיתיים', 'src': 'OSRM על רשת OpenStreetMap, פרופיל הליכה מותאם (כבישים פרטיים ורמפות מותרים), 5 קמ״ש', 'date': gen, 'note': 'שומר גאומטרי לכשלי ניתוב'},
        {'what': 'סטטוס בנייה (אזורים בהקמה מוחרגים)', 'src': 'צפיפות מבנים ב-OSM', 'date': (jdate('parks/checks/built-status.json', 'checked') or '')[:10], 'note': ''},  # יום בלבד — השעה שם ב-UTC
        {'what': 'אשכול חברתי-כלכלי', 'src': (socio or {}).get('source') or 'למ"ס', 'date': str((socio or {}).get('year') or ''), 'note': ''},
    ]
    data = {
        'generated': datetime.datetime.now(zoneinfo.ZoneInfo('Asia/Jerusalem')).strftime('%d.%m.%Y %H:%M'), 'gtfs_date': gen,  # שעון ישראל
        'formula': {'headway_bands': IRIS_HEADWAY, 'walk_bands': IRIS_WALK, 'weights': IRIS_W, 'version': '02.09.2026',
                    'scale': SCALE, 'peak_am': '06:00–09:00 אל האזור', 'peak_pm': '15:00–19:00 מהאזור'},
        'national': national, 'regions': regions, 'sector': sector, 'socio': socio,
        'top10': top10, 'bottom10': bottom10, 'min_area_for_top': 0.3,
        'gaps_within_city': gaps[:10], 'outliers': outliers, 'examples': examples, 'sources': sources,
        'no_stop_zones': no_stop_zones, 'no_peak_zones': no_peak_zones, 'excluded': excluded,
        'decomposition': decomposition, 'dist': dist, 'mot_gaps': mot_gaps, 'mot_chapter': mot_chapter,
    }
    charts(data)
    json.dump(data, open(OUT / 'data.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"נכתב {OUT/'data.json'} · {n} אזורים · חציון {national['median']} · ירוק {tl[0]['pct']}% · "
          f"מגזר: {'יש' if sector else 'אין שדה'} · פערים בתוך רשות: {len(gaps)} · חריגים: {len(outliers)} · דוגמאות למפה: {len(examples)}")


# ── תרשימים ─────────────────────────────────────────────────────────────────
def _mpl_does_bidi():
    """matplotlib 3.11 ומעלה מסדר עברית ימין-לשמאל בעצמו; סידור נוסף הופך את הטקסט."""
    try:
        import matplotlib
        major, minor = (int(x) for x in matplotlib.__version__.split('.')[:2])
        return (major, minor) >= (3, 11)
    except Exception:
        return False


def he(s):
    """עברית ל-matplotlib: בגרסאות ישנות סידור ביצועי (bidi), בחדשות — כפי שהיא."""
    if _mpl_does_bidi():
        import re
        # קו מפריד בין מספרים (70–89) מתהפך בסידור של matplotlib ל-89–70; מקף רגיל נשאר בכיוון הנכון
        return re.sub(r'(?<=\d)–(?=\d)', '-', str(s))
    try:
        from bidi.algorithm import get_display
        return get_display(str(s))
    except Exception:
        return str(s)


def charts(data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.family'] = 'DejaVu Sans'
    plt.rcParams['font.size'] = 11

    def pie(items, title, fn):
        vals = [x['n'] for x in items]; labs = [f"{x['label']}\n{x['pct']}%" for x in items]; cols = [x['color'] for x in items]
        fig, ax = plt.subplots(figsize=(5.2, 4.2), dpi=180)
        w, t = ax.pie(vals, colors=cols, startangle=90, counterclock=False,
                      wedgeprops={'linewidth': 2, 'edgecolor': 'white'})
        # תוויות ישירות מחוץ לעוגה, בלי מקרא נפרד
        for wi, lab in zip(w, labs):
            ang = math.radians((wi.theta2 + wi.theta1) / 2)
            x, y = math.cos(ang), math.sin(ang)
            ax.annotate(he(lab), xy=(0.72 * x, 0.72 * y), xytext=(1.28 * x, 1.22 * y), ha='center', va='center',
                        fontsize=10, fontweight='bold', color='#0f172a',
                        arrowprops={'arrowstyle': '-', 'color': '#94a3b8', 'lw': 0.8})
        ax.set_title(he(title), fontsize=12.5, fontweight='bold', color='#043e7e', pad=14)
        ax.set_aspect('equal'); plt.tight_layout()
        fig.savefig(IMG / fn, facecolor='white'); plt.close(fig)

    pie(data['national']['traffic'], f"{data['national']['n']} אזורי תעשייה לפי הציון המשוקלל", 'pie-national.png')

    def bars(groups, metric, title, unit, fn, lower_better=False):
        names = list(groups); vals = [groups[g][metric] for g in names]
        fig, ax = plt.subplots(figsize=(6.2, 0.55 * len(names) + 1.4), dpi=180)
        y = range(len(names))
        ax.barh(list(y), [v or 0 for v in vals], height=0.5, color=BRAND, zorder=3)
        for i, v in enumerate(vals):
            ax.text((v or 0) + max(vals or [1]) * 0.015, i, he(f"{v}{unit}") if v is not None else he('אין נתון'),
                    va='center', ha='left', fontsize=10.5, fontweight='bold', color='#0f172a')
        ax.set_yticks(list(y)); ax.set_yticklabels([he(f"{g} ({groups[g]['n']})") for g in names], fontsize=10.5)
        ax.invert_yaxis(); ax.set_xlim(0, max([v or 0 for v in vals] + [1]) * 1.28)
        ax.set_title(he(title + (' (נמוך = טוב)' if lower_better else '')), fontsize=12, fontweight='bold', color='#043e7e', loc='right')
        for s in ('top', 'right', 'left'):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis='x', labelsize=9, colors='#64748b'); ax.grid(axis='x', color='#e2e8f0', zorder=0)
        plt.tight_layout(); fig.savefig(IMG / fn, facecolor='white'); plt.close(fig)

    cp = data['regions']['center_periphery']; ncs = data['regions']['north_center_south']
    for key, grp in (('cp', cp), ('ncs', ncs)):
        bars(grp, 'score_mean', 'הציון המשוקלל הממוצע', '', f'bar-{key}-score.png')
        bars(grp, 'far_median', 'הליכת העובד מהנקודה הרחוקה — חציון', ' דק׳', f'bar-{key}-far.png', True)
        bars(grp, 'uf_headway_median', 'מרווח ממוצע בין אוטובוסים בשיא — חציון', ' דק׳', f'bar-{key}-uf.png', True)
        bars(grp, 'bl_headway_median', 'מרווח הקו החזק בשיא הבוקר — חציון', ' דק׳', f'bar-{key}-bl.png', True)
        bars(grp, 'mot_mean', 'ציון השירות של משרד התחבורה — ממוצע', '', f'bar-{key}-mot.png')
    if data.get('sector'):
        sg = {'מגזר מיעוטים (תיוג רשמי)': data['sector']['minority'], 'כל שאר האזורים': data['sector']['other']}
        bars(sg, 'score_mean', 'הציון המשוקלל הממוצע', '', 'bar-sector-score.png')
        bars(sg, 'bl_headway_median', 'מרווח הקו החזק בשיא — חציון', ' דק׳', 'bar-sector-bl.png', True)
    if data.get('socio') and data['socio'].get('groups'):
        bars(data['socio']['groups'], 'score_mean', 'הציון המשוקלל לפי אשכול חברתי-כלכלי של הרשות', '', 'bar-socio-score.png')

    # העובדות המשלימות בתרשימים (איריס 02.09): התפלגויות וריכוזיות
    def hbar(labels, vals, title, fn, unit='', colors=None):
        fig, ax = plt.subplots(figsize=(6.2, 0.5 * len(labels) + 1.4), dpi=180)
        y = list(range(len(labels)))
        ax.barh(y, vals, height=0.55, color=colors or BRAND, zorder=3)
        top = max(vals + [1])
        for i, v in enumerate(vals):
            ax.text(v + top * 0.015, i, he(f'{v}{unit}'), va='center', ha='left', fontsize=10.5, fontweight='bold', color='#0f172a')
        ax.set_yticks(y); ax.set_yticklabels([he(l) for l in labels], fontsize=10.5)
        ax.invert_yaxis(); ax.set_xlim(0, top * 1.28)
        ax.set_title(he(title), fontsize=12, fontweight='bold', color='#043e7e', loc='right')
        for s in ('top', 'right', 'left'):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis='x', labelsize=9, colors='#64748b'); ax.grid(axis='x', color='#e2e8f0', zorder=0)
        plt.tight_layout(); fig.savefig(IMG / fn, facecolor='white'); plt.close(fig)

    # פרק ציון משרד התחבורה: הציון הסובב לפי קבוצה, וארבעת המדדים בעמודות מקובצות
    def grouped(groups, keys, labels, title, fn):
        names = [g for g in groups if groups[g].get('wide_n')]
        if not names:
            return
        fig, ax = plt.subplots(figsize=(6.4, 0.32 * len(names) * len(keys) + 1.6), dpi=180)
        pal = ['#32318e', '#5b21b6', '#0369a1', '#b45309']
        h = 0.8 / len(keys)
        for j, (k, lab) in enumerate(zip(keys, labels)):
            ys = [i + j * h for i in range(len(names))]
            vals = [groups[g].get(k) or 0 for g in names]
            ax.barh(ys, vals, height=h * 0.92, color=pal[j % len(pal)], zorder=3, label=he(lab))
            for y, v in zip(ys, vals):
                ax.text(v + 1, y, he(f'{v:.0f}'), va='center', ha='left', fontsize=8.5, color='#0f172a')
        ax.set_yticks([i + 0.4 - h / 2 for i in range(len(names))]); ax.set_yticklabels([he(f"{g} ({groups[g]['wide_n']})") for g in names], fontsize=10)
        ax.invert_yaxis(); ax.set_xlim(0, 100)
        ax.set_title(he(title), fontsize=12, fontweight='bold', color='#043e7e', loc='right')
        ax.legend(fontsize=8.5, loc='lower right', frameon=False)
        for s in ('top', 'right', 'left'):
            ax.spines[s].set_visible(False)
        ax.tick_params(axis='x', labelsize=9, colors='#64748b'); ax.grid(axis='x', color='#e2e8f0', zorder=0)
        plt.tight_layout(); fig.savefig(IMG / fn, facecolor='white'); plt.close(fig)

    MC = data.get('mot_chapter') or {}
    for i, (sect, groups) in enumerate((MC.get('groups') or {}).items()):
        gg = {g: {**s, 'n': s.get('wide_n') or 0} for g, s in groups.items() if s.get('wide_n')}
        if gg:
            bars(gg, 'wide_mean', f'ציון משרד התחבורה (האזור הסטטיסטי הסובב) — {sect}', '', f'bar-mot-{i}.png')
            grouped(groups, ['sub_av', 'sub_ac', 'sub_co', 'sub_re'], ['זמינות', 'נגישות', 'תחרותיות', 'אמינות'],
                    f'ארבעת מדדי המשרד — {sect}', f'bar-motsub-{i}.png')

    D = data.get('dist') or {}
    n_all = data['national']['n']
    if D.get('far'):
        hbar(list(D['far']), list(D['far'].values()), f'הליכת העובד מהנקודה הרחוקה — {n_all} אזורים', 'bar-far-dist.png', ' אזורים')
    if D.get('bl'):
        hbar(list(D['bl']), list(D['bl'].values()), 'מרווח הקו החזק בשיא הבוקר — אזורים לפי מדרגה', 'bar-bl-dist.png', ' אזורים')
    if D.get('concentration'):
        hbar([c['label'] for c in D['concentration']], [c['pct'] for c in D['concentration']],
             'ריכוזיות השירות: חלקו של כל עשירון אזורים ביציאות השיא', 'bar-concentration.png', '%')
    Nn = data['national']
    hbar(['בלי אף קו בטווח 20 דק׳ הליכה', 'בלי אף יציאה שימושית בשיא', 'הנקודה הרחוקה מעל 20 דק׳ או בלי תחנה'],
         [Nn['no_line_n'], Nn['no_peak_n'], round(Nn['stats']['pct_far_over20'] * n_all / 100)],
         f'אזורים בלי שירות — מתוך {n_all}', 'bar-noservice.png', ' אזורים', ['#c00d18', '#e63c14', '#ee7a16'])


if __name__ == '__main__':
    build()
