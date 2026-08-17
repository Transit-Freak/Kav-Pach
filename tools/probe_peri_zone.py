#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""חיפוש הגדרת אזורי התעריף של "דרך שווה" במאגר הממשלתי הפתוח.

תקרת הפריפריה (139 ₪) חלה "מחוץ לשלושת המטרופולינים", אבל הגבול הרשמי
פורסם רק כמפה מצוירת בחומרי הרפורמה. הסריקה בודקת אם ב-data.gov.il
קיימת רשימת יישובים או שכבה גאוגרפית של אזורי התעריף — נתון שיאפשר
לאתר המחירון זיהוי מדויק של נסיעת פריפריה במקום הקירוב הגאוגרפי
השמרני של היום. דוח בלבד: fares/checks/peri-zone-probe.json.
"""
import json
import time
import urllib.parse
import urllib.request

BASE = 'https://data.gov.il/api/3/action/'
UA = 'kav-bochan-fares/1.0 (derech-shava zone probe)'
OUT = 'fares/checks/peri-zone-probe.json'

QUERIES = ['דרך שווה', 'אזורי תעריף', 'צדק תחבורתי', 'רפורמת התעריפים',
           'תעריפי תחבורה ציבורית', 'חופשי חודשי', 'פריפריה תחבורה',
           'מטרופולין', 'רב קו', 'אזור תעריף 1']
HOT = ('תעריף', 'אזור', 'פריפריה', 'מטרופולין', 'דרך שווה', 'חופשי', 'רב-קו', 'רב קו')


def api(action, **params):
    url = BASE + action + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'user-agent': UA, 'accept': 'application/json'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:
            if attempt == 2:
                return {'error': str(e)}
            time.sleep(20)


def pkg_row(p):
    return {
        'id': p.get('name'),
        'title': p.get('title'),
        'org': (p.get('organization') or {}).get('title'),
        'resources': [{
            'id': r.get('id'), 'name': r.get('name'), 'format': r.get('format'),
            'datastore': bool(r.get('datastore_active')),
        } for r in p.get('resources') or []],
    }


def main():
    report = {'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()),
              'queries': {}, 'mot_packages': [], 'samples': {}}

    seen = {}
    for q in QUERIES:
        res = api('package_search', q=q, rows=15)
        hits = ((res or {}).get('result') or {}).get('results') or []
        rows = []
        for p in hits:
            title = p.get('title') or ''
            if not any(h in title for h in HOT) and not any(
                    h in (p.get('notes') or '') for h in HOT):
                continue
            row = pkg_row(p)
            rows.append(row)
            seen[row['id']] = row
        report['queries'][q] = rows if rows else (res.get('error') or 'אין תוצאות רלוונטיות')

    # כל מאגרי הארגונים שקשורים לתחבורה — כדי לעבור בעין על הכותרות
    orgs = api('organization_list', q='תחבורה', all_fields='true')
    for o in (orgs or {}).get('result') or []:
        det = api('organization_show', id=o.get('name'), include_datasets='true')
        pkgs = ((det or {}).get('result') or {}).get('packages') or []
        report['mot_packages'].append({
            'org': o.get('display_name') or o.get('name'),
            'packages': [p.get('title') for p in pkgs],
        })

    # דגימת שדות לכל מועמד עם datastore — האם יש עמודות יישוב/אזור?
    for pid, row in list(seen.items())[:20]:
        for r in row['resources']:
            if not r['datastore']:
                continue
            s = api('datastore_search', resource_id=r['id'], limit=3)
            result = (s or {}).get('result') or {}
            fields = [f.get('id') for f in result.get('fields') or []]
            sample = result.get('records') or []
            report['samples'][f"{pid}/{r['name']}"] = {'fields': fields, 'sample': sample[:2]}

    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n = sum(len(v) for v in report['queries'].values() if isinstance(v, list))
    print(f'נסרקו {len(QUERIES)} שאילתות · {n} מאגרים רלוונטיים · '
          f'{len(report["samples"])} משאבים נדגמו → {OUT}')


if __name__ == '__main__':
    main()
