#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""תוכנית שבסוף נכנסה לפועל — אינה "שינוי שלא נכנס לתוקף" (שלמה 03.09).

הקטגוריה נועדה לקו שלא נכנס לפעול בחיים, או לשינוי תחנות שלא נכנס לפעול
בחיים. תוכנית שירדה מהרישום ואחר כך בכל זאת יצאה לפועל היא דחייה, לא
אירוע: השינוי עצמו נרשם כאירוע רגיל ביום שנכנס. לכן, לכל גרסת
planned-dropped בקובץ קו בודקים מה קרה אחריה באותו וריאנט:

  · וריאנט שלם (pk=new): אם הווריאנט נסע אחר כך — בכל מסלול — הוא נכנס לפעול,
    והאירוע נמחק.
  · שינוי תחנות (pk=route): אם רצף התחנות שתוכנן הופיע אחר כך כרצף הפעיל של
    הווריאנט — השינוי נכנס לפעול, והאירוע נמחק. אם נכנס שינוי אחר — התוכנית
    הזו לא נכנסה, והאירוע נשאר.

"אחר כך" נקבע לפי הגרסאות המאוחרות בקובץ, ולכן הכלל רץ כל יום: תוכנית שירדה
בשבוע שעבר מוצגת עד שהווריאנט מתחיל, ואז נעלמת. אידמפוטנטי; מוחק גם את
השורה מהפיד החודשי; קובץ קו שנותר בלי גרסאות נמחק (האינדקס נבנה מחדש אחריו).
יומן ב-repair-planned-entered.json. DRY=1 = ספירה בלי כתיבה.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
KIND = 'planned-dropped'
LOG = f'{OUTDIR}/repair-planned-entered.json'


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def jdump(obj, p):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def plan_kind(v):
    return v.get('pk') or ('new' if 'הווריאנט' in (v.get('note') or '') else 'route')


def entered_later(vs, i):
    """האם התוכנית שבגרסה i נכנסה לפועל אחר כך."""
    v = vs[i]
    later = [w for w in vs[i + 1:] if w.get('stops')]
    if not later:
        return False
    if plan_kind(v) == 'new':
        return True
    codes = [str(s[0]) for s in (v.get('pstops') or [])]
    return any([str(s[0]) for s in w['stops']] == codes for w in later)


def main():
    ld = f'{OUTDIR}/lines'
    deleted, n_files_gone, samples = [], 0, []
    by_kind = {'new': 0, 'route': 0}
    for f in sorted(os.listdir(ld)):
        if not f.endswith('.json'):
            continue
        p = f'{ld}/{f}'
        lf = materialize(jload(p, None))
        if not lf:
            continue
        vs = lf.get('versions') or []
        if not any(v.get('k') == KIND for v in vs):
            continue
        keep = []
        changed = False
        for i, v in enumerate(vs):
            if v.get('k') == KIND and entered_later(vs, i):
                deleted.append((lf.get('rd'), v['d']))
                by_kind[plan_kind(v)] += 1
                if len(samples) < 10:
                    samples.append({'rd': lf.get('rd'), 'line': lf.get('line'), 'd': v['d'], 'ps': v.get('ps'), 'pk': plan_kind(v)})
                changed = True
                continue
            keep.append(v)
        if changed and not DRY:
            if keep:
                lf['versions'] = keep
                jdump(compact(lf), p)
            else:
                os.remove(p)
                n_files_gone += 1
    n_rows = 0
    if not DRY and deleted:
        by_month = {}
        for rd, d in deleted:
            by_month.setdefault(d[:7], set()).add((rd, d))
        for month, keys in by_month.items():
            mp = f'{OUTDIR}/changes/{month}.json'
            m = jload(mp, None)
            if not m:
                continue
            before = len(m['changes'])
            m['changes'] = [c for c in m['changes'] if not (c.get('k') == KIND and (c.get('rd'), c.get('d')) in keys)]
            n_rows += before - len(m['changes'])
            if before != len(m['changes']):
                jdump(m, mp)
        log = jload(LOG, {'runs': []})
        log['runs'].append({'at': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC'), 'deleted': len(deleted),
                            'new': by_kind['new'], 'route': by_kind['route'], 'files_gone': n_files_gone, 'monthly_rows': n_rows, 'samples': samples})
        log['runs'] = log['runs'][-60:]
        jdump(log, LOG)
    print(f'תוכניות שבסוף נכנסו לפועל — נמחקו {len(deleted)} (וריאנט שלם {by_kind["new"]}, שינוי תחנות {by_kind["route"]}) · '
          f'קבצים שנותרו ריקים {n_files_gone} · שורות חודשיות {n_rows}' + (' (DRY)' if DRY else ''), file=sys.stderr)
    for s in samples[:5]:
        print('   ', s, file=sys.stderr)


if __name__ == '__main__':
    main()
