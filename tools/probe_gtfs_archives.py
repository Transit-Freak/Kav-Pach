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

# ---------- 1ב. TransitFeeds — עקיפות: openmobilitydata + כותרות דפדפן ----------
print('===== TransitFeeds עקיפות =====')
BHDR = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9,he;q=0.8', 'Referer': 'https://transitfeeds.com/'}
for host in ('https://openmobilitydata.org', 'https://transitfeeds.com'):
    try:
        req = urllib.request.Request(f'{host}/p/ministry-of-transport-and-road-safety/820', headers=BHDR)
        with urllib.request.urlopen(req, timeout=60) as r:
            html = r.read().decode('utf-8', 'replace')
        ds = sorted(set(re.findall(r'/820/(\d{8})', html)))
        print(host, '→ הצלחה | תאריכים בעמוד הראשון:', ds[:10], '...' if len(ds) > 10 else '')
        report.setdefault('tf_bypass', {})[host] = ds
        break
    except Exception as e:
        print(host, '→', str(e)[:80])

# ---------- 1ג. דלי ה-S3 הציבורי של אופן באס — ארכיון GTFS גולמי ----------
print('===== אופן באס S3 =====')
S3S = [
    'https://openbus-stride-public.s3.eu-west-1.amazonaws.com/?list-type=2&prefix=gtfs_archive/&delimiter=/&max-keys=100',
    'https://openbus-stride-public.s3.eu-west-1.amazonaws.com/?list-type=2&delimiter=/&max-keys=100',
    'https://openbus-stride-public.s3.amazonaws.com/?list-type=2&delimiter=/&max-keys=100',
    'https://open-bus-gtfs-data.hasadna.org.il/?list-type=2&delimiter=/&max-keys=100',
]
for u in S3S:
    try:
        xml = get(u, 60)
        pres = re.findall(r'<Prefix>([^<]+)</Prefix>', xml)
        keys = re.findall(r'<Key>([^<]+)</Key>', xml)
        print(u.split('?')[0], '→ תיקיות:', pres[:20], '| קבצים:', keys[:10])
        report.setdefault('s3', {})[u.split('?')[0] + '?' + (u.split('prefix=')[1].split('&')[0] if 'prefix=' in u else '')] = {'prefixes': pres[:40], 'keys': keys[:20]}
    except Exception as e:
        print(u.split('?')[0], '→', str(e)[:80])

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

# ---------- 3. סריקה רחבה: כל תת-הדומיינים של mot.gov.il בווייבק ----------
print('===== Wayback רחב =====')
try:
    u = ('http://web.archive.org/cdx/search/cdx?'
         + urllib.parse.urlencode({'url': 'mot.gov.il', 'matchType': 'domain',
                                   'filter': 'urlkey:.*gtfs.*', 'output': 'json',
                                   'collapse': 'urlkey', 'limit': '500'}))
    rows = json.loads(get(u, 150))
    caps = rows[1:] if rows else []
    print('כתובות GTFS בכל mot.gov.il:', len(caps))
    for c in caps[:20]:
        print('  ', c[1], c[2][:100])
    report['wayback_wide'] = [c[1] + ' ' + c[2][:110] for c in caps[:60]]
except Exception as e:
    print('שגיאה:', str(e)[:100]); report['wayback_wide_error'] = str(e)[:150]

# ---------- 4. Zenodo — מאגרי מחקר ----------
print('===== Zenodo =====')
try:
    z = json.loads(get('https://zenodo.org/api/records?' + urllib.parse.urlencode({'q': 'GTFS Israel', 'size': 15}), 90))
    hits = z.get('hits', {}).get('hits', [])
    print('תוצאות:', len(hits))
    zn = []
    for h in hits:
        md = h.get('metadata', {})
        t = md.get('title', '')
        print('  *', t[:90], '|', md.get('publication_date'), '|', h.get('links', {}).get('self_html', ''))
        zn.append({'title': t[:100], 'date': md.get('publication_date'), 'url': h.get('links', {}).get('self_html', '')})
    report['zenodo'] = zn
except Exception as e:
    print('שגיאה:', str(e)[:100]); report['zenodo_error'] = str(e)[:150]

# ---------- 5. transit.land — גרסאות פיד היסטוריות ----------
print('===== transit.land =====')
for u in ('https://transit.land/api/v2/rest/feeds?search=israel',
          'https://transit.land/api/v2/rest/feeds?onestop_id=f-sv8y~israelministryoftransport'):
    try:
        r = json.loads(get(u, 60))
        feeds = r.get('feeds', [])
        print(u[-40:], '→', len(feeds), 'פידים')
        for f in feeds[:5]:
            print('  *', f.get('onestop_id'), '|', (f.get('name') or '')[:50])
        if feeds:
            report['transitland'] = [{'id': f.get('onestop_id'), 'name': f.get('name')} for f in feeds[:10]]
            break
    except Exception as e:
        print(u[-40:], '→', str(e)[:80])

# ---------- 6. הפרויקט הישן של הסדנא (2017-2021) — איפה הארכיון שלו ----------
print('===== open-bus הישן =====')
for u in ('https://raw.githubusercontent.com/hasadna/open-bus/master/README.md',
          'https://raw.githubusercontent.com/hasadna/open-bus-pipelines/main/README.md'):
    try:
        md = get(u, 60)
        urls = sorted(set(re.findall(r'https?://[^\s\)\]"\'>]+', md)))
        cand = [x for x in urls if re.search(r's3|minio|archive|gtfs|data', x, re.I)][:15]
        print(u.split('/')[4], '→ קישורי דאטה:', cand)
        report.setdefault('oldbus', {})[u.split('/')[4]] = cand
    except Exception as e:
        print(u.split('/')[4], '→', str(e)[:80])

os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(report, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('wrote', OUT)
