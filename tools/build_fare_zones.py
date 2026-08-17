#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""המרת פוליגוני אזורי התעריף הרשמיים לקובץ נתונים של אתר המחירון.

הקלט: fares/checks/pricing-zones.json — תגובת GetPricingZones של
bus.gov.il (נמשכת ב-probe-fare-zones): ארבעה פוליגונים ב-WKT.
  99 + 902 = אזור 1 (פריפריה) · 905 = רצועת המרכז · 901 = אזור אילת
הפלט: fares/data/fare-zones.json — אותם פוליגונים בקידוד polyline
(כמו שכבות פוליגונים אחרות במשפחה), בדיוק מלא בלי דילול.
"""
import json
import os
import re
import time

SRC = os.environ.get('SRC', 'fares/checks/pricing-zones.json')
OUT = os.environ.get('OUT', 'fares/data/fare-zones.json')


def enc_polyline(pts):
    """קידוד polyline (מקביל ל-dec_poly שבאתרים): נקודות (lat, lon)."""
    out, pla, plo = [], 0, 0
    for la, lo in pts:
        ila, ilo = round(la * 1e5), round(lo * 1e5)
        for d in (ila - pla, ilo - plo):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        pla, plo = ila, ilo
    return ''.join(out)


def main():
    d = json.load(open(SRC, encoding='utf-8'))
    zones = {}
    for z in d['data']:
        rings = []
        for ring in re.findall(r'\(([\d.,\s-]+)\)', z['geom']):
            pts = []
            for pair in ring.split(','):
                lo, la = map(float, pair.split())
                pts.append((la, lo))
            rings.append(enc_polyline(pts))
        zones[str(z['zone'])] = rings
    for want in ('99', '901', '902', '905'):
        if want not in zones:
            raise SystemExit(f'אזור {want} חסר בתגובת ה-API — לא כותבים קובץ חלקי')
    out = {'gen': time.strftime('%Y-%m-%d'),
           'src': 'bus.gov.il — GetPricingZones (הרשות הארצית לתחבורה ציבורית)',
           'legend': {'99': 'אזור 1 צפון+מרכז-הארץ ללא המטרופולינים', '902': 'אזור 1 ערבה',
                      '905': 'רצועת המרכז (המטרופולינים)', '901': 'אזור אילת (ללא מע"מ)'},
           'zones': zones}
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('נכתבו', len(zones), 'אזורים →', OUT, f'({os.path.getsize(OUT)} bytes)')


if __name__ == '__main__':
    main()
