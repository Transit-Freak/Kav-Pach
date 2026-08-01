# -*- coding: utf-8 -*-
# "הקו בזמן" — אילו קווים עצרו בתחנה בתקופת האירוע (בקשת המשתמש), בלי אף
# קריאת רשת: מרכיבים אינדקס מרווחי-זמן מרצפי התחנות שכבר נאספו (הצינור
# היומי + שלב ב' + העוגנים), ולכל אירוע תחנה (ביטול/שינוי שם/הזזה)
# מחשבים מי הכיל אותה אז. השאילתה הישירה לשרת ("קווים לפי תחנה") מתעלמת
# בשקט מהפרמטר — לכן החישוב המקומי הוא הדרך האמינה היחידה.
# רץ בכל לילה; ככל שנאספים עוד רצפים הרשימות מתעדכנות ומתרחבות לבד.
import json, os, datetime

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
CAP = 15   # תקרת קווים מוצגת לאירוע

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

def day_before(d):
    return (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()

# ---- אינדקס: קוד תחנה -> [(מתאריך, עד תאריך, מס' קו)] ----
iv = {}
n_files = 0
for fn in os.listdir(f'{OUTDIR}/lines'):
    if not fn.endswith('.json'): continue
    lf = jload(f'{OUTDIR}/lines/{fn}', {})
    vs = lf.get('versions', [])
    line = lf.get('line') or ''
    if not line or not vs: continue
    n_files += 1
    cur_codes = None
    cur_from = None
    for v in vs:
        if v.get('k') == 'removed':
            if cur_codes is not None:
                for c in cur_codes:
                    iv.setdefault(c, []).append((cur_from, v['d'], line))
                cur_codes = None
            continue
        st = v.get('stops') or []
        if not st: continue
        codes = {str(s[0]) for s in st}
        if cur_codes is not None and codes != cur_codes:
            for c in cur_codes:
                iv.setdefault(c, []).append((cur_from, v['d'], line))
        if cur_codes is None or codes != cur_codes:
            cur_codes = codes
            cur_from = v['d']
    if cur_codes is not None:
        for c in cur_codes:
            iv.setdefault(c, []).append((cur_from, '9999-12-31', line))

print(f'אינדקס מרווחים: {len(iv)} תחנות מ-{n_files} קבצים')

def lines_at(code, d):
    out = set()
    for (a, b, ln) in iv.get(str(code), []):
        if a <= d < b: out.add(ln)
    def key(x):
        n = ''.join(ch for ch in x if ch.isdigit())
        return (int(n) if n else 10**9, x)
    return sorted(out, key=key)[:CAP]

# ---- העשרת האירועים: קורות-החיים + קובצי החודש ----
shist = jload(f'{OUTDIR}/stops-hist.json', {})
cur_reg = jload(f'{OUTDIR}/stops-state.json', {})   # [שם, lat, lon, עיר, קווים]
months = {}
def mload(m):
    if m not in months:
        months[m] = jload(f'{OUTDIR}/changes/stops-{m}.json', None)
    return months[m]

def sync_month(c, e, fields):
    mm = mload(e['d'][:7])
    if mm:
        for x in mm['changes']:
            if x.get('c') == c and x.get('k') == e['k'] and x.get('d') == e['d']:
                x.update(fields)

# עיר לתחנות שאינן ברישום הנוכחי (המבוטלות — שהכי חשוב למצוא בחיפוש):
# לפי התחנה הקרובה ביותר ברישום, עד 300 מ' (תחנה תפעולית/כרמי גת 12741)
import math
grid = {}
CELL = 0.005
for c, v in cur_reg.items():
    if len(v) > 3 and v[3]:
        grid.setdefault((int(v[1] / CELL), int(v[2] / CELL)), []).append((v[1], v[2], v[3]))

def city_near(la, lo):
    if la is None or lo is None: return ''
    gy, gx = int(la / CELL), int(lo / CELL)
    best, bestd = '', 300.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for (y, x, ct) in grid.get((gy + dy, gx + dx), []):
                cl = math.cos(math.radians(la))
                d = math.hypot((la - y) * 110540, (lo - x) * 111320 * cl)
                if d < bestd: bestd, best = d, ct
    return best

n_set = n_city = 0
for c, evs in shist.items():
    # שדה העיר — מהרישום הנוכחי; בלעדיו אי-אפשר לחפש תחנות לפי עיר
    # (תחנות קרית גת "נעלמו" מהחיפוש כי t היה ריק בכל האירועים)
    if c in cur_reg and len(cur_reg[c]) > 3:
        city = cur_reg[c][3]
    else:
        e0 = next((e for e in evs if e.get('la') is not None), None)
        city = city_near(e0.get('la'), e0.get('lo')) if e0 else ''
    for e in evs:
        if city and (e.get('t') or '') != city:
            e['t'] = city
            sync_month(c, e, {'t': city})
            n_city += 1
        if e.get('k') not in ('del', 'renamed', 'moved'): continue
        q = day_before(e['d']) if e['k'] == 'del' else e['d']
        lns = lines_at(c, q)
        if lns == (e.get('lines') or []): continue
        # אין כיסוי-רצפים לתקופה — לא דורסים רשימה קיימת: היא מולאה מעוגני
        # הארכיון (enrich_stop_lines_archive.py). הלילה של 01.08 מחק ככה
        # 3,437 רשימות שמולאו יום קודם.
        if not lns: continue
        e['lines'] = lns
        n_set += 1
        sync_month(c, e, {'lines': lns})

json.dump(shist, open(f'{OUTDIR}/stops-hist.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
for m, mm in months.items():
    if mm is not None:
        json.dump(mm, open(f'{OUTDIR}/changes/stops-{m}.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'רשימות קווים עודכנו ל-{n_set} אירועים | שדה עיר מולא ב-{n_city} אירועים')
