#!/usr/bin/env python3
# בונה מחדש את שורות lines.json מקובצי הקווים עצמם (lines/*.json) — הקבצים
# הם מקור האמת. רץ בצעד ה-commit של תהליכי העבודה אחרי מיזוג קבצים בין
# ריצות מקביליות, כדי שהאינדקס תמיד ישקף את מה שבאמת נמצא בקבצים
# (אותה גזירה כמו בזנב האינדקס של backfill_routes_exact.py).
import json
import os

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return d


idxp = f'{OUTDIR}/lines.json'
idx = jload(idxp, {})
if idx.get('lines') is None:
    raise SystemExit('אין אינדקס — מדלגים')

byrd = {e['rd']: e for e in idx['lines']}
n_new = 0
for fn in os.listdir(f'{OUTDIR}/lines'):
    if not fn.endswith('.json'):
        continue
    lf = jload(f'{OUTDIR}/lines/{fn}', {})
    rd = lf.get('rd')
    if not rd:
        continue
    vs = lf.get('versions', [])
    e = byrd.get(rd)
    if e is None:
        e = {'rd': rd, 'line': lf.get('line', ''), 'dest': lf.get('dest', '')[:80],
             'op': lf.get('op', ''), 'ty': lf.get('ty', '')}
        idx['lines'].append(e)
        byrd[rd] = e
        n_new += 1
    else:
        e['line'] = lf.get('line', e.get('line', ''))
        e['dest'] = (lf.get('dest') or e.get('dest', ''))[:80]
        e['op'] = lf.get('op', e.get('op', ''))
    ks = {v['k'] for v in vs if v['k'] != 'baseline'}
    for v in vs:   # קטגוריות התחנות הנגזרות מההשוואות
        if (v.get('src') == 'ob' or v.get('gd')) and v.get('k') != 'removed':
            a, rr = v.get('add'), v.get('rem')
            if a and rr:
                ks.add('stops')
            elif a:
                ks.add('stops-add')
            elif rr:
                ks.add('stops-del')
    ks = sorted(ks)
    e['v'] = len(vs)
    if ks:
        e['ks'] = ks
    else:
        e.pop('ks', None)
    if vs:
        e['lk'] = vs[-1]['k']
        e['ld'] = vs[-1]['d']

idx['lines'].sort(key=lambda x: (x.get('line', ''), x['rd']))
json.dump(idx, open(idxp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print(f'אינדקס נבנה מחדש: {len(idx["lines"])} שורות ({n_new} חדשות)')
