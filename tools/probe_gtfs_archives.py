# -*- coding: utf-8 -*-
# חיפוש קובצי GTFS היסטוריים של ישראל (לפני תחילת ארכיון אופן באס ב-2022):
#  1. TransitFeeds — ארכיון בינלאומי ששמר גרסאות של פידים לאורך שנים.
#  2. Wayback Machine — לכידות של קובץ ה-GTFS הרשמי של משרד התחבורה.
# הפלט: parks/checks/gtfs-archives-probe.json + לוג. דוח בלבד.
import json, os, re, time, urllib.parse, urllib.request

OUT = os.environ.get('OUT', 'parks/checks/gtfs-archives-probe.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
report = {}

def get(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')

# ---------- 1. TransitFeeds ----------
print('===== TransitFeeds =====')
FEED = 'https://transitfeeds.com/p/ministry-of-transport-and-road-safety/820'
versions = set()
try:
    # איתור כל הפידים הישראליים (ליתר ביטחון — אולי יש יותר מפיד אחד)
    try:
        sr = get('https://transitfeeds.com/l/israel')
        feeds = sorted(set(re.findall(r'href="(/p/[^"]+?)"', sr)))
        print('פידים בעמוד ישראל:', [f for f in feeds if f.count('/') == 3][:15])
        report['tf_feeds'] = feeds[:30]
    except Exception as e:
        print('עמוד ישראל:', str(e)[:80])
    page = 1
    while page <= 40:
        html = get(f'{FEED}?p={page}')
        ds = set(re.findall(r'/p/ministry-of-transport-and-road-safety/820/(\d{8})', html))
        new = ds - versions
        versions |= ds
        print(f'עמוד {page}: {len(ds)} תאריכים ({len(new)} חדשים)')
        if not new:
            break
        page += 1
        time.sleep(0.5)
except Exception as e:
    print('TransitFeeds שגיאה:', str(e)[:120])
    report['tf_error'] = str(e)[:200]
years = {}
for v in sorted(versions):
    years.setdefault(v[:4], []).append(v)
print('סה"כ גרסאות שמורות:', len(versions))
for y in sorted(years):
    vs = years[y]
    print(f'  {y}: {len(vs)} גרסאות | ראשונה {vs[0]} אחרונה {vs[-1]}')
report['transitfeeds'] = {'feed': FEED, 'total': len(versions),
                          'by_year': {y: {'count': len(v), 'first': v[0], 'last': v[-1]} for y, v in sorted(years.items())},
                          'download_pattern': FEED + '/YYYYMMDD/download'}

# ---------- 2. Wayback Machine (CDX) ----------
print('===== Wayback Machine =====')
wb = {}
for target in ('gtfs.mot.gov.il', 'gtfs.mot.gov.il/gtfsfiles/israel-public-transportation.zip'):
    try:
        u = ('http://web.archive.org/cdx/search/cdx?'
             + urllib.parse.urlencode({'url': target + ('*' if not target.endswith('.zip') else ''),
                                       'output': 'json', 'collapse': 'timestamp:6', 'limit': '1000'}))
        rows = json.loads(get(u, 120))
        caps = rows[1:] if rows else []
        zips = [c for c in caps if '.zip' in c[2].lower()]
        print(f'{target}: לכידות {len(caps)} | מהן zip: {len(zips)}')
        ys = {}
        for c in (zips or caps):
            ys.setdefault(c[1][:4], 0)
            ys[c[1][:4]] += 1
        print('  לפי שנה:', dict(sorted(ys.items())))
        wb[target] = {'captures': len(caps), 'zips': len(zips), 'by_year': ys,
                      'samples': [c[1] + ' ' + c[2][:90] for c in (zips or caps)[:8]]}
    except Exception as e:
        print(target, 'שגיאה:', str(e)[:100])
        wb[target] = {'error': str(e)[:200]}
    time.sleep(1)
report['wayback'] = wb

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
