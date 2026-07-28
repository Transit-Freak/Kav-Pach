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
           and 'add' not in v and 'rem' not in v:
            diff_here = 'ob'
        # גם "תיעוד ראשון" מושווה לרשומת הארכיון האחרונה — אחרת שינוי תחנות
        # שקרה בפער שבין הארכיון לתחילת המעקב היומי נבלע (קו 595, תחנה 3405)
        elif prev is not None and prev_src == 'ob' and v.get('k') == 'baseline' \
                and 'add' not in v and 'rem' not in v and not v.get('gd'):
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

print(f'הפרשי תחנות חושבו: {n_ev} אירועים ב-{n_files} קבצים')
