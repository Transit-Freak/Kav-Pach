#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""דחיסת קובצי הקווים — מאגר תחנות ומסלולים פר-קובץ (בקשת המשתמש).

הבעיה: כל גרסה שמרה מחדש את רשימת התחנות המלאה (שם+קואורדינטות לכל
תחנה) גם כששינוי נגע בתחנה אחת — ‏59MB תחנות שמתוכם ‏32MB כפילויות.

הפתרון — הפניות במקום העתקים, והמפה נראית אותו דבר:
- lf['pool']  = רשימת תחנות ייחודיות; version['stops'] הופך לרשימת אינדקסים.
- lf['spool'] = מסלולים (polyline) ייחודיים; version['shp'] הופך לאינדקס.
  אינדקס 0 שמור לריק — אינדקס אמיתי תמיד ≥1, כך שבדיקות-אמת קיימות
  (any(v.get('shp'))) ממשיכות לעבוד.
- צילום-ארכיון בלי גאומטריה שרצף-התחנות שלו זהה לגרסה שאחריו מקבל
  הפניה למסלול שלה (shpref=1) — האתר מציג מסלול אמיתי במקום קו מקורב.

הפורמט תאום-לאחור: materialize() פותח גם קבצים ישנים (מחרוזות inline)
וגם חדשים; כלים שכותבים גרסאות חדשות ממשיכים לכתוב inline, והדחיסה
היומית מאחדת אותן פנימה בריצה הבאה.

שימוש כספרייה:  from compact_lines import materialize, compact
שימוש ככלי:     python3 tools/compact_lines.py   (OUTDIR, LIMIT)
"""
import glob
import json
import os
import sys


def materialize(lf):
    """פותח קובץ קו לצורה מלאה (הפניות → תוכן). אידמפוטנטי ובטוח לישן."""
    if not lf:
        return lf
    pool = lf.pop('pool', None)
    spool = lf.pop('spool', None)
    for v in lf.get('versions') or []:
        st = v.get('stops')
        if pool is not None and isinstance(st, list) and st:
            v['stops'] = [pool[i] if isinstance(i, int) else i for i in st]
        s = v.get('shp')
        if isinstance(s, int):
            v['shp'] = spool[s] if spool and 0 < s < len(spool) else ''
    return lf


def _codes(stops):
    return [s[0] for s in stops]


def compact(lf):
    """דוחס קובץ קו: מאגרי תחנות/מסלולים + שדרוג צילומים לרצף זהה."""
    lf = materialize(lf)
    vs = lf.get('versions') or []

    # השאלת שרטוט: גרסה בלי גאומטריה (מילוי מארכיון הסדנא, שאינו מחזיר
    # מסלולים) מקבלת את השרטוט של כל גרסה אחרת — מוקדמת או מאוחרת — שרצף
    # התחנות שלה זהה: אותן תחנות באותו סדר ⇒ אותו מסלול. עדיפות לקרובה
    # בזמן. בלי זה קווים שלמים הוצגו במפה כנקודות בלבד.
    for i, v in enumerate(vs):
        if v.get('shp') or not v.get('stops'):
            continue
        codes = _codes(v['stops'])
        donor = None
        for dist in range(1, len(vs)):
            for j in (i + dist, i - dist):
                if 0 <= j < len(vs):
                    w = vs[j]
                    if w.get('shp') and w.get('stops') and not w.get('shpref') \
                            and _codes(w['stops']) == codes:
                        donor = w
                        break
            if donor:
                break
        if donor:
            v['shp'] = donor['shp']
            v['shpref'] = 1

    pool, pidx = [], {}
    spool, sidx = [''], {}
    for v in vs:
        st = v.get('stops')
        if isinstance(st, list) and st:
            idxs = []
            for x in st:
                k = json.dumps(x, ensure_ascii=False, separators=(',', ':'))
                j = pidx.get(k)
                if j is None:
                    j = pidx[k] = len(pool)
                    pool.append(x)
                idxs.append(j)
            v['stops'] = idxs
        s = v.get('shp')
        if isinstance(s, str) and s:
            j = sidx.get(s)
            if j is None:
                j = sidx[s] = len(spool)
                spool.append(s)
            v['shp'] = j
    if pool:
        lf['pool'] = pool
    if len(spool) > 1:
        lf['spool'] = spool
    return lf


def main():
    outdir = os.environ.get('OUTDIR', 'line-history/data')
    limit = int(os.environ.get('LIMIT', '0'))
    files = sorted(glob.glob(f'{outdir}/lines/*.json'))
    if limit:
        files = files[:limit]
    n_ch = saved = 0
    for p in files:
        try:
            before = os.path.getsize(p)
            lf = json.load(open(p, encoding='utf-8'))
        except Exception as e:
            print(f'{p}: קובץ בעייתי — {e}', file=sys.stderr)
            continue
        out = json.dumps(compact(lf), ensure_ascii=False, separators=(',', ':'))
        if len(out.encode()) != before:
            open(p, 'w', encoding='utf-8').write(out)
            n_ch += 1
            saved += before - len(out.encode())
    print(f'דחיסת קווים: {n_ch} קבצים עודכנו, נחסכו {saved/1e6:.1f}MB')


if __name__ == '__main__':
    main()
