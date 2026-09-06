#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""'הקו בזמן' — סוג הרכב שנקבע לכל קו ברישוי משרד התחבורה, ושינוייו לאורך זמן.

המקור: מאגר "רישוי מערך האוטובוסים" ב-data.gov.il (שלמה 06.09): שורה לכל מק"ט
לכל יום, עם VehicleType_nm (עירוני/בינעירוני…) ו-VehicleSize_nm (אוטובוס/מיניבוס/
מידיבוס/מפרקי). השדות קיימים מקובץ 2022 ואילך.

מה נשמר, בלי לגעת בגרסאות המסלול של הקו:
  lines/<rd>.json  →  veh: [[תאריך, סוג, גודל], …]  (הראשון = מצב הפתיחה, השאר שינויים)
                       vt: הסוג הנוכחי · vsz: הגודל הנוכחי
  rishui-state.json →  {"d": תאריך הסריקה האחרון, "m": {מק"ט: [סוג, גודל, מאז]}}
  changes/YYYY-MM.json → אירוע k='vehicle' לכל שינוי (לפיד החודשי)

הפעלה:
  --day YYYY-MM-DD   סריקה יומית (ברירת מחדל: היום); אם אין שורות ליום — עד שבוע אחורה
  --backfill YYYY    מילוי לאחור מקובצי השנים YYYY..היום (זרימה, בלי לשמור את הקבצים)
"""
import argparse
import collections
import csv
import datetime
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CKAN = 'https://data.gov.il/api/3/action'
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/rishui-state.json'
UA = {'User-Agent': 'kav-bochan-linehistory/1.0', 'Referer': 'https://data.gov.il/'}
# להורדה ישירה של קובץ שנתי — השרת מחזיר 403 לכותרות "רובוט"; מנסים כמה צורות
BROWSER = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
           'Accept': 'text/csv,*/*;q=0.8', 'Accept-Language': 'he,en;q=0.8', 'Referer': 'https://data.gov.il/'}
PAGE = 32000          # מקסימום שורות לקריאה אחת ב-datastore_search
COMPLETE = 0.7        # היום האחרון בקובץ נחשב מלא רק אם יש בו לפחות 70% מהשורות של היום הגדול בשבוע
TODAY = datetime.date.today().isoformat()


def log(*a):
    print(*a, flush=True)


def ckan(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def day_total(rid, day):
    """כמה שורות יש ברישוי ליום נתון (בלי להוריד אותן)."""
    flt = urllib.parse.quote(json.dumps({'rishui_date': day}))
    res = ckan(f'{CKAN}/datastore_search?resource_id={rid}&filters={flt}&fields=office_line_id&limit=1')['result']
    return int(res.get('total') or 0)


def pick_complete_day(rid, day, back=8):
    """היום האחרון (עד `back` ימים אחורה, באותה שנה) שיש בו רישוי מלא. הקובץ
    מתמלא במהלך היום, והיום האחרון בו חלקי (מאות שורות במקום אלפים; בשבת יש
    כמחצית מהשורות של יום חול — וזה מלא). לכן: יום שיש אחריו יום עם שורות —
    מלא; היום האחרון עם שורות — מלא רק אם יש בו לפחות 70% מהיום הגדול בחלון."""
    d0 = datetime.date.fromisoformat(day)
    totals = []
    for b in range(0, back):
        d = (d0 - datetime.timedelta(days=b)).isoformat()
        if d[:4] != day[:4]:
            break
        totals.append((d, day_total(rid, d)))
    mx = max((n for _, n in totals), default=0)
    latest = next((d for d, n in totals if n > 0), None)
    for d, n in totals:
        if n > 0 and (d != latest or n >= COMPLETE * mx):
            return d, totals
    return None, totals


def resources():
    """המשאבים השנתיים של המאגר: שנה → (resource_id, url)."""
    pkg = ckan(f'{CKAN}/package_show?id=licensing_bus_system')['result']
    out = {}
    for r in pkg.get('resources', []):
        if (r.get('format') or '').upper() != 'CSV':
            continue
        for y in range(2017, 2040):
            if str(y) in (r.get('name') or ''):
                out[y] = (r['id'], r.get('url'))
    return out


def clean(s):
    return ' '.join(str(s or '').split())


def fsafe(rd):
    return rd.replace('#', 'H')


def line_files():
    """מק"ט → קובצי הקו (כל הכיוונים והחלופות)."""
    by = collections.defaultdict(list)
    for fn in os.listdir(f'{OUTDIR}/lines'):
        if fn.endswith('.json') and '-' in fn:
            by[fn.split('-', 1)[0]].append(fn)
    return by


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return dflt


def jdump(obj, p):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def apply_to_lines(files, mkt, veh, changes_out):
    """כותב veh/vt/vsz לכל קובצי הקו של המק"ט; מחזיר כמה קבצים עודכנו."""
    n = 0
    for fn in files.get(mkt, []):
        p = f'{OUTDIR}/lines/{fn}'
        lf = jload(p, None)
        if not lf:
            continue
        if lf.get('veh') == veh:
            continue
        lf['veh'] = veh
        lf['vt'], lf['vsz'] = veh[-1][1], veh[-1][2]
        jdump(lf, p)
        n += 1
        for d, t, s, pt, ps in changes_out:
            add_change(d, lf, f'סוג הרכב ברישוי שונה: {ps} {pt} ← {s} {t}')
    return n


_chm = {}


def add_change(d, lf, note):
    month = d[:7]
    if month not in _chm:
        p = f'{OUTDIR}/changes/{month}.json'
        _chm[month] = (p, jload(p, {'month': month, 'changes': []}))
    p, chm = _chm[month]
    rd = lf.get('rd')
    if any(c.get('d') == d and c.get('rd') == rd and c.get('k') == 'vehicle' for c in chm['changes']):
        return
    e = {'d': d, 'rd': rd, 'line': lf.get('line'), 'k': 'vehicle', 'note': note}
    if lf.get('op'):
        e['op'] = lf['op']
    chm['changes'].append(e)


def flush_changes():
    for p, chm in _chm.values():
        chm['changes'].sort(key=lambda c: c.get('d', ''))
        jdump(chm, p)


# ---------------------------------------------------------------- יומי
def fetch_day(rid, day):
    flt = urllib.parse.quote(json.dumps({'rishui_date': day}))
    rows, offset = [], 0
    while True:
        res = ckan(f'{CKAN}/datastore_search?resource_id={rid}&filters={flt}&fields=office_line_id,VehicleType_nm,VehicleSize_nm&limit=32000&offset={offset}')['result']
        recs = res.get('records', [])
        rows.extend(recs)
        if len(recs) < 32000:
            break
        offset += 32000
    return rows


def daily(day):
    res = resources()
    y = int(day[:4])
    if y not in res:
        raise SystemExit(f'אין משאב רישוי לשנת {y}')
    rid = res[y][0]
    used, totals = pick_complete_day(rid, day)
    log('שורות רישוי לפי יום: ' + ' · '.join(f'{d}:{n:,}' for d, n in totals))
    if not used:
        raise SystemExit(f'אין יום רישוי מלא ב-{day} ובשבוע שלפניו')
    rows = fetch_day(rid, used)
    if not rows:
        raise SystemExit(f'אין שורות רישוי ל-{used}')
    state = jload(STATE, {'d': None, 'm': {}})
    if state.get('d') and used <= state['d']:
        log(f'רישוי {used}: כבר נסרק (המצב עד {state["d"]}) — אין מה לעשות')
        return
    today = {}
    for r in rows:
        mkt = str(r.get('office_line_id') or '')
        t, s = clean(r.get('VehicleType_nm')), clean(r.get('VehicleSize_nm'))
        if mkt and (t or s):
            today[mkt] = (t, s)
    files = line_files()
    n_new = n_chg = n_files = 0
    for mkt, (t, s) in sorted(today.items()):
        st = state['m'].get(mkt)
        if st is None:
            state['m'][mkt] = [t, s, used]
            n_new += 1
            # קו שרק עכשיו נראה לראשונה: מצב פתיחה בלי אירוע
            for fn in files.get(mkt, []):
                p = f'{OUTDIR}/lines/{fn}'
                lf = jload(p, None)
                if lf and not lf.get('veh'):
                    lf['veh'] = [[used, t, s]]
                    lf['vt'], lf['vsz'] = t, s
                    jdump(lf, p)
                    n_files += 1
            continue
        if (st[0], st[1]) != (t, s):
            n_chg += 1
            log(f'  שינוי: מק"ט {mkt}: {st[1]} {st[0]} ← {s} {t} ({used})')
            for fn in files.get(mkt, []):
                p = f'{OUTDIR}/lines/{fn}'
                lf = jload(p, None)
                if not lf:
                    continue
                veh = list(lf.get('veh') or [[st[2], st[0], st[1]]])
                veh.append([used, t, s])
                lf['veh'] = veh
                lf['vt'], lf['vsz'] = t, s
                jdump(lf, p)
                add_change(used, lf, f'סוג הרכב ברישוי שונה: {st[1]} {st[0]} ← {s} {t}')
                n_files += 1
            state['m'][mkt] = [t, s, used]
    state['d'] = used
    jdump(state, STATE)
    flush_changes()
    log(f'רישוי {used}: {len(rows):,} שורות · {len(today):,} מק"טים · חדשים {n_new:,} · שינויי סוג רכב {n_chg:,} · קובצי קו שעודכנו {n_files:,}')


# ---------------------------------------------------------------- מילוי לאחור
# לכל מק"ט: לכל מצב (סוג, גודל) — התאריך הראשון, האחרון, וכמה ימים. הקבצים
# גדולים (300–450MB לשנה) ולא בהכרח ממוינים, אז לא שומרים כל יום. שתי דרכים
# לקרוא שנה: הורדת ה-CSV (מהיר; מופרד ב-'|'), ואם השרת מסרב — דפדוף ב-API
# (32,000 שורות לקריאה, ~55 קריאות לשנה). שורות של היום עצמו חלקיות ומדולגות.
def _add(per, mkt, d, key):
    if d >= TODAY:
        return
    st = per[mkt].get(key)
    if st is None:
        per[mkt][key] = [d, d, 1]
    else:
        if d < st[0]:
            st[0] = d
        if d > st[1]:
            st[1] = d
        st[2] += 1


def _add_rows(per, rows):
    """שורות (dict) → per. מחזיר (כמה נקלטו, האם יש שדות סוג רכב)."""
    n = 0
    for r in rows:
        if 'VehicleSize_nm' not in r:
            return n, False
        d = str(r.get('rishui_date') or '')[:10]
        mkt = str(r.get('office_line_id') or '').strip()
        if not mkt or not d:
            continue
        _add(per, mkt, d, (clean(r.get('VehicleType_nm')), clean(r.get('VehicleSize_nm'))))
        n += 1
    return n, True


def year_download(url, per):
    """זרימה של ה-CSV השנתי (בלי לשמור). השרת מחזיר 403 לכותרות "רובוט", והכתובת
    ב-e.data.gov.il מפנה לדף כניסה — אז קודם data.gov.il עם כותרות דפדפן, ובודקים
    שבאמת הגיע CSV עם השדות (ולא HTML). המפריד בקובץ הוא '|' (מזהים מהכותרת)."""
    urls = []
    if url.startswith('https://e.data.gov.il/'):
        urls.append(url.replace('https://e.data.gov.il/', 'https://data.gov.il/', 1))
    urls.append(url)
    errors = []
    for u in urls:
        for hdr in (BROWSER, UA):
            try:
                req = urllib.request.Request(u, headers=hdr)
                with urllib.request.urlopen(req, timeout=600) as resp:
                    f = io.TextIOWrapper(resp, encoding='utf-8-sig', errors='replace')
                    head = f.readline()
                    delim = '|' if head.count('|') > head.count(',') else ','
                    names = [h.strip() for h in head.rstrip('\r\n').split(delim)]
                    if 'office_line_id' not in names or 'rishui_date' not in names:
                        errors.append(f'{u}: לא CSV של רישוי ({head[:60]!r})')
                        continue
                    if 'VehicleSize_nm' not in names:
                        return 0
                    rd = csv.DictReader(f, fieldnames=names, delimiter=delim)
                    n = 0
                    for r in rd:
                        n += 1
                        d = (r.get('rishui_date') or '')[:10]
                        mkt = str(r.get('office_line_id') or '').strip()
                        if mkt and d:
                            _add(per, mkt, d, (clean(r.get('VehicleType_nm')), clean(r.get('VehicleSize_nm'))))
                        if n % 500000 == 0:
                            log(f'  {n:,} שורות…')
                    return n
            except urllib.error.HTTPError as e:
                errors.append(f'{u} ({"דפדפן" if hdr is BROWSER else "רגיל"}): HTTP {e.code}')
    raise RuntimeError(' · '.join(errors) or 'הורדה נכשלה')


def year_paged(rid, per):
    """דפדוף ב-datastore_search (32,000 שורות לקריאה, ~50 קריאות לשנה)."""
    offset = n = 0
    while True:
        res = ckan(f'{CKAN}/datastore_search?resource_id={rid}&fields=office_line_id,rishui_date,VehicleType_nm,VehicleSize_nm&limit={PAGE}&offset={offset}', timeout=600)['result']
        recs = res.get('records', [])
        k, has = _add_rows(per, recs)
        if not has:
            return 0
        n += k
        if len(recs) < PAGE:
            return n
        offset += PAGE
        if offset % (PAGE * 10) == 0:
            log(f'  {offset:,} שורות…')


def backfill(from_year):
    res = resources()
    years = [y for y in sorted(res) if y >= from_year]
    if not years:
        raise SystemExit('אין משאבים לשנים המבוקשות')
    per = collections.defaultdict(dict)   # mkt → {(t,s): [first, last, n]}
    for y in years:
        rid, url = res[y]
        n = None
        for name, fn in (('הורדה', lambda: year_download(url, per)), ('דפדוף', lambda: year_paged(rid, per))):
            log(f'שנה {y}: {name}…')
            try:
                n = fn()
                break
            except Exception as e:  # noqa: BLE001
                log(f'  {name} נכשל: {str(e)[:200]}')
        if n is None:
            raise SystemExit(f'שנה {y}: אף דרך לא עבדה')
        if n == 0:
            log(f'  אין שדות סוג רכב בקובץ {y} — מדלג')
        log(f'  {y}: {n:,} שורות · מק"טים עד כה {len(per):,}')
    files = line_files()
    state = {'d': None, 'm': {}}
    last_d = ''
    n_files = n_chg_mkt = 0
    for mkt, states in per.items():
        # רצף המצבים לפי התאריך הראשון של כל מצב; מצב שחוזר אחרי מצב אחר
        # (חפיפה בתאריכים) נרשם לפי התאריך הראשון שלו — הכי פשוט, ומספיק
        seq = sorted(((v[0], k[0], k[1], v[1]) for k, v in states.items()), key=lambda x: x[0])
        veh = [[d, t, s] for d, t, s, _ in seq]
        # מצב שנעלם לתמיד לפני שהמצב הבא התחיל ומופיע פחות מ-3 ימים — רעש
        veh = [x for i, x in enumerate(veh) if i == 0 or i == len(veh) - 1 or states[(x[1], x[2])][2] >= 3]
        cur = veh[-1]
        state['m'][mkt] = [cur[1], cur[2], cur[0]]
        last_d = max(last_d, max(v[3] for v in seq))
        changes = [(veh[i][0], veh[i][1], veh[i][2], veh[i - 1][1], veh[i - 1][2]) for i in range(1, len(veh))]
        if changes:
            n_chg_mkt += 1
        n_files += apply_to_lines(files, mkt, veh, changes)
    state['d'] = last_d
    jdump(state, STATE)
    flush_changes()
    log(f'מילוי לאחור: {len(per):,} מק"טים · {n_chg_mkt:,} עם שינוי סוג רכב · {n_files:,} קובצי קו עודכנו · המצב עד {last_d}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', default=datetime.date.today().isoformat())
    ap.add_argument('--backfill', type=int, default=0, help='שנת התחלה למילוי לאחור (למשל 2022)')
    a = ap.parse_args()
    os.makedirs(f'{OUTDIR}/changes', exist_ok=True)
    if a.backfill:
        backfill(a.backfill)
    else:
        daily(a.day)
