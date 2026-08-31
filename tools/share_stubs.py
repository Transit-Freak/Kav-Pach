# -*- coding: utf-8 -*-
"""דפי-שיתוף (בקשת שלמה): וואטסאפ קורא את תגי התצוגה בלי להריץ את הדף,
וכתובות עם סולמית (#356) לא מגיעות לשרת — אז כל שיתוף הציג כרטיס גנרי.

כאן נוצר דף זעיר לכל ישות משתפת — קו, רכב, תחנת-התנגשות — שכולל את
השם בכותרת ואת סמל האתר, ומפנה מיד לדף האמיתי. כפתורי השיתוף באתרים
מפיצים את כתובות הדפים האלה. הקבצים דטרמיניסטיים: ריצה חוזרת משנה רק
את מה שבאמת השתנה, ולכן הקומיטים הליליים קטנים.

הפלט: s/l-<variant>.html · s/v-<plate>.html · s/r-<code>.html
"""
import html
import json
import os
import sys

BASE = 'https://transit-freak.github.io/kav-bochan'
OUT = 's'

STUB = '''<!doctype html><html lang="he"><head><meta charset="utf-8">
<title>{title}</title>
<link rel="icon" href="{icon}"><link rel="apple-touch-icon" href="{icon}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{icon}">
<meta name="twitter:card" content="summary">
<meta http-equiv="refresh" content="0;url={url}">
<script>location.replace({url_js});</script>
</head><body style="font-family:sans-serif;text-align:center;padding:40px" dir="rtl">
<a href="{url}">{title}</a>
</body></html>'''


def write_stub(name, title, desc, url, icon):
    p = os.path.join(OUT, name)
    content = STUB.format(title=html.escape(title), desc=html.escape(desc),
                          url=html.escape(url), url_js=json.dumps(url),
                          icon=html.escape(icon))
    try:
        if open(p, encoding='utf-8').read() == content:
            return False
    except FileNotFoundError:
        pass
    with open(p, 'w', encoding='utf-8') as f:
        f.write(content)
    return True


def fsafe(rd):
    return rd.replace('#', 'H').replace('*', 'X').replace(':', '-')


def main():
    os.makedirs(OUT, exist_ok=True)
    n = w = 0

    # --- הקו בזמן: כל וריאנט ---
    try:
        lines = json.load(open('line-history/data/lines.json', encoding='utf-8'))['lines']
    except Exception:
        lines = []
    for e in lines:
        rd = e.get('rd') or ''
        if not rd:
            continue
        line = e.get('line') or ''
        dest = (e.get('dest') or '').split('<->')[-1].split('-')[0][:40]
        title = f'קו {line} — הקו בזמן' if line else f'{rd} — הקו בזמן'
        desc = (f'ההיסטוריה המלאה של קו {line}' + (f' אל {dest}' if dest else '')
                + f' · {e.get("op") or ""} · באתר הקו הבוחן').strip(' ·')
        url = f'{BASE}/line-history/#{rd}'
        w += write_stub(f'l-{fsafe(rd)}.html', title, desc, url,
                        f'{BASE}/line-history/icon-512.png')
        n += 1

    # --- צי הרכבים: כל רכב ---
    try:
        d = json.load(open('fleet/data/fleet.json', encoding='utf-8'))
        off = 1 if d.get('v') == 2 else 0
        for op in d['operators']:
            for v in op['vehicles']:
                plate = str(v[0])
                model = str(v[4 + off] or '') if len(v) > 4 + off else ''
                title = f'רכב {plate} — צי הרכבים'
                desc = (f'{model} · {op.get("name") or ""}'.strip(' ·')
                        or 'כרטיס הרכב המלא') + ' · באתר הקו הבוחן'
                url = f'{BASE}/fleet/#v={plate}'
                w += write_stub(f'v-{plate.replace("/", "")}.html', title, desc, url,
                                f'{BASE}/fleet/icon-512.png')
                n += 1
    except Exception as e:
        print('צי: דילוג —', type(e).__name__, e, file=sys.stderr)

    # --- רציף כפול: תחנות ההתנגשות ---
    try:
        d = json.load(open('ratzif/data/conflicts.json', encoding='utf-8'))
        for st in d.get('st') or []:
            code, name, city = st[0], st[1], st[2]
            if not code:
                continue
            title = f'{name} — רציף כפול'
            desc = (f'התנגשויות רציף המוצא ב{name}' + (f', {city}' if city else '')
                    + ' · באתר הקו הבוחן')
            url = f'{BASE}/ratzif/#st={code}'
            w += write_stub(f'r-{code}.html', title, desc, url,
                            f'{BASE}/ratzif/icon-512.png')
            n += 1
    except Exception as e:
        print('רציף: דילוג —', type(e).__name__, e, file=sys.stderr)

    print(f'דפי שיתוף: {n:,} ישויות · {w:,} נכתבו/עודכנו')


if __name__ == '__main__':
    main()
