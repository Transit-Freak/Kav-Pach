# -*- coding: utf-8 -*-
# השלמה חד-פעמית: העתקת דגל הנגישות (wa) מהמצב היומי אל קובצי הקווים.
# linehistory.py כותב את wa רק כשקובץ הקו נכתב ממילא (שינוי באותו יום),
# ולכן קווים יציבים — הרוב — נשארו בלי הדגל והאתר לא הציג "נגיש".
# מהריצה הזו והלאה שינויי נגישות ממשיכים להתעדכן דרך אירועי access.
import json, os, sys

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')

def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')

st = json.load(open(f'{OUTDIR}/state-routes.json', encoding='utf-8'))
fixed = missing = same = nofile = 0
for rd, c in st.items():
    wa = c.get('wa')
    if not wa:
        missing += 1
        continue
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    if not os.path.exists(p):
        nofile += 1
        continue
    lf = json.load(open(p, encoding='utf-8'))
    if lf.get('wa') == wa:
        same += 1
        continue
    lf['wa'] = wa
    json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    fixed += 1
print(f'עודכנו: {fixed} · כבר תקינים: {same} · בלי דגל במצב: {missing} · בלי קובץ: {nofile}')
