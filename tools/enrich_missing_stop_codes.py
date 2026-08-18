#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""השלמת מק"טים לרשימות ➕/➖ שהאתר לא מצליח לפענח מתוך קובץ הקו.

הבעיה (דיווח המשתמש, קו 393): תחנה שירדה בגרסה הראשונה של קו בארכיון
לא מופיעה באף רשימת תחנות בקובץ — הצילום שהיא שייכת אליו לא נשמר —
ולכן הממשק מציג אותה בלי מק"ט, בעוד שלתחנה שנוספה יש.

הפתרון, בלי שום ניחוש לפי שם בלבד (יש בארץ 4 תחנות "הרצל/ויצמן"!):
1. משפחת הרישיון — אם השם קיים בקובצי החלופות/כיוונים של אותו מק"ט קו
   ומופה שם למק"ט תחנה אחד ויחיד, זו התחנה (אותו מסלול משפחתי).
2. ייחודיות ארצית — אם השם מופה למק"ט אחד ויחיד בכל קובצי הקווים
   שבמאגר, אין מקום לבלבול.
שם שנשאר דו-משמעי — נשאר בלי מק"ט. עדיף חוסר מניחוש.

התוצאה נשמרת על הגרסה כמפה v['nc'] = {שם: מק"ט}; הממשק בודק אותה
לפני החיפוש הרגיל. אידמפוטנטי — מחשב את nc מחדש בכל ריצה.
"""
import glob
import json
import os
import sys


def stop_names(lf):
    """שם -> קבוצת מק"טים מתוך מאגר התחנות של הקובץ (או הגרסאות בישן)."""
    out = {}
    pool = lf.get('pool') or []
    src = pool if pool else [s for v in lf.get('versions') or []
                             for s in v.get('stops') or []]
    for s in src:
        if isinstance(s, list) and len(s) >= 2:
            out.setdefault(s[1], set()).add(str(s[0]))
    return out


def main():
    outdir = os.environ.get('OUTDIR', 'line-history/data')
    files = sorted(glob.glob(f'{outdir}/lines/*.json'))
    fam_map, nat_map, per_file = {}, {}, {}
    for p in files:
        try:
            lf = json.load(open(p, encoding='utf-8'))
        except Exception as e:
            print(f'{p}: קובץ בעייתי — {e}', file=sys.stderr)
            continue
        names = stop_names(lf)
        per_file[p] = (lf, names)
        fam = os.path.basename(p).split('-')[0]
        f = fam_map.setdefault(fam, {})
        for nm, cs in names.items():
            f.setdefault(nm, set()).update(cs)
            nat_map.setdefault(nm, set()).update(cs)

    n_res = n_left = n_files = 0
    for p, (lf, names) in per_file.items():
        fam = fam_map[os.path.basename(p).split('-')[0]]
        changed = False
        for v in lf.get('versions') or []:
            # ערכים קיימים נשמרים — backfill_rem_codes כותב מק"טים מדויקים
            # מצילומי הארכיון, וההיסק כאן רק ממלא חורים שנותרו
            nc = {k: c for k, c in (v.get('nc') or {}).items()
                  if k in set((v.get('rem') or []) + (v.get('add') or []))}
            for nm in (v.get('rem') or []) + (v.get('add') or []):
                if nm in names or nm in nc:
                    continue        # הממשק מוצא לבד בתוך הקובץ / כבר פתור
                cs = fam.get(nm) or set()
                if len(cs) != 1:
                    cs = nat_map.get(nm) or set()
                if len(cs) == 1:
                    nc[nm] = next(iter(cs))
                    n_res += 1
                else:
                    n_left += 1
            if nc != (v.get('nc') or {}):
                if nc:
                    v['nc'] = nc
                else:
                    v.pop('nc', None)
                changed = True
        if changed:
            json.dump(lf, open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            n_files += 1
    print(f'השלמת מק"טים: {n_res} שמות פוענחו, {n_left} נשארו דו-משמעיים, '
          f'{n_files} קבצים עודכנו')


if __name__ == '__main__':
    main()
