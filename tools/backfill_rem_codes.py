#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""השלמת מק"טים מדויקת מצילומי הארכיון — לא היסק לפי שם.

בקשת המשתמש (קו 393): בצילום הארכיון של אותה תקופה יש מק"ט
וקואורדינטות לכל תחנה של כל קו — אז המק"ט של תחנה שירדה נלקח משם,
מרשימת התחנות של הקו עצמו בצילום שקדם לשינוי, ולא מניחוש לפי שם.

לכל גרסת ארכיון (src=tf) עם שמות ➕/➖ שאין להם מק"ט בקובץ הקו:
- שם שירד: נפתר מהצילום שקדם לתאריך הגרסה (שמולו חושב ההפרש).
- שם שנוסף: נפתר מהצילום של תאריך הגרסה עצמו.
הערכים המדויקים דורסים את ההיסק של enrich_missing_stop_codes; היסק
נשאר רק היכן שהצילום לא עוזר (הקו/השם לא בצילום).

מעבר אחד ממוין על הצילומים: כל צילום נטען פעם אחת (snapshot של
backfill_tf) ומשרת את כל הגרסאות התלויות בו. המצב נשמר
(rc-state.json) — ריצה חוזרת מדלגת על צילומים שכבר עובדו.

FROM/TO   טווח צילומים (YYYYMMDD), ברירת מחדל הכל
MAX_MIN   תקציב זמן בדקות לחוליה אחת (0 = בלי הגבלה)
DRY=1     ניתוח בלבד
"""
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backfill_tf as bt  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/rc-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
FROM = os.environ.get('FROM', '20170101')
TO = os.environ.get('TO', '20221231')
T0 = time.time()


def pool_names(lf):
    src = lf.get('pool') or [s for v in lf.get('versions') or []
                             for s in v.get('stops') or []]
    return {s[1] for s in src if isinstance(s, list) and len(s) >= 2}


def main():
    try:
        done = set(json.load(open(STATE, encoding='utf-8')).get('done') or [])
    except Exception:
        done = set()
    snaps = json.load(open(f'{OUTDIR}/tf-state.json', encoding='utf-8'))['done']
    snaps = sorted(snaps)
    prev_of = {snaps[i]: snaps[i - 1] for i in range(1, len(snaps))}

    # יעדים: (קובץ, תאריך גרסה, rd, שם, ➖/➕) לפי הצילום שנדרש לפתרון
    need = {}          # snapdate -> [(path, d, rd, name, is_rem)]
    n_targets = 0
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        try:
            lf = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        rd = lf.get('rd') or ''
        names = None
        for v in lf.get('versions') or []:
            if v.get('src') != 'tf':
                continue
            ds = (v.get('d') or '').replace('-', '')
            if ds not in prev_of and ds not in set(snaps):
                continue
            for nm, is_rem in [(x, True) for x in v.get('rem') or []] + \
                              [(x, False) for x in v.get('add') or []]:
                if names is None:
                    names = pool_names(lf)
                if nm in names:
                    continue        # הממשק מוצא לבד בתוך הקובץ
                snap_d = prev_of.get(ds) if is_rem else (ds if ds in set(snaps) else None)
                if not snap_d or not (FROM <= snap_d <= TO):
                    continue
                need.setdefault(snap_d, []).append((p, v.get('d'), rd, nm, is_rem))
                n_targets += 1
    todo = [d for d in sorted(need) if d not in done]
    print(f'{n_targets} שמות לפתרון · {len(need)} צילומים נדרשים · '
          f'{len(todo)} טרם עובדו')

    resolved = {}      # (path, d) -> {name: code}
    processed = []
    for ds in todo:
        if MAX_MIN and (time.time() - T0) / 60 > MAX_MIN:
            print(f'תקציב הזמן נוצל — נעצר לפני {ds}; המשך בריצה הבאה')
            break
        try:
            snap = bt.snapshot(ds)
        except (SystemExit, Exception) as e:
            print(f'{ds}: הצילום לא נטען ({e}) — מדלגים', file=sys.stderr)
            processed.append(ds)     # צילום חסר לא ישתפר בריצה הבאה
            continue
        hit = miss = 0
        for path, d, rd, nm, is_rem in need[ds]:
            ent = snap.get(rd)
            code = None
            if ent:
                for s in ent[0]:
                    if s[1] == nm:
                        code = str(s[0])
                        break
            if code:
                resolved.setdefault((path, d), {})[nm] = code
                hit += 1
            else:
                miss += 1
        print(f'{ds}: {hit} נפתרו, {miss} לא בצילום')
        processed.append(ds)

    n_files = n_set = 0
    if not DRY:
        by_path = {}
        for (path, d), m in resolved.items():
            by_path.setdefault(path, {})[d] = m
        for path, byd in by_path.items():
            lf = json.load(open(path, encoding='utf-8'))
            ch = False
            for v in lf.get('versions') or []:
                m = byd.get(v.get('d'))
                if not m:
                    continue
                here = set((v.get('rem') or []) + (v.get('add') or []))
                nc = dict(v.get('nc') or {})
                for nm, code in m.items():
                    if nm in here and nc.get(nm) != code:
                        nc[nm] = code
                        n_set += 1
                        ch = True
                if ch:
                    v['nc'] = nc
            if ch:
                json.dump(lf, open(path, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
                n_files += 1
        done.update(processed)
        json.dump({'done': sorted(done)}, open(STATE, 'w', encoding='utf-8'))
    print(f'נכתבו {n_set} מק"טים מדויקים ב-{n_files} קבצים · '
          f'{len(done)}/{len(need)} צילומים עובדו')


if __name__ == '__main__':
    main()
