#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""משמר מחירי המנויים — חופשי יומי, חודשי ותקרת הפריפריה.

מחירי הנסיעה הבודדת נבדקים כל שבוע אוטומטית מול ה-GTFS, אבל המנויים
לא קיימים ב-GTFS בכלל, ולכן הם קבועים ידניים ב-fares/index.html. הכלי
הזה סוגר את הפער: קורא את הקבועים מהדף, מושך את המחירון הרשמי של
רב-פס (בהפצת משרד התחבורה דרך הופ-און, S3), ומוודא שכל מחיר שמוצג
באתר עדיין מופיע במחירון הרשמי — לפי הסדר, טבלה-טבלה.

כל אי-התאמה, כולל שינוי פורמט שמונע בדיקה, מודפסת כ-::warning:: כדי
שתופיע כהתראה על הריצה. הכלי לעולם לא מפיל את הריצה — התרעה בלבד.
"""
import re
import sys
import time
import urllib.request

URL = ('https://s3-eu-west-1.amazonaws.com/static.hopon.co.il'
      '/mot/ravPassPrices.html')
PAGE = 'fares/index.html'


def warn(msg):
    print(f'::warning::מחירי מנויים: {msg}')


def fetch():
    for attempt in range(3):
        try:
            req = urllib.request.Request(URL, headers={'User-Agent': 'kav-bochan/fares (pass-price guard)'})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            if attempt == 2:
                warn(f'לא הצלחתי למשוך את המחירון הרשמי ({e}) — לא נבדק השבוע')
                return None
            time.sleep(30)


def site_zones():
    """קריאת מערך ZONES ו-PERI מהדף — מקור האמת של מה שמוצג בפועל."""
    html = open(PAGE, encoding='utf-8').read()
    pat = re.compile(
        r"bus:\s*([\d.]+),\s*train:\s*([\d.]+|null),\s*daily:\s*([\d.]+),"
        r"\s*dt:\s*([\d.]+|null),\s*mb:\s*([\d.]+|null),\s*mt:\s*([\d.]+)")
    num = lambda s: None if s == 'null' else float(s)
    zones = [tuple(num(g) for g in m.groups()) for m in pat.finditer(html)]
    m = re.search(r'PERI=\{m:\s*([\d.]+),\s*eilat:\s*([\d.]+)\}', html)
    peri = (float(m.group(1)), float(m.group(2))) if m else None
    return zones, peri


def amounts(text):
    """כל הסכומים שצמוד אליהם סימן ₪, לפי סדר ההופעה."""
    out = []
    for m in re.finditer(r'₪\s*([\d.]+)|([\d.]+)\s*₪', text):
        out.append(float(m.group(1) or m.group(2)))
    return out


def subseq(needle, hay):
    """האם needle מופיע כתת-סדרה (לאו דווקא רצופה) בתוך hay."""
    it = iter(hay)
    return all(any(abs(h - n) < 0.005 for h in it) for n in needle)


def main():
    zones, peri = site_zones()
    if len(zones) != 6:
        warn(f'קריאת ZONES מהדף החזירה {len(zones)} שורות במקום 6 — הבדיקה לא רצה')
        return
    if peri is None:
        warn('קבוע PERI לא נמצא בדף — הבדיקה לא רצה')
        return

    html = fetch()
    if html is None:
        return
    text = re.sub(r'<script.*?</script>|<style.*?</style>', '', html, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', text)

    # גבולות הטבלאות בעמוד הרשמי, לפי הכותרות
    anchors = ['תעריף לנסיעה בודדת', 'תקרת תשלום יומית', 'תקרת חיוב חודשי', 'הנחות לזכאים']
    idx = [text.find(a) for a in anchors]
    if any(i < 0 for i in idx) or idx != sorted(idx):
        warn('מבנה העמוד הרשמי השתנה (כותרות חסרות/בסדר אחר) — לבדוק ידנית')
        return
    sec_single = amounts(text[idx[0]:idx[1]])
    sec_daily = amounts(text[idx[1]:idx[2]])
    sec_monthly = amounts(text[idx[2]:idx[3]])

    exp_single, exp_daily, exp_monthly = [], [], []
    for bus, train, daily, dt, mb, mt in zones:
        exp_single += [bus] + ([train] if train is not None else [])
        exp_daily += [daily] + ([dt] if dt is not None else [])
        exp_monthly += ([mb] if mb is not None else []) + [mt]

    for name, exp, sec in [('נסיעה בודדת', exp_single, sec_single),
                           ('חופשי יומי', exp_daily, sec_daily),
                           ('חופשי חודשי', exp_monthly, sec_monthly)]:
        if not subseq(exp, sec):
            warn(f'טבלת "{name}" באתר לא תואמת את המחירון הרשמי — '
                 f'באתר: {exp} · בעמוד הרשמי: {sec}')

    for v, what in [(peri[0], 'תקרת הפריפריה'), (peri[1], 'תקרת הפריפריה באילת')]:
        if not any(abs(a - v) < 0.005 for a in sec_monthly):
            warn(f'{what} ({v} ₪) שמוצגת באתר לא נמצאה במחירון הרשמי')

    print(f'מנויים: בודדת {len(exp_single)} · יומי {len(exp_daily)} · '
          f'חודשי {len(exp_monthly)} ערכים + פריפריה {peri} — נבדקו מול המחירון הרשמי')


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        warn(f'הבדיקה קרסה ({type(e).__name__}: {e}) — לבדוק ידנית')
    sys.exit(0)
