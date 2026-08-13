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
    # מילון הקודים של הלמ"ס: שדה -> קוד -> תווית. שמות העמודות משתנים בין
    # שנים, לכן מזהים אותן לפי תוכן ולא לפי שם.
    rows = fetch_all(resource, f'מילון {year}')
    if not rows:
        return {}
    cols = list(rows[0].keys())
    fld = next((c for c in cols if 'field' in c.lower() or 'משתנה' in c or 'variable' in c.lower()), None)
    code = next((c for c in cols if c.lower() in ('code', 'קוד', 'value') or 'קוד' in c), None)
    lab = next((c for c in cols if 'label' in c.lower() or 'תיאור' in c or 'תווית' in c or 'desc' in c.lower()), None)
    if EXPLORE:
        print(f'  עמודות המילון {year}: {cols} | זוהו: fld={fld} code={code} lab={lab}')
        for r in rows[:12]:
            print('   ', r)
    d = defaultdict(dict)
    if fld and code and lab:
        for r in rows:
            try:
                d[str(r[fld]).strip()][str(r[code]).strip()] = str(r[lab]).strip()
            except Exception:
                continue
    return d


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    # ---- מילון 2024 — לזיהוי קודי "רטוב"/"גשום" באופן דינמי ----
    dic = load_dict(PUF[2024][1], 2024)
    if EXPLORE:
        for f in ('MEZEG_AVIR', 'PNE_KVISH', 'HUMRAT_TEUNA', 'SHAA', 'SUG_DEREH'):
            print(f'== {f}:', dict(list(dic.get(f, {}).items())[:30]))

    def codes_containing(field, *words):
        return {c for c, l in dic.get(field, {}).items() if any(w in l for w in words)}

    wet_pne = codes_containing('PNE_KVISH', 'רטוב')
    rain_mezeg = codes_containing('MEZEG_AVIR', 'גשום', 'גשם')
    unk_pne = codes_containing('PNE_KVISH', 'לא ידוע', 'אחר')
    unk_mezeg = codes_containing('MEZEG_AVIR', 'לא ידוע', 'אחר')
    print('קודי כביש-רטוב:', wet_pne, '| קודי מזג-גשום:', rain_mezeg,
          '| לא-ידוע:', unk_pne, unk_mezeg, flush=True)
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
                'y': year, 'sev': r.get('HUMRAT_TEUNA'),
                'mo': r.get('HODESH_TEUNA'), 'sh': r.get('SHAA'),
                'yb': r.get('SEMEL_YISHUV'), 'kv': r.get('KVISH1'), 'km': r.get('KM'),
                'urb': r.get('THUM_GEOGRAFI'),
            })
    print('תאונות עם מיקום:', len(acc), flush=True)

    known = [a for a in acc if a['known']]
    wet_n = sum(1 for a in known if a['wet'])
    base = wet_n / len(known) if known else 0
    print(f'חלק התאונות בגשם/רטוב ארצית: {base:.3f} ({wet_n}/{len(known)})', flush=True)

    # מכפיל חומרה: חלק הקטלניות+קשות בתוך תאונות רטובות מול יבשות
    def sev_share(items):
        s = [a for a in items if a['sev'] in (1, 2, '1', '2')]
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
            if a['sev'] in (1, 2, '1', '2'):
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
    by_road = defaultdict(lambda: [0, 0])
    for a in known:
        if not a['kv'] or a['km'] is None:
            continue
        try:
            seg = int(float(a['km']) // 50) * 5   # KM נשמר בעשיריות-ק"מ בלמ"ס
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
        'dict_pne': dic.get('PNE_KVISH', {}), 'dict_mezeg': dic.get('MEZEG_AVIR', {}),
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
    print('נכתב:', OUTDIR, flush=True)


if __name__ == '__main__':
    main()
