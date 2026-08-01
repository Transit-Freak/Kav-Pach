# -*- coding: utf-8 -*-
# "הקו בזמן" — בניית קובצי השינויים החודשיים של הקווים לכל התקופה, רטרואקטיבית.
#
# הצינור היומי כותב changes/YYYY-MM.json רק מאז שהתחיל (07.2026), אבל כל
# האירועים ההיסטוריים כבר יושבים עם תאריך בקובצי הווריאנטים (lines/*.json).
# הסקריפט מקבץ אותם לקבצים חודשיים כדי שתצוגת "שינויים לפי יום" תעבוד
# על כל התקופה. חודשים שכבר יש להם קובץ מהצינור היומי לא נגעים — הרשומות
# שלו עשירות יותר (add/rem). רץ פעם אחת; הצינור ממשיך מהחודש הנוכחי.
#
# שדות הרשומה: d, rd, line, k (+note כשקיים). יעד ומפעיל נשלפים בממשק
# מהאינדקס (lines.json) לפי rd — אין טעם לשכפל אותם לאלפי רשומות.
import json, os, re

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
SKIP_KINDS = {'baseline', 'snapshot'}   # תיעוד ראשון/צילום — לא שינוי

def jload(p, dflt):
    try: return json.load(open(p, encoding='utf-8'))
    except Exception: return dflt

existing = {f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$', f)}
cutoff = min(existing) if existing else '9999-99'
print('קבצים קיימים מהצינור היומי:', sorted(existing), '| בונים עד', cutoff)

months = {}
n_ev = n_files = 0
for fn in sorted(os.listdir(f'{OUTDIR}/lines')):
    if not fn.endswith('.json'): continue
    lf = jload(f'{OUTDIR}/lines/{fn}', {})
    rd, line = lf.get('rd'), lf.get('line') or ''
    if not rd: continue
    n_files += 1
    for v in lf.get('versions', []):
        k, d = v.get('k'), v.get('d')
        if not d or k in SKIP_KINDS: continue
        m = d[:7]
        if m >= cutoff: continue   # מכאן הצינור היומי מכסה
        rec = {'d': d, 'rd': rd, 'line': line, 'k': k}
        if v.get('note'): rec['note'] = v['note']
        months.setdefault(m, []).append(rec)
        n_ev += 1

for m, evs in months.items():
    evs.sort(key=lambda e: (e['d'], e['line']))
    json.dump({'month': m, 'changes': evs},
              open(f'{OUTDIR}/changes/{m}.json', 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))

# רשימת החודשים — אותה לוגיקה כמו הצינור היומי (מקבצים על הדיסק)
json.dump({'months': sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$', f)}, reverse=True),
           'stopMonths': sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')}, reverse=True)},
          open(f'{OUTDIR}/months.json', 'w', encoding='utf-8'), ensure_ascii=False)
print(f'{n_ev} אירועים מ-{n_files} וריאנטים נכתבו ל-{len(months)} קובצי חודש')
