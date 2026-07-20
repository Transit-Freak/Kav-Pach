# -*- coding: utf-8 -*-
# זיהוי טעויות בתרגום-האנגלית של שמות תחנות (מ-translations.txt של GTFS משרד
# התחבורה). מזהה 4 סוגים בעזרת כללים (חינם, בלי AI):
#   format  — שגיאות כתיב/פורמט (רווח כפול, מקף תלוי, מספר נדבק, "??")
#   literal — שם-מקום שתורגם מילולית במקום תעתיק (נחל→River/Creek)
#   missing — חלק מהשם (מופרד ב-/) שנשמט באנגלית
#   wrong   — תרגום שגוי סמנטי (רשימה ידנית קטנה — לא ניתן לזיהוי בכללים)
# פלט: OUTFILE (translation-errors.json) עם קיבוץ לפי סוג + תחנות (קוד+עיר).
import csv, json, os, re

STOPS = os.environ.get('STOPS', 'stops.txt')
TRANS = os.environ.get('TRANS', 'translations.txt')
OUTFILE = os.environ.get('OUTFILE', 'translation-errors.json')
MANUAL = os.environ.get('MANUAL', 'tools/translation-errors-manual.json')  # ה"wrong" הסמנטיים

try:
    from spellchecker import SpellChecker
    _spell = SpellChecker()
    def _known(w): return bool(_spell.known([w]))
except Exception:
    def _known(w): return False   # בלי pyspellchecker — מדלגים על בדיקת-מילון

# ---- קריאת תרגומי EN ----
he2en = {}
with open(TRANS, encoding='utf-8-sig') as f:
    next(f, None)
    for line in f:
        line = line.rstrip('\n').rstrip('\r')
        j = line.find(',EN,')
        if j >= 0:
            he2en[line[:j]] = line[j + 4:]

def city_of(desc):
    i = (desc or '').find('עיר:')
    return desc[i + 4:].split('רציף:')[0].strip() if i >= 0 else ''

name2stops = {}
with open(STOPS, encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        n = (r.get('stop_name') or '').strip()
        if not n:
            continue
        d = name2stops.setdefault(n, {'codes': set(), 'cities': set()})
        if r.get('stop_code'):
            d['codes'].add(r['stop_code'])
        c = city_of(r.get('stop_desc', ''))
        if c:
            d['cities'].add(c)

def lev(a, b):
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return 2
    dp = list(range(lb + 1))
    for i in range(1, la + 1):
        prev = dp[0]; dp[0] = i
        for k in range(1, lb + 1):
            cur = dp[k]; dp[k] = min(dp[k] + 1, dp[k - 1] + 1, prev + (a[i - 1] != b[k - 1])); prev = cur
    return dp[lb]

SPELL = set("""international industrial southern northern eastern western auditorium junction
interchange commercial central university cemetery entrance stadium hospital terminal municipal
observatory promenade boulevard community settlement regional national building station parking
college memorial monument roundabout""".split())
SEP = re.compile(r'\s*[/–—]\s*|\s*,\s*|\s+-\s+')
def parts(s): return [p for p in SEP.split(s) if p.strip()]
LIT_HE = re.compile(r'\bנחל\b')
LIT_EN = re.compile(r'\b(River|Creek|Stream|Brook)\b')

def classify(he, en):
    if '  ' in en: return 'format', 'רווח כפול בתרגום'
    if '??' in en: return 'format', 'סימן "??" בתרגום'
    if re.search(r'(^|[ ])[-/]|[-/]([ ]|$)|/\s*/|-\s*-', en): return 'format', 'מקף/לוכסן תלוי או כפול'
    if re.search(r'[A-Za-z]\d|\d[A-Za-z]', en) and not re.search(r'\b[A-Z]\d\b', en): return 'format', 'מספר נדבק למילה'
    if LIT_HE.search(he) and LIT_EN.search(en): return 'literal', 'נחל תורגם ל-River/Creek במקום תעתיק "Nahal"'
    if len(parts(he)) > len(parts(en)) and len(parts(he)) >= 2: return 'missing', 'חלק מהשם (מופרד ב-/) חסר באנגלית'
    for w in re.findall(r'[A-Za-z]+', en):
        wl = w.lower()
        if len(wl) < 7 or wl in SPELL or _known(wl):
            continue
        for e in SPELL:
            if abs(len(e) - len(wl)) <= 1 and lev(wl, e) == 1:
                return 'format', 'שגיאת כתיב: "%s" (צ״ל %s)' % (w, e.capitalize())
    return None, None

errors = []
seen = set()
for n in sorted(name2stops):
    en = he2en.get(n)
    if not en or en == n:
        continue
    cat, issue = classify(n, en)
    if cat:
        st = name2stops[n]
        errors.append({'he': n, 'en': en, 'category': cat, 'issue': issue,
                       'stops': [{'c': c} for c in sorted(st['codes'])][:20],
                       'cities': sorted(st['cities'])[:8]})
        seen.add(n)

# ---- מיזוג ה"wrong" הסמנטיים (רשימה ידנית, לפי שם עברי) ----
if os.path.exists(MANUAL):
    for m in json.load(open(MANUAL, encoding='utf-8')):
        n = m.get('he')
        if n in name2stops and he2en.get(n) == m.get('en') and n not in seen:
            st = name2stops[n]
            errors.append({'he': n, 'en': m['en'], 'category': 'wrong', 'issue': m['issue'],
                           'stops': [{'c': c} for c in sorted(st['codes'])][:20],
                           'cities': sorted(st['cities'])[:8]})
            seen.add(n)

order = {'wrong': 0, 'missing': 1, 'literal': 2, 'format': 3}
errors.sort(key=lambda e: (order.get(e['category'], 9), e['he']))
by = {}
for e in errors:
    by[e['category']] = by.get(e['category'], 0) + 1
import datetime
out = {'generated': datetime.date.today().isoformat(), 'count': len(errors),
       'byCategory': by, 'errors': errors}
json.dump(out, open(OUTFILE, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('טעויות תרגום:', len(errors), '| לפי סוג:', by, '->', OUTFILE)
