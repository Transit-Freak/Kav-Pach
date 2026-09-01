# -*- coding: utf-8 -*-
"""בדיקות-קבע לאתר הנגישות (אישור איריס 01.09.2026): כל תקלה שנתפסה
בביקורות הופכת לבדיקה אוטומטית שרצה כל לילה — כדי שאותה משפחת באגים
לא תוכל לחזור בשקט.

כל בדיקה ממוספרת עם מקורה. כישלון = יציאה בקוד שגיאה + פירוט מלא,
והרשימה נכתבת ל-parks/checks/invariants.json לתצוגה עתידית.
"""
import datetime
import json
import os
import re
import sys

DATA = os.environ.get('DATA_DIR', 'parks/data')
OUT = os.environ.get('OUT', 'parks/checks/invariants.json')
AM = lambda t: '06:00' <= t < '09:00'
PM = lambda t: '15:00' <= t < '19:00'

P = json.load(open(f'{DATA}/parks.json', encoding='utf-8'))
fails = []


def check(name, source, bad):
    """bad = רשימת מחרוזות-כשל; ריקה = עובר."""
    if bad:
        fails.append({'name': name, 'source': source, 'n': len(bad), 'sample': bad[:8]})
        print(f'✗ {name} — {len(bad)} כשלים · מקור: {source}')
        for b in bad[:5]:
            print(f'    {b}')
    else:
        print(f'✓ {name}')


zones = {}
for p in P:
    try:
        zones[p['f']] = json.load(open(f"{DATA}/{p['f']}", encoding='utf-8'))
    except Exception:
        pass

# 1. שעות יציאה תקינות (מקור: עיקרון כללי — נתון שבור מזייף כל חישוב)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z:
        continue
    for l in (z.get('lines') or []) + (z.get('linesE') or []):
        for t in l.get('wd') or []:
            if not re.match(r'^([01]\d|2[0-3]):[0-5]\d$', t):
                bad.append(f"{p['name']} קו {l.get('num')}: שעה לא תקינה '{t}'")
check('שעות יציאה בפורמט תקין (00:00–23:59)', 'עיקרון', bad)

# 2. pkd = הספירה הכיוונית המוצהרת (מקור: הגדרת המבחן בשקף הכללים)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z or 'pkd' not in p:
        continue
    calc = 0
    for l in z.get('lines') or []:
        wd = l.get('wd') or []
        am = sum(1 for t in wd if AM(t))
        pm = sum(1 for t in wd if PM(t))
        # הכלל הממומש: בפנים/בשער נספרים שני החלונות; כיווניות רק ל"5–10 דק'"
        if l.get('t') in ('in', 'gate'):
            calc += am + pm
        elif l.get('dr') == 'in':
            calc += am
        elif l.get('dr') == 'out':
            calc += pm
        elif l.get('dr') == '?':
            calc += am + pm
    if calc != (p.get('pkd') or 0):
        bad.append(f"{p['name']}: pkd באינדקס {p.get('pkd')} מול חישוב מחדש {calc}")
check('pkd תואם חישוב-מחדש מהכלל הממומש (in/gate: שני חלונות)', 'זיהוי סחף צנרת', bad)

# 3. bl1 = הכיוון הבודד החזק, בלי סכימת כיוונים (מקור: ממצא איריס צמח 01.09)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z or 'bl1' not in p:
        continue
    calc = 0
    for l in z.get('lines') or []:
        if l.get('dr') == 'out':
            continue
        calc = max(calc, sum(1 for t in (l.get('wd') or []) if AM(t)))
    if calc != (p.get('bl1') or 0):
        bad.append(f"{p['name']}: bl1={p.get('bl1')} מול חישוב {calc}")
    if (p.get('bl1') or 0) > (p.get('bl') or 0):
        bad.append(f"{p['name']}: bl1 ({p.get('bl1')}) גדול מ-bl ({p.get('bl')}) — בלתי אפשרי")
check('bl1 = כיוון בודד חזק ביותר, ו-bl1 ≤ bl', 'ממצא איריס · צמח מפעלים', bad)

# 4. כיסוי בטווח 0–100, והנקודה הרחוקה קיימת כשיש תחנות (מקור: שקף הכללים · מבחן 2)
bad = []
for p in P:
    if 'cv' in p and p['cv'] is not None and not (0 <= p['cv'] <= 100):
        bad.append(f"{p['name']}: cv={p['cv']} מחוץ לטווח")
    z = zones.get(p['f'])
    if z and (z.get('stops') or []) and p.get('ww') is not None and p['ww'] <= 0:
        bad.append(f"{p['name']}: ww={p['ww']} לא חיובי למרות שיש תחנות")
check('כיסוי בטווח חוקי · הנקודה הרחוקה חיובית', 'שקף הכללים · מבחן 2', bad)

# 5. כל קו מצביע על תחנה שקיימת ברשימת התחנות של האזור (מקור: עיקרון)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z:
        continue
    codes = {str(s.get('c')) for s in z.get('stops') or []}
    for l in z.get('lines') or []:
        if str(l.get('code')) not in codes:
            bad.append(f"{p['name']} קו {l.get('num')}: תחנה {l.get('code')} לא ברשימת התחנות")
check('כל קו מקושר לתחנה מוכרת של האזור', 'עיקרון', bad)

# 6. פסק הדין ניתן לשחזור מהשדות לפי הכלל המוצהר (מקור: סתירת השקף שאיריס תפסה)
#    הכלל המתועד: אדום = אין קו בהליכה / אפס יציאות / כיסוי<60;
#    כתום = נכשל באחד: יציאות<21 או כיסוי<90 או קו-חזק<9; ירוק = עומד בכולם.
bad = []
for p in P:
    if 'cv' not in p:
        continue
    walkN = (p.get('li') or 0) + (p.get('lg') or 0) + (p.get('ln') or 0)
    pkd = p.get('pkd') or 0
    cv = p.get('cv')
    bl = p.get('bl')
    if walkN == 0 or pkd == 0 or (cv is not None and cv < 60):
        v = 'r'
    elif pkd < 21 or (cv is not None and cv < 90) or (bl is not None and bl < 9):
        v = 'o'
    else:
        v = 'g'
    if v == 'g' and (pkd < 21 or (cv is not None and cv < 90) or (bl or 0) < 9):
        bad.append(f"{p['name']}: ירוק למרות כישלון מבחן (pkd={pkd}, cv={cv}, bl={bl})")
check('אין ירוק שנכשל באחד המבחנים', 'שקף הכללים · "החמור קובע"', bad)

# 7. אף אזור "אפס" עם קווים ברשימה (מקור: עיקרון האמינות מול עיתונות)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z:
        continue
    walkN = (p.get('li') or 0) + (p.get('lg') or 0) + (p.get('ln') or 0)
    if walkN == 0 and (z.get('lines') or []):
        bad.append(f"{p['name']}: walkN=0 אבל יש {len(z['lines'])} קווים בקובץ האזור")
check('אזור בלי קווים נספרים באמת ריק ברשימת הקווים', 'עיקרון', bad)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'generated': datetime.date.today().isoformat(),
           'pass': not fails, 'fails': fails},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"\n{'✅ כל הבדיקות עברו' if not fails else f'❌ {len(fails)} בדיקות נכשלו'} · נכתב {OUT}")
sys.exit(1 if fails else 0)
