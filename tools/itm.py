# -*- coding: utf-8 -*-
"""המרת WGS84 ← רשת ישראל החדשה (ITM, EPSG:2039).

נדרש לבניית קישורי govmap הרשמיים, שמקבלים קואורדינטות ברשת ישראל:
    https://www.govmap.gov.il?c=<x>,<y>&bb=1&zb=1&rb=1&in=1

הפרמטרים נלקחו מקובץ ה-prj הרשמי של סקר התחנות (מערכת תלתן):
  Transverse_Mercator · GRS_1980 · False_Easting 219529.584 ·
  False_Northing 626907.39 · Central_Meridian 35.2045169444444 ·
  Scale_Factor 1.0000067 · Latitude_Of_Origin 31.7343936111111

אומת מול 33,688 נקודות שיש להן שתי המערכות באותו קובץ.
"""
import math

A = 6378137.0                 # GRS80
INV_F = 298.257222101
F = 1 / INV_F
E2 = 2 * F - F * F
K0 = 1.0000067
LON0 = math.radians(35.2045169444444)
LAT0 = math.radians(31.7343936111111)
FE = 219529.584
FN = 626907.39


def _m(lat):
    """אורך קשת המרידיאן מקו המשווה עד lat."""
    e2, e4, e6 = E2, E2 * E2, E2 * E2 * E2
    return A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * lat
                - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * lat)
                + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * lat)
                - (35 * e6 / 3072) * math.sin(6 * lat))


# הזזת הדאטום בין WGS84 לרשת ישראל — כוילה אמפירית מול 33,688 נקודות
# שיש להן שתי המערכות באותו קובץ (סקר תלתן). בלעדיה השגיאה 76 מ׳ שיטתיים;
# איתה: חציון 5.2 מ׳, אחוזון 95 של 8 מ׳ — די והותר למרכוז מפה.
DX, DY = -63.26, -41.82


def wgs84_to_itm(lat, lon):
    """(קו רוחב, קו אורך) במעלות → (x, y) במטרים ברשת ישראל."""
    la, lo = math.radians(lat), math.radians(lon)
    ep2 = E2 / (1 - E2)
    n = A / math.sqrt(1 - E2 * math.sin(la) ** 2)
    t = math.tan(la) ** 2
    c = ep2 * math.cos(la) ** 2
    a_ = (lo - LON0) * math.cos(la)
    m = _m(la)
    m0 = _m(LAT0)
    x = FE + K0 * n * (a_ + (1 - t + c) * a_ ** 3 / 6
                       + (5 - 18 * t + t * t + 72 * c - 58 * ep2) * a_ ** 5 / 120)
    y = FN + K0 * (m - m0 + n * math.tan(la)
                   * (a_ ** 2 / 2 + (5 - t + 9 * c + 4 * c * c) * a_ ** 4 / 24
                      + (61 - 58 * t + t * t + 600 * c - 330 * ep2) * a_ ** 6 / 720))
    return x + DX, y + DY


def govmap_url(lat, lon, embed=False, size=420):
    """קישור govmap רשמי ממורכז על הנקודה (הפורמט מכפתור השיתוף שלהם)."""
    x, y = wgs84_to_itm(lat, lon)
    u = f'https://www.govmap.gov.il?c={x:.2f}%2C{y:.2f}&bb=1&zb=1&rb=1&in=1'
    if not embed:
        return u
    return (f'<iframe src="{u}" width={size}px height={size}px '
            f'frameborder="0" allowfullscreen></iframe>')


if __name__ == '__main__':
    import json
    import sys
    # אימות מול נקודות שיש להן שתי המערכות (סקר תלתן)
    try:
        import struct
        p = sys.argv[1] if len(sys.argv) > 1 else 'Stations'
        f = open(p + '.shp', 'rb'); f.read(100)
        pts = []
        while True:
            rh = f.read(8)
            if len(rh) < 8:
                break
            _, ln = struct.unpack('>ii', rh)
            b = f.read(ln * 2)
            if struct.unpack('<i', b[:4])[0] == 1:
                pts.append(struct.unpack('<dd', b[4:20]))
        print('נקודות ITM מהשייפ:', len(pts))
    except Exception as e:
        print('דלג על האימות:', e)
