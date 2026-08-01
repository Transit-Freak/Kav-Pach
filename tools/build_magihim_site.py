#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בניית נתוני אתר "רשת 2012" מתוך ענף magihim-data (תוצרי הסורק).

קורא את parsed/routes-agency-*.jsonl ואת state.json (שמות חברות) ישירות
מהענף המרוחק (git show), ומפיק:
  magihim-2012/data/index.json — רשימת קווים מקובצת: מספר קו, חברה, יעדים
  magihim-2012/data/l<agency>-<line>.json — קובץ לקו: כל וריאנטי המסלול והתחנות

מריצים שוב אחרי כל checkpoint כדי לרענן את האתר בנתונים העדכניים.
"""
import collections
import json
import pathlib
import re
import subprocess
import sys
import time

REF = 'origin/magihim-data'
OUT = pathlib.Path('magihim-2012/data')


def show(path):
    r = subprocess.run(['git', 'show', f'{REF}:{path}'], capture_output=True)
    return r.stdout.decode('utf-8') if r.returncode == 0 else None


def main():
    state = json.loads(show('state.json') or '{}')
    ag_names = {a: (m.get('name') or f'חברה {a}')
                for a, m in state.get('agencies', {}).items()}

    listing = subprocess.run(['git', 'ls-tree', '--name-only', REF, 'parsed/'],
                             capture_output=True, text=True).stdout.split()
    routes = {}   # rid -> row (דה-דופליקציה: שומרים את הגרסה העשירה ביותר)
    for f in listing:
        if not re.match(r'parsed/routes-agency-\d+\.jsonl$', f):
            continue
        for ln in (show(f) or '').splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            rid = str(row.get('route'))
            if rid not in routes or len(row.get('stops', [])) > len(routes[rid].get('stops', [])):
                routes[rid] = row

    # קיבוץ לפי מזהה הקו הפנימי של מגיעים — לא לפי המספר המוצג: "קו 1" של
    # ירושלים ו"קו 1" של קרית שמונה הם ישויות שונות עם אותו מספר
    lines = collections.defaultdict(list)   # (agency, line_id) -> [row]
    for row in routes.values():
        lines[(str(row['agency']), str(row.get('line')))].append(row)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('l*.json'):
        old.unlink()

    idx = []
    for (a, lid), rows in lines.items():
        rows.sort(key=lambda r: -len(r.get('stops', [])))
        title = rows[0].get('title', '')
        m = re.match(r'קו\s+(\S+)', title)
        no = m.group(1) if m else '?'
        dest = title.split(' - ', 1)[1] if ' - ' in title else ''
        key = f'{a}-{lid}'
        payload = {'a': a, 'an': ag_names.get(a, ''), 'no': no, 'dest': dest, 'routes': [
            {'rid': str(r.get('route')), 'n': len(r.get('stops', [])),
             'f': (r['stops'][0]['name'] if r.get('stops') else ''),
             'l': (r['stops'][-1]['name'] if r.get('stops') else ''),
             'stops': [[s['seq'], s['name'], s['t'], s['type']] for s in r.get('stops', [])]}
            for r in rows]}
        (OUT / f'l{key}.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        idx.append({'k': key, 'a': a, 'an': ag_names.get(a, ''), 'no': no,
                    'dest': dest, 'nr': len(rows),
                    'ns': max((len(r.get('stops', [])) for r in rows), default=0)})

    def sort_key(e):
        m = re.match(r'(\d+)', e['no'])
        return (int(e['a']) if e['a'].isdigit() else 999,
                int(m.group(1)) if m else 9999, e['no'])
    idx.sort(key=sort_key)

    total_lines_known = sum(len(m.get('lines') or []) for m in state.get('agencies', {}).values())
    (OUT / 'index.json').write_text(json.dumps({
        'gen': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
        'partial': True,
        'agencies': ag_names,
        'lines_known': total_lines_known,
        'routes_total': len(routes),
        'lines': idx,
    }, ensure_ascii=False), encoding='utf-8')
    print(f'נבנו {len(idx)} קווים | {len(routes)} מסלולים | '
          f'{sum(1 for _ in OUT.glob("l*.json"))} קבצים')


if __name__ == '__main__':
    main()
