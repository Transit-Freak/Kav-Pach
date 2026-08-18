#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — העשרה מהמאגר הממשלתי: כל פרט קיים על כל רכב.

שני תוצרים:
1. fleet/data/fleet.json — לכל רכב מתווספים [שנת ייצור, "יצרן דגם"]
   (קומפקטי, לכרטיסים ולטבלה).
2. fleet/data/gov-details.json — לכל לוחית: *כל* השדות כפי שהם במאגר
   הממשלתי, בלי לוותר על אף אחד. האתר טוען אותו רק בלחיצה על רכב.

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
DETAILS = os.environ.get('DETAILS', 'fleet/data/gov-details.json')
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


def find_resources():
    """כל משאבי ה-datastore שקשורים לרכב ציבורי — יכולים להיות כמה מאגרים
    (פעילים, מבוטלים, הסעות) ואנחנו רוצים את כולם."""
    seen, out = set(), []
    for q in ('רכב ציבורי פעיל', 'אוטובוסים', 'רכב ציבורי'):
        res = get('package_search', q=q, rows=10)
        for pkg in res.get('results', []):
            title = pkg.get('title') or ''
            if 'ציבורי' not in title and 'אוטובוס' not in title:
                continue
            for r in pkg.get('resources', []):
                if r.get('datastore_active') and r['id'] not in seen:
                    seen.add(r['id'])
                    out.append((title, r['id']))
                    print(f"משאב: {title} · {r.get('name')} · {r['id']}", flush=True)
    if not out:
        raise RuntimeError('לא נמצא משאב רכב ציבורי עם datastore')
    return out


def plate_key(record):
    """שם שדה מספר הרכב ברשומה."""
    for k in record:
        lk = k.lower()
        if 'mispar_rechev' in lk or lk == 'mispar rechev' or 'license' in lk:
            return k
    return None


def load_registry(resources, wanted):
    """כל המאגרים → מפה לוחית ← רשומה מלאה (כל השדות, ללא ריקים).
    נשמרות רק לוחיות שמופיעות בסריקה (wanted) — לא כל 65 אלף כלי הרכב."""
    reg = {}
    for title, rid in resources:
        offset, pk = 0, None
        while True:
            res = get('datastore_search', resource_id=rid, limit=PAGE, offset=offset)
            rows = res.get('records', [])
            if not rows:
                break
            if pk is None:
                pk = plate_key(rows[0])
                if not pk:
                    print(f'  {rid}: אין שדה מספר רכב — דילוג', flush=True)
                    break
            for r in rows:
                plate = str(r.get(pk) or '').strip().replace('-', '')
                if not plate.isdigit() or plate not in wanted:
                    continue
                clean = {k: v for k, v in r.items()
                         if k != '_id' and v not in (None, '', 'NULL')}
                clean['_source'] = title
                # מאגר שני לא דורס — רק משלים שדות חסרים
                if plate in reg:
                    for k, v in clean.items():
                        reg[plate].setdefault(k, v)
                else:
                    reg[plate] = clean
            offset += PAGE
            if offset >= res.get('total', 0):
                break
    print(f'מאגר ממשלתי: {len(reg)} התאמות ללוחיות מהסריקה', flush=True)
    return reg


def short_info(rec):
    """[שנה, "יצרן דגם"] לתצוגה הקומפקטית."""
    def pick(*subs):
        for k, v in rec.items():
            lk = k.lower()
            if any(s in lk for s in subs):
                return str(v).strip()
        return ''
    year = pick('shnat_yitzur', 'shnat')
    maker = pick('tozeret_nm', 'tozeret')
    model = pick('kinuy', 'degem_nm', 'degem')
    try:
        year = int(float(year))
    except (TypeError, ValueError):
        year = None
    return [year, ' '.join(x for x in (maker, model) if x)]


def jdump(obj, path):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def main():
    with open(OUT, encoding='utf-8') as f:
        data = json.load(f)
    wanted = {str(v[0]).strip().replace('-', '')
              for op in data['operators'] for v in op['vehicles']}
    reg = load_registry(find_resources(), wanted)

    hit = miss = 0
    for op in data['operators']:
        for v in op['vehicles']:
            plate = str(v[0]).strip().replace('-', '')
            rec = reg.get(plate)
            del v[3:]  # ניקוי העשרה קודמת אם הסקריפט רץ שוב
            if rec:
                v.extend(short_info(rec))
                hit += 1
            else:
                miss += 1
    data['enriched'] = True
    jdump(data, OUT)
    jdump(reg, DETAILS)
    print(f'העשרה: {hit} נמצאו · {miss} לא נמצאו · פרטים מלאים: {DETAILS}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
