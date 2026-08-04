#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""שליפת המדד החברתי-כלכלי של הלמ"ס (אשכול 1–10 לכל יישוב) ממאגר
המידע הממשלתי (data.gov.il) — רץ על runner של GitHub (לסביבה המקומית
אין גישת רשת לדומיין).

פלט: parks/data/socio.json — {"year":…, "by_city":{שם יישוב: {"c":אשכול,
"r":דירוג}}, "source":…}
"""
import json
import re
import sys
import urllib.parse
import urllib.request

API = 'https://data.gov.il/api/3/action/'


def call(action, **params):
    url = API + action + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-data/1.0'})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if not d.get('success'):
        raise RuntimeError(f'{action} נכשל')
    return d['result']


def find_field(fields, *words):
    for f in fields:
        fid = f.get('id', '')
        if all(w in fid for w in words):
            return fid
    return None


def main():
    pkgs = []
    for q in ('מדד חברתי-כלכלי', 'מדד חברתי כלכלי', 'socio-economic'):
        try:
            pkgs += call('package_search', q=q, rows=20).get('results', [])
        except Exception as e:
            print('חיפוש נכשל:', q, e)
    seen = set()
    cands = []
    for p in pkgs:
        if p['id'] in seen:
            continue
        seen.add(p['id'])
        title = p.get('title', '')
        if 'חברתי' not in title or 'כלכלי' not in title:
            continue
        ym = re.findall(r'(20\d\d)', title + ' ' + (p.get('notes') or '')[:200])
        year = max(map(int, ym)) if ym else 0
        cands.append((year, title, p))
    cands.sort(key=lambda x: -x[0])
    print('מועמדים:', [(y, t[:60]) for y, t, _ in cands[:6]])

    for year, title, p in cands:
        for res in p.get('resources', []):
            if not res.get('datastore_active'):
                continue
            rid = res['id']
            try:
                probe = call('datastore_search', resource_id=rid, limit=5)
            except Exception as e:
                print('  דילוג על משאב:', rid, e)
                continue
            fields = probe.get('fields', [])
            f_cluster = find_field(fields, 'אשכול')
            f_name = (find_field(fields, 'שם', 'ישוב') or find_field(fields, 'שם', 'יישוב')
                      or find_field(fields, 'שם', 'רשות') or find_field(fields, 'שם'))
            f_rank = find_field(fields, 'דירוג')
            if not (f_cluster and f_name):
                print('  אין שדות מתאימים:', title[:40], [f.get('id') for f in fields][:8])
                continue
            print(f'נבחר: {title[:70]} | שנה {year} | שדות: {f_name} / {f_cluster}')
            rows = []
            offset = 0
            while True:
                chunk = call('datastore_search', resource_id=rid, limit=5000, offset=offset)
                rec = chunk.get('records', [])
                rows += rec
                if len(rec) < 5000:
                    break
                offset += 5000
            by_city = {}
            for r in rows:
                name = str(r.get(f_name) or '').strip()
                try:
                    c = int(float(r.get(f_cluster)))
                except (TypeError, ValueError):
                    continue
                if not name or not (1 <= c <= 10):
                    continue
                ent = {'c': c}
                if f_rank:
                    try:
                        ent['r'] = int(float(r.get(f_rank)))
                    except (TypeError, ValueError):
                        pass
                by_city[name] = ent
            if len(by_city) < 200:
                print('  מעט מדי יישובים:', len(by_city))
                continue
            out = {'year': year or None, 'source': title,
                   'n': len(by_city), 'by_city': by_city}
            with open('parks/data/socio.json', 'w', encoding='utf-8') as fh:
                json.dump(out, fh, ensure_ascii=False)
            print(f'נשמרו {len(by_city)} יישובים (שנת {year})')
            return
    sys.exit('לא נמצא מאגר מתאים עם datastore פעיל')


if __name__ == '__main__':
    main()
