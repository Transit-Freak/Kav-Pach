#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — כל הנתונים ממאגר "ציי רכב אוטובוסים" של משרד התחבורה.

מעבר אחד על כל המאגר (כ-15 אלף רכבי חברה, בלי קבלנים) מפיק שני קבצים:
- fleet-armor.json — הממוגנים בלבד {'לוחית': 'y'/'s'/'ys'} (תגי ה-🛡️).
- fleet-official.json — המפרט הרשמי לכל רכב:
  {'לוחית': [מד-ק"מ, מושבים, ארץ ייצור, הנעה, סוג, גודל, אשכול]}
  כולל מד הקילומטרים הרשמי (בקשת שלמה) — המאגר מתעדכן שוטף.
"""
import datetime
import json
import os
import sys
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
RID = '91d298ed-a260-4f93-9d50-d5e3c5b82ce1'   # ציי רכב אוטובוסים
OUTDIR = os.environ.get('OUTDIR', 'fleet/data')


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-fleet/1.0'})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def key(plate):
    return ''.join(c for c in str(plate) if c.isdigit()).lstrip('0')


def main():
    armor, official = {}, {}
    nb = ns = 0
    offset = 0
    while True:
        d = get(f'{CKAN}/datastore_search?resource_id={RID}&limit=2000&offset={offset}')
        recs = d['result'].get('records') or []
        for r in recs:
            k = key(r.get('bus_license_id'))
            if not k:
                continue
            a = ''
            if r.get('bullet_proof_nm') == 'ממוגן ירי':
                a += 'y'
                nb += 1
            if r.get('stone_proof_nm') == 'ממוגן אבנים':
                a += 's'
                ns += 1
            if a:
                armor[k] = a
            official[k] = [r.get('total_kilometer'), r.get('SeatsNum'),
                           (r.get('production_country') or '').strip(),
                           (r.get('PropulsionType_nm') or '').strip(),
                           (r.get('BusType_nm') or '').strip(),
                           (r.get('BusSize_nm') or '').strip(),
                           (r.get('cluster_nm') or '').strip()]
        if len(recs) < 2000:
            break
        offset += 2000
    today = datetime.date.today().isoformat()
    for path, obj in [
        (f'{OUTDIR}/fleet-armor.json',
         {'updated': today, 'src': 'מאגר "ציי רכב אוטובוסים" — משרד התחבורה (data.gov.il)',
          'counts': {'bullet': nb, 'stone': ns}, 'armor': armor}),
        (f'{OUTDIR}/fleet-official.json',
         {'updated': today, 'src': 'מאגר "ציי רכב אוטובוסים" — משרד התחבורה (data.gov.il)',
          'of': official}),
    ]:
        tmp = f'{path}.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        os.replace(tmp, path)
    print(f'ציי רכב: {len(official)} רכבים · ממוגנים {len(armor)} ({nb} ירי · {ns} אבנים)',
          flush=True)


if __name__ == '__main__':
    sys.exit(main())
