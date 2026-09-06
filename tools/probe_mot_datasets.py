#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקה חד-פעמית: מה יש במאגרי משרד התחבורה ב-data.gov.il שמופיעים בעמוד
"מאגרי מידע" של הרשות הארצית לתחבורה ציבורית (שלמה 06.09):
רישוי לפי מק"ט קו, תכנון מול ביצוע (חודשי, ולפי נסיעה בודדת עם GPS), זמני הגעה
לתחנה, רכבת ברמת תחנה ונסיעה, ורכבים ציבוריים פעילים. לכל מאגר: המשאבים
(שם, פורמט, גודל, עדכון אחרון), השדות, ושלוש רשומות לדוגמה.
הפלט: docs/fetched/mot-datasets.txt. רץ ב-Actions (data.gov.il חסום מהמכולה)."""
import json
import sys
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
QUERIES = [
    ('רישוי אוטובוסים לפי מק"ט קו', 'licensing_bus_system'),
    ('תכנון וביצוע אוטובוסים (חודשי)', 'Bus_rishui_bitzua'),
    ('תכנון מול ביצוע לפי נסיעה בודדת (GPS)', 'risui_bitzua_bus_trip'),
    ('זמני הגעה לתחנה לפי שעה', 'ArrivalToStationHours'),
    ('זמני הגעה לתחנה לפי יום ושעה', 'ArrivalToStationDayandHours'),
    ('רכבת לו"ז ברמת תחנה', 'Train_luz_station'),
    ('רכבת תכנון מול ביצוע', 'train_trip'),
    ('רכבים ציבוריים פעילים', 'kli_rechev_ciburiim'),
    ('ציי רכב אוטובוסים', 'Bus_fleet'),
    ('תחנות אוטובוסים', 'bus_stops_stations'),
]
out = []


def log(s=''):
    print(s, flush=True)
    out.append(s)


def get(url, timeout=90):
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-probe/1.0', 'Referer': 'https://data.gov.il/'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def getj(url):
    return json.loads(get(url).decode('utf-8'))


def head_bytes(url, n=65536):
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-probe/1.0', 'Range': f'bytes=0-{n - 1}', 'Referer': 'https://data.gov.il/'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(n), r.headers.get('Content-Length'), r.headers.get('Content-Range')


seen = set()
for title, q in QUERIES:
    log(f'\n=== {title} · חיפוש: {q} ===')
    try:
        res = getj(f'{CKAN}/package_search?q={urllib.parse.quote(q)}&rows=6')['result']
    except Exception as e:  # noqa: BLE001
        log(f'  שגיאה בחיפוש: {e}')
        continue
    log(f'  נמצאו {res.get("count")} מאגרים')
    for pkg in res.get('results', []):
        if pkg['id'] in seen:
            log(f'  (כבר הוצג: {pkg.get("title")})')
            continue
        seen.add(pkg['id'])
        log(f'  * מאגר: {pkg.get("title")} · name={pkg.get("name")} · ארגון={pkg.get("organization", {}).get("title")} · עודכן={pkg.get("metadata_modified")} · רישיון={pkg.get("license_title")}')
        notes = (pkg.get('notes') or '').replace('\n', ' ')[:300]
        if notes:
            log(f'    תיאור: {notes}')
        for r in pkg.get('resources', [])[:12]:
            log(f'    - משאב: {r.get("name")} · {r.get("format")} · {r.get("size")} בייט · עודכן={r.get("last_modified")} · datastore={r.get("datastore_active")} · id={r.get("id")}')
            log(f'      url={r.get("url")}')
            if r.get('datastore_active'):
                try:
                    d = getj(f'{CKAN}/datastore_search?resource_id={r["id"]}&limit=3')['result']
                    log(f'      שדות: {[f["id"] for f in d.get("fields", [])]}')
                    log(f'      סה"כ רשומות: {d.get("total")}')
                    for rec in d.get('records', [])[:3]:
                        log(f'      דוגמה: {json.dumps(rec, ensure_ascii=False)[:400]}')
                except Exception as e:  # noqa: BLE001
                    log(f'      datastore שגיאה: {e}')
            elif (r.get('format') or '').upper() in ('CSV', 'TXT', 'XLSX', 'XLS', 'ZIP') and r.get('url'):
                try:
                    b, cl, cr = head_bytes(r['url'])
                    log(f'      הורדה חלקית: {len(b)} בייט · Content-Length={cl} · Content-Range={cr}')
                    if (r.get('format') or '').upper() in ('CSV', 'TXT'):
                        txt = b.decode('utf-8-sig', errors='replace')
                        for line in txt.splitlines()[:4]:
                            log(f'      שורה: {line[:400]}')
                except Exception as e:  # noqa: BLE001
                    log(f'      הורדה שגיאה: {e}')

with open('docs/fetched/mot-datasets.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out) + '\n')
log('\nנכתב docs/fetched/mot-datasets.txt')
