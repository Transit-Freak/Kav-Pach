#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — העשרה מהמאגר הממשלתי: שנת ייצור, יצרן ודגם לכל לוחית.

קורא את fleet/data/fleet.json שנבנה בסריקת דאטאבוס, מצליב כל רכב מול
מאגר "כלי רכב ציבוריים פעילים" ב-data.gov.il לפי מספר הרכב, ומוסיף
לכל רכב שנמצא: [שנת ייצור, "יצרן דגם"]. רכב שלא נמצא נשאר כמות שהוא.

הצעד הזה הוא best-effort: אם המאגר הממשלתי לא זמין — הסריקה עדיין
תקפה והאתר עובד בלעדיו (הצעד רץ עם continue-on-error ב-workflow).
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
OUT = os.environ.get('OUT', 'fleet/data/fleet.json')
PAGE = 5000


def get(action, **params):
    url = f'{CKAN}/{action}?' + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-fleet/1.0'})
            with urllib.request.urlopen(req, timeout=180) as r:
                j = json.load(r)
            if not j.get('success'):
                raise RuntimeError(f'CKAN success=false: {action}')
            return j['result']
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            print(f'  retry {attempt + 1}: {e}', flush=True)
            time.sleep(5 * (attempt + 1))


def find_resource():
    """איתור דינמי של משאב 'כלי רכב ציבוריים פעילים' — בלי מזהה קשיח."""
    res = get('package_search', q='רכב ציבורי פעיל', rows=10)
    for pkg in res.get('results', []):
        title = (pkg.get('title') or '')
        if 'ציבורי' not in title:
            continue
        for r in pkg.get('resources', []):
            if r.get('datastore_active'):
                print(f"משאב: {title} · {r.get('name')} · {r['id']}", flush=True)
                return r['id']
    raise RuntimeError('לא נמצא משאב רכב ציבורי עם datastore')


def field_names(sample_record):
    """שמות השדות משתנים בין מאגרים — מזהים לפי מילות מפתח."""
    keys = {k.lower(): k for k in sample_record}

    def pick(*subs):
        for lk, k in keys.items():
            if any(s in lk for s in subs):
                return k
        return None

    return {
        'plate': pick('mispar_rechev', 'mispar rechev', 'license'),
        'year': pick('shnat_yitzur', 'shnat'),
        'maker': pick('tozeret_nm', 'tozeret'),
        'model': pick('degem_nm', 'kinuy', 'degem'),
    }


def load_registry(rid):
    """כל המאגר → מפה לוחית ← [שנה, "יצרן דגם"]."""
    reg, offset, fields = {}, 0, None
    while True:
        res = get('datastore_search', resource_id=rid, limit=PAGE, offset=offset)
        rows = res.get('records', [])
        if not rows:
            break
        if fields is None:
            fields = field_names(rows[0])
            print(f'שדות: {fields}', flush=True)
            if not fields['plate']:
                raise RuntimeError('לא זוהה שדה מספר רכב')
        for r in rows:
            plate = str(r.get(fields['plate']) or '').strip().replace('-', '')
            if not plate.isdigit():
                continue
            year = r.get(fields['year']) if fields['year'] else None
            maker = str(r.get(fields['maker']) or '').strip() if fields['maker'] else ''
            model = str(r.get(fields['model']) or '').strip() if fields['model'] else ''
            name = ' '.join(x for x in (maker, model) if x)
            try:
                year = int(year)
            except (TypeError, ValueError):
                year = None
            reg[plate] = [year, name]
        offset += PAGE
        if offset >= res.get('total', 0):
            break
    print(f'מאגר ממשלתי: {len(reg)} כלי רכב', flush=True)
    return reg


def main():
    with open(OUT, encoding='utf-8') as f:
        data = json.load(f)
    reg = load_registry(find_resource())
    hit = miss = 0
    for op in data['operators']:
        for v in op['vehicles']:
            plate = str(v[0]).strip().replace('-', '')
            info = reg.get(plate)
            del v[3:]  # ניקוי העשרה קודמת אם הסקריפט רץ שוב
            if info:
                v.extend(info)
                hit += 1
            else:
                miss += 1
    data['enriched'] = True
    tmp = f'{OUT}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f'העשרה: {hit} נמצאו · {miss} לא נמצאו במאגר', flush=True)


if __name__ == '__main__':
    sys.exit(main())
