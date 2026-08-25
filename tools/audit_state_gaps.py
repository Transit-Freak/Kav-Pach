# -*- coding: utf-8 -*-
"""ביקורת ארצית: אירועי מסלול שהסריקה היומית בלעה — איתור ושחזור.

הדפוס (נתגלה בקו 80 כפר חב"ד, דרישת שלמה לבדוק את כל הארץ): וריאנט
חוזר לרישום הפעיל אחרי הפסקה, הסורק משווה אותו לתיעוד-עם-גאומטריה
האחרון — שהיה ישן בשנים כי הרשומות שביניהן היו ריקות — מוצא "זהה" ולא
רושם כלום. השינוי הבא מוצג אז מול מסלול עתיק, וכרטיסו "ממציא" תחנות.

הביקורת עוברת על היסטוריית הגיט של מצב-הסריקה (state-routes.json, קומיט
ליום), ולכל וריאנט שנכנס למצב או שרצף התחנות שלו השתנה בין יום ליום
בלי שנרשמה גרסה בקובץ הקו באותו חלון — משווה מול התיעוד-עם-תחנות
האחרון. שוני אמיתי משוחזר כאירוע 'route' בתאריך הסריקה, מהמצב היומי
עצמו (מקור ראשוני), כולל רשימות ➕/➖ עם מק"טים מדויקים; והרשומה הבאה
אחריו מחושבת מחדש מולו. חזרה זהה לתיעוד נשארת בלי אירוע — כמו שנקבע.

DRY=1 ניתוח בלבד. אידמפוטנטי: גרסה קיימת בתאריך לא נדרסת.
"""
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compact_lines import compact, materialize  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
DRY = os.environ.get('DRY') == '1'
NOTE = ('שוחזר בדיעבד ממצב הסריקה היומי: הפיד פרסם מסלול שונה מהמתועד, '
        'והסריקה דילגה על האירוע (השוותה לתיעוד ישן). ➕/➖ מול התיעוד הקודם')
NOTE_NEXT = 'הרשימות חושבו מחדש מול האירוע ששוחזר שלפני'


def fsafe(rd):
    return rd.replace('#', 'H').replace('/', '_')


def gitshow(h, path):
    try:
        return json.loads(subprocess.check_output(
            ['git', 'show', f'{h}:{path}'], stderr=subprocess.DEVNULL))
    except Exception:
        return None


def diff_lists(prev_stops, cur_stops):
    pc = {str(s[0]) for s in prev_stops}
    cc = {str(s[0]) for s in cur_stops}
    add = [s for s in cur_stops if str(s[0]) not in pc]
    rem = [s for s in prev_stops if str(s[0]) not in cc]
    return ([s[1] for s in add], [str(s[0]) for s in add],
            [s[1] for s in rem], [str(s[0]) for s in rem])


def main():
    log = subprocess.check_output(
        ['git', 'log', '--reverse', '--format=%H %cs', '--',
         f'{OUTDIR}/state-routes.json'], text=True).strip().split('\n')
    days = []          # (date, commit) — הקומיט האחרון של כל יום
    for ln in log:
        h, cs = ln.split()
        if days and days[-1][0] == cs:
            days[-1] = (cs, h)
        else:
            days.append((cs, h))
    print(f'{len(days)} ימי מצב בהיסטוריה ({days[0][0]} עד {days[-1][0]})')
    prev_state = None
    suspects = []      # (date, commit, rd, codes)
    for cs, h in days:
        st = gitshow(h, f'{OUTDIR}/state-routes.json')
        if st is None:
            continue
        if prev_state is not None:
            for rd, e in st.items():
                codes = e.get('codes') or []
                if not codes:
                    continue
                pe = prev_state.get(rd)
                pcodes = (pe or {}).get('codes') or []
                if pe is None or (pcodes and pcodes != codes):
                    if pcodes != codes:
                        suspects.append((cs, h, rd, codes, bool(pe is None)))
        prev_state = st
    print(f'{len(suspects)} כניסות/שינויים במצב לבדיקה')
    n_ok = n_restored = n_nodoc = n_recorded = 0
    by_month = {}
    for cs, h, rd, codes, entered in suspects:
        p = f'{OUTDIR}/lines/{fsafe(rd)}.json'
        if not os.path.exists(p):
            continue
        lf = materialize(json.load(open(p, encoding='utf-8')))
        vs = sorted(lf.get('versions') or [], key=lambda v: v['d'])
        # חלון של יום: ריצה שהתאחרה מתויגת בקומיט של מחרת — בלי החלון
        # אירוע מתועד היה משוחזר שוב ונוצר כפול. רק רשומות שנושאות מידע
        # מסלולי חוסמות (freq/sched באותו יום אינן תיעוד של שינוי המסלול)
        c0 = datetime.date.fromisoformat(cs)
        if any(abs((datetime.date.fromisoformat(v['d']) - c0).days) <= 1
               and (v.get('stops') or v.get('add') or v.get('rem')
                    or v.get('k') in ('new', 'removed'))
               for v in vs):
            n_recorded += 1
            continue
        last_doc = next((v for v in reversed(vs)
                         if v['d'] < cs and (v.get('stops') or [])), None)
        if last_doc is None:
            n_nodoc += 1
            continue
        doc_codes = [str(s[0]) for s in last_doc['stops']]
        if doc_codes == [str(c) for c in codes]:
            n_ok += 1
            continue
        # שוני אמיתי שלא נרשם — שחזור מהמצב היומי
        ss = gitshow(h, f'{OUTDIR}/stops-state.json') or {}
        names = {}
        for v in vs:
            for s in v.get('stops') or []:
                names.setdefault(str(s[0]), s)
        stops = []
        for c in codes:
            c = str(c)
            e = ss.get(c)
            if e:
                stops.append([c, e[0], e[1], e[2]])
            else:
                k = names.get(c)
                stops.append([c, k[1], k[2], k[3]] if k else [c, c, None, None])
        add, ac, rem, rc = diff_lists(last_doc['stops'], stops)
        nv = {'d': cs, 'k': 'route', 'shp': '', 'stops': stops, 'note': NOTE}
        if add:
            nv['add'], nv['ac'] = add[:15], ac[:15]
        if rem:
            nv['rem'], nv['rc'] = rem[:15], rc[:15]
        vs.append(nv)
        vs.sort(key=lambda v: v['d'])
        # הגרסה-עם-תחנות הבאה מחושבת מחדש מול המסלול ששוחזר
        nxt = next((v for v in vs if v['d'] > cs and (v.get('stops') or [])), None)
        if nxt is not None and (nxt.get('add') or nxt.get('rem')):
            a2, ac2, r2, rc2 = diff_lists(stops, nxt['stops'])
            for key in ('add', 'ac', 'rem', 'rc'):
                nxt.pop(key, None)
            if a2:
                nxt['add'], nxt['ac'] = a2[:15], ac2[:15]
            if r2:
                nxt['rem'], nxt['rc'] = r2[:15], rc2[:15]
        if not DRY:
            lf['versions'] = vs
            json.dump(compact(lf), open(p, 'w', encoding='utf-8'),
                      ensure_ascii=False, separators=(',', ':'))
            mp = f'{OUTDIR}/changes/{cs[:7]}.json'
            mm = by_month.get(cs[:7])
            if mm is None:
                try:
                    mm = json.load(open(mp, encoding='utf-8'))
                except Exception:
                    mm = {'changes': []}
                by_month[cs[:7]] = mm
            mm['changes'] = [c2 for c2 in mm['changes']
                             if not (c2.get('rd') == rd and c2.get('d') == cs)]
            ch = {'d': cs, 'rd': rd, 'line': lf.get('line', ''), 'k': 'route'}
            if add:
                ch['add'] = add[:15]
            if rem:
                ch['rem'] = rem[:15]
            mm['changes'].append(ch)
        n_restored += 1
        print(f'  שוחזר: {rd} ב-{cs} (➕{len(add)} ➖{len(rem)})')
    for m, mm in by_month.items():
        json.dump(mm, open(f'{OUTDIR}/changes/{m}.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, separators=(',', ':'))
    print(f'סיכום: {n_restored} אירועים שוחזרו · {n_ok} חזרות זהות לתיעוד (תקין, בלי אירוע)'
          f' · {n_recorded} כבר מתועדים · {n_nodoc} בלי תיעוד להשוואה' + (' · DRY' if DRY else ''))


if __name__ == '__main__':
    main()
