#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""צי הרכבים — סריקת דאטאבוס (Stride API): אילו רכבים פעלו אצל כל מפעיל ומתי.

לכל vehicle_ref (בדרך כלל לוחית הרישוי) נשמרים המפעיל, תאריך הצפייה
הראשון ותאריך הצפייה האחרון בשידורי ה-SIRI. המצב מצטבר בין ריצות
ב-fleet/data/fleet-state.json, כך שסריקה שבועית של הימים האחרונים
מאריכה את התמונה בלי לסרוק שוב את כל ההיסטוריה. Backfill לאחור נעשה
באותה ריצה עצמה עם FROM/TO.

FROM/TO (YYYY-MM-DD) · ברירת מחדל: 8 הימים האחרונים · MAX_MIN — עצירה
נקייה אחרי X דקות (0 = בלי מגבלה) · RETIRE_DAYS — כמה ימי היעדרות
נחשבים "ירד מהשירות" (ברירת מחדל 60).
"""
import datetime
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API = 'https://open-bus-stride-api.hasadna.org.il'
OUTDIR = os.environ.get('OUTDIR', 'fleet/data')
STATE = f'{OUTDIR}/fleet-state.json'
OUT = f'{OUTDIR}/fleet.json'
TODAY = datetime.date.today()
FROM = os.environ.get('FROM') or (TODAY - datetime.timedelta(days=8)).isoformat()
TO = os.environ.get('TO') or TODAY.isoformat()
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))
RETIRE_DAYS = int(os.environ.get('RETIRE_DAYS', '60'))
PAGE = 1000

# שמות המפעילים לפי operator_ref של משרד התחבורה (כמו ב-GTFS agency_id).
# מזהה שאינו ברשימה יוצג כ"מפעיל N" — ואפשר להשלים אותו כאן בעתיד.
OPERATORS = {
    2: 'רכבת ישראל', 3: 'אגד', 4: 'אגד תעבורה', 5: 'דן', 6: 'ש.א.מ',
    7: 'נסיעות ותיירות', 8: 'גי.בי. טורס', 10: 'מועצה אזורית אילות',
    14: 'נתיב אקספרס', 15: 'מטרופולין', 16: 'סופרבוס', 18: 'קווים',
    20: 'כרמלית', 21: 'סיטיפס', 23: 'גלים', 24: 'מועצה אזורית גולן',
    25: 'אלקטרה אפיקים', 30: 'דן צפון', 31: 'דן בדרום', 32: 'דן באר שבע',
    33: 'כפיר', 34: 'תנופה', 35: 'בית שמש אקספרס', 37: 'אקסטרה',
    38: 'אקסטרה ירושלים', 91: 'מוניות שירות',
}


def jdump(obj, path):
    tmp = f'{path}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def get(path, **params):
    url = f'{API}{path}?' + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'kav-bochan-fleet/1.0'})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 — רשת/‏5xx: ננסה שוב בהדרגה
            if attempt == 5:
                raise
            print(f'  retry {attempt + 1}: {e}', flush=True)
            time.sleep(5 * (attempt + 1))


def route_operator_map():
    """מיפוי siri_route.id → operator_ref (עמוד אחר עמוד, פעם אחת לריצה)."""
    m = {}
    offset = 0
    while True:
        rows = get('/siri_routes/list', limit=PAGE, offset=offset)
        for r in rows:
            m[r['id']] = r.get('operator_ref')
        if len(rows) < PAGE:
            break
        offset += PAGE
    print(f'route→operator: {len(m)} מסלולים', flush=True)
    return m


def scan_day(day, routes, state):
    """כל נסיעות ה-SIRI של יום אחד → ראשון/אחרון + ספירת נסיעות לכל רכב."""
    frm = f'{day}T00:00:00+02:00'
    to = f'{day}T23:59:59+02:00'
    offset, n = 0, 0
    today = {}   # key -> מספר נסיעות היום
    while True:
        rows = get('/siri_rides/list', limit=PAGE, offset=offset,
                   scheduled_start_time_from=frm, scheduled_start_time_to=to,
                   order_by='id asc')
        for r in rows:
            v = (r.get('vehicle_ref') or '').strip()
            if not v or v == '0':
                continue
            op = routes.get(r.get('siri_route_id'))
            if op is None:
                continue
            key = f'{op}:{v}'
            cur = state.get(key)
            if cur is None:
                state[key] = [day, day, 0, 0]
            else:
                if len(cur) < 4:      # מצב ישן [ראשון, אחרון] — הרחבה
                    cur += [0, 0]
                if day < cur[0]:
                    cur[0] = day
                if day > cur[1]:
                    cur[1] = day
            today[key] = today.get(key, 0) + 1
        n += len(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    for key, cnt in today.items():   # צבירה: סך נסיעות + ימי פעילות שנמדדו
        cur = state[key]
        cur[2] += cnt
        cur[3] += 1
    print(f'{day}: {n} נסיעות', flush=True)


def build_output(state):
    """קיבוץ לפי מפעיל לקובץ שהאתר קורא. פורמט v2:
    [לוחית, ראשון, אחרון, ממוצע-נסיעות-ליום] + העשרה שנוספת אחר כך."""
    ops = {}
    for key, vals in state.items():
        first, last = vals[0], vals[1]
        rides = vals[2] if len(vals) > 2 else 0
        dcount = vals[3] if len(vals) > 3 else 0
        avg = round(rides / dcount, 1) if dcount else None
        op_s, v = key.split(':', 1)
        op = int(op_s)
        ops.setdefault(op, []).append([v, first, last, avg])
    out = []
    for op, vehicles in sorted(ops.items()):
        vehicles.sort(key=lambda x: x[0])
        out.append({'ref': op, 'name': OPERATORS.get(op, f'מפעיל {op}'),
                    'vehicles': vehicles})
    return {'updated': TODAY.isoformat(), 'retire_days': RETIRE_DAYS,
            'v': 2, 'operators': out}


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    state = {}
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as f:
            state = json.load(f).get('vehicles', {})
    print(f'סריקה {FROM} → {TO} · מצב קיים: {len(state)} רכבים', flush=True)

    routes = route_operator_map()
    t0 = time.time()
    day = datetime.date.fromisoformat(FROM)
    end = datetime.date.fromisoformat(TO)
    scanned = []
    while day <= end:
        if MAX_MIN and (time.time() - t0) / 60 > MAX_MIN:
            print(f'MAX_MIN — עצירה נקייה לפני {day}', flush=True)
            break
        scan_day(day.isoformat(), routes, state)
        scanned.append(day.isoformat())
        # שמירת ביניים כל יום — ריצה שנקטעת לא מאבדת כלום
        jdump({'vehicles': state}, STATE)
        day += datetime.timedelta(days=1)

    jdump({'vehicles': state}, STATE)
    jdump(build_output(state), OUT)
    print(f'סיום: {len(state)} רכבים · {len(scanned)} ימים נסרקו', flush=True)


if __name__ == '__main__':
    sys.exit(main())
