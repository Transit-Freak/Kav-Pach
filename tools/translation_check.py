# -*- coding: utf-8 -*-
# זיהוי טעויות בתרגום-האנגלית של שמות תחנות (מ-translations.txt של GTFS משרד
# התחבורה). מזהה 4 סוגים בעזרת כללים (חינם, בלי AI):
#   format  — שגיאות כתיב/פורמט (רווח כפול, מקף תלוי, מספר נדבק, "??")
#   literal — שם-מקום שתורגם מילולית במקום תעתיק (נחל→River/Creek)
#   missing — חלק מהשם (מופרד ב-/) שנשמט באנגלית
#   wrong   — תרגום שגוי סמנטי (רשימה ידנית קטנה — לא ניתן לזיהוי בכללים)
# כל טעות כוללת גם enHe — תעתיק של התרגום-האנגלי לאותיות עבריות ("איך זה
# נשמע באנגלית"), כדי שמי שלא קורא אנגלית יבין מיד למה התרגום שגוי.
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

# ---- תעתיק של התרגום-האנגלי לאותיות עבריות: "איך זה נשמע באנגלית" ----
# מטרה: מי שלא קורא אנגלית יראה איך התרגום נשמע (She Uziyahu -> "שי אוזייהו")
# ויבין מיד למה הוא שגוי. מילון למילים אנגליות שחוזרות + כללי-תעתיק לשמות מתועתקים.
_EN_WORD = {
  'creek':'קריק','road':'רוד','center':'סנטר','centre':'סנטר','river':'ריבר',
  'junction':'ג׳אנקשן','station':'סטיישן','boulevard':'בולווארד','blvd':'בולווארד',
  'train':'טריין','platforms':'פלטפורמס','platform':'פלטפורם','exit':'אקזיט',
  'school':'סקול','west':'ווסט','east':'איסט','north':'נורת׳','south':'סאות׳',
  'camp':'קמפ','mount':'מאונט','mt':'מאונט','central':'סנטרל','institute':'אינסטיטיוט',
  'to':'טו','high':'היי','terminal':'טרמינל','roundabout':'ראונדאבאוט','rounabout':'ראונדאבאוט',
  'bus':'באס','floor':'פלור','base':'בייס','college':'קולג׳','city':'סיטי',
  'intersection':'אינטרסקשן','reserve':'ריזרב','cemetary':'סמטרי','cemetery':'סמטרי',
  'hall':'הול','commercial':'קומרשל','police':'פוליס','policing':'פוליסינג','hotel':'הוטל',
  'synagogue':'סינגוג','stadium':'סטדיום','parking':'פארקינג','hill':'היל','arena':'ארנה',
  'sports':'ספורטס','sport':'ספורט','food':'פוד','directories':'דיירקטוריס',
  'construction':'קונסטרקשן','infrastruction':'אינפרהסטרקשן','engineering':'אינג׳ינירינג',
  'containers':'קונטיינרס','container':'קונטיינר','brigade':'בריגייד','jewish':'ג׳ואיש',
  'ammunition':'אמוניישן','girl':'גירל','mr':'מיסטר','internazional':'אינטרנציונל',
  'international':'אינטרנציונל','she':'שי','he':'הי','the':'דה','of':'אוף','and':'אנד',
  'new':'ניו','old':'אולד','lake':'לייק','park':'פארק','beach':'ביץ׳','square':'סקוור',
  'university':'יוניברסיטי','hospital':'הוספיטל','airport':'אירפורט','gate':'גייט',
  'bridge':'ברידג׳','tower':'טאואר','museum':'מיוזיאום','market':'מרקט','factory':'פקטורי',
  'kibbutz':'קיבוץ','kibuts':'קיבוץ','moshav':'מושב','industrial':'אינדסטריאל',
  'mall':'מול','kfar':'כפר','kiryat':'קריית','derech':'דרך','beit':'בית','bet':'בית',
}
_DIG = [
  ('tch','צ׳'),('sch','ש'),('sh','ש'),('ch','ח'),('th','ת'),('ph','פ'),
  ('ck','ק'),('kh','ח'),('tz','צ'),('ts','צ'),('gh','ג'),('wh','ו'),('qu','קוו'),
  ('ee','י'),('oo','ו'),('ou','או'),('ow','או'),('ai','יי'),('ay','יי'),
  ('ei','יי'),('ey','יי'),('au','או'),('aw','או'),('oa','או'),('oi','וי'),('oy','וי'),
]
_CON = {'b':'ב','d':'ד','f':'פ','g':'ג','h':'ה','j':'ג׳','k':'ק','l':'ל',
        'm':'מ','n':'נ','p':'פ','q':'ק','r':'ר','s':'ס','t':'ט','v':'ב','w':'ו',
        'x':'קס','z':'ז'}
_V_START = {'a':'א','e':'א','i':'אי','o':'או','u':'או'}
_V_MID   = {'a':'', 'e':'', 'i':'י', 'o':'ו', 'u':'ו'}
_V_END   = {'a':'ה','e':'', 'i':'י', 'o':'ו', 'u':'ו'}
_SOFIT = {'מ':'ם','נ':'ן','צ':'ץ','פ':'ף','כ':'ך'}

def _translit_word(w):
    if w in _EN_WORD:
        return _EN_WORD[w]
    w = re.sub(r'(.)\1+', r'\1', w)   # אותיות כפולות -> בודדת (Sammy->Sami)
    out, i, n = [], 0, len(w)
    while i < n:
        for d, h in _DIG:
            if w.startswith(d, i):
                out.append(h); i += len(d); break
        else:
            ch = w[i]
            if ch in _V_MID:
                out.append(_V_START[ch] if i == 0 else _V_END[ch] if i == n - 1 else _V_MID[ch])
            elif ch == 'y':
                out.append('י')
            elif ch == 'c':
                out.append('ס' if i + 1 < n and w[i + 1] in 'eiy' else 'ק')
            elif ch in _CON:
                out.append(_CON[ch])
            i += 1
    s = ''.join(out)
    return s[:-1] + _SOFIT[s[-1]] if s and s[-1] in _SOFIT else s

def translit_en_he(s):
    parts = re.split(r'([A-Za-z]+)', s or '')
    return ''.join(_translit_word(p.lower()) if p.isalpha() else p for p in parts).strip()

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
        errors.append({'he': n, 'en': en, 'enHe': translit_en_he(en), 'category': cat, 'issue': issue,
                       'stops': [{'c': c} for c in sorted(st['codes'])][:20],
                       'cities': sorted(st['cities'])[:8]})
        seen.add(n)

# ---- מיזוג ה"wrong" הסמנטיים (רשימה ידנית, לפי שם עברי) ----
if os.path.exists(MANUAL):
    for m in json.load(open(MANUAL, encoding='utf-8')):
        n = m.get('he')
        if n in name2stops and he2en.get(n) == m.get('en') and n not in seen:
            st = name2stops[n]
            errors.append({'he': n, 'en': m['en'], 'enHe': translit_en_he(m['en']), 'category': 'wrong', 'issue': m['issue'],
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
