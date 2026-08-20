# -*- coding: utf-8 -*-
# מושך את רשימת אזורי-התעשייה הרשמית (משרד הכלכלה) מ-data.gov.il, ממיר את
# הגאומטריה מ-ITM (רשת ישראל, EPSG:2039) ל-WGS84, ומוציא official.json:
#   [{name, eng, district, avail, occ, cur_emp, fut_emp, open, polys:[[[la,lo],...],...]}]
# משמש את parks.py כדי (א) להשלים אזורים רשמיים שחסרים ב-OSM, (ב) להעשיר את
# הקיימים בנתוני עובדים/שטח. best-effort — כישלון לא מפיל את ה-pipeline.
import json, os, re, time, urllib.request, urllib.parse
from pyproj import Transformer

RID = os.environ.get('OFFICIAL_RID', '30af8da4-7586-4b00-ac88-c5ee75251632')
OUT = os.environ.get('OFFICIAL_OUT', 'official.json')
BASE = 'https://data.gov.il/api/3/action/'
UA = 'kav-bochan-parks/1.0'
TR = Transformer.from_crs('EPSG:2039', 'EPSG:4326', always_xy=True)  # (E,N)->(lon,lat)

# רצף קואורדינטות בודד (טבעת) בתוך WKT: "x y, x y, ..." (ITM, מטרים)
RING_RE = re.compile(r'\d[\d.]*\s+\d[\d.]*(?:\s*,\s*\d[\d.]*\s+\d[\d.]*)*')


def rings_wgs84(wkt):
    out = []
    for m in RING_RE.finditer(wkt or ''):
        pts = []
        for pair in m.group(0).split(','):
            xy = pair.split()
            if len(xy) != 2:
                continue
            lo, la = TR.transform(float(xy[0]), float(xy[1]))
            pts.append([round(la, 5), round(lo, 5)])
        if len(pts) >= 4:
            out.append(pts)
    return out


def main():
    u = BASE + 'datastore_search?' + urllib.parse.urlencode({'resource_id': RID, 'limit': 1000})
    req = urllib.request.Request(u, headers={'user-agent': UA, 'accept': 'application/json'})
    # data.gov.il נעלם לפעמים לדקות ארוכות (timeout בודד הפיל את הריצה
    # השבועית ב-9.8) — ניסיונות חוזרים על פני ~10 דקות לפני ויתור
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                recs = json.load(r).get('result', {}).get('records', [])
            break
        except Exception as e:
            if attempt == 5:
                raise
            print(f'ניסיון {attempt + 1} נכשל ({e}) — ממתין 2 דקות')
            time.sleep(120)
    zones = []
    for rec in recs:
        polys = rings_wgs84(rec.get('geom') or '')
        if not polys:
            continue

        def num(k):
            v = rec.get(k)
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None
        # רשימות המפעלים (בקשת איריס): המאגר מפריד שורות ב-<br> ולפעמים כמה
        # חברות באותה שורה מופרדות ב-';'. מפרקים לשמות בודדים בלי כפילויות.
        def facts(k):
            raw = rec.get(k)
            if not isinstance(raw, str):
                return []
            out = []
            for part in raw.replace('\r', '').split('<br>'):
                for q in part.split(';'):
                    q = q.strip()
                    if q and q not in out:
                        out.append(q)
            return out
        zones.append({
            'name': (rec.get('alina_name') or '').strip(),
            'eng': (rec.get('alina_eng_name') or '').strip(),
            'district': (rec.get('district') or '').strip(),
            'avail': num('available_space'), 'occ': num('occupied_space'),
            'cur_emp': num('current_employees'), 'fut_emp': num('future_employees'),
            'open': (rec.get('open_to_market') or '').strip(),
            'website': (rec.get('website') or '').strip(),
            'fs': facts('small_factories'), 'fm': facts('medium_factories'),
            'fb': facts('big_factories'),
            'polys': polys,
        })
    json.dump(zones, open(OUT, 'w'), ensure_ascii=False, separators=(',', ':'))
    print('אזורים רשמיים שנכתבו:', len(zones), '->', OUT)


if __name__ == '__main__':
    main()
