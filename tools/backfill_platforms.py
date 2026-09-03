#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מילוי לאחור של שינויי רציף מארכיון TransitFeeds — 2017 עד 2022 (בקשת שלמה 03.09).

הסורק היומי (linehistory.py) רושם מהיום שינוי רציף: תחנה שבתיאורה
"עיר: X רציף: N" ומספר הרציף השתנה. כאן אותו כלל בדיוק על צילומי
הארכיון: לכל צילום נקרא stops.txt בלבד (קטן), נגזר הרציף של כל תחנה,
ומושווה לצילום הקודם. הכלל של שלמה: ריק/0 = "לא מוגדר"; מעבר אליו אינו
אירוע; מעבר ממנו מנוסח "עוצר מעכשיו ברציף N"; בין שני רציפים — "עבר
מרציף A לרציף B".

יציבות (03.09, אחרי הריצה הראשונה): בספטמבר–אוקטובר 2021 תיאורי התחנות
בפיד ריצדו יום-יום (מרכזית אשדוד: 10→8→2→8→2→10), ו-1,862 "שינויים" נרשמו
בחודשיים. לכן רציף חדש נרשם רק אחרי שהחזיק לפחות STABLE_DAYS ימים ולפחות
STABLE_SNAPS צילומים ברצף; ערך שחזר לקודמו בינתיים אינו אירוע כלל. תאריך
האירוע = היום שבו הרציף החדש נראה לראשונה; sd = הצילום שלפניו.

לכל שינוי נרשמים:
  · אירוע תחנה — stops-hist.json ו-changes/stops-YYYY-MM.json (k=platform)
  · אירוע קו — לכל וריאנט שרצף התחנות המתועד שלו באותו תאריך כולל את
    התחנה: גרסה k=platform (src=tf) עם pl=[[מק"ט, שם, ישן, חדש]] והערה,
    וגם שורה ב-changes/YYYY-MM.json

הצילום הראשון בריצה הראשונה הוא בסיס שקט (בלי אירועים), כמו בסורק היומי.
המצב נשמר ב-backfill-platforms-state.json: אפשר לעצור ולהמשיך; ריצה
חוזרת מדלגת על צילומים שעובדו. RESET=1 מוחק קודם כל תוצר קודם של הכלי
(אירועי platform עם src=tf) ואת המצב, ומתחיל מההתחלה.

FROM/TO   טווח תאריכים (YYYYMMDD) · MAX_DAYS צילומים לריצה · MAX_MIN תקציב
דקות · DRY=1 ניתוח בלי כתיבה · RESET=1 איפוס
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import central_dir, member_rows  # noqa: E402
from compact_lines import compact, materialize  # noqa: E402

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/backfill-platforms-state.json'
FROM = os.environ.get('FROM', '20170101')
TO = os.environ.get('TO', '20221231')
MAX_DAYS = int(os.environ.get('MAX_DAYS', '0') or 0)
MAX_MIN = float(os.environ.get('MAX_MIN', '0') or 0)
DRY = os.environ.get('DRY') == '1'
RESET = os.environ.get('RESET') == '1'
SRC = 'tf'
STABLE_DAYS = 7      # רציף חדש נרשם רק אחרי שהחזיק שבוע
STABLE_SNAPS = 2     # ולפחות שני צילומים ברצף


def iso(ds):
    return f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'


def fsafe(rd):
    return rd.replace('#', 'H')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def jdump(obj, p):
    json.dump(obj, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))


def days_between(a, b):
    return (datetime.date.fromisoformat(b) - datetime.date.fromisoformat(a)).days


def city(d):
    m = re.search(r'עיר:\s*(.*?)\s*רציף:', d or '')
    return m.group(1).strip() if m else ''


def plat_norm(p):
    """'' = לא מוגדר: ריק, 0, או ערך שאינו רציף (למשל 'קומה:' כשהרציף ריק)."""
    p = (p or '').strip()
    return '' if (p in ('', '0', '-', '—') or ':' in p or len(p) > 6) else p


def plat(d):
    """כמו ב-linehistory.py: התיאור ממשיך אחרי הרציף ('קומה:'), ולכן נתפס רק
    מה שבין 'רציף:' ל'קומה:' או לסוף השורה."""
    m = re.search(r'רציף:\s*(.*?)\s*(?:קומה:|$)', d or '')
    return plat_norm(m.group(1) if m else '')


def snapshot_platforms(ds):
    """{מק"ט: [רציף, שם, עיר, lat, lon]} — רק תחנות עם רציף מוגדר."""
    url = f'{BASE}/{ds}/gtfs.zip'
    members = central_dir(url)
    c, rows = member_rows(url, members, 'stops.txt')
    out = {}
    for r in rows:
        try:
            p = plat(r[c['stop_desc']])
            if not p:
                continue
            code = (r[c['stop_code']] or '').strip() or r[c['stop_id']]
            out[code] = [p, ' '.join(r[c['stop_name']].split()), city(r[c['stop_desc']]),
                         round(float(r[c['stop_lat']]), 5), round(float(r[c['stop_lon']]), 5)]
        except (KeyError, ValueError, IndexError):
            continue
    return out


def note_for(pl):
    parts = [(f"עוצר מעכשיו ברציף {nw} בתחנה {nm}" if not old else f"בתחנה {nm} עבר מרציף {old} לרציף {nw}")
             for _c, nm, old, nw in pl[:8]]
    return 'שינוי רציף: ' + ' · '.join(parts) + ' (אותר בהשוואת צילומי הארכיון של הפיד הארצי)'


def reset_previous():
    """מחיקת כל תוצר קודם של הכלי: אירועי platform עם src=tf בתחנות, בחודשים ובקווים."""
    shist = jload(f'{OUTDIR}/stops-hist.json', {})
    n_s = 0
    for c in list(shist):
        before = len(shist[c])
        shist[c] = [e for e in shist[c] if not (e.get('k') == 'platform' and e.get('src') == SRC)]
        n_s += before - len(shist[c])
        if not shist[c]:
            shist.pop(c)
    jdump(shist, f'{OUTDIR}/stops-hist.json')
    n_m = 0
    for f in os.listdir(f'{OUTDIR}/changes'):
        p = f'{OUTDIR}/changes/{f}'
        m = jload(p, None)
        if not m or 'changes' not in m:
            continue
        before = len(m['changes'])
        m['changes'] = [x for x in m['changes'] if not (x.get('k') == 'platform' and (x.get('src') == SRC or ('rd' in x and x.get('d', '') < '2023')))]
        if len(m['changes']) != before:
            n_m += before - len(m['changes'])
            jdump(m, p)
    n_l = 0
    ld = f'{OUTDIR}/lines'
    for f in os.listdir(ld):
        if not f.endswith('.json'):
            continue
        p = f'{ld}/{f}'
        lf = materialize(jload(p, None))
        if not lf:
            continue
        vs = lf.get('versions') or []
        keep = [v for v in vs if not (v.get('k') == 'platform' and v.get('src') == SRC)]
        if len(keep) != len(vs):
            n_l += len(vs) - len(keep)
            lf['versions'] = keep
            jdump(compact(lf), p)
    if os.path.exists(STATE):
        os.remove(STATE)
    print(f'איפוס: נמחקו {n_s} אירועי תחנה, {n_m} שורות חודשיות, {n_l} גרסאות קו', file=sys.stderr)


def build_stop_index():
    """מק"ט → [(rd, מתאריך, עד-תאריך)] מכל קובצי הקווים — לפי רצף התחנות
    המתועד; גרסה בתוקף מיום פרסומה ועד הגרסה הבאה עם תחנות."""
    idx = {}
    ld = f'{OUTDIR}/lines'
    files = [f for f in os.listdir(ld) if f.endswith('.json')]
    for i, f in enumerate(files):
        lf = materialize(jload(f'{ld}/{f}', None))
        if not lf:
            continue
        rd = lf.get('rd') or f[:-5]
        vs = [v for v in (lf.get('versions') or []) if v.get('stops')]
        for j, v in enumerate(vs):
            end = vs[j + 1]['d'] if j + 1 < len(vs) else '9999-12-31'
            seen = set()
            for s in v['stops']:
                code = str(s[0])
                if code in seen:
                    continue
                seen.add(code)
                idx.setdefault(code, []).append((rd, v['d'], end))
        if i % 3000 == 0:
            print(f'  אינדקס תחנות: {i}/{len(files)} קבצים', file=sys.stderr)
    return idx


def main():
    if RESET and not DRY:
        reset_previous()
    src = os.environ.get('DAYS') or f'{OUTDIR}/tf-days.txt'
    days = [l.strip() for l in open(src) if l.strip() and FROM <= l.strip() <= TO]
    st = jload(STATE, {'done': [], 'stable': {}, 'pending': {}})
    done = set(st['done'])
    todo = [d for d in days if d not in done]
    if MAX_DAYS:
        todo = todo[:MAX_DAYS]
    print(f'צילומים בטווח: {len(days)} · כבר עובדו: {len(done)} · בריצה זו: {len(todo)}', file=sys.stderr)
    if not todo:
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return
    # stable: מק"ט → [רציף, שם, עיר, lat, lon] — הרציף המאושר האחרון
    # pending: מק"ט → [רציף, שם, עיר, lat, lon, מאז (ISO), צילומים ברצף, הצילום שלפני]
    stable = st.get('stable') or {}
    pending = st.get('pending') or {}
    baseline = not stable and not done
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    events = []          # (d, sd, code, name, city, la, lo, old, new)
    last_ds = max(done) if done else None
    for ds in todo:
        if deadline and time.monotonic() > deadline:
            print('תקציב הזמן נגמר — נעצר בין צילומים', file=sys.stderr)
            break
        try:
            cur = snapshot_platforms(ds)
        except BaseException as e:
            print(f'  {iso(ds)}: דילוג — {type(e).__name__}: {str(e)[:70]}', file=sys.stderr)
            continue
        n = 0
        if baseline:
            stable = dict(cur)
            baseline = False
        else:
            for code, v in cur.items():
                stab = (stable.get(code) or [''])[0]
                if v[0] == stab:
                    pending.pop(code, None)
                    continue
                pd = pending.get(code)
                if pd and pd[0] == v[0]:
                    pd[6] += 1
                    if pd[6] >= STABLE_SNAPS and days_between(pd[5], iso(ds)) >= STABLE_DAYS:
                        # החזיק: האירוע נרשם מהיום שבו נראה לראשונה
                        events.append((pd[5], pd[7], code, v[1], v[2], v[3], v[4], stab, v[0]))
                        stable[code] = list(v)
                        pending.pop(code, None)
                        n += 1
                else:
                    pending[code] = list(v) + [iso(ds), 1, iso(last_ds) if last_ds else None]
            # רציף שנעלם מהצילום (לא מוגדר עוד): לא אירוע; המועמדות שלו נמחקת
            for code in list(pending):
                if code not in cur:
                    pending.pop(code)
        done.add(ds)
        last_ds = ds
        print(f'  {iso(ds)}: {len(cur)} תחנות עם רציף · {n} שינויים מאושרים · {len(pending)} ממתינים', file=sys.stderr)
    print(f'סה"כ אירועי רציף מאושרים: {len(events)}', file=sys.stderr)
    if DRY:
        for e in events[:30]:
            print('   ', e, file=sys.stderr)
        return
    # ---- אירועי תחנה ----
    shist = jload(f'{OUTDIR}/stops-hist.json', {})
    by_month = {}
    for d, sd, code, name, cty, la, lo, old, new in events:
        ev = {'d': d, 'k': 'platform', 'src': SRC, 'n': name, 't': cty, 'op': old, 'np': new, 'la': la, 'lo': lo}
        if sd:
            ev['sd'] = sd
        h = shist.setdefault(code, [])
        h[:] = [x for x in h if not (x.get('d') == d and x.get('k') == 'platform')]
        h.append(ev)
        h.sort(key=lambda x: x['d'])
        by_month.setdefault(d[:7], []).append({'c': code, **ev})
    for month, evs in by_month.items():
        p = f'{OUTDIR}/changes/stops-{month}.json'
        m = jload(p, {'month': month, 'changes': []})
        keys = {(e['c'], e['d']) for e in evs}
        m['changes'] = [x for x in m['changes'] if not (x.get('k') == 'platform' and (x.get('c'), x.get('d')) in keys)] + evs
        m['changes'].sort(key=lambda x: x.get('d', ''))
        jdump(m, p)
    # ---- אירועי קו ----
    n_lines = 0
    ch_by_month = {}
    if events:
        idx = build_stop_index()
        per_rd = {}     # rd → {d: [pl entries]}
        for d, sd, code, name, cty, la, lo, old, new in events:
            for rd, s, e in idx.get(code, ()):
                if s <= d < e:
                    per_rd.setdefault(rd, {}).setdefault(d, []).append([code, name, old, new])
        for rd, byd in per_rd.items():
            p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
            lf = materialize(jload(p, None))
            if not lf:
                continue
            vs = lf.get('versions') or []
            for d, pl in sorted(byd.items()):
                base = next((v for v in reversed(vs) if v.get('stops') and v['d'] <= d), None)
                if base is None:
                    continue
                ex = next((v for v in vs if v['d'] == d and v.get('k') == 'platform'), None)
                if ex is not None:
                    have = {tuple(x[:2]) for x in ex.get('pl') or []}
                    ex['pl'] = (ex.get('pl') or []) + [x for x in pl if tuple(x[:2]) not in have]
                    ex['note'] = note_for(ex['pl'])
                    continue
                v = {'d': d, 'k': 'platform', 'src': SRC, 'stops': base['stops'], 'shp': base.get('shp', ''),
                     'pl': pl, 'note': note_for(pl)}
                vs.append(v)
                n_lines += 1
                ch_by_month.setdefault(d[:7], []).append({'d': d, 'rd': rd, 'line': lf.get('line', ''), 'op': lf.get('op', ''), 'k': 'platform', 'src': SRC, 'pl': pl[:15]})
            vs.sort(key=lambda x: x['d'])
            lf['versions'] = vs
            jdump(compact(lf), p)
    for month, chs in ch_by_month.items():
        p = f'{OUTDIR}/changes/{month}.json'
        m = jload(p, {'month': month, 'changes': []})
        keys = {(c['rd'], c['d']) for c in chs}
        m['changes'] = [x for x in m['changes'] if not (x.get('k') == 'platform' and (x.get('rd'), x.get('d')) in keys)] + chs
        m['changes'].sort(key=lambda x: x.get('d', ''))
        jdump(m, p)
    jdump(shist, f'{OUTDIR}/stops-hist.json')
    st['done'] = sorted(done)
    st['stable'] = stable
    st['pending'] = pending
    st.pop('prev', None)
    st['updated'] = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    jdump(st, STATE)
    print(f'נכתבו: {len(events)} אירועי תחנה · {n_lines} גרסאות קו', file=sys.stderr)


if __name__ == '__main__':
    main()
