# -*- coding: utf-8 -*-
# סיווג אזורי התעשייה-תעסוקה לפי סוג, וסינון מה שאינו מקום עבודה.
# הכלל (בקשת המשתמש): בטבלה נשארים רק מקומות שאנשים באמת נוסעים אליהם
# לעבודה. מתקן אוטומטי כמו מאגר מים או תחנת שאיבה — החוצה; מכרה, נמל
# ומע"ר — נשארים, עם תיוג שמבדיל אותם מאזור תעשייה קלאסי.
#
# הסוגים: ind = תעשייה קלאסית · emp = תעסוקה/משרדים/מסחר ·
#         infra = תשתית (נמל, זיקוק, תעופה...)
# אתרי כרייה וחציבה הוסרו כליל מהאתר (בקשת המשתמש, 31.07.2026).
#
# חריגים פר-אזור (שם ← סוג/שם עברי/הוצאה) יושבים ב-parks/zone-types.json.
import json, os, re

OVERRIDES_PATH = os.environ.get('ZONE_TYPES', 'parks/zone-types.json')

# תווי כיווניות בשמות מ-OSM (LRM/RLM וכו') שוברים השוואת-שמות
_BIDI = dict.fromkeys(map(ord, '‎‏‪‫‬؜'))
def norm(s): return ' '.join((s or '').translate(_BIDI).split())

# הסדר קובע: הראשון שתופס מנצח
_RULES = [
    ('exclude', r'^שכונת |טיהור שפכים|מט"ש|מט״ש|תחנת שאיבה|מאגר מים|כפר הנוער|מחצב|מכרות|כריי|פוספטים|מפעלי ים המלח'),
    ('infra',   r'^נמל |נמל אשדוד|נמל חיפה|זיקוק|שדה תעופה|התעופה|תע"ש|תע״ש|חח"ן|חח״ן|פסולת|מחזור|ממ"ג|ממ״ג|תחנת כוח'),
    ('emp',     r'מע"ר|מע״ר|עסקים|תעסוקה|משרדים|מרכז אזורי|מת"מ|מת״מ|טכנולוגי|פארק המדע|עתידים|ותמל|ותמ"ל|תמ"ל|מסחר'),
]

_EXCLUDE_REASONS = {
    'שכונת': 'שכונת מגורים — לא יעד נסיעה לעבודה',
    'כפר הנוער': 'מוסד חינוכי — לא אזור תעסוקה',
    'מחצב': 'אתר כרייה וחציבה — הוסר מהאתר',
    'מכרות': 'אתר כרייה וחציבה — הוסר מהאתר',
    'כריי': 'אתר כרייה וחציבה — הוסר מהאתר',
    'פוספטים': 'אתר כרייה וחציבה — הוסר מהאתר',
    'ים המלח': 'אתר כרייה וחציבה — הוסר מהאתר',
}

def _load_overrides():
    try:
        return json.load(open(OVERRIDES_PATH, encoding='utf-8')).get('overrides', [])
    except Exception:
        return []
_ov = None

def classify(name):
    """מחזיר dict: zt (ind/emp/infra/mine), ואופציונלית rename או exclude."""
    global _ov
    if _ov is None: _ov = _load_overrides()
    n = norm(name)
    out = {'zt': 'ind'}
    for o in _ov:
        if norm(o.get('match')) == n:
            if o.get('exclude'): return {'zt': 'ind', 'exclude': o['exclude']}
            if o.get('rename'):
                out['rename'] = o['rename']
                n = norm(o['rename'])
            if o.get('zt'): out['zt'] = o['zt']; return out
            break
    for zt, pat in _RULES:
        if re.search(pat, n):
            if zt == 'exclude':
                reason = next((r for k, r in _EXCLUDE_REASONS.items() if k in n),
                              'לא מקום עבודה')
                return {'zt': 'ind', 'exclude': reason}
            out['zt'] = zt
            return out
    return out
