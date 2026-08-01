#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הצלבת קווי 2012 (רשת מגיעים) עם קווי היום — עוגן "2012" בציר הזמן.

התאמה שמרנית: אותה חברה + אותו מספר קו + חפיפת מילים משמעותית בין תיאור
הקו של 2012 (יעד + תחנות קצה) לבין תיאור הקו של היום. קו של 2012 יכול
להתאים לכמה וריאנטים של אותו קו היום (כיוונים/חלופות) — כולם מקבלים
את אותו עוגן.

פלט: line-history/data/anchor-2012.json — מיפוי rd -> עוגן 2012 תמציתי.
מריצים שוב אחרי כל רענון של magihim-2012/data.
"""
import glob
import json
import re

STOP_WORDS = {'העיר', 'מרכז', 'תחנה', 'מרכזית', 'רכבת', 'קניון', 'צומת', 'דרך',
              'שדרות', 'רחוב', 'בית', 'כיכר', 'מסוף', 'חניון', 'קריית', 'קרית'}
ALIAS = {'ת"א': 'תל אביב', 'י-ם': 'ירושלים', 'נצרת עילית': 'נוף הגליל'}


def tokens(s):
    s = s or ''
    for k, v in ALIAS.items():
        s = s.replace(k, v)
    ws = re.findall(r'[א-ת]{3,}', s)
    return {w for w in ws if w not in STOP_WORDS}


AG2OP = {'3': 'אגד', '4': 'אגד תעבורה', '5': 'דן', '14': 'נתיב אקספרס',
         '15': 'מטרופולין', '16': 'סופרבוס', '18': 'קווים', '19': 'מטרודן',
         '25': 'אפיקים'}


def op_match(agency, op):
    want = AG2OP.get(agency)
    if not want:
        return False
    if want == 'אגד':
        return 'אגד' in op and 'תעבורה' not in op
    return want in op


def main():
    idx = json.load(open('line-history/data/lines.json', encoding='utf-8'))
    today = idx['lines'] if isinstance(idx, dict) else idx

    anchors = {}
    n2012 = 0
    for f in glob.glob('magihim-2012/data/l*.json'):
        d = json.load(open(f, encoding='utf-8'))
        n2012 += 1
        r0 = d['routes'][0] if d.get('routes') else None
        if not r0 or not r0.get('stops'):
            continue
        t12 = tokens(d.get('dest', '')) | tokens(r0.get('f', '')) | tokens(r0.get('l', ''))
        no = d.get('no', '')
        no_alt = no.lstrip('0') or no
        cands = [l for l in today
                 if l.get('line') in (no, no_alt) and op_match(d.get('a', ''), l.get('op') or '')]
        for l in cands:
            common = t12 & tokens(l.get('dest', ''))
            if not common:
                continue
            rd = l['rd']
            score = len(common)
            if rd in anchors and anchors[rd]['_s'] >= score:
                continue
            anchors[rd] = {'_s': score, 'k': d['a'] + '-' + f.rsplit('l' + d['a'] + '-', 1)[-1][:-5],
                           'no': no, 'f': r0.get('f', ''), 'l': r0.get('l', ''),
                           'n': r0.get('n', 0), 'nr': len(d.get('routes', []))}

    for a in anchors.values():
        a.pop('_s', None)
    out = {'gen2012': True, 'anchors': anchors}
    with open('line-history/data/anchor-2012.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False)
    print(f'קווי 2012 שנבדקו: {n2012} | וריאנטים של היום שקיבלו עוגן 2012: {len(anchors)}')


if __name__ == '__main__':
    main()
