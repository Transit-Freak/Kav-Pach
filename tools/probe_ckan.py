#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקה חד-פעמית של data.gov.il (רץ ב-Actions, הפלט ללוג בלבד):
1. רישוי 2026 — כמה שורות יש לכל אחד מעשרת הימים האחרונים (האם היום האחרון חלקי).
2. רישוי 2022 — אילו דרכים עובדות לקריאת קובץ שנתי: SQL מקובץ (datastore_search_sql),
   הורדה ישירה של ה-CSV עם כותרות שונות, ודפדוף ב-datastore_search עם offset גדול.
3. ביצוע נסיעות 2026/2025 — אילו תאריכים (trip_dt) קיימים בקובץ.
"""
import datetime
import json
import time
import urllib.error
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
UA = {'User-Agent': 'kav-bochan-linehistory/1.0', 'Referer': 'https://data.gov.il/'}
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
           'Accept': 'text/csv,*/*;q=0.8', 'Accept-Language': 'he,en;q=0.8'}
RISHUI_2026 = '58593e9b-2d71-4c39-8663-b34ab29607ab'
RISHUI_2022 = '8fd3aa6c-a64f-4c91-818e-fd35017cd19b'
BITZUA = {'2026': 'eafccff0-7552-44ee-8beb-26e5c3d94133', '2025': '084b8e33-e359-47aa-95f7-26782e52c9af'}


def log(*a):
    print(*a, flush=True)


def getj(url, headers=UA, timeout=300):
    t = time.time()
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode('utf-8')), time.time() - t, len(body)


def ds(rid, **kw):
    q = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in kw.items())
    return getj(f'{CKAN}/datastore_search?resource_id={rid}&{q}')


log('=== 1. רישוי 2026 — שורות לכל יום (10 ימים אחרונים) ===')
today = datetime.date.today()
for back in range(0, 10):
    d = (today - datetime.timedelta(days=back)).isoformat()
    try:
        j, dt, _ = ds(RISHUI_2026, filters=json.dumps({'rishui_date': d}), limit=1)
        log(f'  {d}: total={j["result"].get("total")} · {dt:.1f} שנ׳')
    except Exception as e:  # noqa: BLE001
        log(f'  {d}: שגיאה {e}')

log('\n=== 2. רישוי 2022 — דרכי קריאה ===')
log('--- 2א. datastore_search_sql מקובץ ---')
sql = (f'SELECT "office_line_id","VehicleType_nm","VehicleSize_nm", MIN("rishui_date") AS a, MAX("rishui_date") AS b, COUNT(*) AS n '
       f'FROM "{RISHUI_2022}" GROUP BY 1,2,3')
try:
    j, dt, sz = getj(f'{CKAN}/datastore_search_sql?sql={urllib.parse.quote(sql)}', timeout=600)
    recs = j.get('result', {}).get('records', [])
    log(f'  הצלחה: {len(recs):,} קבוצות · {dt:.1f} שנ׳ · {sz/1e6:.1f}MB · דוגמה: {json.dumps(recs[:2], ensure_ascii=False)[:300]}')
except urllib.error.HTTPError as e:
    log(f'  HTTP {e.code}: {e.read()[:300]!r}')
except Exception as e:  # noqa: BLE001
    log(f'  שגיאה: {e}')

log('--- 2ב. הורדה ישירה (Range 0-1023) ---')
try:
    pkg = getj(f'{CKAN}/package_show?id=licensing_bus_system')[0]['result']
    url22 = next(r['url'] for r in pkg['resources'] if r['id'] == RISHUI_2022)
except Exception as e:  # noqa: BLE001
    url22 = f'https://data.gov.il/dataset/a38ee853-150f-4360-9177-669063f3322b/resource/{RISHUI_2022}/download/{RISHUI_2022}.csv'
    log(f'  package_show שגיאה: {e}')
variants = [
    ('url של package_show + UA שלנו', url22, UA),
    ('url של package_show + דפדפן', url22, BROWSER),
    ('url של package_show + בלי כותרות', url22, {}),
    ('data.gov.il במקום e.data.gov.il + דפדפן', url22.replace('https://e.data.gov.il/', 'https://data.gov.il/'), BROWSER),
    ('נתיב datastore/dump + UA שלנו', f'https://data.gov.il/datastore/dump/{RISHUI_2022}?format=csv', UA),
    ('נתיב datastore/dump + דפדפן', f'https://data.gov.il/datastore/dump/{RISHUI_2022}?format=csv', BROWSER),
]
for name, u, h in variants:
    try:
        req = urllib.request.Request(u, headers={**h, 'Range': 'bytes=0-1023'})
        t = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
            b = r.read(1024)
            log(f'  ✓ {name}: {r.status} · {r.headers.get("Content-Type")} · Content-Range={r.headers.get("Content-Range")} · {time.time()-t:.1f} שנ׳ · {b[:120]!r}')
    except urllib.error.HTTPError as e:
        log(f'  ✗ {name}: HTTP {e.code} · {e.read()[:150]!r}')
    except Exception as e:  # noqa: BLE001
        log(f'  ✗ {name}: {e}')

log('--- 2ג. datastore_search בדפדוף (offset גדול) ---')
for off in (0, 1000000):
    try:
        j, dt, sz = ds(RISHUI_2022, fields='office_line_id,rishui_date,VehicleType_nm,VehicleSize_nm', limit=32000, offset=off)
        recs = j['result'].get('records', [])
        log(f'  offset={off:,}: {len(recs):,} שורות · total={j["result"].get("total")} · {dt:.1f} שנ׳ · {sz/1e6:.1f}MB · ראשונה {json.dumps(recs[:1], ensure_ascii=False)}')
    except Exception as e:  # noqa: BLE001
        log(f'  offset={off:,}: שגיאה {e}')

log('\n=== 3. ביצוע נסיעות — תאריכים בקובץ ===')
for y, rid in BITZUA.items():
    try:
        j, dt, sz = ds(rid, distinct='true', fields='trip_dt', limit=2000)
        ds_ = sorted(str(r.get('trip_dt') or '')[:10] for r in j['result'].get('records', []))
        log(f'  {y}: {len(ds_)} תאריכים · {dt:.1f} שנ׳ · ראשון {ds_[:1]} · אחרון {ds_[-1:]}')
        log(f'    כולם: {" ".join(ds_)}')
    except Exception as e:  # noqa: BLE001
        log(f'  {y}: distinct שגיאה {e}')
        for order in ('asc', 'desc'):
            try:
                j, dt, _ = ds(rid, sort=f'trip_dt {order}', fields='trip_dt', limit=1)
                log(f'    sort {order}: {j["result"].get("records")} · {dt:.1f} שנ׳')
            except Exception as e2:  # noqa: BLE001
                log(f'    sort {order}: שגיאה {e2}')
    # כמה שורות ביום לדוגמה
    for d in ('2026-02-25', '2026-03-10', '2026-05-12'):
        if y != '2026':
            break
        try:
            j, dt, _ = ds(rid, filters=json.dumps({'trip_dt': d}), limit=1)
            log(f'    {d}: total={j["result"].get("total")} · {dt:.1f} שנ׳')
        except Exception as e:  # noqa: BLE001
            log(f'    {d}: שגיאה {e}')
