#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""קטעי מסילה בין תחנות עוקבות — למפת הנסיעה במדד אמינות הרכבת.

ב-GTFS של רכבת ישראל אין צורות מסלול (שלמה 04.09: "בקובץ GTFS אין מסלול
רכבת, רק תחנות"), לכן המסילה נלקחת מרשת המסילות של OSM: כל way עם
railway=rail בישראל (בלי מסילות שירות: siding/yard/spur), נבנה גרף לפי
מזהי הצמתים של OSM, כל תחנה מוצמדת לצומת הקרוב אליה, ולכל זוג תחנות עוקבות
שמופיע בקבצי הימים מחושב המסלול הקצר ביותר על המסילה (Dijkstra).

תוצר: rail/data/segments.json — {"segments": {"קוד-קוד": פוליליין מקודד}}.
זוגות שכבר בקובץ נשמרים; הריצה שולפת מ-OSM רק כשיש זוגות חסרים. מסלול
שאורכו יותר מפי 2.5 מהמרחק האווירי נפסל (הצמדה שגויה) ונשאר קו מקווקו.
"""
import datetime
import heapq
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_geo import enc_polyline  # noqa: E402

OUTDIR = os.environ.get('OUTDIR', 'rail/data')
OUT = f'{OUTDIR}/segments.json'
STATIONS = f'{OUTDIR}/stations.json'
FORCE = os.environ.get('FORCE') == '1'
MIRRORS = [
    'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://maps.mail.ru/osm/tools/overpass/api/interpreter',
]
BBOX = '29.4,34.2,33.4,35.95'          # ישראל
SNAP_M = 400                           # תחנה רחוקה מזה מהמסילה — לא מוצמדת
MAX_RATIO = 2.5                        # מסלול/אווירי — מעל זה ההצמדה שגויה


def jload(p, d):
    try:
        return json.load(open(p, encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return d


def hav(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def wanted_pairs():
    """זוגות תחנות עוקבות מכל קבצי הימים (מפתח 'a-b' עם a<b כמחרוזות)."""
    pairs = set()
    ddir = f'{OUTDIR}/days'
    if not os.path.isdir(ddir):
        return pairs
    for fn in os.listdir(ddir):
        if not fn.endswith('.json'):
            continue
        day = jload(f'{ddir}/{fn}', {})
        for r in day.get('rides', []):
            s = r.get('s', [])
            for i in range(1, len(s)):
                a, b = s[i - 1][0], s[i][0]
                if a is None or b is None or a == b:
                    continue
                pairs.add(f'{a}-{b}' if str(a) < str(b) else f'{b}-{a}')
    return pairs


def fetch_rail():
    q = ('[out:json][timeout:300];'
         f'way["railway"="rail"]["service"!~"^(siding|yard|spur)$"]({BBOX});'
         'out geom;')
    data = urllib.parse.urlencode({'data': q}).encode()
    for ep in MIRRORS:
        try:
            req = urllib.request.Request(ep, data=data, headers={'User-Agent': 'kav-bochan-rail/1.0'})
            with urllib.request.urlopen(req, timeout=350) as r:
                j = json.load(r)
            ways = [e for e in j.get('elements', []) if e.get('type') == 'way' and e.get('geometry')]
            print(f'OSM: {len(ways)} קטעי מסילה מ-{ep}', flush=True)
            return ways
        except Exception as ex:  # noqa: BLE001
            print(f'  {ep} נכשל: {ex!r}', flush=True)
            time.sleep(10)
    raise SystemExit('Overpass נכשל בכל המראות')


def build_graph(ways):
    """גרף: מזהה צומת OSM → [(שכן, אורך במטרים)]; ומיקומי הצמתים."""
    adj = {}
    pos = {}
    for w in ways:
        nodes = w.get('nodes') or []
        geom = w.get('geometry') or []
        if len(nodes) != len(geom):
            continue
        for i, nid in enumerate(nodes):
            pos[nid] = (geom[i]['lat'], geom[i]['lon'])
        for i in range(1, len(nodes)):
            a, b = nodes[i - 1], nodes[i]
            d = hav(*pos[a], *pos[b])
            adj.setdefault(a, []).append((b, d))
            adj.setdefault(b, []).append((a, d))
    return adj, pos


def main_component(adj):
    """צמתי הרכיב הקשיר הגדול ביותר — רשת המסילות הראשית. תחנה שהוצמדה לשבר
    מסילה מבודד (קטע שירות בתחנה) לא מוצאת מסלול לשכנותיה — קרה באשקלון."""
    seen = set()
    best = set()
    for s in adj:
        if s in seen:
            continue
        comp = {s}
        stack = [s]
        while stack:
            u = stack.pop()
            for v, _ in adj.get(u, ()):
                if v not in comp:
                    comp.add(v)
                    stack.append(v)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    return best


def snap(st, pos, allowed=None):
    """תחנה → הצומת הקרוב ביותר ברשת הראשית (סריקה בתיבה של ~0.01 מעלה)."""
    lat, lon = st[1], st[2]
    best, bd = None, SNAP_M
    for nid, (la, lo) in pos.items():
        if abs(la - lat) > 0.006 or abs(lo - lon) > 0.007:
            continue
        if allowed is not None and nid not in allowed:
            continue
        d = hav(lat, lon, la, lo)
        if d < bd:
            best, bd = nid, d
    return best


def dijkstra(adj, pos, src, dst, limit_m):
    dist = {src: 0.0}
    prev = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, 1e18) or d > limit_m:
            continue
        for v, w in adj.get(u, ()):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None, None
    path = [dst]
    while path[-1] != src:
        path.append(prev[path[-1]])
    path.reverse()
    return [pos[n] for n in path], dist[dst]


def main():
    cur = jload(OUT, {})
    segs = cur.get('segments', {})
    stations = jload(STATIONS, {})
    pairs = wanted_pairs()
    missing = sorted(p for p in pairs if p not in segs and p not in cur.get('failed', {}))
    if FORCE:
        missing = sorted(pairs)
    print(f'זוגות תחנות עוקבות: {len(pairs)} · בקובץ: {len(segs)} · לחישוב: {len(missing)}')
    if not missing:
        return
    ways = fetch_rail()
    adj, pos = build_graph(ways)
    comp = main_component(adj)
    print(f'גרף: {len(pos)} צמתים · ברשת הראשית: {len(comp)}')
    snapped = {}
    for code, st in stations.items():
        if st[1] is None:
            continue
        n = snap(st, pos, comp)
        if n is None:
            print(f'  תחנה {code} {st[0]} — אין מסילה עד {SNAP_M} מ׳')
        snapped[code] = n
    failed = dict(cur.get('failed', {}))
    n_ok = 0
    for key in missing:
        a, b = key.split('-', 1)
        na, nb = snapped.get(a), snapped.get(b)
        if not na or not nb:
            failed[key] = 'אין הצמדה'
            continue
        sa, sb = stations[a], stations[b]
        air = hav(sa[1], sa[2], sb[1], sb[2])
        path, length = dijkstra(adj, pos, na, nb, air * MAX_RATIO + 3000)
        if not path:
            failed[key] = 'אין מסלול'
            continue
        if length > air * MAX_RATIO + 1500:
            failed[key] = f'ארוך מדי ({length / 1000:.1f} ק״מ מול {air / 1000:.1f} אווירי)'
            continue
        segs[key] = enc_polyline(path)
        n_ok += 1
    os.makedirs(OUTDIR, exist_ok=True)
    json.dump({'updated': datetime.date.today().isoformat(), 'source': 'OpenStreetMap railway=rail',
               'segments': segs, 'failed': failed},
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f'נשמרו {len(segs)} קטעים ({n_ok} חדשים) · נכשלו: {len(failed)}')
    for k, v in list(failed.items())[:15]:
        a, b = k.split('-', 1)
        print(f'  {stations.get(a, ["?"])[0]} ↔ {stations.get(b, ["?"])[0]}: {v}')


if __name__ == '__main__':
    main()
