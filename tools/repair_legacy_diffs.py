# -*- coding: utf-8 -*-
"""תיקון רשומות ➕/➖ ישנות בהיסטוריית הקווים — שאלת שלמה 02.09 (קו 391-א):
"קריית מחקר גרעינית" הופיעה כתחנה ש"ירדה" גם ב-01.07.2025 (נכון: הקיץ ההוא
ירדה) וגם ב-01.07.2026 (שגוי: ההבדל האמיתי מול 2025 היה רק החלפת מק"ט של
תחנת אילת). הרשומה של 2026 נשאה שם בלי מק"ט (rc=None) — צורה שאף כותב
נוכחי אינו מייצר. אלה שאריות של גרסת כותב ישנה.

הכלל: בגרסה שיש לה רשימת תחנות וגם רשימת ➕/➖ שבה מק"ט חסר, הרשימות
מחושבות מחדש מההפרש בין רשימת התחנות שלה לרשימת התחנות המתועדת שלפניה —
כמו ב-backfill_new_routes.enrich_diffs. רשימות התחנות הן מקור האמת, וזה גם
מה שהאתר מצייר כ"המסלול הקודם". רשומות עם מק"טים מלאים לא נוגעים כאן.
גם רשומת השינוי במקבץ החודשי (data/changes/YYYY-MM.json) מתעדכנת בהתאם.

    python3 tools/repair_legacy_diffs.py            # יבש: סופר ומדגים
    python3 tools/repair_legacy_diffs.py --apply    # כותב
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize, compact  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
APPLY = '--apply' in sys.argv
ALL = '--all' in sys.argv      # לא רק רשומות בלי מק"ט — כל רשומה שסותרת את ההפרש בין הרשימות
LIMIT = 15


def diff(prev_stops, cur_stops):
    pc = {str(s[0]) for s in prev_stops}
    cc = {str(s[0]) for s in cur_stops}
    add = [s for s in cur_stops if str(s[0]) not in pc]
    rem = [s for s in prev_stops if str(s[0]) not in cc]
    return add, rem


def main():
    files = sorted(glob.glob(f'{OUTDIR}/lines/*.json'))
    n_ver = n_fixed = n_cleared = 0
    months = {}          # חודש → (נתיב, json, dirty)
    examples = []
    log = []
    for p in files:
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = sorted(lf.get('versions') or [], key=lambda v: v.get('d', ''))
        prev = None
        dirty = False
        for v in vs:
            st = v.get('stops') or []
            if not st:
                continue
            rem, rc = v.get('rem') or [], v.get('rc') or []
            add, ac = v.get('add') or [], v.get('ac') or []
            legacy = (rem and (len(rc) < len(rem) or any(c is None for c in rc))) or \
                     (add and (len(ac) < len(add) or any(c is None for c in ac)))
            # --all (שלמה 02.09): הכלל מחייב בכל רשומה שמצהירה על שינוי — תחנה יכולה
            # "לרדת" רק אם הייתה במצב המתועד הקודם, ו"להתווסף" רק אם לא הייתה בו.
            # מה שאינו נובע מההפרש בין שתי הרשימות אינו שינוי, לא משנה איזה בסיס
            # השוואה השתמש בו כותב ישן. רשומות בלי הצהרה על שינוי לא מקבלות אחת.
            inconsistent = False
            # מק"טים בלי שמות (rc בלי rem, ac בלי add) — שארית של כותב שאסף מק"טים
            # של כל מה שירד אי-פעם; באתר לא נראה, אבל סותר את הכלל ומבלבל ביקורת
            if ALL and prev is not None and ((rc and not rem) or (ac and not add)):
                inconsistent = True
            if ALL and prev is not None and (rem or add):
                a2, r2 = diff(prev['stops'], st)
                inconsistent = ({str(c) for c in rc if c} != {str(s[0]) for s in r2}) or \
                               ({str(c) for c in ac if c} != {str(s[0]) for s in a2})
            if (legacy or inconsistent) and prev is not None:
                n_ver += 1
                a2, r2 = diff(prev['stops'], st)
                old = {'rem': rem, 'rc': rc, 'add': add, 'ac': ac}
                for k in ('add', 'ac', 'rem', 'rc'):
                    v.pop(k, None)
                if a2:
                    v['add'] = [s[1] for s in a2][:LIMIT]
                    v['ac'] = [str(s[0]) for s in a2][:LIMIT]
                if r2:
                    v['rem'] = [s[1] for s in r2][:LIMIT]
                    v['rc'] = [str(s[0]) for s in r2][:LIMIT]
                if not a2 and not r2:
                    n_cleared += 1
                n_fixed += 1
                dirty = True
                if len(examples) < 6:
                    examples.append((os.path.basename(p), v['d'], v.get('k'), old['rem'], '→', v.get('rem')))
                # יומן ביקורת: כל רשומה שנגענו בה, לפני ואחרי — כדי שאפשר לבדוק ולהחזיר
                log.append({'file': os.path.basename(p), 'rd': lf.get('rd'), 'd': v['d'], 'k': v.get('k'),
                            'prev_d': prev.get('d'), 'old': old,
                            'new': {k: v.get(k) for k in ('add', 'ac', 'rem', 'rc') if v.get(k)}})
                # רשומת השינוי החודשית — אותו אירוע, אותן רשימות
                mon = v['d'][:7]
                if mon not in months:
                    mp = f'{OUTDIR}/changes/{mon}.json'
                    try:
                        months[mon] = [mp, json.load(open(mp, encoding='utf-8')), False]
                    except Exception:
                        months[mon] = [mp, None, False]
                mm = months[mon][1]
                if mm:
                    for ch in mm.get('changes') or []:
                        if ch.get('rd') == lf.get('rd') and ch.get('d') == v['d'] and ('rem' in ch or 'add' in ch):
                            ch.pop('rem', None); ch.pop('add', None)
                            if v.get('add'):
                                ch['add'] = v['add']
                            if v.get('rem'):
                                ch['rem'] = v['rem']
                            months[mon][2] = True
            prev = v
        if dirty and APPLY:
            lf['versions'] = vs
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    if APPLY:
        for mon, (mp, mm, d) in months.items():
            if mm and d:
                json.dump(mm, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        import datetime
        json.dump({'ran': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'), 'rule': __doc__.strip().split('\n')[0], 'n': len(log), 'items': log},
                  open(f'{OUTDIR}/repair-legacy-diffs.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f"גרסאות עם רשימת ➕/➖ ישנה (מק\"ט חסר): {n_ver} · חושבו מחדש: {n_fixed} · מהן בלי שינוי אמיתי (הרשימה נמחקה): {n_cleared}"
          f" · קובצי חודש שעודכנו: {sum(1 for x in months.values() if x[2])} · {'נכתב' if APPLY else 'יבש'}")
    for e in examples:
        print('  ', e)


if __name__ == '__main__':
    main()
