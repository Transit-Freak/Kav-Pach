#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — העשרה מהמאגר הממשלתי: כל פרט קיים על כל רכב.

מקור הנתונים: קובץ ה-CSV של "כלי הרכב הציבוריים הפעילים" שמועלה ידנית
לריפו (fleet/data/*.csv) — כי data.gov.il חוסם שרתי ענן. אם אין קובץ
מקומי, מנסים את ה-API הישיר כגיבוי.

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
            # data.gov.il מחזיר 403 לבקשות בלי חתימת דפדפן מלאה
            req = urllib.request.Request(url, headers={
                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 (KHTML, like Gecko) '
                               'Chrome/126.0 Safari/537.36'),
                'Accept': 'application/json',
            })
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


def norm_plate(p):
    """נרמול לוחית: בלי מקפים ואפסים מובילים — ככה משווים רישוי מול SIRI."""
    p = str(p or '').strip().replace('-', '')
    return p.lstrip('0') if p.strip('0') else p


def load_local_csv(wanted):
    """מאגר הרישוי מקובץ ה-CSV שבריפו (מופרד ב-|) → לוחית ← רשומה מלאה."""
    import csv
    import glob
    outs = {os.path.basename(OUT)}
    cands = [p for p in glob.glob(os.path.join(os.path.dirname(OUT), '*.csv'))
             if os.path.basename(p) not in outs]
    if not cands:
        return None
    path = max(cands, key=os.path.getsize)
    reg = {}
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f, delimiter='|')
        for r in rd:
            plate = norm_plate(r.get('mispar_rechev'))
            if not plate.isdigit() or plate not in wanted:
                continue
            clean = {k: v.strip().strip('"') for k, v in r.items()
                     if k and v and v.strip() and v.strip() != 'NULL'}
            clean['_source'] = 'כלי רכב ציבוריים פעילים (קובץ בריפו)'
            reg[plate] = clean
    print(f'CSV מקומי {os.path.basename(path)}: {len(reg)} התאמות', flush=True)
    return reg, path


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
    """[שנה, "יצרן דגם", דלתות, סוג] לתצוגה בטבלה בלי לטעון את הפרטים המלאים."""
    def pick(*subs):
        for s in subs:                      # סדר העדיפות של המתקשר נשמר
            for k, v in rec.items():
                if s in k.lower():
                    return str(v).strip()
        return ''
    year = pick('shnat_yitzur', 'shnat')
    maker = pick('tozeret_nm', 'tozeret')
    model = pick('kinuy', 'degem_nm', 'degem')
    doors = pick('dlatot')
    vtype = pick('sug_rechev_nm', 'sug_rechev').replace('אוטובוס', '').strip() or None
    fuel = pick('sug_delek')
    if vtype and 'חשמל' in fuel and 'חשמל' not in vtype:
        vtype += ' חשמלי'
    try:
        year = int(float(year))
    except (TypeError, ValueError):
        year = None
    try:
        doors = int(float(doors))
    except (TypeError, ValueError):
        doors = None
    return [year, ' '.join(x for x in (maker, model) if x), doors, vtype]


def jdump(obj, path):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, path)


def main():
    with open(OUT, encoding='utf-8') as f:
        data = json.load(f)
    wanted = {norm_plate(v[0])
              for op in data['operators'] for v in op['vehicles']}
    loaded = load_local_csv(wanted)
    if loaded is None:
        reg, gov_date = load_registry(find_resources(), wanted), None
    else:
        reg, csv_path = loaded
        # מתי קובץ הרישוי הועלה לאחרונה לריפו — מוצג באתר כ"עדכון פרטי הרכב".
        # בצ'קאאוט רדוד git מייחס את הקובץ לקומיט הגבול (של היום) — תאריך שקרי,
        # ולכן במצב כזה עדיף לא לגעת בערך הקיים מאשר לדרוס אותו בתאריך שגוי.
        import subprocess
        try:
            shallow = subprocess.run(
                ['git', 'rev-parse', '--is-shallow-repository'],
                capture_output=True, text=True, timeout=30).stdout.strip()
            if shallow == 'true':
                print('אזהרה: צ׳קאאוט רדוד — תאריך העלאת הקובץ לא אמין, נשמר הערך הקודם', flush=True)
                gov_date = None
            else:
                gov_date = subprocess.run(
                    ['git', 'log', '-1', '--format=%cs', '--', csv_path],
                    capture_output=True, text=True, timeout=30).stdout.strip() or None
        except Exception:  # noqa: BLE001
            gov_date = None

    hit = miss = 0
    total = sum(len(op['vehicles']) for op in data['operators'])
    # הגנה: אם ההצלבה נכשלה כמעט לגמרי (מאגר חסר/שינוי שדות) — לא מסננים,
    # כדי שהאתר לא יתרוקן בגלל תקלה במקור הממשלתי
    strict = len(reg) >= max(100, total // 20)
    if not strict:
        print(f'אזהרה: רק {len(reg)} התאמות — מדלגים על סינון לא-מאומתים', flush=True)
    base = 4 if data.get('v') == 2 else 3   # v2: ההעשרה אחרי ממוצע הנסיעות
    for op in data['operators']:
        kept = []
        for v in op['vehicles']:
            plate = norm_plate(v[0])
            rec = reg.get(plate)
            del v[base:]  # ניקוי העשרה קודמת אם הסקריפט רץ שוב
            if rec:
                v.extend(short_info(rec))
                kept.append(v)
                hit += 1
            else:
                # רכב שאינו במאגר הרישוי הממשלתי — לא מוצג באתר
                # (מזהה פנימי של המפעיל, רכב שנגרט, או שידור שגוי)
                if not strict:
                    kept.append(v)
                miss += 1
        op['vehicles'] = kept
    # חברה שנשארה בלי רכבים מאומתים — לא מוצגת
    data['operators'] = [op for op in data['operators'] if op['vehicles']]
    data['enriched'] = True
    if gov_date:
        data['gov_updated'] = gov_date
    jdump(data, OUT)
    # הפרטים המלאים נחתכים ל-10 קבצים לפי הספרה האחרונה של הלוחית —
    # האתר טוען רק את הקובץ הרלוונטי בלחיצה על רכב (במקום קובץ ענק אחד)
    base_path = DETAILS.rsplit('.json', 1)[0]
    shards = {str(d): {} for d in range(10)}
    for plate, rec in reg.items():
        shards[plate[-1]][plate] = rec
    for d, shard in shards.items():
        jdump(shard, f'{base_path}-{d}.json')
    print(f'העשרה: {hit} נמצאו · {miss} לא נמצאו · פרטים מלאים: {DETAILS}', flush=True)


if __name__ == '__main__':
    sys.exit(main())
