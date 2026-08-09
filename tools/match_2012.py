#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הצלבת קווי 2012 (רשת מגיעים) עם קווי היום — עוגן "2012" בציר הזמן.

שני מעברים: התאמה שמרנית לפי אותו מספר קו + חפיפת מילים בין התיאורים,
ואחריה התאמה לפי חפיפת מק"טים בין רצף התחנות של 2012 לרצף הישן ביותר
שיש לנו. השני חזק יותר ואינו תלוי במספר הקו, ולכן הוא גם קולט קווים
שמוספרו מחדש מאז — ומכריע כשהשניים חלוקים.

קו של 2012 יכול להתאים לכמה וריאנטים של אותו קו היום (כיוונים/חלופות)
— כולם מקבלים את אותו עוגן.

פלט: line-history/data/anchor-2012.json — מיפוי rd -> עוגן 2012 תמציתי.
מריצים שוב אחרי כל רענון של magihim-2012/data.
"""
import collections
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import materialize  # noqa: E402

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
        # ערי הקצה של קו 2012: מהיעד ("מX לY") ומסיומות שמות תחנות הקצה.
        # מפעילים התחלפו במכרזים מאז 2012 (548 עבר מאגד לאלקטרה אפיקים) —
        # לכן ההתאמה לפי עיר, ומפעיל זהה הוא רק בונוס לניקוד.
        cities = set()
        mm = re.match(r'מ(.+?) ל(.+)$', d.get('dest', '') or '')
        if mm:
            cities.update((mm.group(1).strip(), mm.group(2).strip()))
        for x in (r0.get('f', ''), r0.get('l', '')):
            p = str(x).split(' - ')
            if len(p) > 1:
                cities.add(p[-1].strip())
        cities = {c for c in cities if len(c) >= 3}
        no = d.get('no', '')
        no_alt = no.lstrip('0') or no
        cands = [l for l in today if l.get('line') in (no, no_alt)]
        for l in cands:
            dest = l.get('dest', '')
            city_hits = [c for c in cities if c in dest]
            if not city_hits:
                continue
            rd = l['rd']
            score = len(city_hits) * 2 + len(t12 & tokens(dest)) \
                + (3 if op_match(d.get('a', ''), l.get('op') or '') else 0)
            if rd in anchors and anchors[rd]['_s'] >= score:
                continue
            anchors[rd] = {'_s': score, 'k': d['a'] + '-' + f.rsplit('l' + d['a'] + '-', 1)[-1][:-5],
                           'no': no, 'f': r0.get('f', ''), 'l': r0.get('l', ''),
                           'n': r0.get('n', 0), 'nr': len(d.get('routes', []))}

    # --- מעבר שני: חפיפת תחנות ---
    # ההתאמה שלמעלה מחייבת אותו מספר קו, ולכן קו שקיבל מספר חדש מאז 2012
    # לא יכול היה להתאים לעצמו. חפיפת מק"טים היא עדות ישירה ולא נסמכת על
    # שמות: אותן עשרים תחנות אינן צירוף מקרים.
    meta12, inv = {}, collections.defaultdict(list)
    for f in glob.glob('magihim-2012/data/l*.json'):
        d = json.load(open(f, encoding='utf-8'))
        r0 = d['routes'][0] if d.get('routes') else None
        if not r0:
            continue
        cs = set()
        for r in d.get('routes') or []:
            for s in r.get('stops') or []:
                # עד שלושה מק"טים לשם: רשימה רחבה מזו כבר לא מזהה תחנה
                if len(s) > 4 and isinstance(s[4], list) and 0 < len(s[4]) <= 3:
                    cs.update(str(x) for x in s[4])
        if not cs:
            continue
        key = d['a'] + '-' + f.rsplit('l' + d['a'] + '-', 1)[-1][:-5]
        meta12[key] = (cs, {'k': key, 'no': d.get('no', ''), 'f': r0.get('f', ''),
                            'l': r0.get('l', ''), 'n': r0.get('n', 0),
                            'nr': len(d.get('routes', []))})
        for c in cs:
            inv[c].append(key)

    n_ov = n_fix = 0
    for p in glob.glob('line-history/data/lines/*.json'):
        try:
            lf = materialize(json.load(open(p, encoding='utf-8')))
        except Exception:
            continue
        vs = [v for v in (lf.get('versions') or []) if v.get('stops')]
        if not vs:
            continue
        # הגרסה הישנה ביותר שיש לנו — הקרובה ביותר ל-2012 מבין מה שידוע
        v0 = min(vs, key=lambda x: x.get('d') or '')
        cs = {s[0] for s in v0['stops'] if s and s[0]}
        cnt = collections.Counter()
        for c in cs:
            for k in inv.get(c, ()):
                cnt[k] += 1
        if not cnt:
            continue
        k, n = cnt.most_common(1)[0]
        # שני תנאים: מספר מוחלט של תחנות משותפות, וחלק משמעותי מהקצר
        # שבשני המסלולים — כדי שקו ארוך לא יבלע קו קצר שחולק איתו רחוב
        if n < 5 or n < 0.5 * min(len(cs), len(meta12[k][0])):
            continue
        rd = lf['rd']
        if rd in anchors and anchors[rd]['k'] != k:
            n_fix += 1
        elif rd not in anchors:
            n_ov += 1
        anchors[rd] = dict(meta12[k][1], ov=n)

    for a in anchors.values():
        a.pop('_s', None)
    out = {'gen2012': True, 'anchors': anchors}
    with open('line-history/data/anchor-2012.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False)
    print(f'קווי 2012 שנבדקו: {n2012} | וריאנטים של היום שקיבלו עוגן 2012: {len(anchors)} '
          f'| מחפיפת תחנות: {n_ov} חדשים, {n_fix} תוקנו')


if __name__ == '__main__':
    main()
