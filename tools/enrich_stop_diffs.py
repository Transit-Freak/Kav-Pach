# -*- coding: utf-8 -*-
# "הקו בזמן" — העשרה מקומית, בלי אף קריאת רשת: אחרי ששלב ב' מילא רצפי
# תחנות לגרסאות-עבר מהארכיון, משווים כל גרסה לגרסה הקודמת שיש לה רצף
# ומצרפים "➕ נוספו / ➖ ירדו". ההשוואה לפי קוד תחנה, התצוגה לפי שם.
# ביטול באמצע לא מאפס את הבסיס — קו שחזר עם תחנות אחרות יראה את ההבדל.
# רץ בסוף כל ריצת לילה של שלב ב', ואפשר גם ידנית.
import json, os

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
KINDS = {'new', 'dest', 'renum', 'operator'}   # רק גרסאות ארכיון; ליומי יש דיפים משלו

n_ev = n_files = 0
ks_by_rd = {}   # לרענון האינדקס בסוף — ההשוואה היא מקור האמת לקטגוריות התחנות
for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
    if not fn.endswith('.json'): continue
    p = f'{OUTDIR}/lines/{fn}'
    try:
        lf = json.load(open(p, encoding='utf-8'))
    except Exception:
        continue
    changed = False
    prev = None
    prev_d = None
    prev_src = None
    for v in lf.get('versions', []):
        st = v.get('stops') or []
        if not st: continue
        diff_here = None
        if prev is not None and v.get('src') == 'ob' and v.get('k') in KINDS \
           and 'add' not in v and 'rem' not in v and not v.get('dated'):
            diff_here = 'ob'
        # גם "תיעוד ראשון" מושווה לרשומת הארכיון האחרונה — אחרת שינוי תחנות
        # שקרה בפער שבין הארכיון לתחילת המעקב היומי נבלע (קו 595, תחנה 3405)
        elif prev is not None and prev_src == 'ob' and v.get('k') == 'baseline' \
                and 'add' not in v and 'rem' not in v and not v.get('gd') and not v.get('dated'):
            diff_here = 'gap'
        if diff_here:
            pc = {str(s[0]) for s in prev}
            cc = {str(s[0]) for s in st}
            add = [s[1] for s in st if str(s[0]) not in pc]
            rem = [s[1] for s in prev if str(s[0]) not in cc]
            if add: v['add'] = add
            if rem: v['rem'] = rem
            if add or rem:
                changed = True; n_ev += 1
                if diff_here == 'gap':
                    v['gd'] = 1
                    v['note'] = (f"התחנות השתנו מתישהו בין {prev_d[5:7]}.{prev_d[:4]} "
                                 f"(הרשומה הקודמת בארכיון) לתחילת המעקב היומי — התאריך המדויק לא מתועד")
        prev = st
        prev_d = v.get('d')
        prev_src = v.get('src')
    if changed:
        json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        n_files += 1
    if lf.get('rd'):
        ders = set()
        for v in lf.get('versions', []):
            if (v.get('src') == 'ob' or v.get('gd')) and v.get('k') != 'removed':
                a, r = v.get('add'), v.get('rem')
                if a and r: ders.add('stops')
                elif a: ders.add('stops-add')
                elif r: ders.add('stops-del')
        ks_by_rd[lf['rd']] = (ders, {v['k'] for v in lf.get('versions', []) if v['k'] != 'baseline'})

print(f'הפרשי תחנות חושבו: {n_ev} אירועים ב-{n_files} קבצים')

# ---- רענון האינדקס: קטגוריות התחנות נגזרות מחדש לכל הקווים. בלי זה,
# ריצה ארוכה שמעתיקה את תיקיית הנתונים שלה דורסת העשרות שנוצרו בינתיים
# והקטגוריות מתרוקנות (קרה ב-28.07) — עכשיו כל ריצה מרפאת את עצמה ----
idxp = f'{OUTDIR}/lines.json'
try:
    idx = json.load(open(idxp, encoding='utf-8'))
    n_idx = 0
    for e in idx.get('lines', []):
        got = ks_by_rd.get(e['rd'])
        if not got: continue
        ders, kinds = got
        new_ks = sorted(kinds | ders)
        if new_ks != (e.get('ks') or []):
            if new_ks: e['ks'] = new_ks
            else: e.pop('ks', None)
            n_idx += 1
    json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('רשומות אינדקס שרועננו:', n_idx)
except Exception as ex:
    print('רענון אינדקס נכשל (יתוקן בריצה היומית):', ex)
