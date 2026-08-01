#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""סורק ארכיוני של magihim.co.il — צילום מצב של רשת התחבורה הציבורית ~2012.

מבנה האתר (פוענח מקוד הדפים):
  ?pts                       — רשימת כל החברות
  ?pts&agency=N              — רשימת הקווים של חברה N (מזהים פנימיים)
  ?pts&agency=N&line=M       — דף קו: המסלול הראשי + קישורים לשאר המסלולים
  ?pts&agency=N&line=M&route=R — מסלול: כל התחנות, זמן מצטבר, סוג עצירה
  POST ajax_f3.php  get_info=&day=D&times=&station_from=&station_to=&routes_from=R
                             — שעות היציאה של מסלול R ביום D (א'=1..ש'=7);
                               שורות מופרדות ב-';!;' ושדות ב-';*;'

הסורק מנומס: בקשה אחת בשנייה, User-Agent מזוהה, מכבד robots.txt,
עם checkpoint מלא — אפשר לעצור ולהמשיך מאותה נקודה.

פלט (בתיקיית $OUT):
  state.json                 — מצב ההתקדמות (להמשכה)
  parsed/routes-agency-N.jsonl — רשומת מסלול: תחנות+זמנים+כותרת
  parsed/times.jsonl         — שעות יציאה לכל מסלול/יום
  raw/*.gz                   — ה-HTML הגולמי (לא נכנס ל-git; עולה כ-artifact)
"""
import gzip
import html
import json
import os
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = 'http://www.magihim.co.il/'
OUT = pathlib.Path(os.environ.get('OUT', 'magihim-out'))
MAX_MIN = float(os.environ.get('MAX_MIN', '330'))
DELAY = float(os.environ.get('DELAY', '1.1'))
UA = 'kav-bochan-archive-bot/1.0 (+https://github.com/transit-freak/kav-bochan; historical transit archive; 1 req/s)'

START = time.time()


def out_of_time():
    return (time.time() - START) / 60 > MAX_MIN


def fetch(url, data=None, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
            time.sleep(DELAY)
            return b
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    print(f'  !! נכשלה בקשה {url}: {last}', flush=True)
    return None


def get(suffix):
    b = fetch(BASE + suffix)
    return b.decode('utf-8', 'replace') if b else None


def save_raw(name, data):
    d = OUT / 'raw'
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / (name + '.gz'), 'wb') as f:
        f.write(data)


def append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False) + '\n')


def load_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


STATE_P = OUT / 'state.json'
state = load_json(STATE_P, {'agencies': {}, 'lines_done': [], 'routes_done': [],
                            'times_done': [], 'route_meta': {}})
lines_done = set(state['lines_done'])
routes_done = set(state['routes_done'])
times_done = set(state['times_done'])


def save_state():
    state['lines_done'] = sorted(lines_done)
    state['routes_done'] = sorted(routes_done)
    state['times_done'] = sorted(times_done)
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = str(STATE_P) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, STATE_P)


def robots_allows():
    b = fetch(BASE + 'robots.txt', tries=2)
    if b is None:
        return True
    txt = b.decode('utf-8', 'replace')
    save_raw('robots.txt', b)
    block_all = False
    in_star = False
    for line in txt.splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith('user-agent:'):
            in_star = line.split(':', 1)[1].strip() == '*'
        elif in_star and low.startswith('disallow:'):
            path = line.split(':', 1)[1].strip()
            if path == '/':
                block_all = True
    return not block_all


STOP_RE = re.compile(
    r'<div class="pQues2"><span>(\d+)</span>\s*(.*?)</div>\s*'
    r'<div class="pTime2">([\d:]+)</div>\s*'
    r'<div class="pHow2">(.*?)</div>', re.S)


def parse_route_page(h):
    stops = [{'seq': int(s), 'name': html.unescape(n.strip()), 't': t,
              'type': html.unescape(ty.strip())}
             for s, n, t, ty in STOP_RE.findall(h)]
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S)
    title = html.unescape(re.sub(r'<[^>]+>', '', m.group(1)).strip()) if m else ''
    rf = re.search(r"routes_from='(\d+)'", h)
    return title, stops, (rf.group(1) if rf else None)


def record_route(a, l, rid, url_route, title, stops):
    append_jsonl(OUT / 'parsed' / f'routes-agency-{a}.jsonl',
                 {'agency': a, 'line': l, 'route': rid, 'url_route': url_route,
                  'title': title, 'stops': stops})
    state['route_meta'][rid] = {'a': a, 'l': l}


def crawl_route(a, l, r):
    if r in routes_done:
        return True
    if out_of_time():
        return False
    h = get(f'?pts&agency={a}&line={l}&route={r}')
    routes_done.add(r)
    if h is None:
        return True
    save_raw(f'route-{r}.html', h.encode())
    title, stops, rf = parse_route_page(h)
    record_route(a, l, rf or r, r, title, stops)
    return True


def crawl_line(a, l):
    key = f'{a}:{l}'
    if key in lines_done:
        return True
    if out_of_time():
        return False
    h = get(f'?pts&agency={a}&line={l}')
    if h is None:
        lines_done.add(key)
        return True
    save_raw(f'line-{a}-{l}.html', h.encode())
    title, stops, rf = parse_route_page(h)
    if rf and rf not in routes_done:
        routes_done.add(rf)
        record_route(a, l, rf, None, title, stops)
    for r in sorted(set(re.findall(r'[?&](?:amp;)?route=(\d+)', h)), key=int):
        if not crawl_route(a, l, r):
            return False
    lines_done.add(key)
    save_state()
    return True


def crawl_times(rid):
    for d in range(1, 8):
        key = f'{rid}:{d}'
        if key in times_done:
            continue
        if out_of_time():
            return False
        body = urllib.parse.urlencode(
            {'get_info': '', 'day': d, 'times': '', 'station_from': '',
             'station_to': '', 'routes_from': rid}).encode()
        b = fetch(BASE + 'ajax_f3.php', data=body)
        times_done.add(key)
        if b is None:
            continue
        save_raw(f'times-{rid}-d{d}.txt', b)
        deps = []
        for row in b.decode('utf-8', 'replace').split(';!;'):
            if not row.strip():
                continue
            f = row.split(';*;')
            if len(f) >= 2:
                deps.append({'rid': f[0], 'label': f[1],
                             'exit': f[4] if len(f) > 4 else None})
        append_jsonl(OUT / 'parsed' / 'times.jsonl',
                     {'route': rid, 'day': d, 'departures': deps})
    return True


def discover_agencies():
    h = get('?pts')
    if h is None:
        sys.exit('לא ניתן להביא את רשימת החברות — עוצר')
    save_raw('pts.html', h.encode())
    ags = sorted(set(re.findall(r'[?&](?:amp;)?agency=(\d+)', h)), key=int)
    names = {}
    for m in re.finditer(r'agency=(\d+)[^>]*>(?:<font[^>]*>)?([^<]{1,60})<', h):
        names.setdefault(m.group(1), m.group(2).strip())
    state['agencies'] = {a: {'name': html.unescape(names.get(a, '')), 'lines': None}
                         for a in ags}
    save_state()
    print(f'נמצאו {len(ags)} חברות', flush=True)


def discover_lines(a, meta):
    seen_pages = set()
    queue = [f'?pts&agency={a}']
    lines = set()
    while queue and len(seen_pages) < 200:
        u = queue.pop(0)
        if u in seen_pages:
            continue
        seen_pages.add(u)
        h = get(u)
        if h is None:
            continue
        save_raw(f'agency-{a}-p{len(seen_pages)}.html', h.encode())
        lines |= set(re.findall(r'[?&](?:amp;)?line=(\d+)', h))
        for href in re.findall(r'href="([^"]*\?pts[^"]*)"', h):
            q = '?' + href.split('?', 1)[1] if '?' in href else ''
            q = html.unescape(q)
            if q and f'agency={a}' in q and 'line=' not in q and q not in seen_pages:
                queue.append(q)
    meta['lines'] = sorted(lines, key=int)
    save_state()
    print(f'חברה {a} ({meta["name"]}): {len(lines)} קווים', flush=True)


def main():
    print(f'מתחיל סריקה. תקציב זמן: {MAX_MIN:.0f} דקות. השהיה: {DELAY}s בין בקשות.', flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if not robots_allows():
        sys.exit('robots.txt של האתר אוסר סריקה גורפת — עוצר מטעמי נימוס')

    if not state['agencies']:
        discover_agencies()

    # שלב 1: מבנה — קווים, מסלולים ותחנות (קודם, כדי שתמונת הרשת תושלם מוקדם)
    for a, meta in state['agencies'].items():
        if out_of_time():
            break
        if meta['lines'] is None:
            discover_lines(a, meta)
        for l in meta['lines']:
            if not crawl_line(a, l):
                break

    # שלב 2: לוחות זמנים לכל מסלול שנאסף
    for rid in sorted(state['route_meta'], key=int):
        if not crawl_times(rid):
            break

    save_state()
    n_ag = len(state['agencies'])
    print(f'סיכום: {n_ag} חברות | {len(lines_done)} דפי קו | '
          f'{len(routes_done)} מסלולים | {len(times_done)} שאילתות זמנים',
          flush=True)
    done_struct = all(m['lines'] is not None for m in state['agencies'].values()) and \
        all(f'{a}:{l}' in lines_done
            for a, m in state['agencies'].items() for l in m['lines'] or [])
    done_times = all(f'{r}:{d}' in times_done
                     for r in state['route_meta'] for d in range(1, 8))
    print('הסריקה הושלמה במלואה!' if done_struct and done_times
          else 'נותרה עבודה — הרץ שוב להמשך מה-checkpoint.', flush=True)


if __name__ == '__main__':
    main()
