# -*- coding: utf-8 -*-
# בדיקה חד-פעמית: איתור קו 1א נס ציונה בארכיון אופן באס — בכל התקופה.
# סורק חודש-חודש את רישום הקווים ומדפיס כל וריאנט ששמו 1א והיעד נס ציונה,
# עם המק"ט, הכיוון, החלופה וטווח התאריכים. דוח בלבד.
import json, os, time, urllib.parse, urllib.request

API = 'https://open-bus-stride-api.hasadna.org.il'
OUT = os.environ.get('OUT', 'parks/checks/nz1a-probe.json')
PAUSE = float(os.environ.get('PAUSE', '0.3'))

def api(path, **params):
    url = f'{API}{path}?{urllib.parse.urlencode(params)}'
    for a in range(4):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan/line-history (nz probe; polite)'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if a == 3:
                print('כשל:', url[:120], str(e)[:80])
                return None
            time.sleep(5)

found = {}
months = []
y, m = 2022, 1
while (y, m) <= (2026, 7):
    months.append(f'{y}-{m:02d}-15')
    m += 1
    if m > 12:
        y, m = y + 1, 1
print('חודשים לסריקה:', len(months))
for d in months:
    rows = []
    # א. כל הווריאנטים של מק"ט 32001 (חלופה יכולה להירשם בשם "1" עם שדה חלופה)
    for mk in ('32001', '032001'):
        rr = api('/gtfs_routes/list', date_from=d, date_to=d, route_mkt=mk, limit=300)
        time.sleep(PAUSE)
        if isinstance(rr, list):
            rows += rr
    # ב. כל קו ששמו 1 או 1א עם יעד נס ציונה — גם תחת מק"טים אחרים
    for sn in ('1', '1א'):
        rr = api('/gtfs_routes/list', date_from=d, date_to=d, route_short_name=sn, limit=300)
        time.sleep(PAUSE)
        if isinstance(rr, list):
            rows += [r for r in rr if 'נס ציונה' in str(r.get('route_long_name') or '')]
    for r in rows:
        ln = str(r.get('route_long_name') or '')
        key = (str(r.get('route_mkt')), str(r.get('route_direction')), str(r.get('route_alternative')))
        e = found.setdefault(key, {'mkt': key[0], 'dir': key[1], 'alt': key[2],
                                   'long': ln[:90], 'first': d, 'last': d, 'hits': 0})
        e['last'] = d
        e['hits'] += 1
        e['short'] = str(r.get('route_short_name') or '')
print('וריאנטים 1א נס ציונה שנמצאו:', len(found))
for e in found.values():
    print(f"  מק\"ט {e['mkt']} כיוון {e['dir']} חלופה {e['alt']} | {e['first']} → {e['last']} ({e['hits']} חודשים) | {e['long']}")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'checked': time.strftime('%Y-%m-%d %H:%M'), 'months': len(months),
           'variants': list(found.values())}, open(OUT, 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)
print('wrote', OUT)
