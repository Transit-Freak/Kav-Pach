#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""היסטוריה לפי תחנה — אילו קווים שירתו כל תחנה ומתי זה השתנה.

הופך את ציר הזמן של הקווים (lines/*.json) לציר זמן של תחנות: לכל
מק"ט תחנה נבנית רשימת אירועים — קו התחיל לעצור בה, קו הפסיק, וקו
שתועד בה מהגרסה הראשונה. מעברי רציפים עולים מהצלבת out+in של אותו
קו באותו תאריך בתחנות סמוכות (הממשק מזהה לפי השם).

פלט: stopev/XX.json — מפוצל לפי שתי הספרות הראשונות של המק"ט, כדי
שעמוד תחנה יטען קובץ קטן אחד. מבנה: {code: {n: שם אחרון, ev:
[[תאריך, קו, מק"ט-וריאנט, סוג], ...]}}. סוגים: base=תועד מהגרסה
הראשונה · in=התחיל לעצור · out=הפסיק לעצור.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')


def main():
    stops = {}   # code → {'n': name, 'ev': [...]}

    def emit(code, name, date, line, rd, kind):
        s = stops.setdefault(code, {'n': '', 'ev': []})
        if name:
            s['n'] = name       # השם האחרון שנראה — עדכני יותר
        s['ev'].append([date, line, rd, kind])

    n_files = 0
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = lf.get('versions') or []
        rd = lf.get('rd', '')
        line = lf.get('line', '') or ''
        sv = [(v.get('d', ''), v) for v in vs if v.get('stops')]
        if not sv:
            continue
        n_files += 1
        prev_codes, prev_names = None, {}
        for d, v in sv:
            names = {}
            codes = set()
            for s in v['stops']:
                if not isinstance(s, (list, tuple)) or len(s) < 2:
                    continue
                c = str(s[0])
                codes.add(c)
                names[c] = s[1]
            if prev_codes is None:
                for c in codes:
                    emit(c, names.get(c), d, line, rd, 'base')
            else:
                for c in codes - prev_codes:
                    emit(c, names.get(c), d, line, rd, 'in')
                for c in prev_codes - codes:
                    emit(c, prev_names.get(c), d, line, rd, 'out')
            prev_codes, prev_names = codes, names
        # ביטול הקו — כל התחנות של הגרסה האחרונה מאבדות אותו
        last = vs[-1]
        if last.get('k') == 'removed' and prev_codes:
            for c in prev_codes:
                emit(c, prev_names.get(c), last.get('d', ''), line, rd, 'out')

    # פיצול לקבצים לפי קידומת המק"ט + מיון אירועים לפי תאריך
    shards = {}
    for c, s in stops.items():
        s['ev'].sort(key=lambda e: e[0])
        shards.setdefault((c[:2] if len(c) >= 2 else '0x'), {})[c] = s
    outdir = f'{OUTDIR}/stopev'
    os.makedirs(outdir, exist_ok=True)
    old = set(os.listdir(outdir))
    for pre, data in shards.items():
        fn = f'{pre}.json'
        json.dump(data, open(f'{outdir}/{fn}', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        old.discard(fn)
    for fn in old:      # קידומות שהתרוקנו
        os.remove(f'{outdir}/{fn}')
    n_ev = sum(len(s['ev']) for s in stops.values())
    print(f'היסטוריית תחנות: {len(stops)} תחנות · {n_ev} אירועים · '
          f'{len(shards)} קבצים (מ-{n_files} קווים)')


if __name__ == '__main__':
    main()
