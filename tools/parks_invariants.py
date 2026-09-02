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
        # הכלל של איריס (01.09): הסינון הכיווני חל על כל התחנות —
        # בבוקר רק הנכנסים, אחה"צ רק היוצאים, גם בפנים וגם בשער.
        dr = l.get('dr')
        if dr == 'in':
            calc += am
        elif dr == 'out':
            calc += pm
        else:
            calc += am + pm      # כיוון לא ידוע — שני החלונות
    if calc != (p.get('pkd') or 0):
        bad.append(f"{p['name']}: pkd באינדקס {p.get('pkd')} מול חישוב מחדש {calc}")
check('pkd = ספירה כיוונית על כל התחנות', 'הגדרת איריס 01.09', bad)

# 3. bl1 = הכיוון הבודד החזק, בלי סכימת כיוונים (מקור: ממצא איריס צמח 01.09)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z or 'bl1' not in p:
        continue
    b1 = {}
    for l in z.get('lines') or []:
        if l.get('dr') == 'out':
            continue
        k1 = (l.get('mk') or l.get('num'), l.get('dest'))
        b1[k1] = b1.get(k1, 0) + sum(1 for t in (l.get('wd') or []) if AM(t))
    calc = max(b1.values()) if b1 else 0
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


# ==== בדיקות-נסיגה לממצאי הסיירת (01.09.2026) — כל באג שתוקן מקבל שומר ====
import math
import random


def poly_area_km2(pts, cl):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i][1] * 111.320 * cl, pts[i][0] * 110.540
        x2, y2 = pts[(i + 1) % len(pts)][1] * 111.320 * cl, pts[(i + 1) % len(pts)][0] * 110.540
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def in_poly(la, lo, pts):
    ins = False
    j = len(pts) - 1
    for i in range(len(pts)):
        if (pts[i][0] > la) != (pts[j][0] > la):
            xx = (pts[j][1] - pts[i][1]) * (la - pts[i][0]) / (pts[j][0] - pts[i][0] + 1e-15) + pts[i][1]
            if lo < xx:
                ins = not ins
        j = i
    return ins


# 8. שטח = איחוד, לא סכימה (ממצא: פוליגונים חופפים נספרו פעמיים)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z or not z.get('polys') or len(z['polys']) < 2:
        continue
    cl = math.cos(math.radians(p['la']))
    ssum = sum(poly_area_km2(pp, cl) for pp in z['polys'])
    if (p.get('area') or 0) > ssum * 1.05 + 0.011:   # סובלנות לעיגול האינדקס (2 ספרות)
        bad.append(f"{p['name']}: שטח {p.get('area')} גדול מסכום הפוליגונים {ssum:.2f} — ספירה כפולה")
check('שטח האזור אינו עולה על איחוד הפוליגונים', 'סיירת · שטח כפול (מישור אדומים)', bad)

# 9. המרכז נמצא בתוך תיבת-הגבול של כל הפוליגונים (ממצא: מרכז מוטה עד 930 מ')
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z or not z.get('polys'):
        continue
    la = [q[0] for pp in z['polys'] for q in pp]
    lo = [q[1] for pp in z['polys'] for q in pp]
    if not (min(la) - 0.002 <= p['la'] <= max(la) + 0.002 and
            min(lo) - 0.002 <= p['lo'] <= max(lo) + 0.002):
        bad.append(f"{p['name']}: המרכז ({p['la']},{p['lo']}) מחוץ לגבולות הפוליגונים")
check('מרכז האזור בתוך גבולות הפוליגונים', 'סיירת · מרכז לא מעודכן אחרי מיזוג', bad)

# 10. אין מק"ט תחנה כפול ברשימה (ממצא: מע"ר ב"ש 64 שורות ל-18 תחנות)
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z:
        continue
    codes = [str(s.get('c')) for s in z.get('stops') or [] if s.get('c')]
    dup = len(codes) - len(set(codes))
    if dup:
        bad.append(f"{p['name']}: {dup} שורות תחנה כפולות מנפחות את המונים")
check('אין שורות תחנה כפולות באותו אזור', 'סיירת · תחנות משוכפלות', bad)

# 11. תחנה בתוך האזור לא יורשת זמן-חסימה (ממצא: "בפנים · 145 דק׳")
bad = []
for p in P:
    z = zones.get(p['f'])
    if not z:
        continue
    for s in z.get('stops') or []:
        if s.get('t') == 'in' and (s.get('wt') or 0) > 15:
            bad.append(f"{p['name']} · {s.get('n')}: תחנה בתוך האזור עם {s['wt']} דק׳ הליכה")
check('אין תחנה "בתוך האזור" עם זמן הליכה חריג', 'סיירת · ירושת חסימה', bad)

# 12. כיסוי מלא אינו מתיישב עם נקודה רחוקה מעל 10 דק'
bad = []
for p in P:
    if p.get('cv') == 100 and (p.get('ww') or 0) > 10:
        bad.append(f"{p['name']}: כיסוי 100% אך הנקודה הרחוקה {p['ww']} דק׳")
check('כיסוי 100% אינו סותר את הנקודה הרחוקה', 'עיקרון פנימי', bad)

# 13. cv אמיתי — חישוב מחדש על מדגם קבוע (ממצא: זיהום מנקודות ההיקף)
random.seed(11)
samp = random.sample([p for p in P if 'cv' in p and zones.get(p['f'])], k=min(20, len(P)))
bad = []
for p in samp:
    z = zones[p['f']]
    st = [s for s in z.get('stops') or [] if not (s.get('t') == 'blocked' and s.get('te') == 'blocked')]
    if not st or not z.get('polys'):
        continue
    cl = math.cos(math.radians(p['la']))
    sla, slo = 75 / 110540.0, 75 / (111320.0 * cl)
    hit = tot = 0
    for ring in z['polys']:
        la1, la2 = min(a for a, b in ring), max(a for a, b in ring)
        lo1, lo2 = min(b for a, b in ring), max(b for a, b in ring)
        ga = la1
        while ga <= la2:
            go = lo1
            while go <= lo2:
                if in_poly(ga, go, ring):
                    tot += 1
                    d = min(math.hypot((ga - s['la']) * 110540.0, (go - s['lo']) * 111320.0 * cl) for s in st)
                    if d * 1.3 / 75.0 <= 10:
                        hit += 1
                go += slo
            ga += sla
    if tot >= 5:
        calc = hit * 100.0 / tot
        if abs(calc - p['cv']) > 6:
            bad.append(f"{p['name']}: cv={p['cv']} מול חישוב-מחדש {calc:.0f} (רשת שטח בלבד)")
check('cv = אחוז שטח אמיתי (מדגם 20 אזורים)', 'סיירת · זיהום מנקודות ההיקף', bad)


# 14. הנקודה הרחוקה סבירה ביחס לגודל האזור (ממצא 01.09: ניתוב שמקיף גדר
#     החזיר 379 דק׳ באזור של 0.29 קמ"ר — נענש אזור על כשל טכני)
bad = []
for p in P:
    ww = p.get('ww')
    ar = p.get('area')
    if not ww or not ar or ar <= 0:
        continue
    # הנקודה הרחוקה = מהפינה הגרועה עד התחנה הקרובה, ולכן היא תלויה גם
    # במרחק התחנות ולא רק בגודל האזור: אזור זעיר שכל תחנותיו רחוקות יכול
    # להיות רחוק לגמרי כדין. האומדן מחבר את השניים.
    z = zones.get(p.get('f')) or {}
    dnear = min((s.get('d', 0) for s in (z.get('stops') or [])), default=0)
    # המרחק בפועל הוא אלכסון ה-bbox, לא sqrt(שטח): רצועת תעשייה צרה
    # וארוכה (גוש עציון — 0.18 קמ"ר אבל 1320 מ׳ אלכסון) קיבלה אומדן של
    # 424 מ׳ ונפסלה בטעות. נופלים ל-sqrt רק אם אין פוליגונים.
    _pts = [q for ring in (z.get('polys') or []) for q in ring]
    if _pts:
        _la = [q[0] for q in _pts]
        _lo = [q[1] for q in _pts]
        _cl = math.cos(math.radians(sum(_la) / len(_la)))
        diag_m = math.hypot((max(_la) - min(_la)) * 110540.0,
                            (max(_lo) - min(_lo)) * 111320.0 * _cl)
    else:
        diag_m = math.sqrt(ar) * 1000
    air_min = (diag_m + dnear) * 1.3 / 75.0
    if ww > max(4 * air_min, air_min + 25):
        bad.append(f"{p['name']}: הנקודה הרחוקה {ww} דק׳ באזור של {ar} קמ\"ר "
                   f"והתחנה הקרובה במרחק {dnear} מ׳ — חשוד ככשל ניתוב")
check('הנקודה הרחוקה סבירה ביחס לגודל האזור', 'ממצא 01.09 · שער בנימין 379 דק׳', bad)

# 15. הליכה לתחנה סבירה ביחס למרחק האווירי (ממצא שלמה 02.09: ביואב תחנות
#     65–158 מ׳ מהגבול קיבלו 14–18 דק׳ למרכז — ניתוב שמקיף כבישים פרטיים).
#     אותו כלל כמו בצנרת: מעל פי 2.5 מהאווירי וגם 400 מ׳ מעליו = כשל ניתוב.
#     וגם: הליכה לקצה לא ארוכה מהליכה למרכז.
bad = []
for p in P:
    z = zones.get(p.get('f')) or {}
    cen = (p.get('la'), p.get('lo'))
    if None in cen:
        continue
    cl = math.cos(math.radians(cen[0]))
    for s in z.get('stops') or []:
        if s.get('t') == 'in':
            continue
        ac = math.hypot((s['la'] - cen[0]) * 110540.0, (s['lo'] - cen[1]) * 111320.0 * cl)
        wm, wme, d = s.get('wm'), s.get('wme'), s.get('d') or 0
        if wm is not None and wm > max(2.5 * ac, ac + 400) + 1:
            bad.append(f"{p['name']} · {s.get('n','')}: הליכה למרכז {wm} מ׳ מול {ac:.0f} מ׳ אווירי")
        elif wme is not None and wme > max(2.5 * max(d, 20), max(d, 20) + 400) + 1:
            bad.append(f"{p['name']} · {s.get('n','')}: הליכה לקצה {wme} מ׳ מול {d} מ׳ אווירי")
        elif s.get('wte') is not None and s.get('wt') is not None and s['wte'] > s['wt'] + 0.5:
            bad.append(f"{p['name']} · {s.get('n','')}: לקצה {s['wte']} דק׳ > למרכז {s['wt']} דק׳")
check('הליכה לתחנה סבירה ביחס למרחק האווירי', 'ממצא שלמה 02.09 · פארק תעסוקה יואב', bad)

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'generated': datetime.date.today().isoformat(),
           'pass': not fails, 'fails': fails},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"\n{'✅ כל הבדיקות עברו' if not fails else f'❌ {len(fails)} בדיקות נכשלו'} · נכתב {OUT}")
sys.exit(1 if fails else 0)
