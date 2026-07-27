# -*- coding: utf-8 -*-
# צילום אמיתי של מפת החום לכפתור באתר אזורי התעשייה: מוריד את אריחי
# OpenStreetMap שמכסים את ישראל, מצייר עליהם את עיגולי החום של האזורים
# (אותם צבעים/מדרגות כמו באתר), חותך לגבולות הארץ ושומר PNG קטן.
# רץ ב-CI (שרת האריחים חסום מסביבת הפיתוח).
import io, json, math, os, sys, time, urllib.request

from PIL import Image, ImageDraw

Z = 8
LAT_N, LAT_S = 33.35, 29.45
LON_W, LON_E = 34.15, 35.95
OUT = os.environ.get('OUT', 'parks/heatbtn-map.png')
UA = 'kav-bochan/parks heat-button generator (one-off; github.com/Transit-Freak/kav-bochan)'

def ll2px(la, lo):
    n = 2 ** Z * 256
    x = (lo + 180) / 360 * n
    r = math.radians(la)
    y = (1 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2 * n
    return x, y

x0, y0 = ll2px(LAT_N, LON_W)
x1, y1 = ll2px(LAT_S, LON_E)
tx0, ty0, tx1, ty1 = int(x0 // 256), int(y0 // 256), int(x1 // 256), int(y1 // 256)
W, H = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
img = Image.new('RGB', (W, H))
for tx in range(tx0, tx1 + 1):
    for ty in range(ty0, ty1 + 1):
        url = f'https://tile.openstreetmap.org/{Z}/{tx}/{ty}.png'
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            img.paste(Image.open(io.BytesIO(r.read())).convert('RGB'),
                      ((tx - tx0) * 256, (ty - ty0) * 256))
        time.sleep(0.4)
print(f'אריחים: {(tx1-tx0+1)*(ty1-ty0+1)} | קנבס {W}x{H}')

# עיגולי החום — בדיוק כמו hcol/hsiz באתר (מצב מדידה: מרכז), מוגדלים פי ~2
# כדי שיישארו נראים אחרי ההקטנה לגודל כפתור
def hcol(t):
    if not t: return '#dc2626'
    if t <= 5: return '#fde047'
    if t <= 15: return '#84cc16'
    if t <= 40: return '#16a34a'
    return '#065f46'

def hsiz(t):
    if not t: return 8
    if t <= 5: return 9
    if t <= 15: return 13
    if t <= 40: return 18
    return 24

parks = json.load(open('parks/data/parks.json', encoding='utf-8'))
dr = ImageDraw.Draw(img, 'RGBA')
for p in sorted(parks, key=lambda p: -((p.get('li') or 0) + (p.get('lg') or 0) + (p.get('ln') or 0))):
    tot = (p.get('li') or 0) + (p.get('lg') or 0) + (p.get('ln') or 0)
    px, py = ll2px(p['la'], p['lo'])
    px, py = px - tx0 * 256, py - ty0 * 256
    rad = hsiz(tot) * 2.0
    c = hcol(tot)
    fill = tuple(int(c[i:i+2], 16) for i in (1, 3, 5)) + (217,)
    dr.ellipse([px - rad, py - rad, px + rad, py + rad], fill=fill, outline=(255, 255, 255, 255), width=3)

crop = img.crop((int(x0 - tx0 * 256), int(y0 - ty0 * 256), int(x1 - tx0 * 256), int(y1 - ty0 * 256)))
print('חיתוך:', crop.size)
# גובה סופי 272px = פי 8 מגובה התצוגה בכפתור (34px) — חד גם ברשתות רטינה
h = 272
w = round(crop.width * h / crop.height)
crop = crop.resize((w, h), Image.LANCZOS)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
crop.save(OUT, optimize=True)
print('נשמר:', OUT, f'{w}x{h}', os.path.getsize(OUT), 'bytes')
