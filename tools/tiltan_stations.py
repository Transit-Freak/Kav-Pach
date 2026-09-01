# -*- coding: utf-8 -*-
"""סקר התחנות של מערכת תלתן (משרד התחבורה) — המרה לפורמט שמיש והצלבה.

הקובץ המקורי הוא שייפ-פייל (Stations.shp/.dbf) עם 33,688 תחנות ו-62
שדות, כולל שני שדות שאין בשום מקור פתוח אחר: מבנה הסככה והשילוט
הסטטי, ולצידם נתוני עולים/יורדים אמיתיים לפי חלונות שעות וסוג נוסע.

מגבלה שחייבים לזכור: הסקר ישן מהפיד החי. המק"ט הגבוה בו הוא 35,608
בעוד שבפיד יש תחנות מעל 65,000 — כלומר תחנה שאינה בסקר אינה "תחנה
בלי סככה", היא פשוט לא נסקרה. כל שימוש חייב להבחין בין השניים.

  BUILD=1 python3 tools/tiltan_stations.py   — יוצר data/tiltan-stops.json
"""
import json
import os
import pathlib
import struct
import sys

SRC = pathlib.Path(os.environ.get('TILTAN_DIR', '/tmp/claude-0/-home-user-kav-bochan/'
                                  '83b02d2f-2c1e-5817-a32e-be01db41bb83/scratchpad/stations'))
OUT = pathlib.Path(os.environ.get('TILTAN_OUT', 'sakachot-lab/tiltan-stops.json'))

# השדות שנשמרים. שאר 40+ השדות נזרקים כדי שהקובץ יישאר קטן מספיק לאתר.
KEEP = {
    'STOP_ID': 'c',        # מק"ט
    'CORRECTPHS': 'n',     # שם התחנה בסקר
    'CITYNAME': 'city',
    'SHED_STRUC': 'shed',  # מבנה סככה (משמעות הקודים — ראו decode_note)
    'STATIC_SIG': 'sign',  # שילוט סטטי
    'E_R_CONTRO': 'erc',   # בקרה אלקטרונית
    'ROUTES': 'routes',
    'ONDAY': 'on_day',     # עולים ביום
    'ON0609': 'on_am',     # עולים 06-09
    'ON1519': 'on_pm',     # עולים 15-19
    'DEPDAY': 'dep_day',   # יורדים ביום
    'ADULT': 'adult', 'STUDENT': 'student', 'ELDERLY': 'elderly', 'DISABLED': 'disabled',
}


def read_dbf(path):
    f = open(path, 'rb')
    n_rec, hlen, rlen = struct.unpack('<I H H', f.read(32)[4:12])
    fields = []
    while True:
        d = f.read(32)
        if d[0:1] in (b'\r', b''):
            break
        fields.append((d[:11].split(b'\x00')[0].decode('utf-8', 'replace'), d[16]))
    f.seek(hlen)
    out = []
    for _ in range(n_rec):
        rec = f.read(rlen)
        if not rec or rec[:1] == b'\x1a':
            break
        vals, off = {}, 1
        for nm, ln in fields:
            raw = rec[off:off + ln]
            off += ln
            if nm in KEEP:
                try:
                    vals[nm] = raw.decode('utf-8').strip()
                except UnicodeDecodeError:
                    vals[nm] = raw.decode('cp1255', 'replace').strip()
        out.append(vals)
    return out


def num(v):
    """*** בקובץ = הערך רחב מדי לשדה. לא 0 — פשוט לא ידוע."""
    v = (v or '').strip()
    if not v or '*' in v:
        return None
    try:
        f = float(v)
        return int(f) if f == int(f) else round(f, 1)
    except ValueError:
        return None


def build():
    recs = read_dbf(SRC / 'Stations.dbf')
    out = {}
    for r in recs:
        code = (r.get('STOP_ID') or '').strip().lstrip('0')
        if not code:
            continue
        # קואורדינטות מהשדות עצמם — מעלות במיליוניות (WGS84)
        e = {}
        for src, dst in KEEP.items():
            v = r.get(src)
            if src in ('CORRECTPHS', 'CITYNAME'):
                if v:
                    e[dst] = v
            elif src in ('SHED_STRUC', 'STATIC_SIG', 'E_R_CONTRO'):
                if v and v != '9':      # 9 = לא נסקר/לא ידוע — לא נשמר
                    e[dst] = int(v)
            elif src != 'STOP_ID':
                n = num(v)
                if n is not None:
                    e[dst] = n
        out[code] = e
    OUT.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        'src': 'סקר התחנות — מערכת תלתן, משרד התחבורה והבטיחות בדרכים',
        'n': len(out),
        'max_code': max((int(c) for c in out if c.isdigit()), default=0),
        'note': ('הסקר ישן מהפיד החי: תחנה שאינה בו לא נסקרה, ואין להסיק ממנה '
                 '"אין סככה". משמעות קודי SHED_STRUC טרם אומתה — ההכרעה '
                 'תיעשה בהצלבה מול זיהוי הסככות מתצלומי האוויר.'),
        'fields': {'shed': 'מבנה סככה', 'sign': 'שילוט סטטי', 'erc': 'בקרה אלקטרונית',
                   'on_day': 'עולים ביום', 'on_am': 'עולים 06-09', 'on_pm': 'עולים 15-19',
                   'dep_day': 'יורדים ביום', 'routes': 'מספר קווים'},
    }
    json.dump({'meta': meta, 'stops': out}, open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    print(f'נכתב {OUT} · {len(out):,} תחנות · מק"ט מקסימלי {meta["max_code"]:,}')


if __name__ == '__main__':
    build()
