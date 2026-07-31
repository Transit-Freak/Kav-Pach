# -*- coding: utf-8 -*-
# גבולות אזורי התעשייה-תעסוקה של משרד התחבורה — מהמקור עצמו.
#
# הדאטהסט "תחום אזורי תעשיה תעסוקה" (data.gov.il) מפורסם בארבעה פורמטים:
# CSV, SHP, KMZ, PDF. עד כה השתמשנו רק ב-CSV (טבלת התכונות) ולכן היינו צריכים
# לנחש את הגבול לפי מספר התב"ע במנהל התכנון — שיטה שהצליחה בחלק מהמקרים בלבד.
# ה-SHP הוא אותה טבלה *עם הפוליגונים*, כלומר הגבול הרשמי של משרד התחבורה לכל
# אזור. אין צורך בהתאמה, אין ניחושים.
#
# פלט:
#   parks/osm-check/mot-zones.json  — האזורים + גבולות (מה שהאתר בונה ממנו)
#   parks/checks/mot-shapes.json    — דוח בקרה: תכונות בלבד, בלי גאומטריה
#
# הרצה: python3 tools/fetch_mot_shapes.py
import json, math, os, re, shutil, sys, tempfile, urllib.parse, urllib.request, zipfile

DS = '8db5effd-59ca-44ef-b561-86e0ce2911d1'
CSV_RES = '71799e72-7a1f-45cf-9d81-5cd1d5f3b201'   # אותה טבלה ב-API הפתוח
SHP_URL = os.environ.get('MOT_SHP_URL', '')   # ריק = מאתרים דרך ה-API של data.gov.il
OUT_ZONES = os.environ.get('OUT_ZONES', 'parks/osm-check/mot-zones.json')
OUT_REPORT = os.environ.get('OUT_REPORT', 'parks/checks/mot-shapes.json')
MAXPTS = int(os.environ.get('MAXPTS', '200'))
MIN_KM2 = float(os.environ.get('MIN_KM2', '0.02'))
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

import shapefile                      # pyshp
from pyproj import CRS, Transformer

# מוקדי תעסוקה שאינם אזור-תעשייה קלאסי — שכבת תצוגה נפרדת באתר (בקשת איריס:
# נמלים, שדות תעופה, בתי חולים, אוניברסיטאות; וגם מחצבות/תחנות-כוח/מט"שים,
# שהם מוקדי עבודה אבל לא אזורי תעשייה).
HUB_RE = re.compile('|'.join([
    'נמל', 'שדה תעופה', 'שדה-תעופה', 'נמת"ע',
    'בית חולים', 'בית-חולים', 'בתי חולים', 'מרכז רפואי', 'מרכז-רפואי',
    'אוניברסיט', 'מכלל', 'קמפוס',
    'מחצב', 'מכרות', 'מכרה', 'כריה', 'כרייה',
    'תחנת כח', 'תחנת כוח', 'תחנת-כח', 'תחנת-כוח',
    'ממ"ג', 'ממ״ג', 'סילוק פסולת', 'מטמנ',
    'מט"ש', 'מט״ש', 'טיהור שפכים', 'בתי זיקוק', 'התפלה',
]))


def fetch(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    return os.path.getsize(dest)


def is_zip(path):
    with open(path, 'rb') as f:
        return f.read(2) == b'PK'


def fetch_via_browser(urls, dest):
    """הורדה בדפדפן אמיתי.

    שרת ההורדות של data.gov.il (e.data.gov.il) מגיש לכל בקשה שאינה דפדפן דף
    JavaScript של הגנת-בוטים במקום הקובץ. הקובץ עצמו ציבורי ופתוח — אין סיסמה
    ואין הרשאה — אלא שצריך להריץ את ה-JS כדי לקבל את ה-cookie. לכן נכנסים
    לעמוד הדאטהסט בכרומיום, מחכים שהאתגר ייפתר, ומורידים עם אותו הקשר.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(args=['--no-sandbox'])
        ctx = br.new_context(accept_downloads=True, locale='he-IL',
                             user_agent=UA['User-Agent'])
        pg = ctx.new_page()
        title = ''
        try:
            pg.goto(f'https://data.gov.il/dataset/{DS}',
                    wait_until='domcontentloaded', timeout=120000)
            pg.wait_for_timeout(8000)
            title = (pg.title() or '').strip()
            print('  עמוד הדאטהסט נטען:', title[:60] or '(בלי כותרת)')
        except Exception as e:
            print('  טעינת עמוד הדאטהסט נכשלה:', e)
        if not title:
            # דף בלי כותרת = אתגר הגנת-הבוטים לא נפתר, גם האתר עצמו לא נטען.
            # אין טעם לנסות להוריד — זה רק ייתקע עד ה-timeout על כל כתובת.
            print('  האתר לא נטען בדפדפן — לא ממשיכים לניסיונות הורדה')
            br.close()
            return None
        for url in urls:
            try:
                r = ctx.request.get(url, timeout=180000)
                body = r.body()
                if body[:2] == b'PK':
                    open(dest, 'wb').write(body)
                    print('  ירד בדפדפן:', len(body), 'bytes |', url)
                    br.close()
                    return url
                print('  עדיין לא ארכיון (', len(body), 'bytes ) |', url)
            except Exception as e:
                print('  בקשה בדפדפן נכשלה:', e)
            try:   # נפילה לאחור: ניווט שמפעיל הורדת-קובץ בדפדפן
                with pg.expect_download(timeout=30000) as dl:
                    try:
                        pg.goto(url, timeout=30000)
                    except Exception:
                        pass
                dl.value.save_as(dest)
                if is_zip(dest):
                    print('  ירד כהורדת-דפדפן:', os.path.getsize(dest), 'bytes')
                    br.close()
                    return url
            except Exception as e:
                print('  הורדת-דפדפן נכשלה:', e)
        br.close()
    return None


def candidates():
    """כתובות ההורדה של השכבה, לפי סדר עדיפות: SHP ואז KMZ.

    הכתובות לא מקובעות בקוד — נשלפות מה-API של data.gov.il, כי מזהי המשאבים
    מתחלפים כשמתפרסמת גרסה חדשה של השכבה.
    """
    if SHP_URL:
        return [(SHP_URL, 'SHP')]
    out = []
    try:
        pkg = json.loads(fetch_bytes(
            f'https://data.gov.il/api/3/action/package_show?id={DS}').decode('utf-8', 'replace'))
        res = pkg['result']['resources']
        print('משאבים בדאטהסט:', [(r.get('format'), r.get('name')) for r in res])
        for want in ('SHP', 'KMZ', 'KML'):
            for r in res:
                if (r.get('format') or '').upper().startswith(want) and r.get('url'):
                    out.append((r['url'], want))
    except Exception as e:
        print('שליפת רשימת המשאבים נכשלה:', e)
    if not out:   # נפילה לאחור: המזהים שהיו בתוקף בזמן הכתיבה
        out = [(f'https://data.gov.il/dataset/{DS}/resource/'
                'c9447ab4-f167-4194-92e4-a5718915004c/download/industrial.zip', 'SHP'),
               (f'https://data.gov.il/dataset/{DS}/resource/'
                'a7b34e8a-fb46-448c-ad3a-244bae6d137c/download/industrial_kmz.zip', 'KMZ')]
    return out


def fetch_bytes(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def read_prj(base):
    """CRS מתוך קובץ ה-prj; ברירת מחדל רשת ישראל החדשה (2039)."""
    for ext in ('.prj', '.PRJ'):
        p = base + ext
        if os.path.exists(p):
            try:
                return CRS.from_wkt(open(p, encoding='utf-8', errors='replace').read())
            except Exception as e:
                print('prj לא נקרא:', e)
    return CRS.from_epsg(2039)


def open_shp(base):
    """פתיחה עם קידוד עברי — utf-8 ואם לא, cp1255."""
    for enc in ('utf-8', 'cp1255'):
        try:
            sf = shapefile.Reader(base, encoding=enc)
            recs = sf.records()
            joined = ' '.join(str(v) for r in recs[:80] for v in r)
            if re.search('[א-ת]', joined):
                print('קידוד:', enc)
                return sf, recs
        except Exception as e:
            print(f'פתיחה ב-{enc} נכשלה:', e)
    sf = shapefile.Reader(base, encoding='cp1255')
    return sf, sf.records()


def pick(flds, *names):
    """שם שדה ב-DBF מקוצר ל-10 תווים — התאמה לפי תחילית."""
    up = {f.upper(): f for f in flds}
    for n in names:
        n = n.upper()
        if n in up:
            return up[n]
        for k, v in up.items():
            if k.startswith(n[:10]) or n.startswith(k):
                return v
    return None


def ring_area_km2(rg):
    if len(rg) < 4:
        return 0.0
    cl = math.cos(math.radians(sum(p[0] for p in rg) / len(rg)))
    q = [(p[1] * 111320 * cl, p[0] * 110540) for p in rg]
    s = sum(q[i][0] * q[(i + 1) % len(q)][1] - q[(i + 1) % len(q)][0] * q[i][1]
            for i in range(len(q)))
    return abs(s) / 2 / 1e6


def simplify(pts):
    if len(pts) <= MAXPTS:
        return pts
    step = len(pts) / MAXPTS
    out = [pts[int(i * step)] for i in range(MAXPTS)]
    out.append(pts[-1])
    return out


def load_shp(base):
    """(תכונות, טבעות ב-WGS84) לכל רשומה בשכבת ה-shapefile."""
    crs = read_prj(base)
    print('CRS:', (crs.to_epsg() or crs.name))
    tr = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    sf, recs = open_shp(base)
    flds = [f[0] for f in sf.fields[1:]]
    print('שדות:', flds)
    f_name = pick(flds, 'NAME', 'SHEM', 'SHEM_EZOR')
    f_city = pick(flds, 'CITY', 'YISHUV', 'SHEM_YISHUV')
    f_dist = pick(flds, 'DISTRICT', 'MAHOZ')
    f_taba = pick(flds, 'TABA_NUM', 'TABA')
    f_bruto = pick(flds, 'BRUTOAREA', 'BRUTO')
    print('מיפוי שדות:', dict(name=f_name, city=f_city, district=f_dist,
                              taba=f_taba, bruto=f_bruto))
    if not f_name:
        raise SystemExit('אין שדה שם בשכבה — לא ממשיכים')
    shapes = sf.shapes()
    print('רשומות:', len(recs), '| גאומטריות:', len(shapes),
          '| סוג:', getattr(sf, 'shapeTypeName', sf.shapeType))
    out = []
    for rec, sh in zip(recs, shapes):
        d = dict(zip(flds, rec))
        at = {'name': str(d.get(f_name) or ''),
              'city': str(d.get(f_city) or '') if f_city else '',
              'district': str(d.get(f_dist) or '') if f_dist else '',
              'taba': str(d.get(f_taba) or '') if f_taba else '',
              'bruto': d.get(f_bruto) if f_bruto else 0}
        rings = []
        if sh.points:
            parts = list(sh.parts) + [len(sh.points)]
            for a, b in zip(parts, parts[1:]):
                seg = sh.points[a:b]
                if len(seg) < 4:
                    continue
                rings.append([[la, lo] for lo, la in
                              (tr.transform(x, y) for x, y in simplify(seg))])
        out.append((at, rings))
    return out


def load_kml(path):
    """(תכונות, טבעות) מקובץ KML — הקואורדינטות שם ממילא ב-WGS84."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    ns = {'k': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}
    def fa(el, tag):
        return el.findall(f'.//k:{tag}', ns) if ns else el.findall(f'.//{tag}')
    def keyof(k):
        k = (k or '').strip().upper()
        for want, key in (('NAME', 'name'), ('SHEM', 'name'), ('CITY', 'city'),
                          ('YISHUV', 'city'), ('DISTRICT', 'district'), ('MAHOZ', 'district'),
                          ('TABA', 'taba'), ('BRUTO', 'bruto')):
            if k.startswith(want):
                return key
        return None
    out = []
    for pm in fa(root, 'Placemark'):
        at = {'name': '', 'city': '', 'district': '', 'taba': '', 'bruto': 0}
        for sd in fa(pm, 'SimpleData') + fa(pm, 'Data'):
            k = keyof(sd.get('name'))
            if not k:
                continue
            v = sd.text
            if v is None:                      # <Data><value>...</value></Data>
                vv = fa(sd, 'value')
                v = vv[0].text if vv else ''
            at[k] = (v or '').strip()
        if not at['name']:
            nm = fa(pm, 'name')
            at['name'] = (nm[0].text or '').strip() if nm else ''
        rings = []
        for c in fa(pm, 'coordinates'):
            pts = []
            for tok in (c.text or '').split():
                bits = tok.split(',')
                if len(bits) >= 2:
                    try:
                        pts.append((float(bits[0]), float(bits[1])))
                    except ValueError:
                        pass
            if len(pts) >= 4:
                rings.append([[la, lo] for lo, la in simplify(pts)])
        out.append((at, rings))
    print('Placemarks ב-KML:', len(out))
    return out


tmp = tempfile.mkdtemp(prefix='motshp')
_seq = [0]


def read_layer(path, tag):
    """קריאת שכבה מקובץ שהורד — ZIP עם shapefile/KML, או KML גלוי."""
    if not is_zip(path):
        head = open(path, 'rb').read(300).decode('utf-8', 'replace').replace('\n', ' ')
        print('  לא ארכיון ZIP. תחילת התשובה:', head[:200])
        if '<kml' not in head and '<?xml' not in head:
            return None
        kp = os.path.join(tmp, 'layer.kml')
        shutil.copy(path, kp)
        return load_kml(kp)
    _seq[0] += 1
    d = os.path.join(tmp, f'{tag}{_seq[0]}')
    os.makedirs(d, exist_ok=True)
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(d)
    except Exception as e:
        print('  פתיחת ה-ZIP נכשלה:', e); return None
    shp = kml = None
    for root_d, _dirs, files in os.walk(d):
        for fn in files:
            if fn.lower().endswith('.shp'):
                shp = os.path.join(root_d, fn)
            elif fn.lower().endswith(('.kml', '.kmz')):
                kml = os.path.join(root_d, fn)
    if shp:
        print('  shapefile:', os.path.basename(shp))
        return load_shp(shp[:-4])
    if kml:
        print('  kml:', os.path.basename(kml))
        return load_kml(kml)
    print('  אין שכבה מוכרת בארכיון:',
          sorted(f for _r, _d, fs in os.walk(d) for f in fs)[:12])
    return None


# מועמדים + גרסת-מארח חלופית (הפורטל מגיש הורדות מ-e.data.gov.il, אבל לפעמים
# גם מהמארח הראשי — שווה לנסות את שניהם לפני שמפעילים דפדפן)
cands = []
for url, kind in candidates():
    for u in (url, url.replace('://e.data.gov.il', '://data.gov.il'),
              url.replace('://data.gov.il', '://e.data.gov.il')):
        if (u, kind) not in cands:
            cands.append((u, kind))

records, src_used = None, None

# קובץ מקומי קודם לכול: אם השכבה הועלתה ידנית ל-parks/sources (למשל אחרי
# הורדה מהדפדפן), משתמשים בה ולא פונים לרשת בכלל.
import glob as _glob
for lp in sorted(_glob.glob('parks/sources/industrial*.zip'), reverse=True):
    print('שכבה מקומית:', lp)
    try:
        records, src_used = read_layer(lp, 'local'), lp
    except Exception as e:
        print('  קריאה נכשלה:', e)
    if records:
        break

for url, kind in ([] if records else cands):
    zp = os.path.join(tmp, 'dl.bin')
    print(f'מוריד ({kind}):', url)
    try:
        print('  גודל:', fetch(url, zp), 'bytes')
    except Exception as e:
        print('  הורדה נכשלה:', e); continue
    try:
        r = read_layer(zp, kind.lower())
    except SystemExit as e:
        print(' ', e); continue
    except Exception as e:
        print('  קריאת השכבה נכשלה:', e); continue
    if r:
        records, src_used = r, url
        break

if not records:
    print('הורדה רגילה לא הצליחה — מנסים בדפדפן')
    zp = os.path.join(tmp, 'browser.bin')
    try:
        got = fetch_via_browser([u for u, _k in cands], zp)
    except Exception as e:
        print('  הפעלת הדפדפן נכשלה:', e); got = None
    if got:
        try:
            records, src_used = read_layer(zp, 'br'), got
        except Exception as e:
            print('  קריאת השכבה שירדה בדפדפן נכשלה:', e)

if not records:
    print('אף אחד ממקורות השכבה לא נקרא בהצלחה')
    # אבחון: מה בכלל יש ב-API הפתוח של הדאטהסט? אם יש שם עמודת גאומטריה,
    # אפשר לקבל את הגבולות בלי להוריד קובץ בכלל.
    try:
        ds = json.loads(fetch_bytes(
            'https://data.gov.il/api/3/action/datastore_search?'
            + urllib.parse.urlencode({'resource_id': CSV_RES, 'limit': 1})
        ).decode('utf-8', 'replace'))
        print('עמודות בטבלה הפתוחה:',
              [f.get('id') for f in ds['result'].get('fields', [])])
    except Exception as e:
        print('בדיקת הטבלה הפתוחה נכשלה:', e)
    print('')
    print('מה שנשאר לעשות ידנית (פעם אחת): להיכנס לעמוד הדאטהסט בדפדפן,')
    print(f'  https://data.gov.il/dataset/{DS}')
    print('להוריד את הקובץ בפורמט SHP, ולהעלות אותו כמו-שהוא לתיקייה')
    print('  parks/sources/industrial.zip')
    print('התהליך הזה מזהה קובץ מקומי כזה ומעדיף אותו על הרשת.')
    sys.exit(1)

zones, report, skipped = [], [], []
for at, raw_rings in records:
    nm = ' '.join(str(at.get('name') or '').split())
    city = ' '.join(str(at.get('city') or '').split())
    dist = ' '.join(str(at.get('district') or '').split())
    taba = str(at.get('taba') or '').strip()
    try:
        bruto = float(str(at.get('bruto') or 0).replace(',', '')) / 1e6
    except Exception:
        bruto = 0.0
    rings = []
    for rg0 in raw_rings:
        rg = [[round(p[0], 5), round(p[1], 5)] for p in rg0]
        # שפיות גאוגרפית: הכול חייב ליפול בתוך תיבת ישראל
        if not all(29.0 <= p[0] <= 33.6 and 33.9 <= p[1] <= 36.0 for p in rg):
            continue
        rings.append(rg)
    if not rings:
        skipped.append({'name': nm, 'why': 'אין גאומטריה או שהיא מחוץ לישראל'}); continue
    rings.sort(key=lambda rg: -ring_area_km2(rg))
    rings = rings[:8]
    area = round(sum(ring_area_km2(rg) for rg in rings), 3)
    if area < MIN_KM2:
        skipped.append({'name': nm, 'why': f'שטח זעיר ({area} קמ"ר)'}); continue
    ly = 'hub' if HUB_RE.search(nm) else 'ind'
    zones.append({'name': nm, 'city': city, 'district': dist, 'taba': taba,
                  'ly': ly, 'polys': rings})
    report.append({'name': nm, 'city': city, 'district': dist, 'taba': taba,
                   'ly': ly, 'area_km2': area, 'bruto_km2': round(bruto, 3),
                   'rings': len(rings),
                   'ratio_ok': bool(bruto <= 0.01 or bruto / 3 <= area <= bruto * 3)})

ok = sum(1 for r in report if r['ratio_ok'])
hub = sum(1 for z in zones if z['ly'] == 'hub')
recs = records
print(f'אזורים עם גבול: {len(zones)}/{len(recs)} | מוקדי תעסוקה: {hub} | '
      f'שטח מתאים לרשום: {ok}/{len(report)} | דולגו: {len(skipped)}')
for s in skipped[:20]:
    print('  דולג:', s['name'][:40], '|', s['why'])
bad = [r for r in report if not r['ratio_ok']]
for r in sorted(bad, key=lambda r: -r['bruto_km2'])[:15]:
    print(f"  יחס-שטח חריג: {r['name'][:34]} | נמצא {r['area_km2']} | רשום {r['bruto_km2']}")

# מנגנון בטיחות: לא מחליפים את קובץ האזורים בגרסה גרועה יותר. אם השכבה
# השתנתה בצד שלהם (נקודות במקום פוליגונים, שדות אחרים, הורדה חלקית) — נופלים
# עם שגיאה ומשאירים את הקובץ הקיים על תילו.
_prev = 0
if os.path.exists(OUT_ZONES):
    try:
        _prev = len(json.load(open(OUT_ZONES, encoding='utf-8'))['zones'])
    except Exception:
        _prev = 0
_floor = max(100, int(_prev * 0.8))
if len(zones) < _floor:
    print(f'עצירה: נמצאו {len(zones)} אזורים בלבד (מינימום {_floor}, קודם {_prev}) — '
          'הקובץ הקיים נשאר כמו שהוא')
    sys.exit(1)

for path, data in (
    (OUT_ZONES, {'src': 'משרד התחבורה — תחום אזורי תעשיה תעסוקה (גבולות מהשכבה הרשמית)',
                 'url': f'https://data.gov.il/dataset/{DS}', 'zones': zones}),
    (OUT_REPORT, {'src': src_used, 'records': len(recs),
                  'with_boundary': len(zones), 'skipped': skipped, 'zones': report}),
):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print('wrote', path, round(os.path.getsize(path) / 1024), 'KB')
shutil.rmtree(tmp, ignore_errors=True)
