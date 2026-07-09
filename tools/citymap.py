# -*- coding: utf-8 -*-
# חילוץ קווים עירוניים לכל עיר מה-GTFS — קלט למחולל מפות הרשת (citymap-render.py).
# קו עירוני (לא תלמידים) משויך לכל עיר שבה יש לו מספיק תחנות בפועל (לפי שדה
# "עיר:" ב-stop_desc) — כך קו שחוצה גבול עיר (חולון-בת ים) מופיע בשתי הערים,
# וגם ערים שאין להן קו "משלהן" אבל קווים עירוניים עוברים בהן מקבלות מפה.
# פלט: OUTDIR/<עיר>.json לכל עיר עם מספיק קווים + OUTDIR/cities.json (רשימה).
import csv, json, os
from collections import defaultdict

MAIN=os.environ.get('MAIN','data-main.json')
OUTDIR=os.environ.get('OUTDIR','citydata')
MIN_LINES=int(os.environ.get('MIN_LINES','2'))
MIN_STOPS=8   # קו עם פחות תחנות מזה לא תורם למפה
CITY_MIN_STOPS=4   # קו נחשב שייך לעיר אם יש לו לפחות כך תחנות בתוכה

rows=json.load(open(MAIN,encoding='utf-8'))
mk2cities={}
for r in rows:
    if str(r[6]).strip()=='עירוני' and 'תלמיד' not in str(r[7]):
        cs={str(r[3]).strip(),str(r[4]).strip()}-{''}
        if cs: mk2cities[str(r[0]).strip().lstrip('0')]=cs
print('מק"טים עירוניים:',len(mk2cities))

def desc_city(desc):
    # stop_desc: " רחוב: X עיר: Y רציף: ... קומה: "
    i=desc.find('עיר:')
    if i<0: return ''
    return desc[i+4:].split('רציף:')[0].strip()

routes={}
for r in csv.DictReader(open('routes.txt',encoding='utf-8-sig')):
    mk=r.get('route_desc','').split('-')[0].strip().lstrip('0')
    if mk in mk2cities and r.get('route_type','3')=='3':
        routes[r['route_id']]={'mk':mk,'num':r.get('route_short_name',''),
                               'long':r.get('route_long_name',''),'cities':mk2cities[mk]}
print('חלופות (route_ids):',len(routes))

# נסיעה נציגה אחת לכל חלופה — כל הנסיעות של אותה חלופה חולקות רצף תחנות
trip_of={}; trip2rid={}
for r in csv.DictReader(open('trips.txt',encoding='utf-8-sig')):
    rid=r['route_id']
    if rid in routes and rid not in trip_of:
        trip_of[rid]=r['trip_id']; trip2rid[r['trip_id']]=rid

seqs=defaultdict(list)
for r in csv.DictReader(open('stop_times.txt',encoding='utf-8-sig')):
    t=r.get('trip_id')
    if t in trip2rid:
        seqs[t].append((int(r['stop_sequence']),r['stop_id']))

stops={}; stopcity={}
for r in csv.DictReader(open('stops.txt',encoding='utf-8-sig')):
    try:
        stops[r['stop_id']]=(r['stop_name'],r.get('stop_code',''),float(r['stop_lat']),float(r['stop_lon']))
        stopcity[r['stop_id']]=desc_city(r.get('stop_desc','') or '')
    except (ValueError,KeyError):
        pass

bycity=defaultdict(list)
for rid,t in trip_of.items():
    sq=sorted(seqs.get(t,[]))
    if len(sq)<MIN_STOPS: continue
    info=routes[rid]
    st=[[stops[sid][0],stops[sid][1],stops[sid][2],stops[sid][3]] for _,sid in sq if sid in stops]
    if len(st)<MIN_STOPS: continue
    # שיוך לפי היכן התחנות בפועל; אם ל-stop_desc אין ערים — נסיגה למוצא/יעד מהרישוי
    percity=defaultdict(int)
    for _,sid in sq:
        c=stopcity.get(sid,'')
        if c: percity[c]+=1
    cs={c for c,n in percity.items() if n>=CITY_MIN_STOPS} or set(info['cities'])
    for c in cs:
        bycity[c].append({'rid':rid,'mk':info['mk'],'num':info['num'],'long':info['long'],'stops':st})

os.makedirs(OUTDIR,exist_ok=True)
cities=[]
for c,ls in sorted(bycity.items()):
    nums=sorted(set(L['num'] for L in ls))
    if len(nums)<MIN_LINES: continue
    json.dump({'city':c,'lines':ls},open(os.path.join(OUTDIR,c+'.json'),'w',encoding='utf-8'),ensure_ascii=False)
    cities.append({'name':c,'lines':len(nums)})
json.dump(cities,open(os.path.join(OUTDIR,'cities.json'),'w',encoding='utf-8'),ensure_ascii=False)
print('ערים עם מפה:',len(cities))
for c in cities: print(f"  {c['name']} ({c['lines']} קווים)")
