#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מילוי לאחור של שינויי רציף מארכיון TransitFeeds — 2017 עד 2022 (בקשת שלמה 03.09).

הסורק היומי (linehistory.py) רושם מהיום שינוי רציף: תחנה שבתיאורה
"עיר: X רציף: N" ומספר הרציף השתנה. כאן אותו כלל בדיוק על צילומי
הארכיון: לכל צילום נקרא stops.txt בלבד (קטן), נגזר הרציף של כל תחנה,
ומושווה לצילום הקודם. הכלל של שלמה: ריק/0 = "לא מוגדר"; מעבר אליו אינו
אירוע; מעבר ממנו מנוסח "עוצר מעכשיו ברציף N"; בין שני רציפים — "עבר
מרציף A לרציף B".

לכל שינוי נרשמים:
  · אירוע תחנה — stops-hist.json ו-changes/stops-YYYY-MM.json (k=platform)
  · אירוע קו — לכל וריאנט שרצף התחנות המתועד שלו באותו תאריך כולל את
    התחנה: גרסה k=platform (src=tf) עם pl=[[מק"ט, שם, ישן, חדש]] והערה,
    וגם שורה ב-changes/YYYY-MM.json

הצילום הראשון בריצה הראשונה הוא בסיס שקט (בלי אירועים), כמו בסורק היומי.
המצב נשמר ב-backfill-platforms-state.json: אפשר לעצור ולהמשיך; ריצה
חוזרת מדלגת על צילומים שעובדו. הארכיון של 2022 ואילך (אופן באס) אינו
מכיל את תיאור התחנה, ולכן משם ואילך מכסה הסורק היומי בלבד.

FROM/TO   טווח תאריכים (YYYYMMDD) · MAX_DAYS צילומים לריצה · MAX_MIN תקציב
דקות · DRY=1 ניתוח בלי כתיבה
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
SRC = 'tf'


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


def build_stop_index():
    """מק"ט → [(rd, מתאריך, עד-תאריך, אינדקס הגרסה)] מכל קובצי הקווים — לפי
    רצף התחנות המתועד; גרסה בתוקף מיום פרסומה ועד הגרסה הבאה עם תחנות."""
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
    src = os.environ.get('DAYS') or f'{OUTDIR}/tf-days.txt'
    days = [l.strip() for l in open(src) if l.strip() and FROM <= l.strip() <= TO]
    st = jload(STATE, {'done': [], 'prev': {}})
    done = set(st['done'])
    todo = [d for d in days if d not in done]
    if MAX_DAYS:
        todo = todo[:MAX_DAYS]
    print(f'צילומים בטווח: {len(days)} · כבר עובדו: {len(done)} · בריצה זו: {len(todo)}', file=sys.stderr)
    if not todo:
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return
    prev = st.get('prev') or {}
    baseline = not prev and not done
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
            baseline = False
        else:
            for code, v in cur.items():
                old = (prev.get(code) or [''])[0]
                if v[0] != old:
                    events.append((iso(ds), iso(last_ds) if last_ds else None, code, v[1], v[2], v[3], v[4], old, v[0]))
                    n += 1
        prev = cur
        done.add(ds)
        last_ds = ds
        print(f'  {iso(ds)}: {len(cur)} תחנות עם רציף · {n} שינויים', file=sys.stderr)
    print(f'סה"כ אירועי רציף: {len(events)}', file=sys.stderr)
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
    idx = build_stop_index()
    per_rd = {}     # rd → {d: [pl entries]}
    for d, sd, code, name, cty, la, lo, old, new in events:
        for rd, s, e in idx.get(code, ()):
            if s <= d < e:
                per_rd.setdefault(rd, {}).setdefault(d, []).append([code, name, old, new])
    n_lines = 0
    ch_by_month = {}
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
            ch_by_month.setdefault(d[:7], []).append({'d': d, 'rd': rd, 'line': lf.get('line', ''), 'op': lf.get('op', ''), 'k': 'platform', 'pl': pl[:15]})
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
    st['prev'] = prev
    st['updated'] = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')
    jdump(st, STATE)
    print(f'נכתבו: {len(events)} אירועי תחנה · {n_lines} גרסאות קו ב-{len(per_rd)} וריאנטים', file=sys.stderr)


if __name__ == '__main__':
    main()
