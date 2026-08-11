#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""קובץ דלתא לילי לקו פח ולקו המוזהב — מה שהארכיון יודע והצילום לא.

נתוני הליבה של קו פח (data-main.json) הם צילום חד-פעמי מ-17.06.2026 בלי
שום מסלול רענון. הארכיון של "הקו בזמן" מתעדכן יומית באותו ריפו, ובהצלבה
התברר: 628 מהקווים שהכלי מדרג "מועמדים לביטול" כבר בוטלו בפועל, וכמעט
20% שינו תדירות. הכלי הזה גוזר מהארכיון תקציר קטן לפי (מקט, כיוון):

  rm    הקו מבוטל כרגע (כל הווריאנטים של הצמד ב-removed)
  rmd   תאריך הביטול האחרון
  ntr   נסיעות ביום כרגע (סכום הווריאנטים, מ-line-trips.json)
  red   כמה אירועי הפחתת-שירות ב-12 החודשים האחרונים (freq/sched עם "ירדו")
  newd  תאריך ההופעה אם הקו הופיע לראשונה בשנה האחרונה (הגנת הרצה)
  gap   השבתה-וחזרה בשנה האחרונה: [מתאריך, עד תאריך] הארוכה ביותר

הפלט קטן (מאות ק"ב) ונטען באתר בלי לחסום — אם אינו קיים, הכל עובד כרגיל.
"""
import datetime
import glob
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
OUT = os.environ.get('OUT', 'kavpach-live.json')
TODAY = os.environ.get('TODAY') or datetime.date.today().isoformat()
YEAR_AGO = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=365)).isoformat()


def key_of(rd):
    """'10339-2-א' -> '10339-2' — הרזולוציה של קו פח היא מקט+כיוון."""
    parts = rd.split('-')
    return f'{parts[0]}-{parts[1]}' if len(parts) >= 2 else rd


def main():
    idx = json.load(open(f'{OUTDIR}/lines.json', encoding='utf-8'))['lines']
    try:
        ntr = json.load(open(f'{OUTDIR}/line-trips.json', encoding='utf-8'))
    except Exception:
        ntr = {}

    per = defaultdict(lambda: {'variants': 0, 'removed': 0, 'rmd': '', 'ntr': 0,
                               'red': 0, 'first': '', 'gap': None})
    for l in idx:
        rd = l.get('rd') or ''
        if rd.count('-') < 2:
            continue
        k = key_of(rd)
        e = per[k]
        e['variants'] += 1
        if l.get('lk') == 'removed':
            e['removed'] += 1
            e['rmd'] = max(e['rmd'], l.get('ld') or '')
        e['ntr'] += int(ntr.get(rd) or 0)

    # אירועי הפחתה, הופעה והשבתות — מקובצי הווריאנטים, שנה אחורה בלבד
    for p in glob.glob(f'{OUTDIR}/lines/*.json'):
        lf = materialize(json.load(open(p, encoding='utf-8')))
        rd = lf.get('rd') or ''
        if rd.count('-') < 2:
            continue
        k = key_of(rd)
        if k not in per:
            continue
        e = per[k]
        vs = sorted(lf.get('versions') or [], key=lambda v: v['d'])
        # "קו חדש" = הווריאנט המוקדם ביותר של הקו הופיע רק השנה. חלופה
        # חדשה על קו ותיק (קטעי המלחמה של הקו האדום) אינה קו חדש.
        first_seen = vs[0]['d'] if vs else ''
        if first_seen:
            e['first'] = min(e['first'], first_seen) if e['first'] else first_seen
        last_rm = ''
        for v in vs:
            d, kk = v['d'], v.get('k')
            if d >= YEAR_AGO and kk in ('freq', 'sched') and 'ירדו' in (v.get('note') or ''):
                e['red'] += 1
            if kk in ('removed', 'removed-year'):
                last_rm = d
            elif kk in ('new', 'baseline') and last_rm:
                gap = (datetime.date.fromisoformat(d) - datetime.date.fromisoformat(last_rm)).days
                if d >= YEAR_AGO and gap >= 14:
                    cur = e['gap']
                    if cur is None or gap > cur[2]:
                        e['gap'] = [last_rm, d, gap]
                last_rm = ''

    # רמה שנייה: מקט שלם — הכרטיסים בקו פח מאגדים את שני הכיוונים יחד,
    # ו"בוטל" נכון לקבוצה רק כשכל הווריאנטים של המקט כולו בוטלו
    per_mk = defaultdict(lambda: {'variants': 0, 'removed': 0, 'rmd': '', 'ntr': 0,
                                  'red': 0, 'first': '', 'gap': None})
    for k, e in per.items():
        mk = k.split('-')[0]
        m = per_mk[mk]
        m['variants'] += e['variants']
        m['removed'] += e['removed']
        m['rmd'] = max(m['rmd'], e['rmd'])
        m['ntr'] += e['ntr']
        m['red'] += e['red']
        if e['first']:
            m['first'] = min(m['first'], e['first']) if m['first'] else e['first']
        if e['gap'] and (m['gap'] is None or e['gap'][2] > m['gap'][2]):
            m['gap'] = e['gap']
    for mk, m in per_mk.items():
        per[mk] = m

    out = {}
    for k, e in per.items():
        rec = {}
        if e['variants'] and e['removed'] == e['variants']:
            rec['rm'] = 1
            if e['rmd']:
                rec['rmd'] = e['rmd']
        if e['ntr']:
            rec['ntr'] = e['ntr']
        if e['red']:
            rec['red'] = e['red']
        # קו שהושבת וחזר אינו "קו חדש בהרצה": תאריך ההופעה-מחדש שלו נראה
        # כמו תאריך לידה, והתג הטעה (ציד הבאגים של שלב ב)
        if e['first'] and e['first'] >= YEAR_AGO and not e['gap']:
            rec['newd'] = e['first']
        if e['gap']:
            rec['gap'] = e['gap'][:2]
        if rec:
            out[k] = rec

    doc = {'gen': TODAY, 'archiveGen': json.load(open(f'{OUTDIR}/lines.json', encoding='utf-8')).get('gen', ''),
           'lines': out}
    json.dump(doc, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    n_rm = sum(1 for v in out.values() if v.get('rm'))
    n_red = sum(1 for v in out.values() if v.get('red'))
    n_new = sum(1 for v in out.values() if v.get('newd'))
    n_gap = sum(1 for v in out.values() if v.get('gap'))
    kb = os.path.getsize(OUT) // 1024
    print(f'נכתב {OUT} ({kb} ק"ב): {len(out)} צמדי מקט-כיוון · '
          f'{n_rm} מבוטלים · {n_red} עם צמצומים · {n_new} חדשים · {n_gap} עם השבתה-וחזרה',
          file=sys.stderr)


if __name__ == '__main__':
    main()
