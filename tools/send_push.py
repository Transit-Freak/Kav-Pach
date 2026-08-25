# -*- coding: utf-8 -*-
"""הקו בזמן — שולח התראות הדפדפן היומי (OneSignal).

רץ אחרי הסריקה היומית: אוסף את שינויי היום (מהותיים בלבד — בלי לו"ז
ותדירות), ולכל קו ששונה שולח התראה אחת לעוקבי הקו (תג l<מקט>) ולעוקבי
ערי הקצה שלו (תג עיר מגובב, OR — כפילויות מסוננות אצל הספק).

env: ONESIGNAL_APP_ID, ONESIGNAL_API_KEY (בלעדיהם — יציאה שקטה),
     DATE (ברירת מחדל: היום), DRY=1 להדפסה בלבד.
"""
import datetime
import json
import os
import sys
import urllib.request

OUTDIR = os.environ.get('OUTDIR', 'line-history/data')
APP_ID = os.environ.get('ONESIGNAL_APP_ID', '')
API_KEY = os.environ.get('ONESIGNAL_API_KEY', '')
DATE = os.environ.get('DATE') or datetime.date.today().isoformat()
DRY = os.environ.get('DRY') == '1'
BASE_URL = 'https://transit-freak.github.io/kav-bochan/line-history/'
MAX_SENDS = int(os.environ.get('MAX_SENDS', '200'))

SKIP_KINDS = {'freq', 'sched', 'times', 'baseline', 'snapshot'}
# קבוצות ההרשמה במרכז ההתראות (זהה ל-KIND_GROUPS_N שבאתר)
KIND_GROUP = {}
for _tag, _kinds in (('kg_rem', ['removed']), ('kg_new', ['new']),
                     ('kg_route', ['route', 'redraw', 'extend', 'shorten', 'terminal',
                                   'stops', 'stops-add', 'stops-del']),
                     ('kg_ident', ['dest', 'renum', 'renamed', 'operator', 'mode'])):
    for _k in _kinds:
        KIND_GROUP[_k] = _tag

KIND_LBL = {
    'new': 'וריאנט חדש', 'route': 'שינוי מסלול', 'redraw': 'תיקון שרטוט',
    'terminal': 'שינוי קצה המסלול', 'extend': 'הארכת קו', 'shorten': 'קיצור קו',
    'stops-add': 'תחנות נוספו', 'stops-del': 'תחנות ירדו', 'stops': 'שינוי תחנות',
    'operator': 'החלפת מפעיל', 'dest': 'שינוי יעד', 'renum': 'שינוי מספר',
    'renamed': 'שינוי שם תחנת קצה', 'mode': 'שינוי סוג הקו',
    'access': 'שינוי נגישות', 'board': 'שינוי עלייה/ירידה', 'removed': 'הקו בוטל',
}


def city_tag(name):
    """זהה ל-cityTag שב-app.jsx: djb2 xor על קוד-התו, base36."""
    h = 5381
    for ch in str(name or '').strip():
        h = ((h * 33) ^ ord(ch)) & 0xFFFFFFFF
    out = ''
    n = h
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    if n == 0:
        out = '0'
    while n:
        out = digits[n % 36] + out
        n //= 36
    return 'c' + out


def dest_cities(dest):
    # העיר = המקטע העברי האחרון; סיומות טכניות ("2#") מדולגות
    import re
    out = []
    for side in str(dest or '').split('<->'):
        for p in reversed(side.strip().split('-')):
            p = p.strip()
            if len(p) >= 2 and '#' not in p and re.search('[א-ת]', p) and not re.search('[0-9]', p):
                if p not in out:
                    out.append(p)
                break
    return out[:2]


def collect_changes():
    """{makat: {'line','dest','kinds':set,'rd'}} לשינויים המהותיים של DATE."""
    idx = {}
    try:
        cat = {x['rd']: x for x in json.load(open(f'{OUTDIR}/lines.json'))['lines']}
    except Exception:
        cat = {}
    for f in os.listdir(f'{OUTDIR}/lines'):
        try:
            d = json.load(open(f'{OUTDIR}/lines/{f}', encoding='utf-8'))
        except Exception:
            continue
        for v in d.get('versions') or []:
            if str(v.get('d', ''))[:10] != DATE or v.get('k') in SKIP_KINDS:
                continue
            rd = d.get('rd') or f.rsplit('.', 1)[0]
            mk = rd.split('-')[0]
            e = idx.setdefault(mk, {'line': d.get('line') or (cat.get(rd) or {}).get('line', ''),
                                    'dest': d.get('dest') or (cat.get(rd) or {}).get('dest', ''),
                                    'kinds': set(), 'rd': rd})
            e['kinds'].add(v.get('k'))
    return idx


def send(payload):
    req = urllib.request.Request(
        'https://api.onesignal.com/notifications',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json; charset=utf-8',
                 'Authorization': f'Key {API_KEY}'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    changes = collect_changes()
    print(f'{DATE}: {len(changes)} קווים עם שינוי מהותי')
    if not changes:
        return
    if not (APP_ID and API_KEY) and not DRY:
        print('אין מפתחות OneSignal — יציאה שקטה (הפיצ׳ר עוד לא הופעל)')
        return
    sent = 0
    for mk, e in sorted(changes.items()):
        if sent >= MAX_SENDS:
            print(f'הגעת לתקרת {MAX_SENDS} שליחות — היתר יחכו למחר')
            break
        kinds = ' · '.join(KIND_LBL.get(k, k) for k in sorted(e['kinds']))
        title = f'קו {e["line"]}' if e['line'] else 'קו'
        body = f'{kinds} — {e["dest"][:90]}' if e['dest'] else kinds
        url = f'{BASE_URL}#{e["rd"]}@{DATE}'
        groups = sorted({KIND_GROUP.get(k) for k in e['kinds']} - {None})
        filters = [{'field': 'tag', 'key': f'l{mk}', 'relation': '=', 'value': '1'}]
        for ct in dest_cities(e['dest']):
            ctag = {'field': 'tag', 'key': city_tag(ct), 'relation': '=', 'value': '1'}
            # עוקבי-עיר מהכפתור הפשוט (בלי תדירות) — מקבלים הכל יומית
            filters += [{'operator': 'OR'}, ctag,
                        {'field': 'tag', 'key': 'freq', 'relation': 'not_exists'}]
            # נרשמי מרכז ההתראות במצב יומי — רק בסוגים שסימנו
            for g in groups:
                filters += [{'operator': 'OR'}, ctag,
                            {'field': 'tag', 'key': 'freq', 'relation': '=', 'value': '1'},
                            {'field': 'tag', 'key': g, 'relation': '=', 'value': '1'}]
        payload = {'app_id': APP_ID,
                   'headings': {'en': title, 'he': title},
                   'contents': {'en': body, 'he': body},
                   'url': url, 'filters': filters}
        if DRY:
            print('DRY:', title, '|', body, '|', url, '|', [f.get('key') for f in filters if 'key' in f])
        else:
            try:
                res = send(payload)
                rec = res.get('recipients', 0)
                if rec:
                    print(f'נשלח: קו {e["line"]} → {rec} נמענים')
            except Exception as ex:
                print(f'שגיאת שליחה לקו {e["line"]}: {ex}', file=sys.stderr)
        sent += 1
    print(f'סה"כ קריאות שליחה: {sent}')
    send_digests()


def collect_range(days):
    since = (datetime.date.fromisoformat(DATE) - datetime.timedelta(days=days)).isoformat()
    by_city = {}
    for f in os.listdir(f'{OUTDIR}/lines'):
        try:
            d = json.load(open(f'{OUTDIR}/lines/{f}', encoding='utf-8'))
        except Exception:
            continue
        for v in d.get('versions') or []:
            dd = str(v.get('d', ''))[:10]
            if not (since < dd <= DATE) or v.get('k') in SKIP_KINDS or v.get('k') in ('baseline', 'snapshot'):
                continue
            rd = d.get('rd') or f.rsplit('.', 1)[0]
            for ct in dest_cities(d.get('dest') or ''):
                e = by_city.setdefault(ct, {'kinds': set(), 'bykind': {}})
                e['kinds'].add(v.get('k'))
                e['bykind'].setdefault(v.get('k'), set()).add(rd.split('-')[0])
    return by_city


def list_players():
    """כל הנרשמים והתגים שלהם — לצורך סיכום מאוחד פר-נרשם."""
    out, offset = [], 0
    while True:
        req = urllib.request.Request(
            f'https://api.onesignal.com/players?app_id={APP_ID}&limit=300&offset={offset}',
            headers={'Authorization': f'Key {API_KEY}'})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        ps = d.get('players') or []
        out += ps
        if len(ps) < 300:
            return out
        offset += 300


def send_digests():
    """סיכום כל 3 ימים / שבועי (יום ראשון) — הודעה אחת לכל נרשם, שמאחדת
    את כל הערים שבחר (בקשת שלמה: לא הודעה לכל עיר)."""
    today = datetime.date.fromisoformat(DATE)
    jobs = []
    if today.toordinal() % 3 == 0:
        jobs.append(('3', 3))
    if today.weekday() == 6:   # ראשון
        jobs.append(('7', 7))
    if not jobs:
        return
    # מפה מהתג המגובב חזרה לשם העיר — מערי הקצה של כל הקטלוג
    rev = {}
    try:
        for x in json.load(open(f'{OUTDIR}/lines.json'))['lines']:
            for ct in dest_cities(x.get('dest') or ''):
                rev[city_tag(ct)] = ct
    except Exception:
        pass
    if not (APP_ID and API_KEY):
        print('סיכומים: אין מפתחות — דילוג')
        return
    try:
        players = list_players()
    except Exception as ex:
        print(f'סיכומים: רשימת הנרשמים נכשלה ({ex})', file=sys.stderr)
        return
    for freq, days in jobs:
        by_city = collect_range(days)
        sent = 0
        for p in players:
            tags = p.get('tags') or {}
            if tags.get('freq') != freq or p.get('invalid_identifier'):
                continue
            ucities = [rev[t] for t, val in tags.items() if t in rev and val == '1']
            ugroups = {g for g in ('kg_rem', 'kg_new', 'kg_route', 'kg_ident') if tags.get(g) == '1'}
            mks, kinds = set(), set()
            for ct in ucities:
                e = by_city.get(ct)
                if not e:
                    continue
                for k, kmks in e['bykind'].items():
                    if KIND_GROUP.get(k) in ugroups:
                        kinds.add(k)
                        mks |= kmks
            if not mks:
                continue
            title = f'🔔 {len(mks)} קווים השתנו ב{"ערים שלך" if len(ucities) > 1 else (ucities[0] if ucities else "")}'
            body = ('סיכום ' + ('שבועי' if days == 7 else f'{days} ימים') + f' — {", ".join(ucities[:4])}: ' +
                    ' · '.join(sorted({KIND_LBL.get(k, k) for k in kinds})[:4]))
            url = f'{BASE_URL}#digest={",".join(ucities)}@{days}'
            payload = {'app_id': APP_ID, 'headings': {'en': title, 'he': title},
                       'contents': {'en': body, 'he': body}, 'url': url,
                       'include_subscription_ids': [p.get('id')]}
            if DRY:
                print('DRY-DIGEST:', title, '|', body, '|', url)
            else:
                try:
                    send(payload)
                except Exception as ex:
                    print(f'שגיאת סיכום לנרשם: {ex}', file=sys.stderr)
            sent += 1
        print(f'סיכומי {days} ימים: {sent} נרשמים קיבלו הודעה מאוחדת אחת')


if __name__ == '__main__':
    main()
