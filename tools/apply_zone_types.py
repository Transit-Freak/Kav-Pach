# -*- coding: utf-8 -*-
# החלה חד-פעמית של סיווג הסוגים (tools/zone_type.py) על נתוני האתר הקיימים,
# בלי לחכות לריצה השבועית של tools/parks.py: מוסיף zt לכל אזור, נותן שמות
# עבריים, ומסיר אזורים שאינם מקום עבודה (כולל מחיקת הקובץ שלהם).
# הריצה השבועית הבאה מפיקה את אותה תוצאה מהמקור — הסקריפט רק מקדים אותה.
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_type import classify

OUTDIR = os.environ.get('OUTDIR', 'parks/data')
idx = json.load(open(f'{OUTDIR}/parks.json', encoding='utf-8'))
kept, dropped, renamed, counts = [], [], [], {}
for row in idx:
    zc = classify(row['name'])
    if zc.get('exclude'):
        dropped.append((row['name'], zc['exclude']))
        try: os.remove(f"{OUTDIR}/{row['f']}")
        except FileNotFoundError: pass
        continue
    rec = json.load(open(f"{OUTDIR}/{row['f']}", encoding='utf-8'))
    if zc.get('rename'):
        renamed.append((row['name'], zc['rename']))
        row['name'] = rec['name'] = zc['rename']
    zt = zc['zt']
    if zt == 'ind' and row.get('ly') == 'hub':
        zt = 'emp'
    row['zt'] = rec['zt'] = zt
    counts[zt] = counts.get(zt, 0) + 1
    json.dump(rec, open(f"{OUTDIR}/{row['f']}", 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    kept.append(row)
kept.sort(key=lambda x: (x['city'], x['name']))
json.dump(kept, open(f'{OUTDIR}/parks.json', 'w', encoding='utf-8'),
          ensure_ascii=False, separators=(',', ':'))
print('נשארו:', len(kept), '| לפי סוג:', counts)
print('הוסרו:', *[f'\n  - {n} ({r})' for n, r in dropped] or [' —'])
print('שמות עבריים:', *[f'\n  - {a} ← {b}' for a, b in renamed] or [' —'])
