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
נחשבים "ירד מהשירות" (ברירת מחדל 30 — חודש בלי פעילות).
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
RETIRE_DAYS = int(os.environ.get('RETIRE_DAYS', '30'))
# מצב "חודשים בלבד": סריקה חוזרת של העבר שממלאת רק את מסיכת חודשי
# הפעילות של כל רכב, בלי לצבור שוב נסיעות/ימים שכבר נספרו בסריקה
# המקורית (צבירה חוזרת הייתה מכפילה את ממוצע הנסיעות ליום)
MONTHS_ONLY = os.environ.get('MONTHS_ONLY') == '1'
MBASE = 2020 * 12   # ביט 0 במסיכת החודשים = ינואר 2020
# עדכון-ביניים לאתר כל X ימים סרוקים (0 = רק בסוף); נקבע ב-workflow
FLUSH_DAYS = int(os.environ.get('FLUSH_DAYS', '0'))
PAGE = 1000

# שמות מפעילים מובנים (גיבוי) — הרשימה המלאה נטענת בזמן ריצה מ-agency.txt
OPERATORS = {
    2: 'רכבת ישראל', 3: 'אגד', 4: 'אגד תעבורה', 5: 'דן', 6: 'ש.א.מ',
    7: 'נסיעות ותיירות', 8: 'גי.בי. טורס', 10: 'מועצה אזורית אילות',
    14: 'נתיב אקספרס', 15: 'מטרופולין', 16: 'סופרבוס', 18: 'קווים',
    20: 'כרמלית', 21: 'סיטיפס', 23: 'גלים', 24: 'מועצה אזורית גולן',
    25: 'אלקטרה אפיקים', 30: 'דן צפון', 31: 'דן בדרום', 32: 'דן באר שבע',
    33: 'כפיר', 34: 'תנופה', 35: 'בית שמש אקספרס', 37: 'אקסטרה',
    38: 'אקסטרה ירושלים', 91: 'מוניות שירות',
}

# לא חברות אוטובוסים — מסוננים לפי שם: רכבות, רק"ל, רכבל ומוניות
EXCLUDE_WORDS = ('רכבת', 'כרמלית', 'סיטיפס', 'רכבל', 'מוניות', 'כביש 6')
S3GTFS = ('https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
          '/gtfs_archive/{y}/{m}/{d}/israel-public-transportation.zip')
NAMES = dict(OPERATORS)   # מועשר בזמן ריצה מ-agency.txt


def load_agency_names():
    """agency_id → שם המפעיל מתוך ה-GTFS היומי — הרשימה הרשמית המלאה."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from backfill_geo import central_dir, member_rows
        day = TODAY - datetime.timedelta(days=1)
        url = S3GTFS.format(y=day.year, m=f'{day.month:02d}', d=f'{day.day:02d}')
        c, rows = member_rows(url, central_dir(url), 'agency.txt')
        got = {int(r[c['agency_id']]): (r[c['agency_name']] or '').strip()
               for r in rows if (r[c['agency_id']] or '').strip().isdigit()}
        NAMES.update({k: v for k, v in got.items() if v})
        print(f'agency.txt: {len(got)} מפעילים רשמיים', flush=True)
    except Exception as e:  # noqa: BLE001 — נופלים לרשימה המובנית
        print(f'agency.txt לא נטען ({e}) — הרשימה המובנית בשימוש', flush=True)


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
    """מיפוי siri_route.id → (operator_ref, line_ref) — פעם אחת לריצה."""
    m = {}
    offset = 0
    while True:
        rows = get('/siri_routes/list', limit=PAGE, offset=offset)
        for r in rows:
            m[r['id']] = (r.get('operator_ref'), r.get('line_ref'))
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
            ent = routes.get(r.get('siri_route_id'))
            if ent is None:
                continue
            op, line = ent
            if op is None:
                continue
            key = f'{op}:{v}'
            cur = state.get(key)
            if cur is None:
                cur = state[key] = [day, day, 0, 0, [], 0]
            else:
                while len(cur) < 6:   # מצב ישן — הרחבה הדרגתית
                    cur.append([] if len(cur) == 4 else 0)
                if day < cur[0]:
                    cur[0] = day
                if day > cur[1]:
                    cur[1] = day
            # באיזה חודש הרכב פעל — ביט במסיכה (לספירה חודשית בערים)
            cur[5] |= 1 << (int(day[:4]) * 12 + int(day[5:7]) - 1 - MBASE)
            # אילו קווים הרכב שירת (עד 40 — מספיק לשיוך ערים)
            if line and line not in cur[4] and len(cur[4]) < 40:
                cur[4].append(line)
            today[key] = today.get(key, 0) + 1
        n += len(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
        if MONTHS_ONLY:
            time.sleep(0.1)   # מילוי היסטורי — בעדינות, לא להעמיס על דאטאבוס
    if not MONTHS_ONLY:
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
        # רק מפעיל שמופיע ברשימה הרשמית, ושאינו רכבת/רק"ל/מונית
        name = NAMES.get(op)
        if not name or any(w in name for w in EXCLUDE_WORDS):
            continue
        ops.setdefault(op, []).append([v, first, last, avg])
    out = []
    for op, vehicles in sorted(ops.items()):
        vehicles.sort(key=lambda x: x[0])
        out.append({'ref': op, 'name': NAMES.get(op, f'מפעיל {op}'),
                    'vehicles': vehicles})
    return {'updated': TODAY.isoformat(), 'retire_days': RETIRE_DAYS,
            'v': 2, 'operators': out}


def flush_site(state):
    """עדכון ביניים באמצע ריצה ארוכה: בנייה, העשרה, קומיט ודחיפה לאתר.
    כל כשל כאן אינו מפיל את הסריקה — הנתונים ממשיכים להצטבר."""
    import subprocess
    jdump(build_output(state), OUT)
    try:
        subprocess.run([sys.executable, 'tools/fleet_enrich_gov.py'],
                       check=True, timeout=1500)
    except Exception as e:  # noqa: BLE001
        print(f'  העשרת-ביניים נכשלה: {e}', flush=True)
    try:
        # ניקוי rebase שנקטע בעדכון קודם — אחרת כל פעולות ה-git ייתקעו
        subprocess.run(['git', 'rebase', '--abort'],
                       check=False, capture_output=True)
        subprocess.run(['git', 'add', 'fleet/data'], check=True)
        subprocess.run(['git', '-c', 'user.name=fleet-bot',
                        '-c', 'user.email=noreply@github.com',
                        'commit', '-m', 'data: fleet — עדכון ביניים תוך כדי סריקה'],
                       check=True)
        subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], check=True)
        subprocess.run(['git', 'push'], check=True)
        print('  עדכון ביניים נדחף לאתר ✓', flush=True)
    except Exception as e:  # noqa: BLE001
        subprocess.run(['git', 'rebase', '--abort'],
                       check=False, capture_output=True)
        print(f'  דחיפת-ביניים לא בוצעה ({e}) — יתאחד בעדכון הבא', flush=True)


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    root = {}
    if os.path.exists(STATE):
        with open(STATE, encoding='utf-8') as f:
            root = json.load(f)
    state = root.setdefault('vehicles', {})
    # ברירת המחדל של FROM: היום שאחרי האחרון שנסרק (scanned_to) — כך ריצה
    # חודשית מכסה בדיוק את החודש שעבר, בלי חפיפה שסופרת נסיעות פעמיים
    # ובלי חורים. גיבוי (מצב ישן בלי המצביע): 8 ימים אחורה, כמו פעם.
    frm = FROM
    if not os.environ.get('FROM') and root.get('scanned_to') and not MONTHS_ONLY:
        frm = (datetime.date.fromisoformat(root['scanned_to'])
               + datetime.timedelta(days=1)).isoformat()
    print(f'סריקה {frm} → {TO}{" (חודשים בלבד)" if MONTHS_ONLY else ""}'
          f' · מצב קיים: {len(state)} רכבים', flush=True)
    if frm > TO:
        print('אין ימים חדשים לסריקה', flush=True)
        return

    load_agency_names()
    routes = route_operator_map()
    t0 = time.time()
    start = datetime.date.fromisoformat(frm)
    end = datetime.date.fromisoformat(TO)
    # מילוי החודשים רץ מהחדש לישן: כל עצירה משאירה רצף רציף מלמעלה,
    # והמצביע months_done מתקדם אחרי כל יום — ריצה איטית לעולם לא נתקעת
    day = end if MONTHS_ONLY else start
    step = -1 if MONTHS_ONLY else 1
    scanned = []
    while start <= day <= end:
        if MAX_MIN and (time.time() - t0) / 60 > MAX_MIN:
            print(f'MAX_MIN — עצירה נקייה לפני {day}', flush=True)
            break
        scan_day(day.isoformat(), routes, state)
        scanned.append(day.isoformat())
        if MONTHS_ONLY:
            prev = root.get('months_done')
            root['months_done'] = min(prev, day.isoformat()) if prev else day.isoformat()
        else:
            root['scanned_to'] = max(root.get('scanned_to') or '', day.isoformat())
        # שמירת ביניים כל יום — ריצה שנקטעת לא מאבדת כלום
        jdump(root, STATE)
        # דחיפת עדכון חי לאתר תוך כדי הריצה
        if FLUSH_DAYS and len(scanned) % FLUSH_DAYS == 0:
            flush_site(state)
        day += datetime.timedelta(days=step)

    jdump(root, STATE)
    # במצב חודשים-בלבד אסור לכתוב את fleet.json: הכתיבה כאן דרסה את
    # הקובץ המועשר (שנתון/דגם/סוג מהמאגר הממשלתי) בגרסה חשופה, כי
    # ה-workflow של החודשים לא מריץ את שלב ההעשרה — "דגם נעלם" באתר
    if not MONTHS_ONLY:
        jdump(build_output(state), OUT)
    print(f'סיום: {len(state)} רכבים · {len(scanned)} ימים נסרקו', flush=True)


if __name__ == '__main__':
    sys.exit(main())
