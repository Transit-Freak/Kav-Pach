#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — מיגון ירי/אבנים מהמאגר "ציי רכב אוטובוסים".

מאגר הרישוי הציבורי (ההעשרה הרגילה) לא כולל מיגון; משרד התחבורה
מפרסם אותו במאגר נפרד — bus_fleet, עם שדות bullet_proof_nm ו-
stone_proof_nm לכל אוטובוס. נשמרים רק הממוגנים (כ-500 רכבים):
fleet/data/fleet-armor.json — {'armor': {לוחית: 'y'|'s'|'ys'}}.
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
RID = '91d298ed-a260-4f93-9d50-d5e3c5b82ce1'   # ציי רכב אוטובוסים
OUTDIR = os.environ.get('OUTDIR', 'fleet/data')
OUT = f'{OUTDIR}/fleet-armor.json'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-fleet/1.0'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def fetch(field, value):
    out, offset = [], 0
    flt = urllib.parse.quote(json.dumps({field: value}, ensure_ascii=False))
    while True:
        d = get(f'{CKAN}/datastore_search?resource_id={RID}&filters={flt}'
                f'&limit=1000&offset={offset}')
        recs = d['result'].get('records') or []
        out += recs
        if len(recs) < 1000:
            return out, d['result'].get('total')
        offset += 1000


def key(plate):
    return ''.join(c for c in str(plate) if c.isdigit()).lstrip('0')


def main():
    armor = {}
    bullet, tb = fetch('bullet_proof_nm', 'ממוגן ירי')
    for r in bullet:
        k = key(r.get('bus_license_id'))
        if k:
            armor[k] = armor.get(k, '') + 'y'
    stone, ts = fetch('stone_proof_nm', 'ממוגן אבנים')
    for r in stone:
        k = key(r.get('bus_license_id'))
        if k and 's' not in armor.get(k, ''):
            armor[k] = armor.get(k, '') + 's'
    res = {'updated': datetime.date.today().isoformat(),
           'src': 'מאגר "ציי רכב אוטובוסים" — משרד התחבורה (data.gov.il)',
           'counts': {'bullet': tb, 'stone': ts},
           'armor': armor}
    tmp = f'{OUT}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, OUT)
    print(f'מיגון: {len(armor)} רכבים ({tb} ירי · {ts} אבנים)', flush=True)


if __name__ == '__main__':
    sys.exit(main())
