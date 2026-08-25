# -*- coding: utf-8 -*-
"""השלמת מסלול לרשומות "וריאנט חדש" של סריקת-הקיום מהארכיון.

סריקת ארכיון אופן באס (scan_seen_ob) רשמה מתי וריאנט הופיע ברישום —
קיום בלבד, בלי מסלול ובלי תחנות. התוצאה באתר (דיווח שלמה, קו 80 כפר
חב"ד): כרטיס "וריאנט חדש" שמציג את המסלול המתועד הסמוך במקום את מה
שבאמת נסע אז, והשינוי הבא בתור נראה כאילו הוא ממציא תחנות שכבר קיימות.

לכל תאריך עם רשומות כאלה שולפים מצילום הארכיון של אותו יום בדיוק את
המסלול והתחנות של כל הווריאנטים הרלוונטיים בבת אחת, וכותבים אותם על
הרשומה עצמה. וריאנט שרשום בלי נסיעות באותו צילום נשאר קיום-בלבד.

checkpoint: nr-state.json (done/skip) — ריצה חוזרת ממשיכה מאיפה שעצרה.
התאריכים מטופלים מהחדש לישן: הכרטיסים שהמשתמשים רואים קודם נפתרים קודם.

MAX_MIN  תקציב זמן בדקות (ברירת מחדל 45)
DRY=1    ניתוח בלבד, בלי כתיבה
"""
import collections
import glob
import json
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402
from backfill_geo_truth import day_full  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/nr-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
PAUSE = float(os.environ.get('PAUSE', '0.6'))
ARC_FROM, ARC_TO = '2022-01-16', '2026-07-24'   # טווח צילומי gtfs_archive
T0 = time.time()


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def build_worklist():
    """date -> [(path, rd)] — רשומות 'וריאנט חדש' מהארכיון בלי מסלול."""
    by = collections.defaultdict(list)
    for p in sorted(glob.glob(f'{OUTDIR}/lines/*.json')):
        d = jload(p, None)
        if not d:
            continue
        for v in d.get('versions') or []:
            if v.get('k') == 'new' and v.get('src') == 'ob' \
               and not (v.get('stops') or v.get('shp')):
                by[v['d']].append((p, d.get('rd')))
    return by


def save_state(st, done, skip):
    st['done'] = sorted(done)
    st['skip'] = sorted(skip)
    if not DRY:
        json.dump(st, open(STATE, 'w', encoding='utf-8'))


def main():
    st = jload(STATE, {'done': [], 'skip': []})
    done = set(st.get('done') or [])
    skip = set(st.get('skip') or [])
    by = build_worklist()
    dates = [d for d in sorted(by, reverse=True)
             if d not in done and d not in skip and ARC_FROM <= d <= ARC_TO]
    out_range = [d for d in by if not (ARC_FROM <= d <= ARC_TO)]
    total = sum(len(v) for v in by.values())
    print(f'{total} רשומות ב-{len(by)} תאריכים · {len(dates)} תאריכים נותרו לטיפול'
          + (f' · {len(out_range)} מחוץ לטווח הארכיון' if out_range else ''))
    n_fix = n_miss = 0
    for i, ds in enumerate(dates):
        if (time.time() - T0) / 60 > MAX_MIN:
            print('נגמר תקציב הזמן — ההמשך בריצה הבאה')
            break
        rds = sorted({rd for _, rd in by[ds] if rd})
        print(f'{ds}: {len(rds)} וריאנטים')
        try:
            got = day_full(ds, rds)
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                print(f'{ds}: אין צילום ({e.code}) — נרשם דילוג קבוע', file=sys.stderr)
                skip.add(ds)
                save_state(st, done, skip)
                continue
            print(f'{ds}: HTTP {e.code} — דילוג זמני', file=sys.stderr)
            time.sleep(20)
            continue
        except Exception as e:
            print(f'{ds}: {type(e).__name__}: {e} — דילוג זמני', file=sys.stderr)
            time.sleep(10)
            continue
        for p, rd in by[ds]:
            g = got.get(rd)
            lf = materialize(jload(p, None))
            if not lf:
                continue
            dirty = False
            for v in lf.get('versions') or []:
                if v.get('d') == ds and v.get('k') == 'new' and v.get('src') == 'ob' \
                   and not (v.get('stops') or v.get('shp')):
                    if g and g.get('stops'):
                        v['stops'] = g['stops']
                        v['shp'] = g.get('shp') or ''
                        v['note'] = ('הווריאנט הופיע ברישום (ארכיון אופן באס, תאריך מדויק)'
                                     ' · המסלול והתחנות הושלמו מצילום הארכיון של אותו יום')
                        dirty = True
                        n_fix += 1
                    else:
                        n_miss += 1   # רשום בלי נסיעות בצילום — נשאר קיום-בלבד
            if dirty and not DRY:
                json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
        done.add(ds)
        if i % 8 == 0:
            save_state(st, done, skip)
        time.sleep(PAUSE)
    save_state(st, done, skip)
    print(f'סיכום הריצה: {n_fix} רשומות קיבלו מסלול ותחנות · {n_miss} לא פעלו בצילום היום שלהן')


if __name__ == '__main__':
    main()
