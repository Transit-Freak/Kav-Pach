# -*- coding: utf-8 -*-
"""השלמת מק"טים לרשימות ➕/➖ של כל הארכיון — לפי מספר, לא לפי שם.

עד 25.08.2026 הצנרת שמרה על אירועי שינוי רק את שמות התחנות שנוספו/ירדו,
והאתר שחזר את המספר בחיפוש הפוך לפי שם — שנשבר בשם כפול, בשם שהשתנה
ובמק"ט שהוחלף. דרישת שלמה: לעבור על הכל ולתקן — הזיהוי לפי מספר תחנה,
והשם רק תצוגה.

לכל גרסה עם ➕/➖ בלי ac/rc מלאים: ההפרש האמיתי בין רצף התחנות של הגרסה
לרצף של הגרסה-עם-תחנות שלפניה נותן את קבוצות המק"טים המדויקות. כל שם
מקבל מספר רק ממקור ודאי, לפי הסדר: שם-בתוך-קבוצת-ההפרש, הפענוח הקיים
מצילומי הארכיון (v.nc), מק"ט חשוף שנשמר כשם, וזיווג-הפרש כשנשאר בדיוק
זוג אחד. שם שלא נפתר בוודאות נשאר null — האתר ממשיך אליו בדרך הישנה,
וריצה חוזרת משלימה אותו כשנפתח מידע חדש (למשל אחרי backfill_new_routes,
שנותן מסלול לרשומות קיום-בלבד ופותח את ההפרש לגרסאות שאחריהן).

הכלי אידמפוטנטי: ac/rc קיימים ומלאים לא נגעים; null-ים מנסים שוב.
DRY=1 ניתוח בלבד.
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'


def resolve(names, pool, restrict, nc, seed):
    """מספר לכל שם ברשימה. pool = רשומות התחנות לחיפוש (בסדר המסלול),
    restrict = קבוצת המק"טים שבאמת השתנו (None = לא ידוע), nc = פענוח
    קיים, seed = ac/rc קיימים (ערכים שכבר נקבעו נשמרים)."""
    out = [str(seed[i]) if seed and i < len(seed) and seed[i] is not None else None
           for i in range(len(names))]
    used = {c for c in out if c}
    # שלב 1: שם מדויק בתוך קבוצת-ההפרש (או שם חד-משמעי כשאין הפרש ידוע)
    for ix, n in enumerate(names):
        if out[ix]:
            continue
        cands = [str(s[0]) for s in pool
                 if s[1] == n and str(s[0]) not in used
                 and (restrict is None or str(s[0]) in restrict)]
        if restrict is None and len({str(s[0]) for s in pool if s[1] == n}) != 1:
            continue                     # בלי הפרש ידוע — רק שם חד-משמעי
        if cands:
            out[ix] = cands[0]
            used.add(cands[0])
    # שלב 2: הפענוח מצילומי הארכיון (v.nc)
    for ix, n in enumerate(names):
        if out[ix]:
            continue
        e = (nc or {}).get(n)
        c = str(e[0]) if isinstance(e, list) else (str(e) if e else None)
        if c and c not in used:
            out[ix] = c
            used.add(c)
    # שלב 3: מק"ט חשוף שנשמר בתור השם
    for ix, n in enumerate(names):
        if out[ix] is None and re.fullmatch(r'\d{3,}', n or ''):
            out[ix] = n
            used.add(n)
    # שלב 4: זיווג-הפרש — בדיוק שם אחד בלי מספר מול מק"ט אחד שלא נתבע.
    # לא מופעל כשהרשימה קוצצה ל-15 (אז ההפרש המלא גדול מהרשימה)
    if restrict is not None and len(names) < 15:
        free = sorted(restrict - used)
        blank = [ix for ix, v in enumerate(out) if v is None]
        if len(free) == 1 and len(blank) == 1:
            out[blank[0]] = free[0]
    return out


def main():
    files = sorted(glob.glob(f'{OUTDIR}/lines/*.json'))
    n_v = n_full = n_part = n_codes = n_blank = 0
    n_files = 0
    for p in files:
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = sorted(lf.get('versions') or [], key=lambda v: v.get('d', ''))
        prevS = None
        dirty = False
        for v in vs:
            add, rem = v.get('add') or [], v.get('rem') or []
            curS = v.get('stops') or None
            if add or rem:
                n_v += 1
                ac0, rc0 = v.get('ac'), v.get('rc')
                need_a = add and (not ac0 or any(c is None for c in ac0))
                need_r = rem and (not rc0 or any(c is None for c in rc0))
                if need_a or need_r:
                    cur_codes = {str(s[0]) for s in curS} if curS else None
                    prev_codes = {str(s[0]) for s in prevS} if prevS else None
                    r_add = (cur_codes - prev_codes) if (cur_codes and prev_codes) else None
                    r_rem = (prev_codes - cur_codes) if (cur_codes and prev_codes) else None
                    nc = v.get('nc')
                    if need_a:
                        ac = resolve(add, curS or [], r_add, nc, ac0)
                        if any(c is not None for c in ac) and ac != ac0:
                            v['ac'] = ac
                            dirty = True
                    if need_r:
                        rc = resolve(rem, prevS or [], r_rem, nc, rc0)
                        if any(c is not None for c in rc) and rc != rc0:
                            v['rc'] = rc
                            dirty = True
                ac1, rc1 = v.get('ac') or [], v.get('rc') or []
                got = [c for c in list(ac1) + list(rc1) if c is not None]
                blanks = (len(add) - len([c for c in ac1 if c is not None])) + \
                         (len(rem) - len([c for c in rc1 if c is not None]))
                n_codes += len(got)
                n_blank += blanks
                if blanks == 0:
                    n_full += 1
                elif got:
                    n_part += 1
            if curS:
                prevS = curS
        if dirty and not DRY:
            lf['versions'] = vs
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            n_files += 1
    print(f'גרסאות עם ➕/➖: {n_v} · נפתרו במלואן: {n_full} · חלקית: {n_part}'
          f' · מק"טים שנקבעו: {n_codes} · שמות שנותרו בלי מספר ודאי: {n_blank}'
          f' · קבצים שנכתבו: {n_files}' + (' · (DRY)' if DRY else ''))


if __name__ == '__main__':
    main()
