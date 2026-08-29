# -*- coding: utf-8 -*-
"""סריקה צילום-מול-צילום של כל ארכיון TransitFeeds: 2017–2022 נבדק מחדש.

דרישת שלמה ("תעלה מחדש בדיקה לשני המקורות — הכל לבדוק מחדש"): כמו
הסריקה היומית של אופן באס, אבל על 1,100 צילומי TransitFeeds. משווים
את רצף התחנות של כל וריאנט בין כל שני צילומים עוקבים, מהחדש לישן;
שינוי שאין לו רשומת-מסלול בחלון שבין הצילומים נכתב בתאריך הצילום
הצעיר, עם sd=הצילום הישן (האתר מציג ≈ על טווח אי-הוודאות, כמו תמיד
בעידן הזה). התחנות והשרטוט המלא (בלי דילול) נלקחים מהצילום עצמו.

checkpoint: att-state.json (מצביע הצילום + טביעות רצף).
MAX_MIN תקציב דקות · DRY=1 גילוי בלבד.
"""
import datetime
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402
import backfill_tf as bt  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
STATE = f'{OUTDIR}/att-state.json'
DRY = os.environ.get('DRY') == '1'
MAX_MIN = float(os.environ.get('MAX_MIN', '45'))
PAUSE = float(os.environ.get('PAUSE', '0.5'))
T0 = time.time()
NOTE = 'שוחזר בדיעבד מהשוואת צילומי TransitFeeds'
ROUTEINFO = {'new', 'removed', 'baseline', 'snapshot'}


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def jload(p, dflt):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:
        return dflt


def iso(ds):
    return f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'


def sig_of(stops):
    return hashlib.sha1(','.join(str(s[0]) for s in stops).encode()).hexdigest()[:10]


def save_recheck(st):
    """סטטוס הבדיקה-מחדש לתצוגה באתר (data/recheck.json)."""
    p = f'{OUTDIR}/recheck.json'
    rc = jload(p, {})
    rc['tf_young'] = iso(st['young'])
    rc['updated'] = datetime.date.today().isoformat()
    if not DRY:
        json.dump(rc, open(p, 'w', encoding='utf-8'), ensure_ascii=False)


def has_route_record(rd, lo_iso, hi_iso):
    """יש כבר רשומת-מסלול בחלון (lo, hi]? הדגימה דלילה — כל החלון נבדק."""
    lf = jload(f'{OUTDIR}/lines/{fsafe(rd)}.json', None)
    if not lf:
        return True   # וריאנט בלי קובץ — לא נוגעים
    for v in materialize(lf).get('versions') or []:
        d = v.get('d', '')
        if lo_iso < d <= hi_iso and (v.get('stops') or v.get('add') or v.get('rem')
                                     or v.get('k') in ROUTEINFO):
            return True
    return False


def write_event(rd, young_iso, old_iso, gy, go):
    """אירוע אחד: ההפרש בין הצילומים, בתאריך הצילום הצעיר, עם טווח sd."""
    p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
    lf = materialize(jload(p, None))
    if not lf:
        return 0
    ys, yshp = gy
    os_, _ = go
    yc = {str(s[0]) for s in ys}
    oc = {str(s[0]) for s in os_}
    add = [s for s in ys if str(s[0]) not in oc]
    rem = [s for s in os_ if str(s[0]) not in yc]
    if not add and not rem:
        return 0   # שינוי סדר בלבד — לא נרשם כאן
    kind = 'stops-del' if rem and not add else ('stops-add' if add and not rem else 'route')
    v = {'d': young_iso, 'k': kind, 'shp': yshp or '', 'stops': ys,
         'src': 'tf', 'sd': old_iso, 'note': f'{NOTE} ({old_iso} ← {young_iso})'}
    if add:
        v['add'] = [s[1] for s in add][:15]
        v['ac'] = [str(s[0]) for s in add][:15]
    if rem:
        v['rem'] = [s[1] for s in rem][:15]
        v['rc'] = [str(s[0]) for s in rem][:15]
    vs = [x for x in lf['versions'] if x['d'] != young_iso or x.get('k') != kind]
    vs.append(v)
    vs.sort(key=lambda x: x['d'])
    lf['versions'] = vs
    if not DRY:
        json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
        mp = f'{OUTDIR}/changes/{young_iso[:7]}.json'
        mm = jload(mp, {'changes': []})
        mm['changes'] = [x for x in mm['changes']
                         if not (x.get('rd') == rd and x.get('d') == young_iso)]
        ch = {'d': young_iso, 'rd': rd, 'line': lf.get('line', ''), 'k': kind}
        if add:
            ch['add'] = v['add']
        if rem:
            ch['rem'] = v['rem']
        mm['changes'].append(ch)
        json.dump(mm, open(mp, 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
    print(f'  נכתב: {rd} — {kind} ב-{young_iso} (➕{len(add)} ➖{len(rem)})')
    return 1


def main():
    snaps = sorted(jload(f'{OUTDIR}/tf-state.json', {}).get('done') or [])
    if not snaps:
        print('אין רשימת צילומי TransitFeeds (tf-state.json) — אין מה לסרוק')
        return
    st = jload(STATE, {})
    if not st.get('young'):
        young = snaps[-1]
        print(f'אתחול: צילום {iso(young)}')
        st = {'young': young, 'sigs': None, 'done_pairs': 0, 'written': 0}
    idx = {d: i for i, d in enumerate(snaps)}
    cur_data = None            # הצילום הצעיר המלא — בזיכרון בלבד
    while (time.time() - T0) / 60 < MAX_MIN:
        yi = idx.get(st['young'])
        if yi is None or yi == 0:
            print('הסריקה הגיעה לתחילת ארכיון TransitFeeds — הושלם')
            break
        if cur_data is None:
            try:
                cur_data = bt.snapshot(st['young'])
            except (Exception, SystemExit) as e:
                print(f"{iso(st['young'])}: {type(e).__name__} — הצילום לא נטען, מדלגים אחורה",
                      file=sys.stderr)
                st['young'] = snaps[yi - 1]
                time.sleep(8)
                continue
        old = snaps[yi - 1]
        try:
            old_data = bt.snapshot(old)
        except (Exception, SystemExit) as e:
            print(f'{iso(old)}: {type(e).__name__} — מדלגים על הצילום', file=sys.stderr)
            st['young'] = old   # הזוג הבא יגשר מעל החור
            cur_data = None
            time.sleep(8)
            continue
        n = 0
        for rd, gy in cur_data.items():
            go = old_data.get(rd)
            if go is None or not gy[0] or not go[0]:
                continue
            if sig_of(gy[0]) == sig_of(go[0]):
                continue
            if has_route_record(rd, iso(old), iso(st['young'])):
                continue
            n += write_event(rd, iso(st['young']), iso(old), gy, go)
        if n:
            print(f"{iso(old)} ← {iso(st['young'])}: {n} שינויים בלי תיעוד נכתבו")
        st['written'] = st.get('written', 0) + n
        st['done_pairs'] = st.get('done_pairs', 0) + 1
        st['young'] = old
        cur_data = old_data
        if not DRY:
            json.dump({k: v for k, v in st.items() if k != 'sigs'},
                      open(STATE, 'w', encoding='utf-8'))
        save_recheck(st)
        time.sleep(PAUSE)
    print(f"מצב: הגענו עד {iso(st['young'])} · זוגות: {st.get('done_pairs', 0)}"
          f" · אירועים שנכתבו: {st.get('written', 0)}")


if __name__ == '__main__':
    main()
