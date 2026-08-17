#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ציד מקור הנתונים של אזורי התעריף — איך אפליקציות התשלום יודעות?

רב-פס, הופ-און ו-bus.gov.il מחשבים את תקרת הפריפריה, ולכן חייב להיות
קובץ נתונים (רשימת יישובים או פוליגון) שהם טוענים. הסריקה מושכת את
הדפים הרלוונטיים ואת קובצי ה-JS/JSON שהם מפנים אליהם, ומחפשת בתוכם
עדות להגדרת האזורים: שמות ערים גבוליות לצד מילות מפתח של אזור/תעריף,
כתובות API של תעריפים, או קובצי GeoJSON. דוח: fares/checks/fare-zone-src.json
"""
import json
import re
import time
import urllib.parse
import urllib.request

OUT = 'fares/checks/fare-zone-src.json'
UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/126.0 Safari/537.36')

PAGES = [
    'https://bus.gov.il/FaresDistance',
    'https://bus.gov.il/FaresDiscounts',
    'https://bus.gov.il/',
    'https://ravpass.co.il/calculator/',
    'https://ravpass.co.il/%D7%A6%D7%93%D7%A7-%D7%AA%D7%97%D7%91%D7%95%D7%A8%D7%AA%D7%99/',
    'https://s3-eu-west-1.amazonaws.com/static.hopon.co.il/mot/ravPassPrices.html',
    'https://s3-eu-west-1.amazonaws.com/static.hopon.co.il/mot/profiles.html',
]

# מילים שמסגירות הגדרת אזורים, וערים גבוליות שיכריעו איזה צד של הגבול
KEYS = ['אזור 1', 'אזור1', 'פריפר', 'מטרופול', 'zone', 'Zone', 'periphery',
        'geojson', 'GeoJSON', 'polygon']
CITIES = ['קרית מלאכי', 'קריית מלאכי', 'חדרה', 'אשקלון', 'קרית גת', 'קריית גת',
          'עפולה', 'נתניה', 'באר שבע']


def get(url, limit=6_000_000):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': '*/*',
                                               'Accept-Language': 'he,en;q=0.8'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read(limit).decode('utf-8', 'replace')
        except Exception as e:
            if attempt == 2:
                return f'__ERR__ {e}'
            time.sleep(15)


def snippets(text, needles, ctx=140, cap=8):
    out = []
    for n in needles:
        for m in re.finditer(re.escape(n), text):
            s = text[max(0, m.start() - ctx):m.end() + ctx].replace('\n', ' ')
            out.append(s.strip())
            if len(out) >= cap:
                return out
    return out


def asset_urls(html, base):
    urls = set()
    for m in re.finditer(r'(?:src|href)=["\']([^"\']+\.(?:js|json))(?:\?[^"\']*)?["\']', html):
        urls.add(urllib.parse.urljoin(base, m.group(1)))
    # קריאות fetch/api בתוך העמוד עצמו
    for m in re.finditer(r'["\'](https?://[^"\']*(?:api|Api|fare|Fare|zone|Zone)[^"\']*)["\']', html):
        urls.add(m.group(1))
    return list(urls)[:25]


def dissect_bundle(report):
    """ניתוח ממוקד של ה-bundle של bus.gov.il: רכיב mapOfAreas נמצא שם —
    מחלצים את ההקשר סביבו, ואת כל הכתובות שהקוד טוען, כדי לאתר את
    קובץ/שירות הנתונים של אזורי התעריף."""
    html = get('https://bus.gov.il/')
    m = re.search(r'src=["\']((?:[^"\']*/)?main-[\w]+\.js)["\']', html or '')
    if not m:
        report['bundle'] = {'error': 'main bundle לא נמצא'}
        return
    burl = urllib.parse.urljoin('https://bus.gov.il/', m.group(1))
    body = get(burl, limit=20_000_000)
    if body.startswith('__ERR__'):
        report['bundle'] = {'error': body[:150]}
        return
    b = {'url': burl, 'bytes': len(body)}
    b['map_of_areas_ctx'] = snippets(body, ['apOfAreas', 'apofareas'], ctx=400, cap=40)
    b['zone_ctx'] = snippets(body, ['zone1NoVat', 'OutsideZones', 'CenterInZone'], ctx=400, cap=20)
    b['urls'] = sorted(set(re.findall(r'https?://[\w.-]+[\w./?=&%-]*', body)))[:120]
    b['json_refs'] = sorted(set(re.findall(r'["\']([\w./-]+\.(?:geo)?json)["\']', body)))[:60]
    b['api_ctx'] = snippets(body, ['api.bus.gov.il', '/api/', 'arcgis', 'ArcGIS'], ctx=250, cap=25)
    report['bundle'] = b


def main():
    report = {'generated': time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), 'pages': {}}
    dissect_bundle(report)
    for page in PAGES:
        html = get(page)
        entry = {'bytes': len(html)}
        if html.startswith('__ERR__'):
            entry['error'] = html
            report['pages'][page] = entry
            continue
        entry['key_hits'] = snippets(html, KEYS)
        entry['city_hits'] = snippets(html, CITIES)
        assets = asset_urls(html, page)
        entry['assets'] = {}
        for a in assets:
            body = get(a)
            if body.startswith('__ERR__'):
                entry['assets'][a] = {'error': body[:120]}
                continue
            hits = snippets(body, KEYS, cap=6)
            cities = snippets(body, CITIES, cap=6)
            apis = sorted(set(re.findall(
                r'["\'](/?[\w./-]*(?:fare|Fare|zone|Zone|tariff|Tariff|price|Price)[\w./-]*)["\']',
                body)))[:20]
            if hits or cities or apis:
                entry['assets'][a] = {'bytes': len(body), 'key_hits': hits,
                                      'city_hits': cities, 'api_paths': apis}
        report['pages'][page] = entry
    json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('נסרקו', len(PAGES), 'עמודים →', OUT)


if __name__ == '__main__':
    main()
