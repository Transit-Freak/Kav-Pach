#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""מנוע ההשוואה על ארכיון TransitFeeds — 2017 עד 2022.

אותו היגיון שהסריקה היומית מפעילה על היום מול אתמול, רק על צילומי
הארכיון: זורמים דרכם לפי סדר, משווים כל אחד לקודמו, וכותבים רק את
אירועי השינוי. הצילומים עצמם אינם נשמרים — 768 מהם היו תופסים עשרות
ג'יגה — ולכן רק הקודם מוחזק בזיכרון בכל רגע.

מצב הריצה נשמר לקובץ, כך שאפשר לעצור ולהמשיך: ריצה חוזרת מדלגת על
הימים שכבר עובדו.

FROM/TO   טווח תאריכים (YYYYMMDD), ברירת מחדל כל הארכיון
MAX_DAYS  מספר צילומים מרבי לריצה אחת
DRY=1     ניתוח בלבד, בלי כתיבה לקבצי הקווים
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import (central_dir, enc_polyline, fsafe, http,  # noqa: E402
                          member_rows, stream_member, thin)
from compact_lines import compact, materialize  # noqa: E402

BASE = ('https://openmobilitydata-data.s3-us-west-1.amazonaws.com'
        '/public/feeds/ministry-of-transport-and-road-safety/820')
OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/tf-state.json'
SRC = 'tf'
DRY = os.environ.get('DRY') == '1'
SNAP_META = {}      # פרטי הקווים של הצילום הנוכחי, לצורך יצירת קבצים חדשים
MAX_DAYS = int(os.environ.get('MAX_DAYS', '0'))
MAX_MIN = float(os.environ.get('MAX_MIN', '0'))   # תקציב זמן לחוליה אחת
FROM = os.environ.get('FROM', '20170101')
TO = os.environ.get('TO', '20221231')


def iso(ds):
    return f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'


# סוג התחבורה לפי route_type של ה-GTFS. אוטובוס הוא ברירת המחדל ואינו
# מסומן, כדי לא לשנות אף קובץ קיים. שאר הסוגים היו מסוננים החוצה עד כה.
TT = {'2': 'rail', '8': 'taxi', '0': 'lightrail', '5': 'cable', '715': 'demand'}


def snapshot(ds):
    """{rd: (stops, shp)} מצילום יחיד. stops = [[מק"ט, שם, lat, lon], ...]

    meta[rd] נאסף במקביל: מספר הקו, היעד, המפעיל וסוג התחבורה — נדרש כדי
    ליצור קובץ קו לסוגים שמעולם לא נכנסו לאתר (רכבת, מוניות שירות וכו').
    """
    url = f'{BASE}/{ds}/gtfs.zip'
    members = central_dir(url)
    c, rows = member_rows(url, members, 'routes.txt')
    rows = list(rows)
    try:
        c2, arows = member_rows(url, members, 'agency.txt')
        agency = {r[c2['agency_id']]: r[c2['agency_name']].strip() for r in arows}
    except (KeyError, ValueError):
        agency = {}
    rid2rd, meta = {}, {}
    for r in rows:
        rd = r[c['route_desc']].strip()
        if rd.count('-') < 2:
            continue
        rid2rd[r[c['route_id']]] = rd
        rt = r[c['route_type']].strip()
        meta.setdefault(rd, {
            'line': r[c['route_short_name']].strip(),
            'dest': r[c['route_long_name']].strip(),
            'op': agency.get(r[c['agency_id']], ''),
            'tt': TT.get(rt) if rt != '3' else None,
        })
    SNAP_META.clear()
    SNAP_META.update(meta)
    if not rid2rd:
        return {}
    # נסיעה נציגה לכל וריאנט. הכלל הקודם היה "הראשונה בקובץ שיש לה שרטוט",
    # והוא נשען על סדר השורות ב-trips.txt — סדר שאינו יציב בין צילומים.
    # בקו 548 היו בשני הצילומים 23 נסיעות בתבנית של 21 תחנות ו-7 בתבנית של
    # 25, ורק הסדר התחלף; הכלל בחר ב-13.1 את בת ה-25 וב-14.1 את בת ה-21,
    # ונרשם "ירדו ארבע תחנות" על נתונים שלא זזו.
    #
    # הבחירה כאן אינה תלויה בסדר: התבנית שרוב הנסיעות רצות בה, ובתוכה
    # מזהה הנסיעה הקטן ביותר. שוויון נשבר לפי מזהה השרטוט.
    c, rows = member_rows(url, members, 'trips.txt')
    cnt, first_t, noshape = {}, {}, {}
    for r in rows:
        rd = rid2rd.get(r[c['route_id']])
        if not rd:
            continue
        tid = r[c['trip_id']]
        sh = r[c['shape_id']] if 'shape_id' in c else ''
        if not sh:
            if rd not in noshape or tid < noshape[rd]:
                noshape[rd] = tid
            continue
        cnt.setdefault(rd, {})[sh] = cnt.setdefault(rd, {}).get(sh, 0) + 1
        k = (rd, sh)
        if k not in first_t or tid < first_t[k]:
            first_t[k] = tid
    picked = {}
    for rd, shapes in cnt.items():
        sh = min(shapes, key=lambda x: (-shapes[x], x))
        picked[rd] = (first_t[(rd, sh)], sh)
    for rd, tid in noshape.items():
        picked.setdefault(rd, (tid, ''))

    trip2rd = {v[0].encode(): k for k, v in picked.items()}
    seqs, buf, hdr = {}, [b''], {}

    def on_st(data):
        buf[0] += data
        *lines, buf[0] = buf[0].split(b'\n')
        for ln in lines:
            if not hdr:
                for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr[h.strip()] = i
                continue
            f = ln.split(b',')
            try:
                rd = trip2rd.get(f[hdr['trip_id']].strip())
                if rd is not None:
                    seqs.setdefault(rd, []).append(
                        (int(f[hdr['stop_sequence']]), f[hdr['stop_id']].decode()))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    stream_member(url, members, 'stop_times.txt', on_st)

    need = {s for lst in seqs.values() for _, s in lst}
    c, rows = member_rows(url, members, 'stops.txt')
    sinfo = {}
    for r in rows:
        sid = r[c['stop_id']]
        if sid in need:
            sinfo[sid] = [r[c['stop_code']] or sid, r[c['stop_name']].strip(),
                          round(float(r[c['stop_lat']]), 5),
                          round(float(r[c['stop_lon']]), 5)]

    want = {v[1] for v in picked.values() if v[1]}
    pts, buf2, hdr2 = {}, [b''], {}

    def on_shp(data):
        buf2[0] += data
        *lines, buf2[0] = buf2[0].split(b'\n')
        for ln in lines:
            if not hdr2:
                for i, h in enumerate(ln.decode('utf-8-sig').strip().split(',')):
                    hdr2[h.strip()] = i
                continue
            f = ln.split(b',')
            try:
                sid = f[hdr2['shape_id']].decode()
                if sid in want:
                    pts.setdefault(sid, []).append((int(f[hdr2['shape_pt_sequence']]),
                                                    float(f[hdr2['shape_pt_lat']]),
                                                    float(f[hdr2['shape_pt_lon']])))
            except (IndexError, ValueError, UnicodeDecodeError):
                continue

    if want:
        try:
            stream_member(url, members, 'shapes.txt', on_shp)
        except (KeyError, ValueError):
            pass

    out = {}
    for rd, lst in seqs.items():
        lst.sort()
        stops = [sinfo[s] for _, s in lst if s in sinfo]
        if len(stops) < 2:
            continue
        p = pts.get(picked[rd][1]) or []
        p.sort()
        out[rd] = (stops, enc_polyline(thin([(x[1], x[2]) for x in p])) if p else '')
    return out


def classify(old, new, old_shp, new_shp):
    """קטגוריית השינוי — העתק מדויק של הכלל בסריקה היומית (linehistory.classify),
    כדי שאירוע מהארכיון ייראה בדיוק כמו אירוע שנמדד היום."""
    oc = [s[0] for s in old]
    nc = [s[0] for s in new]
    geo, stp = old_shp != new_shp, oc != nc
    if not geo and not stp:
        return None, [], []
    if geo and not stp:
        return 'redraw', [], []
    so, sn = set(oc), set(nc)
    add = [s[1] for s in new if s[0] not in so]
    rem = [s[1] for s in old if s[0] not in sn]
    term = bool(oc and nc and (oc[0] != nc[0] or oc[-1] != nc[-1]))
    d = len(nc) - len(oc)
    if term and d >= 3:
        return 'extend', add, rem
    if term and d <= -3:
        return 'shorten', add, rem
    if term:
        return 'terminal', add, rem
    if add and rem:
        return ('route' if geo else 'stops'), add, rem
    if add:
        return 'stops-add', add, rem
    if rem:
        return 'stops-del', add, rem
    return ('route' if geo else 'stops'), add, rem


TTNOTE = {'rail': 'קו רכבת', 'taxi': 'קו מוניות שירות',
          'lightrail': 'קו רכבת קלה', 'cable': 'קו כבלים',
          'demand': 'קו שירות לפי דרישה'}


def ensure_line(rd, ds, stops, shp):
    """יצירת קובץ קו לסוגי תחבורה שמעולם לא נכנסו לאתר.

    עד היום הסריקה סיננה כל route_type שאינו אוטובוס, ולכן לרכבת, למוניות
    השירות ולרכבת הקלה אין קובץ כלל. כאן נוצר קובץ עם המצב שנצפה לראשונה
    כתיעוד ראשון, ומכאן והלאה השינויים נרשמים בו כמו בכל קו אחר.
    """
    m = SNAP_META.get(rd)
    if not m or not m.get('tt'):
        return False              # אוטובוס — הקווים שנעלמו הם משימה נפרדת
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    if os.path.exists(p):
        return False
    lf = {'rd': rd, 'line': m['line'], 'dest': m['dest'], 'op': m['op'],
          'ty': '', 'tt': m['tt'],
          'versions': [{'d': iso(ds), 'k': 'baseline', 'src': SRC,
                        'stops': stops, 'shp': shp,
                        'note': f'{TTNOTE.get(m["tt"], "קו")} — התיעוד הראשון, '
                                f'מארכיון הפיד הארצי'}]}
    json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    return True


def apply_event(rd, ds, kind, stops, shp, add, rem, since):
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    if not os.path.exists(p):
        return False
    lf = materialize(json.load(open(p, encoding='utf-8')))
    vs = lf.get('versions') or []
    d = iso(ds)
    if any(v['d'] == d and v.get('src') == SRC for v in vs):
        return False
    # התאריך הוא יום הגילוי, לא בהכרח יום השינוי: הארכיון מצלם אחת לכמה
    # ימים. הטווח נרשם במפורש כדי לא להציג ודאות שאינה קיימת.
    v = {'d': d, 'k': kind, 'src': SRC, 'stops': stops, 'shp': shp,
         'note': 'שינוי שאותר בהשוואת צילומי הארכיון של הפיד הארצי'}
    # 'sd' = הצילום האחרון שבו המצב עוד היה הקודם. הפער בינו ל-'d' הוא
    # דיוק המדידה בפועל: יום אחד ב-2020, שבועיים ב-2017. בלי השדה הזה
    # התאריך נראה מדויק תמיד, גם כשהוא בעצם אמצע חלון של שבועיים.
    if iso(since) != d:
        v['sd'] = iso(since)
    if add:
        v['add'] = add
    if rem:
        v['rem'] = rem
    vs.append(v)
    vs.sort(key=lambda x: x['d'])
    lf['versions'] = vs
    json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    return True


def main():
    # רשימת תאריכי הארכיון נשמרת בריפו: היא נבנתה מסריקה של אלפי ימים מול
    # שרת חיצוני, ואיבודה היה מחייב לחזור על כל הסריקה. עותק ב-/tmp נשאר
    # כגיבוי תאום-לאחור.
    src = os.environ.get('DAYS')
    if not src:
        src = (f'{OUTDIR}/tf-days.txt' if os.path.exists(f'{OUTDIR}/tf-days.txt')
               else '/tmp/hits.txt')
    days = [l.strip() for l in open(src)
            if l.strip() and FROM <= l.strip() <= TO]
    st = json.load(open(STATE)) if os.path.exists(STATE) else {'done': []}
    done = set(st['done'])
    todo = [d for d in days if d not in done]
    if MAX_DAYS:
        todo = todo[:MAX_DAYS]
    print(f'צילומים בטווח: {len(days)} · כבר עובדו: {len(done)} · בריצה זו: {len(todo)}',
          file=sys.stderr)

    # המצב הידוע האחרון לכל וריאנט, לא הצילום הקודם כמות שהוא: מספר
    # הווריאנטים בפיד מתנודד במאות בין צילום לצילום (לוח שירות שנגמר
    # תוקפו), והחלפה גורפת הייתה מאבדת את השינויים של כל מי שנעדר לרגע.
    prev = {}
    if done:
        last = max(done)
        prev = {rd: (s, h, last) for rd, (s, h) in snapshot(last).items()}
    if not todo:
        print('הכל עובד — אין צילומים שנותרו', file=sys.stderr)
        return

    total, tally, made, skipped = 0, {}, 0, []
    deadline = time.monotonic() + MAX_MIN * 60 if MAX_MIN else None
    for ds in todo:
        # עצירה נקייה בגבול תקציב הזמן, בין צילומים ולא באמצע כתיבה —
        # החוליה הבאה ממשיכה מהמצב השמור.
        if deadline and time.monotonic() > deadline:
            print(f'תקציב הזמן נגמר — נעצר אחרי {len(done) - len(st["done"])} '
                  f'צילומים בחוליה זו', file=sys.stderr)
            break
        # צילום בודד שנכשל לא מפיל ריצה של מאות צילומים. הכשל השכיח הוא
        # ניתוק SSL באמצע קריאה מול S3; הוא חולף, והיום פשוט יטופל בהרצה
        # הבאה — לכן הוא גם לא מסומן כ"עובד".
        try:
            cur = snapshot(ds)
        except BaseException as e:
            skipped.append(ds)
            print(f'  {iso(ds)}: דילוג — {type(e).__name__}: {str(e)[:70]}',
                  file=sys.stderr)
            continue
        n = c = 0
        for rd, (stops, shp) in cur.items():
            if not DRY and ensure_line(rd, ds, stops, shp):
                c += 1
            old = prev.get(rd)
            if old:               # וריאנט שלא נראה קודם — מטופל בצנרת הראשית
                k, add, rem = classify(old[0], stops, old[1], shp)
                if k and (DRY or apply_event(rd, ds, k, stops, shp, add, rem, old[2])):
                    tally[k] = tally.get(k, 0) + 1
                    n += 1
            prev[rd] = (stops, shp, ds)
        made += c
        print(f'  {iso(ds)}: {len(cur)} וריאנטים · {n} שינויים · '
              f'{len(prev)} במעקב' + (f' · {c} קווים חדשים' if c else ''),
              file=sys.stderr)
        total += n
        if not DRY:
            done.add(ds)
            json.dump({'done': sorted(done)}, open(STATE, 'w'))
    brk = ' · '.join(f'{k}:{v}' for k, v in sorted(tally.items(), key=lambda x: -x[1]))
    print(f'סה"כ {total} אירועי שינוי — {brk}', file=sys.stderr)
    if made:
        print(f'נוצרו {made} קבצי קו לסוגי תחבורה חדשים', file=sys.stderr)
    if skipped:
        print(f'דולגו {len(skipped)} צילומים בגלל תקלות רשת — ' +
              'ייטופלו בהרצה הבאה: ' + ', '.join(skipped[:8]), file=sys.stderr)


if __name__ == '__main__':
    main()
