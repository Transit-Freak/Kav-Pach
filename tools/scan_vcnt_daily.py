# -*- coding: utf-8 -*-
# "הקו בזמן" — מעקב יומי אחרי יציאות מרובות-רכבים (תגבורים מתוכננים).
#
# המקור: Gtfs_10_days.zip מפרסום הרישוי היומי של משרד התחבורה — הפורמט
# החדש שיודע לייצג 2-3 אוטובוסים שיוצאים באותה דקה על אותה נסיעה (מה
# שהקובץ הקלאסי israel-public-transportation.zip לא ידע). הארכיונים לא
# שומרים את הקובץ הזה, ולכן ההיסטוריה נבנית מהיום והלאה: כל ריצה משווה
# את מפת התגבורים להיום מול הריצה הקודמת (vcnt-state.json) ורושמת אירוע
# k='freq' עם המילה "תגבור" בהערה — הממשק כבר מסווג אירועים כאלה
# לקטגוריית "שינוי מספר הרכבים באותה נסיעה".
import collections
import csv
import datetime
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile

OUT = os.environ.get('OUTDIR', 'line-history/data')
URL = 'https://gtfs.mot.gov.il/gtfsfiles/Gtfs_10_days.zip'
# בקובץ ה-10 ימים route_desc ריק — המיפוי למק"ט נעשה דרך TripIdToDate
# (TripId -> מק"ט-כיוון-חלופה). נופל לארכיון הסדנא אם שרת המשרד לא זמין.
TID_URLS = ['https://gtfs.mot.gov.il/gtfsfiles/TripIdToDate.zip']
S3 = 'https://openbus-stride-public.s3.eu-west-1.amazonaws.com'
for _back in range(0, 3):
    _d = (datetime.date.today() - datetime.timedelta(days=_back))
    TID_URLS.append(f'{S3}/gtfs_archive/{_d.year}/{_d.month:02d}/{_d.day:02d}/TripIdToDate.zip')
UA = 'kav-bochan/line-history (daily vcnt scan; github.com/Transit-Freak/kav-bochan)'
DAY_HE = {6: 'א', 0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש'}
BH = {'א': 'ימי ראשון', 'ב': 'ימי שני', 'ג': 'ימי שלישי', 'ד': 'ימי רביעי',
      'ה': 'ימי חמישי', 'ו': 'ימי שישי', 'ש': 'שבת'}
TODAY = datetime.date.today().isoformat()


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def download(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA})
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
            with urllib.request.urlopen(req, timeout=600) as r:
                while True:
                    b = r.read(1 << 22)
                    if not b:
                        break
                    tmp.write(b)
            tmp.close()
            return tmp.name
        except Exception as e:
            print(f'{url} — ניסיון {attempt + 1} נכשל: {e}', file=sys.stderr)
    return None


def load_tid2rd():
    """TripId -> rd (מק"ט-כיוון-חלופה) מקובץ הרישוי TripIdToDate."""
    for url in TID_URLS:
        p = download(url)
        if not p:
            continue
        try:
            z = zipfile.ZipFile(p)
            f = io.TextIOWrapper(z.open(z.namelist()[0]), 'utf-8-sig')
            rd_ = csv.reader(f)
            h = {c.strip(): i for i, c in enumerate(next(rd_))}
            m = {}
            for r in rd_:
                try:
                    mkt = r[h['OfficeLineId']].lstrip('0')
                    if mkt:
                        m[r[h['TripId']]] = f"{mkt}-{r[h['Direction']]}-{r[h['LineAlternative']]}"
                except IndexError:
                    continue
            os.unlink(p)
            print(f'TripIdToDate: {len(m):,} נסיעות ממופות ({url.split("/")[2]})')
            return m
        except Exception as e:
            print(f'{url} — קובץ בעייתי: {e}', file=sys.stderr)
    print('אין TripIdToDate זמין — מדלגים על היום')
    sys.exit(0)


def build_map(zpath, tid2rd):
    """rd -> bucket -> {hh:mm: מספר רכבים} — רק דקות עם 2+ רכבים מתוכננים."""
    z = zipfile.ZipFile(zpath)
    svc2dates = collections.defaultdict(list)
    rd_ = csv.reader(io.TextIOWrapper(z.open('calendar_dates.txt'), 'utf-8-sig'))
    h = {c.strip(): i for i, c in enumerate(next(rd_))}
    for r in rd_:
        if r[h['exception_type']] == '1':
            svc2dates[r[h['service_id']]].append(r[h['date']])
    rd_ = csv.reader(io.TextIOWrapper(z.open('trips.txt'), 'utf-8-sig'))
    h = {c.strip(): i for i, c in enumerate(next(rd_))}
    trip2r = {}
    unmapped = 0
    for r in rd_:
        # trip_id בפורמט "12345_100826" — המזהה שלפני הקו התחתון הוא TripId ברישוי
        rd2 = tid2rd.get(r[h['trip_id']].split('_')[0])
        if rd2 is None:
            unmapped += 1
            continue
        trip2r[r[h['trip_id']]] = (rd2, r[h['service_id']])
    print(f'נסיעות ממופות למק"ט: {len(trip2r):,} | בלי מיפוי: {unmapped:,}')
    per_date = collections.defaultdict(list)   # (rd, date) -> [hh:mm]
    hdr = None
    for ln in io.TextIOWrapper(z.open('stop_times.txt'), 'utf-8-sig'):
        p = ln.rstrip('\n').split(',')
        if hdr is None:
            hdr = {c.strip(): i for i, c in enumerate(p)}
            continue
        try:
            if p[hdr['stop_sequence']].strip() != '1':
                continue
            ri = trip2r.get(p[hdr['trip_id']])
            if ri is None:
                continue
            for ds in svc2dates.get(ri[1], ()):
                per_date[(ri[0], ds)].append(p[hdr['departure_time']][:5])
        except (IndexError, KeyError):
            continue
    # לכל (וריאנט, יום-בשבוע): המקסימום לכל שעה על פני התאריכים בחלון —
    # תגבור שמופיע בשישי אחד ייתפס גם אם השישי השני רגיל
    out = collections.defaultdict(lambda: collections.defaultdict(dict))
    for (rd2, ds), ts in per_date.items():
        d = datetime.datetime.strptime(ds, '%Y%m%d').date()
        bucket = DAY_HE[d.weekday()]
        cnt = collections.Counter(ts)
        for t, n in cnt.items():
            if n >= 2:
                cur = out[rd2][bucket].get(t, 0)
                if n > cur:
                    out[rd2][bucket][t] = n
    return {rd2: {b: dict(sorted(m.items())) for b, m in bk.items()} for rd2, bk in out.items()}


def main():
    statep = f'{OUT}/vcnt-state.json'
    try:
        state = json.load(open(statep, encoding='utf-8'))
    except Exception:
        state = {}
    prev = state.get('map')
    tid2rd = load_tid2rd()
    zpath = download(URL)
    if not zpath:
        print('הורדת Gtfs_10_days נכשלה — מדלגים על היום')
        sys.exit(0)
    cur = build_map(zpath, tid2rd)
    os.unlink(zpath)
    n_routes = len(cur)
    n_slots = sum(len(m) for bk in cur.values() for m in bk.values())
    print(f'מפת תגבורים להיום: {n_routes} וריאנטים, {n_slots} דקות מרובות-רכבים')

    events = []
    if prev is None:
        print('ריצה ראשונה — נזרע בסיס ההשוואה; אירועים יירשמו מהריצה הבאה')
    else:
        for rd2 in set(prev) | set(cur):
            pb, cb = prev.get(rd2, {}), cur.get(rd2, {})
            for b in set(pb) | set(cb):
                po, co = pb.get(b, {}), cb.get(b, {})
                if po == co:
                    continue
                parts = []
                for t in sorted(set(po) | set(co)):
                    o, n = po.get(t, 1), co.get(t, 1)
                    if o == n:
                        continue
                    if o == 1:
                        parts.append(f'ב-{t} מתוכננים עכשיו {n} אוטובוסים (תגבור חדש)')
                    elif n == 1:
                        parts.append(f'התגבור של {t} בוטל ({o} ← 1 אוטובוסים)')
                    else:
                        parts.append(f'ב-{t} — {o} ← {n} אוטובוסים (תגבור)')
                if parts:
                    events.append((rd2, f'שינוי תגבור ({BH[b]}): ' + ' · '.join(parts[:6])))

    n_written = 0
    feed = {}
    for rd2, note in events:
        p = f'{OUT}/lines/{fsafe(rd2)}.json'
        if not os.path.exists(p):
            continue
        lf = json.load(open(p, encoding='utf-8'))
        if any(v.get('d') == TODAY and v.get('note') == note for v in lf['versions']):
            continue
        lf['versions'].append({'d': TODAY, 'k': 'freq', 'note': note, 'src': 'v10'})
        lf['versions'].sort(key=lambda x: x['d'])
        json.dump(lf, open(p, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        feed[rd2] = (lf.get('line', ''), note)
        n_written += 1

    # פיד השינויים החודשי + קטגוריית הסינון באינדקס
    if feed:
        mp = f'{OUT}/changes/{TODAY[:7]}.json'
        try:
            month = json.load(open(mp, encoding='utf-8'))
        except Exception:
            month = []
        for rd2, (line, note) in feed.items():
            month.append({'d': TODAY, 'rd': rd2, 'line': line, 'k': 'freq', 'note': note})
        json.dump(month, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        try:
            idx = json.load(open(f'{OUT}/lines.json', encoding='utf-8'))
            for e in idx['lines']:
                if e.get('rd') in feed:
                    ks = set(e.get('ks') or [])
                    ks.add('freq')
                    e['ks'] = sorted(ks)
            json.dump(idx, open(f'{OUT}/lines.json', 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
        except Exception as ex:
            print('עדכון האינדקס נכשל:', ex)

    json.dump({'updated': TODAY, 'map': cur}, open(statep, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'{len(events)} שינויי תגבור זוהו | {n_written} נכתבו לקווים')


if __name__ == '__main__':
    main()
