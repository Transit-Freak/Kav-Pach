#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""אירוע שאינו שינוי — נמחק (הכלל של שלמה, 03.09).

"יש שינוי, ואז עוד פעם אותו שינוי שהיה קודם, בלי שינוי באמצע": אירוע
שמדווח על שינוי תחנות (route / stops / stops-add / stops-del / extend /
shorten / terminal) בעוד רצף התחנות המתועד שלו זהה לרצף המתועד שלפניו —
אינו שינוי. רובם נכתבו בסריקת הארכיון יום-מול-יום (אופן באס), שהשוותה
לבסיס שגוי ורשמה את אותו מצב כאירוע.

הטיפול:
  · 'route' שרק השרטוט שלו שונה מהקודם — הופך ל-'redraw' (תיקון שרטוט,
    קטגוריה טכנית), בלי רשימות ➕/➖.
  · כל השאר — הגרסה נמחקת מקובץ הקו, והשורה שלה נמחקת מהפיד החודשי.
אידמפוטנטי; יומן ב-repair-noop-events.json. DRY=1 = ספירה בלי כתיבה.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
STOPK = {'route', 'stops', 'stops-add', 'stops-del', 'extend', 'shorten', 'terminal'}
LOG = f'{OUTDIR}/repair-noop-events.json'


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def jdump(obj, p):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def main():
    ld = f'{OUTDIR}/lines'
    deleted, redrawn, samples = [], [], []
    for f in sorted(os.listdir(ld)):
        if not f.endswith('.json'):
            continue
        p = f'{ld}/{f}'
        lf = materialize(jload(p, None))
        if not lf:
            continue
        vs = lf.get('versions') or []
        keep, changed = [], False
        prev_codes, prev_shp = None, None
        for v in vs:
            codes = [str(s[0]) for s in (v.get('stops') or [])]
            k = v.get('k')
            if codes and prev_codes is not None and codes == prev_codes and k in STOPK:
                if k == 'route' and v.get('shp') and prev_shp and v['shp'] != prev_shp:
                    v = dict(v)
                    v['k'] = 'redraw'
                    for key in ('add', 'rem', 'ac', 'rc', 'nc'):
                        v.pop(key, None)
                    v['note'] = 'תיקון שרטוט — רצף התחנות לא השתנה'
                    redrawn.append((lf.get('rd'), v['d']))
                    keep.append(v)
                    changed = True
                else:
                    deleted.append((lf.get('rd'), v['d'], k, v.get('src') or 'daily'))
                    if len(samples) < 12:
                        samples.append({'rd': lf.get('rd'), 'line': lf.get('line'), 'd': v['d'], 'k': k, 'src': v.get('src') or 'daily'})
                    changed = True
                    continue
            keep.append(v)
            if codes:
                prev_codes = codes
            if v.get('shp'):
                prev_shp = v['shp']
        if changed and not DRY:
            lf['versions'] = keep
            jdump(compact(lf), p)
    # הפיד החודשי: הורדת השורות של האירועים שנמחקו
    by_month = {}
    for rd, d, k, src in deleted:
        by_month.setdefault(d[:7], set()).add((rd, d, k))
    n_rows = 0
    if not DRY:
        for month, keys in by_month.items():
            mp = f'{OUTDIR}/changes/{month}.json'
            m = jload(mp, None)
            if not m:
                continue
            before = len(m['changes'])
            m['changes'] = [c for c in m['changes'] if (c.get('rd'), c.get('d'), c.get('k')) not in keys]
            n_rows += before - len(m['changes'])
            if before != len(m['changes']):
                jdump(m, mp)
        log = jload(LOG, {'runs': []})
        log['runs'].append({'at': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), 'deleted': len(deleted),
                            'redrawn': len(redrawn), 'monthly_rows': n_rows, 'samples': samples})
        log['runs'] = log['runs'][-60:]
        jdump(log, LOG)
    print(f'אירועים שאינם שינוי: נמחקו {len(deleted)} · הפכו לתיקון שרטוט {len(redrawn)} · שורות חודשיות {n_rows}'
          + (' (DRY)' if DRY else ''), file=sys.stderr)
    for s in samples[:6]:
        print('   ', s, file=sys.stderr)


if __name__ == '__main__':
    main()
