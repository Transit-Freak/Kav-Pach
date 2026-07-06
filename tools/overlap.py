# -*- coding: utf-8 -*-
# חפיפת מסלולים בין קווים: לכל קו (מקט) — אילו קווים אחרים עוצרים באותן תחנות.
# קו בזבזני שרוב תחנותיו מכוסות ע"י קו אחר = מועמד חזק לאיחוד/ביטול (קו פח);
# ההפך נכון לקו שאין לו שום חלופה.
# קלט (סביבה): TRIPS, STOP_TIMES, ROUTES; פלט: OUT (kavpach-overlap.json)
import csv, os, json, datetime
from collections import defaultdict

TRIPS=os.environ.get('TRIPS','trips.txt')
STOP_TIMES=os.environ.get('STOP_TIMES','stop_times.txt')
ROUTES=os.environ.get('ROUTES','routes.txt')
OUT=os.environ.get('OUT','kavpach-overlap.json')

MIN_SHARED=int(os.environ.get('MIN_SHARED','8'))   # לפחות כך תחנות משותפות
MIN_PCT=float(os.environ.get('MIN_PCT','0.5'))      # מול הקו הקצר מבין השניים
TOP=5            # כמה קווים חופפים שומרים לכל קו
HUB_CAP=120      # תחנה שמשרתת יותר מכך קווים (מסוף ענק) לא מלמדת על חפיפת מסלול

# ---- קווים: מקט, מספר, יעד ----
rroutes={}
for r in csv.DictReader(open(ROUTES,encoding='utf-8-sig')):
    if r.get('route_type','3')!='3': continue
    mk=r.get('route_desc','').split('-')[0].strip().lstrip('0')
    if not mk: continue
    rroutes[r['route_id']]={'mk':mk,'num':r.get('route_short_name',''),'long':r.get('route_long_name','')}
print('route_ids (אוטובוס):',len(rroutes))

# ---- נסיעה נציגה לכל route_id ----
rep={}
for r in csv.DictReader(open(TRIPS,encoding='utf-8-sig')):
    rid=r['route_id']
    if rid in rroutes and rid not in rep: rep[rid]=r['trip_id']
rep_trips={t:rid for rid,t in rep.items()}
print('נציגים:',len(rep))

# ---- קבוצת התחנות של כל נציג ----
stops_of=defaultdict(set)
with open(STOP_TIMES,encoding='utf-8-sig') as f:
    rd=csv.reader(f); hdr=next(rd); hi={h:i for i,h in enumerate(hdr)}
    TI,SI=hi['trip_id'],hi['stop_id']
    for r in rd:
        rid=rep_trips.get(r[TI])
        if rid: stops_of[rid].add(r[SI])

# לכל מקט — קבוצת התחנות של החלופה הגדולה ביותר (המסלול הראשי) + פרטי תצוגה
makat_stops={}; makat_info={}
for rid,ss in stops_of.items():
    info=rroutes[rid]; mk=info['mk']
    if mk not in makat_stops or len(ss)>len(makat_stops[mk]):
        makat_stops[mk]=ss
        makat_info[mk]={'num':info['num'],'long':info['long'][:60]}
print('מקטים עם מסלול:',len(makat_stops))

# ---- אינדקס הפוך + ספירת תחנות משותפות לכל זוג ----
by_stop=defaultdict(list)
for mk,ss in makat_stops.items():
    for s in ss: by_stop[s].append(mk)
pair=defaultdict(int)
skipped_hubs=0
for s,mks in by_stop.items():
    if len(mks)>HUB_CAP: skipped_hubs+=1; continue
    mks=sorted(mks)
    for i in range(len(mks)):
        for j in range(i+1,len(mks)):
            pair[(mks[i],mks[j])]+=1
print('זוגות עם תחנה משותפת:',len(pair),'| מסופי-ענק שדולגו:',skipped_hubs)

# ---- בחירת החפיפות המשמעותיות ----
cand=defaultdict(list)
for (a,b),n in pair.items():
    if n<MIN_SHARED: continue
    pct=n/min(len(makat_stops[a]),len(makat_stops[b]))
    if pct<MIN_PCT: continue
    cand[a].append((b,pct,n)); cand[b].append((a,pct,n))
out={}
for mk,lst in cand.items():
    lst.sort(key=lambda x:-x[1])
    out[mk]=[[b,makat_info[b]['num'],makat_info[b]['long'],round(p*100),n] for b,p,n in lst[:TOP]]
print('קווים עם חפיפה משמעותית:',len(out))

json.dump({'gen':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'),'lines':out},
          open(OUT,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
print('נכתב',OUT,'(%.0fKB)'%(os.path.getsize(OUT)/1024))
