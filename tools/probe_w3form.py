#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""בקשת מפתח Web3Forms לטופס הדיווח של המחירון.

Web3Forms מעביר טפסים מאתרים סטטיים ישירות לתיבת מייל — בלי חשבון,
רק מפתח שנשלח למייל של בעל האתר. הכלי מאתר את ה-endpoint של יצירת
המפתח באתר שלהם ומבקש מפתח עבור תיבת המחירון; המפתח מגיע למייל של
שלמה ומוזן ידנית ל-fares/index.html (W3K).
דוח: fares/checks/w3form-probe.json (בלי סודות — המפתח לא עובר כאן).
"""
import json
import re
import time
import urllib.request

OUT = 'fares/checks/w3form-probe.json'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'
EMAIL = 'shlomihartman@gmail.com'


def req(url, method='GET', payload=None, ctype='application/json'):
    headers = {'User-Agent': UA, 'Accept': 'application/json, text/html'}
    data = None
    if payload is not None:
        if ctype == 'application/json':
            data = json.dumps(payload).encode()
        else:
            from urllib.parse import urlencode
            data = urlencode(payload).encode()
        headers['Content-Type'] = ctype
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return {'status': resp.status, 'body': resp.read(2000).decode('utf-8', 'replace')}
    except urllib.error.HTTPError as e:
        return {'status': e.code, 'body': e.read(800).decode('utf-8', 'replace')}
    except Exception as e:
        return {'error': str(e)[:150]}


def main():
    report = {'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'steps': {}}
    home = req('https://web3forms.com')
    endpoints = sorted(set(re.findall(r'https://api\.web3forms\.com/[\w/-]+', home.get('body', ''))))
    report['steps']['home'] = {'status': home.get('status'), 'endpoints_found': endpoints}

    # מועמדים ליצירת מפתח — הידועים + מה שנמצא בדף
    cands = ['https://api.web3forms.com/keys', 'https://api.web3forms.com/key',
             'https://api.web3forms.com/access-keys'] + [e for e in endpoints if 'key' in e]
    for url in dict.fromkeys(cands):
        for ctype in ('application/json', 'application/x-www-form-urlencoded'):
            r = req(url, 'POST', {'email': EMAIL}, ctype)
            key = f'{url} [{ctype.split("/")[-1]}]'
            report['steps'][key] = r
            if r.get('status') == 200 and 'success' in r.get('body', '').lower():
                report['steps'][key]['note'] = 'נראה שהצליח — המפתח אמור להגיע למייל'
                json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                print('בקשת מפתח נשלחה בהצלחה')
                return
    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('אף endpoint לא אישר — ראו דוח')


if __name__ == '__main__':
    main()
