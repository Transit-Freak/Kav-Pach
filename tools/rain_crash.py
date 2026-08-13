# -*- coding: utf-8 -*-
# הקו הרטוב — גשם מול תאונות: הורדה ועיבוד של קובצי התאונות של הלמ"ס (PUF)
# ונתוני הגשם של השירות המטאורולוגי, מ-data.gov.il (API פתוח, בלי טוקן).
#
# הפלט: rain-crash/data/
#   summary.json — מספרי-העל הארציים (חלק התאונות בגשם, מכפיל חומרה, לפי שעה)
#   cells.json   — רשת תאים ~500 מ' עם ספירת תאונות רטוב/יבש ומקדם גשם
#   cities.json  — טבלת יישובים: חלק תאונות הגשם מול הממוצע הארצי + ימי גשם
#   roads.json   — כבישים בין-עירוניים לפי קטעי ק"מ
#
# EXPLORE=1 — מצב סיור: מדפיס מילונים ושדות בלי לבנות (לריצה ראשונה ב-CI).
import csv, io, json, math, os, sys, time, urllib.parse, urllib.request
from collections import defaultdict

API = 'https://data.gov.il/api/3/action/datastore_search'
UA = {'User-Agent': 'Mozilla/5.0 (kav-bochan rain-crash research; github.com/Transit-Freak/kav-bochan)'}
OUTDIR = os.environ.get('OUTDIR', 'rain-crash/data')
EXPLORE = os.environ.get('EXPLORE') == '1'

# משאבי ה-PUF המלא (למ"ס) — data + Dictionary לכל שנה
PUF = {
    2024: ('05d14adb-fe54-49f7-b7ce-f30348e2d959', 'c557fe0c-5f18-41ff-b756-44d26ed4aee4'),
    2023: ('ae0f1679-139f-4e69-a869-a60d5d76518b', '6ba1e593-36c6-48e0-9913-46afc1493102'),
    2022: ('ede3f02a-f9aa-4a6f-9eca-4c11a06f0043', '0bc58775-fed9-4ec2-bd8a-208c4a6c6f53'),
    2021: ('6957e7c2-6d68-4332-bbc8-2ee8d5ba6bd6', '589eda92-7c09-4e43-a553-db5e8e8c31a4'),
    2020: ('70a93f04-2ffe-4b02-a062-a818600a5b67', 'b1b7b2b1-e04b-4704-a929-792f19c6019b'),
}
IMS_STATIONS = '83841660-b9c4-4ecc-a403-d435b3e8c92f'   # תחנות השמ"ט
IMS_RAIN_DAILY = 'e80b470f-fcbc-4987-a685-d4fbefbd75d1'  # גשם יומי לפי תחנה


def fetch(resource, limit=32000, offset=0, tries=5):
    q = urllib.parse.urlencode({'resource_id': resource, 'limit': limit, 'offset': offset})
    for a in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(f'{API}?{q}', headers=UA), timeout=180) as r:
                return json.load(r)['result']
        except Exception as e:
            if a == tries - 1:
                raise
            print(f'  ניסיון {a+1} נכשל ({e}) — ממתינים', flush=True)
            time.sleep(8 * (a + 1))


def fetch_all(resource, label):
    rows, offset = [], 0
    while True:
        res = fetch(resource, offset=offset)
        batch = res.get('records', [])
        rows.extend(batch)
        total = res.get('total')
        print(f'  {label}: {len(rows)}/{total}', flush=True)
        if not batch or len(rows) >= (total or 0):
            break
        offset += len(batch)
    return rows


# ---- המרת רשת ישראל (ITM, EPSG:2039) ל-WGS84 — pyproj מותקן ב-CI ----
def itm_to_wgs():
    from pyproj import Transformer
    return Transformer.from_crs(2039, 4326, always_xy=True)


def load_dict(resource, year):
    # מילון הקודים של הלמ"ס בנוי כ-(MS_TAVLA, KOD, TEUR): שורות עם טבלה 0 הן
    # אינדקס — מספר טבלה לשם משתנה בעברית ("מזג אוויר"), ושורות עם מספר
    # טבלה N הן הקודים של אותו משתנה. ב-datastore שלוש העמודות לפעמים
    # מגיעות מאוחדות לעמודה דחוסה אחת ('0,1,יחידה משטרתית') — תומכים בשניהם.
    rows = fetch_all(resource, f'מילון {year}')
    if not rows:
        return {}
    cols = [c for c in rows[0].keys() if c != '_id']
    tv = next((c for c in cols if 'tavla' in c.lower()), None)
    kd = next((c for c in cols if c.lower() == 'kod'), None)
    tr_ = next((c for c in cols if 'teur' in c.lower()), None)
    fused = None if (tv and kd and tr_) else cols[0]

    def triple(r):
        if fused:
            parts = str(r.get(fused, '')).split(',', 2)
            return parts if len(parts) == 3 else None
        return [str(r.get(tv, '')), str(r.get(kd, '')), str(r.get(tr_, ''))]

    tables, codes = {}, defaultdict(dict)
    for r in rows:
        t = triple(r)
        if not t:
            continue
        tav, kod, teur = (str(x).strip() for x in t)
        if tav == '0':
            tables[kod] = teur          # מספר טבלה -> שם המשתנה
        else:
            codes[tav][kod] = teur      # קודי המשתנה עצמו
    named = {name: dict(codes.get(num, {})) for num, name in tables.items()}
    if EXPLORE:
        print(f'  מילון {year}: {len(tables)} טבלאות | פורמט {"דחוס" if fused else "עמודות"}')
        for name in named:
            if any(w in name for w in ('מזג', 'פני', 'חומרת', 'שעה')):
                print(f'   == {name}:', dict(list(named[name].items())[:12]))
    return named


def enc_poly(pts):
    # קידוד polyline (גוגל, דיוק 1e5) — תואם decPoly שבצד הלקוח
    out = []
    pla = plo = 0
    for la, lo in pts:
        ila, ilo = round(la * 1e5), round(lo * 1e5)
        for v in (ila - pla, ilo - plo):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        pla, plo = ila, ilo
    return ''.join(out)


def street_names():
    # (סמל יישוב, קוד רחוב) -> שם רחוב: מאתרים דינמית את מאגר הרחובות הארצי
    q = urllib.parse.urlencode({'q': 'רחובות בישראל', 'rows': 10})
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f'https://data.gov.il/api/3/action/package_search?{q}', headers=UA), timeout=90) as r:
            pkgs = json.load(r)['result']['results']
    except Exception as e:
        print('חיפוש מאגר הרחובות נכשל:', e)
        return {}
    for p in pkgs:
        for res in p.get('resources', []):
            if (res.get('format') or '').upper() != 'CSV':
                continue
            try:
                probe = fetch(res['id'], limit=1)
            except Exception:
                continue
            flds = [f['id'] for f in probe.get('fields', [])]
            sem = next((f for f in flds if 'סמל_ישוב' in f or 'סמל_יישוב' in f), None)
            stc = next((f for f in flds if 'סמל_רחוב' in f), None)
            stn = next((f for f in flds if 'שם_רחוב' in f), None)
            if not (sem and stc and stn):
                continue
            print('מאגר הרחובות:', p.get('title'), res['id'])
            rows = fetch_all(res['id'], 'רחובות')
            return {(str(r[sem]).strip(), str(r[stc]).strip()): str(r[stn]).strip()
                    for r in rows if r.get(sem) and r.get(stc) and r.get(stn)}
    print('לא נמצא מאגר רחובות — מדלגים על שכבת הרחובות')
    return {}


OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter']


def _norm_st(n):
    # נרמול שם רחוב להשוואה: בלי גרשיים, מקפים וקידומות שד'/רח'
    n = str(n or '')
    for ch in '"\'׳״`’':
        n = n.replace(ch, '')
    n = n.replace('-', ' ').replace('שדרות ', '').replace('שד ', '').replace('רח ', '')
    return ' '.join(n.split())


def overpass_streets(items):
    # מקבל [{'name','la','lo',...}] ומחזיר לכל אחד segs=[polyline,...] מ-OSM.
    # שאילתות באצוות. השמות של הלמ"ס לא זהים לשמות ב-OSM ("קדיש לוז" מול
    # "שד' קדיש לוז") — לכן חיפוש הכלה (regex) על שם מנורמל, לא שוויון מדויק.
    import re as _re
    out = {}
    for c0 in range(0, len(items), 20):
        chunk = items[c0:c0 + 20]
        parts = ''.join(
            f'way[highway]["name"~"{_re.escape(_norm_st(s["name"]).replace(" ", ".?"))}"]'
            f'(around:1500,{s["la"]:.5f},{s["lo"]:.5f});'
            for s in chunk)
        qy = f'[out:json][timeout:90];({parts});out geom;'
        data = None
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(ep, data=urllib.parse.urlencode({'data': qy}).encode(),
                                             headers=UA)
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.load(r)
                break
            except Exception as e:
                print(f'  Overpass נכשל ({ep.split("/")[2]}): {e}', flush=True)
                time.sleep(15)
        if not data:
            continue
        for el in data.get('elements', []):
            nm = (el.get('tags') or {}).get('name')
            geom = el.get('geometry') or []
            if not nm or len(geom) < 2:
                continue
            # שיוך לרחוב הקרוב ביותר ששמו המנורמל מוכל בשם ה-OSM (שמות חוזרים בין ערים)
            g0 = geom[0]
            nmn = _norm_st(nm)
            best, bd = None, 1e9
            for s in chunk:
                if _norm_st(s['name']) not in nmn:
                    continue
                d = (g0['lat'] - s['la']) ** 2 + (g0['lon'] - s['lo']) ** 2
                if d < bd:
                    bd, best = d, s
            if best is None or bd > 0.03 ** 2:
                continue
            out.setdefault(id(best), {'s': best, 'segs': []})['segs'].append(
                enc_poly([(g['lat'], g['lon']) for g in geom]))
        print(f'  Overpass: {min(c0+20,len(items))}/{len(items)} רחובות', flush=True)
        time.sleep(4)
    return [{**v['s'], 'segs': v['segs']} for v in out.values() if v['segs']]


def yishuv_names():
    # סמל יישוב -> שם: מאתרים דינמית את משאב רשימת היישובים ב-data.gov.il
    # (מזהים לפי שדות שמכילים 'סמל' + שם עברי), כדי לא לתלות במזהה קשיח.
    q = urllib.parse.urlencode({'q': 'רשימת יישובים', 'rows': 10})
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f'https://data.gov.il/api/3/action/package_search?{q}', headers=UA), timeout=90) as r:
            pkgs = json.load(r)['result']['results']
    except Exception as e:
        print('חיפוש רשימת יישובים נכשל:', e)
        return {}
    for p in pkgs:
        for res in p.get('resources', []):
            if (res.get('format') or '').upper() != 'CSV':
                continue
            try:
                probe = fetch(res['id'], limit=1)
            except Exception:
                continue
            flds = [f['id'] for f in probe.get('fields', [])]
            sem = next((f for f in flds if 'סמל_י' in f or f.lower() in ('semel', 'סמל')), None)
            nam = next((f for f in flds if 'שם_י' in f or f == 'שם יישוב' or 'city_name_he' in f.lower()), None)
            if not (sem and nam):
                continue
            print('משאב היישובים:', p.get('title'), res['id'], '| שדות:', sem, nam)
            rows = fetch_all(res['id'], 'יישובים')
            return {str(r[sem]).strip(): str(r[nam]).strip().replace('  ', ' ')
                    for r in rows if r.get(sem) and r.get(nam)}
    print('לא נמצא משאב יישובים — נשתמש בסמלים בלבד')
    return {}


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    # ---- מילון 2024 — קודי "רטוב"/"גשום"/חומרה לפי שמות הטבלאות בעברית ----
    dic = load_dict(PUF[2024][1], 2024)

    def table_like(*words):
        for name, tbl in dic.items():
            if any(w in name for w in words):
                return name, tbl
        return None, {}

    pn_name, pne_tbl = table_like('פני הכביש', 'פני כביש')
    mz_name, mez_tbl = table_like('מזג')
    sv_name, sev_tbl = table_like('חומרת התאונה', 'חומרה')
    wet_pne = {c for c, l in pne_tbl.items() if 'רטוב' in l}
    rain_mezeg = {c for c, l in mez_tbl.items() if 'גשום' in l or 'גשם' in l}
    unk_pne = {c for c, l in pne_tbl.items() if 'לא ידוע' in l or 'אחר' in l}
    unk_mezeg = {c for c, l in mez_tbl.items() if 'לא ידוע' in l or 'אחר' in l}
    severe = {c for c, l in sev_tbl.items() if 'קטלנית' in l or 'קשה' in l} or {'1', '2'}
    print(f'טבלאות: "{pn_name}" {pne_tbl} | "{mz_name}" {mez_tbl} | "{sv_name}" {sev_tbl}', flush=True)
    print('קודי כביש-רטוב:', wet_pne, '| קודי מזג-גשום:', rain_mezeg,
          '| חומרה קשה:', severe, '| לא-ידוע:', unk_pne, unk_mezeg, flush=True)
    if not EXPLORE and (not wet_pne or not rain_mezeg):
        # בלי קודי רטוב/גשום כל הבנייה חסרת משמעות — עדיף ליפול בקול
        sys.exit('המילון לא פוענח: לא נמצאו קודי רטוב/גשום. הריצו EXPLORE=1 ובדקו.')

    # ---- תחנות וגשם יומי של השמ"ט: ימי-גשם ממוצעים בשנה לכל תחנה ----
    st_rows = fetch_all(IMS_STATIONS, 'תחנות שמ"ט')
    if EXPLORE and st_rows:
        print('  שדות תחנות:', list(st_rows[0].keys()))
    rain_rows = fetch_all(IMS_RAIN_DAILY, 'גשם יומי')
    if EXPLORE and rain_rows:
        print('  שדות גשם יומי:', list(rain_rows[0].keys()))
        for r in rain_rows[:5]:
            print('   ', r)
    if EXPLORE:
        # במצב סיור מספיקה רשומת תאונה אחת לווידוא השדות
        one = fetch(PUF[2024][0], limit=1)
        print('  שדות תאונה 2024:', [f['id'] for f in one.get('fields', [])])
        return

    # עמודת מ"מ הגשם — מזהים לפי שם שמכיל rain/rn
    rain_col = next((c for c in rain_rows[0].keys()
                     if 'rain' in c.lower() or c.lower() in ('rn', 'prcp', 'rain_06')), None)
    date_col = next((c for c in rain_rows[0].keys() if 'time' in c.lower() or 'date' in c.lower()), None)
    print('עמודת גשם:', rain_col, '| עמודת תאריך:', date_col, flush=True)
    rain_days = defaultdict(lambda: defaultdict(int))   # stn -> year -> ימי גשם ≥1 מ"מ
    for r in (rain_rows if (rain_col and date_col) else []):
        try:
            mm = float(r.get(rain_col) or 0)
            y = int(str(r.get(date_col))[:4])
        except (TypeError, ValueError):
            continue
        if mm >= 1.0:
            rain_days[r.get('stn_num')][y] += 1
    stn_avg = {}
    for stn, ys in rain_days.items():
        full = [n for y, n in ys.items() if n > 0]
        if full:
            stn_avg[stn] = sum(full) / len(full)
    st_loc = {r['stn_num']: (r.get('stn_lat'), r.get('stn_long')) for r in st_rows
              if r.get('stn_lat') and r.get('stn_long')}
    print('תחנות עם ממוצע ימי-גשם:', len(stn_avg), flush=True)

    def rain_days_at(la, lo):
        best, bd = None, 1e9
        for stn, avg in stn_avg.items():
            loc = st_loc.get(stn)
            if not loc:
                continue
            d = (la - loc[0]) ** 2 + (lo - loc[1]) ** 2
            if d < bd:
                bd, best = d, avg
        return best

    # ---- הורדת התאונות ----
    tr = itm_to_wgs()
    acc = []
    for year, (res, _) in sorted(PUF.items()):
        rows = fetch_all(res, f'תאונות {year}')
        for r in rows:
            x, y = r.get('X'), r.get('Y')
            if not x or not y:
                continue
            try:
                lo, la = tr.transform(float(x), float(y))
            except Exception:
                continue
            if not (29.0 < la < 33.5 and 34.0 < lo < 36.0):
                continue
            pne = str(r.get('PNE_KVISH', '')).strip()
            mez = str(r.get('MEZEG_AVIR', '')).strip()
            wet = (pne in wet_pne) or (mez in rain_mezeg)
            known = not (pne in unk_pne and mez in unk_mezeg)
            acc.append({
                'la': la, 'lo': lo, 'wet': wet, 'known': known,
                'y': year, 'sev': str(r.get('HUMRAT_TEUNA', '')).strip(),
                'mo': r.get('HODESH_TEUNA'), 'sh': r.get('SHAA'),
                'yb': r.get('SEMEL_YISHUV'), 'kv': r.get('KVISH1'), 'km': r.get('KM'),
                'rh': r.get('REHOV1'), 'urb': r.get('THUM_GEOGRAFI'),
                'mz': mez, 'pn': pne,
            })
    print('תאונות עם מיקום:', len(acc), flush=True)

    known = [a for a in acc if a['known']]
    wet_n = sum(1 for a in known if a['wet'])
    base = wet_n / len(known) if known else 0
    print(f'חלק התאונות בגשם/רטוב ארצית: {base:.3f} ({wet_n}/{len(known)})', flush=True)

    # מכפיל חומרה: חלק הקטלניות+קשות בתוך תאונות רטובות מול יבשות
    def sev_share(items):
        s = [a for a in items if a['sev'] in severe]
        return len(s) / len(items) if items else 0
    wet_acc = [a for a in known if a['wet']]
    dry_acc = [a for a in known if not a['wet']]

    # ---- רשת תאים ----
    CL, CO = 0.0045, 0.0055   # ~500 מ'
    cells = defaultdict(lambda: [0, 0, 0])   # (gy,gx) -> [wet, dry, קשות-בגשם]
    for a in known:
        k = (int(a['la'] / CL), int(a['lo'] / CO))
        if a['wet']:
            cells[k][0] += 1
            if a['sev'] in severe:
                cells[k][2] += 1
        else:
            cells[k][1] += 1
    out_cells = []
    for (gy, gx), (w, d, ws) in cells.items():
        tot = w + d
        if tot < 8 or w < 2:
            continue
        share = w / tot
        rf = share / base if base else 0
        out_cells.append([round((gy + 0.5) * CL, 4), round((gx + 0.5) * CO, 4), w, d, round(rf, 2), ws])
    out_cells.sort(key=lambda c: -c[4])
    print('תאים במפה:', len(out_cells), flush=True)

    # ---- יישובים ----
    by_city = defaultdict(lambda: [0, 0, [0.0, 0.0], 0])
    for a in known:
        if not a['yb']:
            continue
        e = by_city[a['yb']]
        e[0] += 1 if a['wet'] else 0
        e[1] += 0 if a['wet'] else 1
        e[2][0] += a['la']; e[2][1] += a['lo']
        e[3] += 1
    out_cities = []
    for semel, (w, d, (sla, slo), n) in by_city.items():
        if n < 40:
            continue
        la, lo = sla / n, slo / n
        rd = rain_days_at(la, lo)
        out_cities.append({'s': semel, 'w': w, 'd': d, 'rf': round((w / n) / base, 2) if base else 0,
                           'la': round(la, 4), 'lo': round(lo, 4),
                           'rd': round(rd) if rd else None})
    out_cities.sort(key=lambda c: -c['rf'])
    print('יישובים בטבלה:', len(out_cities), flush=True)

    # ---- כבישים בין-עירוניים לפי קטעי 5 ק"מ ----
    # יחידות ה-KM לא מתועדות חד-משמעית (ק"מ או עשיריות) — קובעים לפי הנתונים:
    # אם האחוזון ה-99 גדול מ-600, אין כביש כזה בישראל => עשיריות-ק"מ.
    kms = sorted(float(a['km']) for a in known
                 if a['kv'] and a['km'] is not None and str(a['km']).replace('.', '').isdigit())
    p99 = kms[int(len(kms) * 0.99)] if kms else 0
    km_scale = 10.0 if p99 > 600 else 1.0
    print(f'KM: p99={p99} | מפרשים כ{"עשיריות-ק"+chr(34)+"מ" if km_scale == 10 else "ק"+chr(34)+"מ"}', flush=True)
    by_road = defaultdict(lambda: [0, 0])
    for a in known:
        if not a['kv'] or a['km'] is None:
            continue
        try:
            seg = int(float(a['km']) / km_scale // 5) * 5
        except (TypeError, ValueError):
            continue
        k = (a['kv'], seg)
        by_road[k][0 if a['wet'] else 1] += 1
    out_roads = []
    for (kv, seg), (w, d) in by_road.items():
        tot = w + d
        if tot < 12 or w < 3:
            continue
        out_roads.append({'kv': kv, 'seg': seg, 'w': w, 'd': d,
                          'rf': round((w / tot) / base, 2) if base else 0})
    out_roads.sort(key=lambda c: -c['rf'])
    print('קטעי כביש:', len(out_roads), flush=True)

    # ---- לפי חודש ----
    by_month = defaultdict(lambda: [0, 0])
    for a in known:
        try:
            m = int(a['mo'])
        except (TypeError, ValueError):
            continue
        by_month[m][0 if a['wet'] else 1] += 1

    import datetime
    summary = {
        'gen': datetime.date.today().isoformat(),
        'years': sorted(PUF.keys()),
        'total': len(acc), 'known': len(known),
        'wet': wet_n, 'base_share': round(base, 4),
        'sev_share_wet': round(sev_share(wet_acc), 4),
        'sev_share_dry': round(sev_share(dry_acc), 4),
        'by_month': {m: v for m, v in sorted(by_month.items())},
        'wet_codes': {'pne': sorted(wet_pne), 'mezeg': sorted(rain_mezeg)},
        'dict_pne': pne_tbl, 'dict_mezeg': mez_tbl, 'dict_sev': sev_tbl,
    }
    json.dump(summary, open(os.path.join(OUTDIR, 'summary.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    json.dump({'gen': summary['gen'], 'base': summary['base_share'], 'cells': out_cells},
              open(os.path.join(OUTDIR, 'cells.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    json.dump({'gen': summary['gen'], 'base': summary['base_share'], 'cities': out_cities},
              open(os.path.join(OUTDIR, 'cities.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    json.dump({'gen': summary['gen'], 'base': summary['base_share'], 'roads': out_roads},
              open(os.path.join(OUTDIR, 'roads.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    names = yishuv_names()
    json.dump({'names': names}, open(os.path.join(OUTDIR, 'names.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print('שמות יישובים:', len(names), flush=True)

    # ---- רחובות (בקשת המשתמשים): סימון קטע הרחוב שבו קרו תאונות הגשם ----
    # קיבוץ לפי (יישוב, קוד רחוב), שם מהמאגר הארצי, גאומטריה מ-OSM.
    stn = street_names()
    by_street = defaultdict(lambda: [0, 0, 0.0, 0.0, 0])
    for a in known:
        if not a['yb'] or not a['rh']:
            continue
        e = by_street[(str(a['yb']), str(a['rh']))]
        e[0] += 1 if a['wet'] else 0
        e[1] += 0 if a['wet'] else 1
        e[2] += a['la']; e[3] += a['lo']; e[4] += 1
    cand = []
    for (sem, rh), (w, d, sla, slo, n) in by_street.items():
        if w < 2 or n < 8:
            continue
        name = stn.get((sem, rh)) or stn.get((sem, rh.lstrip('0')))
        if not name:
            continue
        cand.append({'name': name, 'city': sem, 'w': w, 'd': d,
                     'rf': round((w / n) / base, 2) if base else 0,
                     'la': sla / n, 'lo': slo / n})
    cand.sort(key=lambda s: -s['w'])
    cand = cand[:400]   # תקרה הוגנת ל-Overpass; הרחובות עם הכי הרבה תאונות-גשם
    print('רחובות מועמדים לגאומטריה:', len(cand), flush=True)
    with_geom = overpass_streets(cand)
    out_streets = [{'n': s['name'], 'c': s['city'], 'w': s['w'], 'd': s['d'],
                    'rf': s['rf'], 'segs': s['segs']} for s in with_geom]
    json.dump({'gen': summary['gen'], 'base': summary['base_share'], 'streets': out_streets},
              open(os.path.join(OUTDIR, 'streets.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print('רחובות עם גאומטריה:', len(out_streets), flush=True)

    # ---- הנתונים הגולמיים להורדה (בקשת המשתמשים): כל התאונות, עם התוויות ----
    with open(os.path.join(OUTDIR, 'accidents.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        wcsv = csv.writer(f)
        wcsv.writerow(['שנה', 'חודש', 'סמל_יישוב', 'יישוב', 'כביש', 'קוד_רחוב',
                       'lat', 'lon', 'בגשם_או_רטוב', 'מזג_אוויר', 'פני_כביש', 'חומרה'])
        for a in acc:
            wcsv.writerow([a['y'], a['mo'], a['yb'] or '', names.get(str(a['yb']), ''),
                           a['kv'] or '', a['rh'] or '',
                           round(a['la'], 5), round(a['lo'], 5), 1 if a['wet'] else 0,
                           mez_tbl.get(a['mz'], a['mz']), pne_tbl.get(a['pn'], a['pn']),
                           sev_tbl.get(a['sev'], a['sev'])])
    print('accidents.csv:', len(acc), 'שורות', flush=True)
    print('נכתב:', OUTDIR, flush=True)


if __name__ == '__main__':
    main()
