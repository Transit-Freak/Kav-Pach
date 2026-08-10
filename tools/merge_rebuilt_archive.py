#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מיזוג הארכיון שנבנה מחדש לתוך הנתונים החיים.

הבנייה מחדש רצה בענף נפרד כדי שהאתר ימשיך לעבוד, ובינתיים הסריקה היומית
המשיכה לכתוב לענף הראשי. שני הצדדים צודקים בתחומם: הענף מחזיק את אירועי
הארכיון (src=tf) שנבנו עם כלל הנציג המתוקן, והראשי מחזיק את כל השאר.

המיזוג הוא לפי מקור ולא לפי תאריך: מכל קובץ בראשי מוסרים אירועי הארכיון
הישנים, ובמקומם נכנסים אלה של הענף. שאר האירועים אינם נוגעים.

REBUILT=נתיב לעותק העבודה של הענף · DRY=1 מדווח בלבד
"""
import glob
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
REBUILT = os.environ.get('REBUILT', '/tmp/vrf/line-history/data')
DRY = os.environ.get('DRY') == '1'
ARCHIVE = {'tf', 'tf17'}


def load(p):
    try:
        return materialize(json.load(open(p, encoding='utf-8')))
    except Exception:
        return None


def main():
    if not os.path.isdir(f'{REBUILT}/lines'):
        raise SystemExit(f'אין עותק בנוי ב-{REBUILT}')
    n_merge = n_copy = n_add = n_drop = 0
    seen = set()
    for rp in glob.glob(f'{REBUILT}/lines/*.json'):
        fn = os.path.basename(rp)
        seen.add(fn)
        rb = load(rp)
        if not rb:
            continue
        arch = [v for v in (rb.get('versions') or []) if (v.get('src') or '') in ARCHIVE]
        lp = f'{OUTDIR}/lines/{fn}'
        if not os.path.exists(lp):
            # קו שקיים רק בארכיון (רכבת, מוניות, קווים שנעלמו לפני 2022)
            if not DRY:
                shutil.copy(rp, lp)
            n_copy += 1
            continue
        cur = load(lp)
        if not cur:
            continue
        keep = [v for v in (cur.get('versions') or []) if (v.get('src') or '') not in ARCHIVE]
        n_drop += len(cur.get('versions') or []) - len(keep)
        n_add += len(arch)
        vs = sorted(keep + arch, key=lambda v: (v.get('d') or '', v.get('k') or ''))
        if vs == cur.get('versions'):
            continue
        cur['versions'] = vs
        if not DRY:
            json.dump(compact(cur), open(lp, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
        n_merge += 1

    # קובץ קו שכל תוכנו היה ארכיון ישן ולא נבנה מחדש — אין לו על מה לעמוד
    n_gone = 0
    for lp in glob.glob(f'{OUTDIR}/lines/*.json'):
        fn = os.path.basename(lp)
        if fn in seen:
            continue
        cur = load(lp)
        if not cur:
            continue
        keep = [v for v in (cur.get('versions') or []) if (v.get('src') or '') not in ARCHIVE]
        if keep == cur.get('versions'):
            continue
        n_gone += 1
        if not DRY:
            if keep:
                cur['versions'] = keep
                json.dump(compact(cur), open(lp, 'w', encoding='utf-8'),
                          ensure_ascii=False, separators=(',', ':'))
            else:
                os.remove(lp)

    mode = 'סימולציה' if DRY else 'בוצע'
    print(f'{mode}: {n_merge} קבצים מוזגו · {n_copy} הועתקו כמות שהם · '
          f'{n_drop} אירועי ארכיון ישנים ירדו · {n_add} חדשים נכנסו · '
          f'{n_gone} קבצים נוקו מארכיון שלא נבנה מחדש', file=sys.stderr)


if __name__ == '__main__':
    main()
