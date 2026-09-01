# -*- coding: utf-8 -*-
"""פיילוט הסככות (בקשת שלמה 01.09.2026): המערכת מזהה בעצמה סככות
מתצלום האוויר, ואז משווה למיקומי התחנות ברישוי ומעלה חשדות.

שלבים (STAGE):
  A — דגימות בדיקה: 6 תצלומים עם תיבת הסככה מסומנת, לאימות עין.
  B — ערכת אימון מלאה: תצלום לכל אחת מ-402 הסככות הממופות של תל אביב
      (הפוליגונים העירוניים משמשים רק כתוויות אימון) + רקעים שליליים.
  C — אימון מודל זיהוי (YOLO ננו, CPU).
  D — הרצה על כל תחנות הרישוי בתל אביב: זיהוי סככות בתצלום סביב כל
      תחנה, מדידת מרחק, ורשימת חשדות ("אין סככה" / "רחוקה מהרישום").

מקור התצלומים: האורתופוטו הרשמי של עיריית תל אביב (שרת ה-GIS הפתוח
שלה, אותו שרת שמשרת את הצופה הציבורי) — עדכני 2025.
"""
import io
import json
import math
import os
import pathlib
import random
import sys
import time
import urllib.parse
import urllib.request

GIS = 'https://gisn.tel-aviv.gov.il/arcgis/rest/services'
LAYER = f'{GIS}/IView2MapHeb/MapServer/24'
ORTHO = f'{GIS}/WM/IView2Ortho2025WM/MapServer'
OUT = pathlib.Path('sakachot-lab')
STAGE = os.environ.get('STAGE', 'A')
PAUSE = float(os.environ.get('PAUSE', '0.25'))
HALF = 26      # חצי-חלון במטרים סביב הנקודה (52x52 מ')
PX = 512       # גודל התצלום בפיקסלים (~10 ס"מ לפיקסל)


def get(url, params=None, binary=False, retries=3):
    if params:
        url = url + '?' + urllib.parse.urlencode(params)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=90) as r:
                d = r.read()
            return d if binary else json.loads(d)
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def merc(lon, lat):
    x = lon * 20037508.34 / 180
    y = math.log(math.tan((90 + lat) * math.pi / 360)) / (math.pi / 180) * 20037508.34 / 180
    return x, y


def shelters():
    """כל פוליגוני 'תחנת אוטובוס' מהסקר העירוני, ב-WGS84."""
    d = get(f'{LAYER}/query', {'where': "t_sug_mivne='תחנת אוטובוס'",
                               'outFields': 'oid_mivne', 'returnGeometry': 'true',
                               'outSR': '4326', 'f': 'json'})
    out = []
    for f in d.get('features') or []:
        rings = (f.get('geometry') or {}).get('rings') or []
        pts = [p for r in rings for p in r]
        if not pts:
            continue
        lon = sum(p[0] for p in pts) / len(pts)
        lat = sum(p[1] for p in pts) / len(pts)
        out.append({'id': f['attributes'].get('oid_mivne'), 'lon': lon, 'lat': lat, 'rings': rings})
    return out


def crop(lon, lat):
    x, y = merc(lon, lat)
    bbox = f'{x-HALF},{y-HALF},{x+HALF},{y+HALF}'
    img = get(f'{ORTHO}/export', {'bbox': bbox, 'bboxSR': '3857', 'imageSR': '3857',
                                  'size': f'{PX},{PX}', 'format': 'png',
                                  'transparent': 'false', 'f': 'image'}, binary=True)
    return img, (x, y)


def rings_px(rings, cx, cy):
    """תיבת הפוליגון בפיקסלים של התצלום שסביב (cx,cy)."""
    xs, ys = [], []
    for r in rings:
        for lon, lat in r:
            mx, my = merc(lon, lat)
            xs.append((mx - (cx - HALF)) / (2 * HALF) * PX)
            ys.append((1 - (my - (cy - HALF)) / (2 * HALF)) * PX)
    return min(xs), min(ys), max(xs), max(ys)


def yolo_label(b):
    x0, y0, x1, y1 = [max(0, min(PX, v)) for v in b]
    return f'0 {(x0+x1)/2/PX:.6f} {(y0+y1)/2/PX:.6f} {(x1-x0)/PX:.6f} {(y1-y0)/PX:.6f}\n'


def stage_a():
    from PIL import Image, ImageDraw
    sh = shelters()
    print(f'פוליגוני סככה שנשלפו: {len(sh)}')
    d = OUT / 'samples'
    d.mkdir(parents=True, exist_ok=True)
    for s in sh[:6]:
        img, (cx, cy) = crop(s['lon'], s['lat'])
        im = Image.open(io.BytesIO(img)).convert('RGB')
        dr = ImageDraw.Draw(im)
        b = rings_px(s['rings'], cx, cy)
        dr.rectangle(b, outline=(255, 0, 0), width=3)
        im.save(d / f"sample-{s['id']}.png")
        print(f"  {s['id']}: תיבה {[round(v) for v in b]}")
        time.sleep(PAUSE)
    json.dump({'n': len(sh)}, open(d / 'meta.json', 'w'))


def stage_b():
    sh = shelters()
    random.seed(7)
    img_d = OUT / 'train/images'
    lbl_d = OUT / 'train/labels'
    img_d.mkdir(parents=True, exist_ok=True)
    lbl_d.mkdir(parents=True, exist_ok=True)
    n = 0
    for s in sh:
        try:
            img, (cx, cy) = crop(s['lon'], s['lat'])
        except Exception as e:
            print(f"  {s['id']}: כשל ({type(e).__name__})")
            continue
        # כל הסככות שנופלות בתוך החלון — לא רק המרכזית
        labels = ''
        for s2 in sh:
            b = rings_px(s2['rings'], cx, cy)
            if b[2] > 6 and b[0] < PX - 6 and b[3] > 6 and b[1] < PX - 6:
                labels += yolo_label(b)
        (img_d / f"p{s['id']}.png").write_bytes(img)
        (lbl_d / f"p{s['id']}.txt").write_text(labels)
        n += 1
        if n % 40 == 0:
            print(f'  {n} תצלומי אימון…', flush=True)
        time.sleep(PAUSE)
    # שליליים: נקודות אקראיות בעיר, רחוקות מכל סככה ממופה
    negs = 0
    tries = 0
    while negs < 180 and tries < 2000:
        tries += 1
        base = random.choice(sh)
        lon = base['lon'] + random.uniform(-0.004, 0.004)
        lat = base['lat'] + random.uniform(-0.004, 0.004)
        x, y = merc(lon, lat)
        near = any(abs(merc(s['lon'], s['lat'])[0] - x) < 60 and
                   abs(merc(s['lon'], s['lat'])[1] - y) < 60 for s in sh)
        if near:
            continue
        try:
            img, _ = crop(lon, lat)
        except Exception:
            continue
        (img_d / f'n{negs}.png').write_bytes(img)
        (lbl_d / f'n{negs}.txt').write_text('')
        negs += 1
        time.sleep(PAUSE)
    print(f'ערכת אימון: {n} חיוביים + {negs} שליליים')


def stage_c():
    from ultralytics import YOLO
    import shutil
    root = OUT / 'train'
    imgs = sorted((root / 'images').glob('*.png'))
    random.seed(7)
    random.shuffle(imgs)
    cut = int(len(imgs) * 0.85)
    for grp, lst in (('train', imgs[:cut]), ('val', imgs[cut:])):
        (root / f'im_{grp}').mkdir(exist_ok=True)
        (root / f'lb_{grp}').mkdir(exist_ok=True)
        for p in lst:
            shutil.copy(p, root / f'im_{grp}' / p.name)
            shutil.copy(root / 'labels' / (p.stem + '.txt'), root / f'lb_{grp}' / (p.stem + '.txt'))
        # ultralytics מצפה ל-images/labels מקבילים
        os.makedirs(root / grp / 'images', exist_ok=True)
        os.makedirs(root / grp / 'labels', exist_ok=True)
        for p in (root / f'im_{grp}').glob('*'):
            shutil.move(str(p), root / grp / 'images' / p.name)
        for p in (root / f'lb_{grp}').glob('*'):
            shutil.move(str(p), root / grp / 'labels' / p.name)
    yaml = root / 'data.yaml'
    yaml.write_text(f"path: {root.resolve()}\ntrain: train/images\nval: val/images\nnames:\n  0: shelter\n")
    m = YOLO('yolov8n.pt')
    m.train(data=str(yaml), epochs=60, imgsz=512, batch=8, device='cpu',
            project=str((OUT / 'runs').resolve()), name='shelter', exist_ok=True, verbose=False)
    # ultralytics עלול להפנות את התוצרים לתיקיית ההגדרות שלו — הנתיב
    # האמין הוא זה שהמאמן עצמו מדווח (שעתיים אבדו על ההנחה ההפוכה)
    best = pathlib.Path(getattr(m.trainer, 'best', '') or '')
    if not best.is_file():
        cands = sorted(pathlib.Path.home().rglob('best.pt'), key=lambda x: x.stat().st_mtime)
        cands += sorted((OUT / 'runs').rglob('best.pt'), key=lambda x: x.stat().st_mtime)
        best = cands[-1]
    shutil.copy(best, OUT / 'shelter-model.pt')
    metrics = m.val(data=str(yaml))
    print('mAP50:', getattr(metrics.box, 'map50', '?'))


def tlv_stops():
    """תחנות הרישוי בתל אביב-יפו מהפיד העדכני (ארכיון אתמול)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from backfill_pubdest import S3, _exists
    import datetime
    from backfill_geo import central_dir, member_rows
    d0 = datetime.date.today() - datetime.timedelta(days=1)
    for back in range(6):
        d = d0 - datetime.timedelta(days=back)
        url = S3.format(y=d.year, m=f'{d.month:02d}', d=f'{d.day:02d}')
        if _exists(url):
            break
    cd = central_dir(url)
    c, rows = member_rows(url, cd, 'stops.txt')
    out = []
    for r in rows:
        if 'עיר: תל אביב יפו' in (r[c['stop_desc']] or ''):
            out.append({'code': r[c['stop_code']], 'name': r[c['stop_name']],
                        'lat': float(r[c['stop_lat']]), 'lon': float(r[c['stop_lon']])})
    return out


def stage_d():
    from ultralytics import YOLO
    from PIL import Image
    m = YOLO(str(OUT / 'shelter-model.pt'))
    stops = tlv_stops()
    print(f'תחנות רישוי בתל אביב-יפו: {len(stops)}')
    res = []
    ex_d = OUT / 'suspects'
    ex_d.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(stops):
        try:
            img, (cx, cy) = crop(s['lon'], s['lat'])
        except Exception:
            continue
        im = Image.open(io.BytesIO(img)).convert('RGB')
        r = m.predict(im, conf=0.3, verbose=False)[0]
        best_d = None
        for b in r.boxes.xyxy.tolist() if r.boxes is not None else []:
            px_x = (b[0] + b[2]) / 2
            px_y = (b[1] + b[3]) / 2
            # מרחק הזיהוי מנקודת הרישוי (מרכז התמונה), במטרים
            dist = math.hypot((px_x - PX / 2), (px_y - PX / 2)) * (2 * HALF / PX)
            if best_d is None or dist < best_d:
                best_d = dist
        verdict = ('no_shelter' if best_d is None else
                   'far' if best_d > 25 else 'ok')
        res.append({'code': s['code'], 'name': s['name'], 'lat': s['lat'],
                    'lon': s['lon'], 'dist': round(best_d, 1) if best_d is not None else None,
                    'v': verdict})
        if (i + 1) % 100 == 0:
            print(f'  {i+1}/{len(stops)}…', flush=True)
        time.sleep(PAUSE)
    json.dump({'gen': time.strftime('%Y-%m-%d'), 'stops': res},
              open(OUT / 'results.json', 'w', encoding='utf-8'), ensure_ascii=False)
    ok = sum(1 for r in res if r['v'] == 'ok')
    far = [r for r in res if r['v'] == 'far']
    no = [r for r in res if r['v'] == 'no_shelter']
    print(f"תקין: {ok} · חשד 'רחוקה': {len(far)} · לא זוהתה סככה: {len(no)}")
    # תמונות דוגמה ל-12 החשדות הראשונים לאימות עין
    for r in (far + no)[:12]:
        try:
            img, _ = crop(r['lon'], r['lat'])
            (ex_d / f"{r['v']}-{r['code']}.png").write_bytes(img)
            time.sleep(PAUSE)
        except Exception:
            pass


def stage_e():
    """חיפוש מתרחב לחשודות בלבד + כלל השיוך של שלמה: סככה שנמצאה
    משויכת לתחנה רק אם היא התחנה הרשומה הקרובה ביותר אליה (בפער ברור
    מהבאה בתור) — אם תחנה אחרת קרובה יותר, "זו לא היא"."""
    from ultralytics import YOLO
    from PIL import Image
    m = YOLO(str(OUT / 'shelter-model.pt'))
    res = json.load(open(OUT / 'results.json', encoding='utf-8'))
    stops = res['stops']
    allxy = [(s['code'], *merc(s['lon'], s['lat'])) for s in stops]
    suspects = [s for s in stops if s['v'] == 'no_shelter']
    print(f'חשודות לחיפוש מורחב: {len(suspects)}')
    found = []
    for i, s in enumerate(suspects):
        sx, sy = merc(s['lon'], s['lat'])
        dets = []
        # רשת 3x3 של חלונות 52 מ' = כיסוי ~156x156 מ' סביב הרישום
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                lon = s['lon'] + dx * (2 * HALF) / (111320 * math.cos(math.radians(s['lat'])))
                lat = s['lat'] + dy * (2 * HALF) / 110540
                try:
                    img, (cx, cy) = crop(lon, lat)
                except Exception:
                    continue
                im = Image.open(io.BytesIO(img)).convert('RGB')
                r = m.predict(im, conf=0.45, verbose=False)[0]
                for b in (r.boxes.xyxy.tolist() if r.boxes is not None else []):
                    wx = (cx - HALF) + (b[0] + b[2]) / 2 / PX * 2 * HALF
                    wy = (cy + HALF) - (b[1] + b[3]) / 2 / PX * 2 * HALF
                    dets.append((wx, wy))
                time.sleep(PAUSE)
        best = None
        for wx, wy in dets:
            dist_me = math.hypot(wx - sx, wy - sy)
            # כלל שלמה: אם תחנה רשומה אחרת קרובה יותר לסככה — זו לא היא
            others = sorted(math.hypot(wx - ox, wy - oy)
                            for c, ox, oy in allxy if c != s['code'])
            other_d = others[0] if others else 1e9
            if dist_me < other_d - 20 and (best is None or dist_me < best[0]):
                best = (dist_me, wx, wy, other_d)
        if best:
            found.append({'code': s['code'], 'name': s['name'],
                          'dist': round(best[0]), 'other_stop_dist': round(best[3])})
            print(f"  {s['code']} {s['name']}: סככה במרחק {best[0]:.0f} מ' מהרישום (התחנה האחרת הקרובה: {best[3]:.0f} מ')")
        if (i + 1) % 20 == 0:
            print(f'  {i+1}/{len(suspects)}…', flush=True)
    json.dump({'gen': time.strftime('%Y-%m-%d'), 'found': found},
              open(OUT / 'displaced.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'תחנות שכנראה "לא במקום" (סככה שלהן נמצאה רחוק): {len(found)}')


if __name__ == '__main__':
    OUT.mkdir(exist_ok=True)
    {'A': stage_a, 'B': stage_b, 'C': stage_c, 'D': stage_d, 'E': stage_e}[STAGE]()
