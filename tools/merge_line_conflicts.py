#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""פתרון התנגשויות מיזוג בקבצי הקווים — איחוד גרסאות, לא בחירת צד.

כששני צינורות כותבים לאותם קבצים (הסריקה היומית מול מילוי הארכיון), שני
הצדדים מוסיפים אירועים אמיתיים. בחירה בצד אחד הייתה מוחקת היסטוריה שנמדדה
כהלכה, ולכן הגרסאות מאוחדות לפי המפתח (תאריך, סוג, מקור).

פרטי הקו עצמו (מספר, יעד, מפעיל, סוג) נלקחים מצד היעד — הוא משקף את
הרישום העדכני. סוג התחבורה נלקח מכל צד שיש לו אותו, כי רק אחד מהם מכיר
אותו.

הרצה בתוך מיזוג פעיל, אחרי ש-git סימן התנגשויות.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402


def stage(n, path):
    """גרסת הקובץ מאחד משלבי המיזוג: 2=היעד, 3=המקור."""
    r = subprocess.run(['git', 'show', f':{n}:{path}'],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        return materialize(json.loads(r.stdout.decode('utf-8')))
    except (ValueError, UnicodeDecodeError):
        return None


def vkey(v):
    return (v.get('d'), v.get('k'), v.get('src') or '')


def richer(a, b):
    """בין שתי גרסאות באותו מפתח — זו שנושאת יותר מידע."""
    score = lambda v: (len(v.get('stops') or []), len(v.get('shp') or ''),
                       len(v.get('note') or ''))
    return a if score(a) >= score(b) else b


def main():
    # -z חובה: שמות קבצים בעברית מוחזרים מצוטטים ומוברחים בפלט הרגיל,
    # והתאמת נתיב עליהם נכשלת בשקט — כלומר דווקא הקבצים בעברית היו
    # נשארים לא-פתורים.
    raw = subprocess.run(['git', 'diff', '--name-only', '--diff-filter=U', '-z'],
                         capture_output=True).stdout
    files = [f.decode('utf-8') for f in raw.split(b'\0') if f]
    files = [f for f in files if f.startswith('line-history/data/lines/')]
    merged = failed = added = 0
    for p in files:
        ours, theirs = stage(2, p), stage(3, p)
        if ours is None or theirs is None:
            failed += 1
            continue
        vs = {}
        for v in (theirs.get('versions') or []):
            vs[vkey(v)] = v
        for v in (ours.get('versions') or []):
            k = vkey(v)
            vs[k] = richer(vs[k], v) if k in vs else v
        before = len(ours.get('versions') or [])
        out = dict(ours)                      # פרטי הקו מצד היעד
        if not out.get('tt') and theirs.get('tt'):
            out['tt'] = theirs['tt']
        out['versions'] = sorted(vs.values(), key=lambda x: (x['d'], x.get('k') or ''))
        added += len(out['versions']) - before
        json.dump(compact(out), open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        subprocess.run(['git', 'add', '--', p], check=True)
        merged += 1

    print(f'אוחדו {merged} קבצים · נוספו {added} גרסאות · {failed} ללא הכרעה',
          file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
