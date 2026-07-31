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
import json, math, os, re, shutil, subprocess, sys, tempfile, urllib.request, zipfile

DS = '8db5effd-59ca-44ef-b561-86e0ce2911d1'
SHP_URL = os.environ.get(
    'MOT_SHP_URL',
    f'https://data.gov.il/dataset/{DS}/resource/c9447ab4-f167-4194-92e4-a5718915004c/download/industrial.zip')
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


tmp = tempfile.mkdtemp(prefix='motshp')
zp = os.path.join(tmp, 'industrial.zip')
print('מוריד:', SHP_URL)
print('גודל:', fetch(SHP_URL, zp), 'bytes')
with zipfile.ZipFile(zp) as z:
    z.extractall(tmp)
shp = None
for root, _dirs, files in os.walk(tmp):
    for fn in files:
        if fn.lower().endswith('.shp'):
            shp = os.path.join(root, fn)
if not shp:
    print('לא נמצא shapefile בתוך ה-ZIP:', sorted(os.listdir(tmp)))
    sys.exit(1)
base = shp[:-4]
print('shapefile:', os.path.basename(shp))

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
    print('אין שדה שם — לא ממשיכים'); sys.exit(1)

shapes = sf.shapes()
print('רשומות:', len(recs), '| גאומטריות:', len(shapes),
      '| סוג:', getattr(sf, 'shapeTypeName', sf.shapeType))

zones, report, skipped = [], [], []
for rec, sh in zip(recs, shapes):
    d = dict(zip(flds, rec))
    nm = ' '.join(str(d.get(f_name) or '').split())
    city = ' '.join(str(d.get(f_city) or '').split()) if f_city else ''
    dist = ' '.join(str(d.get(f_dist) or '').split()) if f_dist else ''
    taba = str(d.get(f_taba) or '').strip() if f_taba else ''
    try:
        bruto = float(str(d.get(f_bruto) or 0).replace(',', '')) / 1e6
    except Exception:
        bruto = 0.0
    if not sh.points:
        skipped.append({'name': nm, 'why': 'אין גאומטריה'}); continue
    parts = list(sh.parts) + [len(sh.points)]
    rings = []
    for a, b in zip(parts, parts[1:]):
        seg = sh.points[a:b]
        if len(seg) < 4:
            continue
        wgs = [tr.transform(x, y) for x, y in simplify(seg)]
        rg = [[round(la, 5), round(lo, 5)] for lo, la in wgs]
        # שפיות גאוגרפית: הכול חייב ליפול בתוך תיבת ישראל
        if not all(29.0 <= p[0] <= 33.6 and 33.9 <= p[1] <= 36.0 for p in rg):
            continue
        rings.append(rg)
    if not rings:
        skipped.append({'name': nm, 'why': 'גאומטריה מחוץ לישראל או ריקה'}); continue
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
    (OUT_REPORT, {'src': SHP_URL, 'fields': flds, 'records': len(recs),
                  'with_boundary': len(zones), 'skipped': skipped, 'zones': report}),
):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print('wrote', path, round(os.path.getsize(path) / 1024), 'KB')
shutil.rmtree(tmp, ignore_errors=True)
