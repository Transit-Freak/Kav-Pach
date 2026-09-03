# -*- coding: utf-8 -*-
"""מפות אזורים לדוגמה לדו"ח (סעיף 11 במפרט): רקע רחובות של OpenStreetMap,
ועליו גבול האזור, התחנות בצבעי הסיווג לפי מרחק ההליכה, ומרכז האזור.

רץ ב-GitHub Actions בלבד — הסביבה המקומית חוסמת את שרת האריחים. כמות
האריחים קטנה (4 אזורים × ~12 אריחים), עם User-Agent מזהה ושהייה בין בקשות,
לפי מדיניות השימוש של OSM. הקרדיט "© OpenStreetMap contributors" נכתב על
המפה עצמה ומופיע גם בדו"ח.

    python3 tools/report_maps.py     # קורא parks/report/data.json → img/map-<f>.png
"""
import io
import json
import math
import pathlib
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
REP = ROOT / 'parks' / 'report'
IMG = REP / 'img'
TILE = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
UA = 'kav-bochan-report/1.0 (+https://transit-freak.github.io/kav-bochan/; industrial-zone accessibility report)'
COL = {'in': '#16a34a', 'gate': '#84cc16', 'near': '#eab308', 'far': '#f97316', 'blocked': '#94a3b8'}
TIER_HE = {'in': 'בתוך האזור', 'gate': 'עד 5 דק׳', 'near': '5–10 דק׳', 'far': '10–14 דק׳', 'blocked': '15 ומעלה — לא נספרת'}


def deg2tile(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def fetch_tile(z, x, y):
    req = urllib.request.Request(TILE.format(z=z, x=x, y=y), headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def render(ex, out):
    from PIL import Image, ImageDraw, ImageFont
    pts = [q for ring in (ex.get('polys') or []) for q in ring]
    stops = ex.get('stops') or []
    allp = pts + [[s['la'], s['lo']] for s in stops if s.get('t') != 'blocked']
    if not allp:
        return False
    la1, la2 = min(p[0] for p in allp), max(p[0] for p in allp)
    lo1, lo2 = min(p[1] for p in allp), max(p[1] for p in allp)
    # זום שמכניס את הכל ב-~3×3 אריחים
    for z in (16, 15, 14, 13):
        x1, y2 = deg2tile(la1, lo1, z); x2, y1 = deg2tile(la2, lo2, z)
        if (x2 - x1) <= 3.2 and (y2 - y1) <= 3.2:
            break
    pad = 0.35
    tx1, tx2 = int(math.floor(x1 - pad)), int(math.floor(x2 + pad))
    ty1, ty2 = int(math.floor(y1 - pad)), int(math.floor(y2 + pad))
    W, H = (tx2 - tx1 + 1) * 256, (ty2 - ty1 + 1) * 256
    canvas = Image.new('RGB', (W, H), (240, 240, 240))
    n = 0
    for tx in range(tx1, tx2 + 1):
        for ty in range(ty1, ty2 + 1):
            try:
                canvas.paste(Image.open(io.BytesIO(fetch_tile(z, tx, ty))).convert('RGB'), ((tx - tx1) * 256, (ty - ty1) * 256))
                n += 1
            except Exception as e:
                print('  אריח נכשל', z, tx, ty, e)
            time.sleep(0.25)
    def px(la, lo):
        x, y = deg2tile(la, lo, z)
        return ((x - tx1) * 256, (y - ty1) * 256)
    ov = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for ring in ex.get('polys') or []:
        poly = [px(a, b) for a, b in ring]
        d.polygon(poly, fill=(13, 107, 180, 45), outline=(50, 49, 142, 255))
        d.line(poly + poly[:1], fill=(50, 49, 142, 255), width=4)
    for s in stops:
        if s.get('t') == 'blocked':
            continue
        c = COL.get(s.get('t'), '#94a3b8'); c = tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        x, y = px(s['la'], s['lo'])
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=c + (255,), outline=(255, 255, 255, 255), width=2)
    cx, cy = px(ex['la'], ex['lo'])
    d.line([cx - 12, cy, cx + 12, cy], fill=(0, 0, 0, 255), width=4); d.line([cx, cy - 12, cx, cy + 12], fill=(0, 0, 0, 255), width=4)
    canvas = Image.alpha_composite(canvas.convert('RGBA'), ov).convert('RGB')
    # מקרא + קרדיט
    d2 = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
        fb = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 16)
    except Exception:
        font = fb = ImageFont.load_default()
    d2.rectangle([0, canvas.height - 26, canvas.width, canvas.height], fill=(255, 255, 255))
    d2.text((8, canvas.height - 22), '© OpenStreetMap contributors', fill=(60, 60, 60), font=font)
    # בלי כותרת על המפה: PIL לא מסדר עברית, והחיתוך קצץ אותה — השם בכותרת שבמסמך
    # חיתוך לתיבה + שוליים
    bx1, by1 = px(la2, lo1); bx2, by2 = px(la1, lo2)
    m = 60
    crop = canvas.crop((max(0, bx1 - m), max(0, by1 - m - 30), min(canvas.width, bx2 + m), min(canvas.height, by2 + m)))
    crop.save(out)
    print(f"  {ex['name']}: z{z}, {n} אריחים → {out.name} {crop.size}")
    return True


def main():
    data = json.load(open(REP / 'data.json', encoding='utf-8'))
    IMG.mkdir(parents=True, exist_ok=True)
    # ארבע הדוגמאות של סעיף 11 וששת החריגים של סעיף 10 (מישור אדומים בשניהם — פעם אחת)
    items, seen = [], set()
    for ex in (data.get('examples') or []) + (data.get('outliers') or []):
        if ex.get('f') and ex['f'] not in seen:
            seen.add(ex['f'])
            items.append(ex)
    ok = 0
    for ex in items:
        out = IMG / f"map-{ex['f'].replace('.json', '')}.png"
        try:
            ok += bool(render(ex, out))
        except Exception as e:
            print('  מפה נכשלה:', ex.get('name'), e)
    print(f'מפות: {ok} מתוך {len(items)}')


if __name__ == '__main__':
    main()
