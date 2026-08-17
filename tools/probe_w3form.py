#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""הקמת ערוץ טופס-הדיווח של המחירון דרך FormSubmit.

FormSubmit מעביר טפסים מאתרים סטטיים לתיבת מייל בלי חשבון ובלי מפתח:
שליחה ראשונה מפעילה מייל אישור חד-פעמי לבעל התיבה, ומרגע האישור
הטפסים עוברים. הכלי שולח שליחת-בדיקה (מצב ברירת מחדל), או — כשמועבר
ACTIVATE_URL — פותח את קישור האישור שהגיע במייל.
דוח: fares/checks/w3form-probe.json
"""
import json
import os
import time
import urllib.request

OUT = 'fares/checks/w3form-probe.json'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36'
EMAIL = 'shlomihartman@gmail.com'


def req(url, method='GET', payload=None):
    headers = {'User-Agent': UA, 'Accept': 'application/json, text/html'}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            return {'status': resp.status, 'body': resp.read(2500).decode('utf-8', 'replace')}
    except urllib.error.HTTPError as e:
        return {'status': e.code, 'body': e.read(1200).decode('utf-8', 'replace')}
    except Exception as e:
        return {'error': str(e)[:150]}


def main():
    report = {'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'steps': {}}
    act = os.environ.get('ACTIVATE_URL', '').strip()
    if act:
        if not act.startswith('https://formsubmit.co/'):
            report['steps']['activate'] = {'error': 'קישור לא של formsubmit — לא נפתח'}
        else:
            r = req(act)
            report['steps']['activate'] = {'status': r.get('status', r.get('error')),
                                           'body_head': (r.get('body') or '')[:300]}
    else:
        r = req('https://formsubmit.co/ajax/' + EMAIL, 'POST',
                {'name': 'בדיקת מערכת — המחירון', '_subject': 'הפעלת טופס הדיווח של המחירון',
                 'message': 'שליחת בדיקה להפעלת הערוץ. יגיע מייל אישור מ-FormSubmit — הקישור שבו נפתח אוטומטית.'})
        report['steps']['test_submit'] = r
    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('בוצע:', 'activate' if act else 'test_submit')


if __name__ == '__main__':
    main()
