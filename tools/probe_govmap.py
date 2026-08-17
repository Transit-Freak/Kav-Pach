#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בדיקת GovMap כמקור כתובות למחירון — במקום/לצד Nominatim.

GovMap (מרכז מיפוי ישראל) בנוי על מרשם הכתובות הארצי, וזה השירות
שאתר bus.gov.il עצמו משתמש בו. הבדיקה: אילו endpoints של חיפוש
עונים, האם הם מחזירים כותרות CORS שמאפשרות קריאה מדפדפן של אתר
חיצוני, ובאיזה פורמט הקואורדינטות (ITM/WGS84).
דוח: fares/checks/govmap-probe.json
"""
import json
import time
import urllib.parse
import urllib.request

OUT = 'fares/checks/govmap-probe.json'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'
Q = 'הרב עובדיה יוסף 5 קרית מלאכי'
Q2 = 'רוטשילד 1 תל אביב'


def try_req(url, method='GET', body=None, origin='https://transit-freak.github.io'):
    headers = {'User-Agent': UA, 'Accept': 'application/json', 'Origin': origin}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    out = {'method': method}
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                out['status'] = r.status
                h = {k.lower(): v for k, v in r.headers.items()}
                out['cors'] = {k: v for k, v in h.items() if k.startswith('access-control')}
                out['body'] = r.read(3000).decode('utf-8', 'replace')
                return out
        except urllib.error.HTTPError as e:
            out['status'] = e.code
            out['body'] = e.read(500).decode('utf-8', 'replace')
            return out
        except Exception as e:
            out['error'] = str(e)[:150]
            time.sleep(10)
    return out


def main():
    enc = urllib.parse.quote(Q)
    tests = {
        'tld_autocomplete': ('GET', f'https://es.govmap.gov.il/TldSearch/api/AutoComplete?ids=276267023&text={enc}&gid=govmap', None),
        'tld_details': ('GET', f'https://es.govmap.gov.il/TldSearch/api/DetailsByQuery?query={enc}&lyrs=276267023&gid=govmap', None),
        'new_autocomplete': ('POST', 'https://www.govmap.gov.il/api/search-service/autocomplete',
                             {'searchText': Q2, 'language': 'he', 'isAccurate': False, 'maxResults': 10}),
        'api_search': ('GET', f'https://www.govmap.gov.il/api/search-service/autocomplete?searchText={urllib.parse.quote(Q2)}', None),
        'api_js': ('GET', 'https://www.govmap.gov.il/govmap/api/govmap.api.js', None),
    }
    report = {'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'tests': {}}
    for name, (method, url, body) in tests.items():
        report['tests'][name] = {'url': url} | try_req(url, method, body)
    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('נבדקו', len(tests), 'endpoints →', OUT)


if __name__ == '__main__':
    main()
