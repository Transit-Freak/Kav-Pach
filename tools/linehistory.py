# -*- coding: utf-8 -*-
# "הקו בזמן" — תיעוד היסטוריית מסלולים ותחנות מתוך השוואת GTFS יומית.
#
# העיקרון: לכל וריאנט קו (route_desc = מק"ט-כיוון-חלופה, המפתח היציב ב-GTFS
# הישראלי) נשמרת הגאומטריה המלאה של המסלול (polyline מקודד, בלי דילול — כדי
# שגם תיקון-שרטוט שלא משנה אף תחנה ייראה על המפה) ורצף התחנות. בכל ריצה
# משווים למצב הקודם ורושמים שינויים בקובצי חודש (בקשת המשתמש: קובץ לכל חודש).
#
# קלט: STOPS, STOP_TIMES, TRIPS, ROUTES, SHAPES, AGENCY (קובצי GTFS), MAIN
#       (data-main.json — סוג קו), OUTDIR (ברירת מחדל line-history/data)
# פלט תחת OUTDIR:
#   lines.json                אינדקס וריאנטים (לחיפוש)
#   lines/<rd>.json           גרסאות מלאות לכל וריאנט (גאומטריה+תחנות)
#   changes/YYYY-MM.json      שינויי מסלול/רצף של החודש
#   changes/stops-YYYY-MM.json שינויי תחנות של החודש (בוטלה/חדשה/שם/מיקום)
#   stops-hist.json           קורות-חיים מצטברים לכל תחנה
#   state-routes.json, stops-state.json  מצב פנימי להשוואה הבאה
import csv, json, math, os, re, sys, datetime
from collections import defaultdict

STOPS=os.environ.get('STOPS','stops.txt')
STOP_TIMES=os.environ.get('STOP_TIMES','stop_times.txt')
TRIPS=os.environ.get('TRIPS','trips.txt')
ROUTES=os.environ.get('ROUTES','routes.txt')
SHAPES=os.environ.get('SHAPES','shapes.txt')
AGENCY=os.environ.get('AGENCY','agency.txt')
MAIN=os.environ.get('MAIN','data-main.json')
OUTDIR=os.environ.get('OUTDIR','line-history/data')
TODAY=os.environ.get('TODAY') or datetime.date.today().isoformat()
MOVE_M=25          # הזזת תחנה נספרת מעל מרחק זה
MAX_LINES_LIST=12  # כמה קווים לשמור ברשומת תחנה שבוטלה

def city(d):
    m=re.search(r'עיר:\s*(.*?)\s*רציף:', d or ''); return m.group(1).strip() if m else ''

# ---- polyline encoding (precision 5) — קומפקטי פי ~10 מרשימת קואורדינטות ----
def enc_num(v,out):
    v=int(round(v)); v=~(v<<1) if v<0 else v<<1
    while v>=0x20:
        out.append(chr((0x20|(v&0x1f))+63)); v>>=5
    out.append(chr(v+63))
def encode_shape(pts):
    out=[]; pla=plo=0
    for la,lo in pts:
        ila,ilo=int(round(la*1e5)),int(round(lo*1e5))
        enc_num(ila-pla,out); enc_num(ilo-plo,out)
        pla,plo=ila,ilo
    return ''.join(out)

def fsafe(rd):  # route_desc בטוח לשם קובץ ("10390-2-#" -> "10390-2-H")
    return rd.replace('#','H').replace('/','_')

# ---- agencies ----
agencies={}
if os.path.exists(AGENCY):
    for r in csv.DictReader(open(AGENCY,encoding='utf-8-sig')):
        agencies[r.get('agency_id','')]=r.get('agency_name','')

# ---- סוג קו מהקובץ המצומצם ----
linetype={}
if MAIN and os.path.exists(MAIN):
    for r in json.load(open(MAIN,encoding='utf-8')):
        mk=str(r[0]).strip().lstrip('0')
        if mk: linetype[mk]=str(r[6]).strip()

# ---- routes: route_id -> (desc, line, dest, agency) ----
routes={}
for r in csv.DictReader(open(ROUTES,encoding='utf-8-sig')):
    if r.get('route_type','3')!='3': continue   # אוטובוסים בלבד
    rd=(r.get('route_desc') or '').strip()
    if not rd: continue
    routes[r['route_id']]={'rd':rd,'line':r.get('route_short_name',''),
                           'long':r.get('route_long_name',''),'ag':r.get('agency_id','')}
print('וריאנטים (route_desc):',len({v['rd'] for v in routes.values()}))

# ---- trips: נציג לכל route_id ----
rep={}          # route_id -> (trip_id, shape_id)
for r in csv.DictReader(open(TRIPS,encoding='utf-8-sig')):
    rid=r['route_id']
    if rid in routes and rid not in rep and r.get('shape_id'):
        rep[rid]=(r['trip_id'],r['shape_id'])
rep_trips={t:(rid,sh) for rid,(t,sh) in rep.items()}
print('נסיעות נציג:',len(rep))

# ---- stops ----
stops={}
rows=list(csv.reader(open(STOPS,encoding='utf-8-sig')))
ix={h:i for i,h in enumerate(rows[0])}
SN,SD,SC,LA,LO,SI=ix['stop_name'],ix['stop_desc'],ix['stop_code'],ix['stop_lat'],ix['stop_lon'],ix['stop_id']
LT=ix.get('location_type')
for r in rows[1:]:
    if len(r)<=SD: continue
    if LT is not None and len(r)>LT and r[LT] not in ('','0'): continue
    try: stops[r[SI]]={'c':r[SC],'n':' '.join(r[SN].split()),'t':city(r[SD]),
                       'la':round(float(r[LA]),5),'lo':round(float(r[LO]),5)}
    except: pass
print('תחנות:',len(stops))

# ---- stop_times: רצף תחנות לנציגים + אילו קווים עוצרים בכל תחנה ----
seqs=defaultdict(list)      # trip_id -> [(seq, stop_id)]
stop_lines=defaultdict(set) # stop_code -> קווים
with open(STOP_TIMES,encoding='utf-8-sig') as f:
    rd_=csv.reader(f); hdr=next(rd_); hi={h:i for i,h in enumerate(hdr)}
    TI,SIx,SQ=hi['trip_id'],hi['stop_id'],hi['stop_sequence']
    for r in rd_:
        t=r[TI]
        if t in rep_trips:
            try: seqs[t].append((int(r[SQ]),r[SIx]))
            except: pass
        s=stops.get(r[SIx])
        if s is not None:
            rid=None  # ספירת קווים לתחנה — רק לנציגים (חיסכון: מייצג את הקו)
            if t in rep_trips: rid=rep_trips[t][0]
            if rid: stop_lines[s['c']].add(routes[rid]['line'])
print('רצפים שנקראו:',len(seqs))

# ---- shapes: רק של הנציגים, בדיוק מלא ----
need={sh for _,sh in rep.values()}
shp_pts=defaultdict(list)
with open(SHAPES,encoding='utf-8-sig') as f:
    rd_=csv.reader(f); hdr=next(rd_); hi={h:i for i,h in enumerate(hdr)}
    SH,SLA,SLO,SSQ=hi['shape_id'],hi['shape_pt_lat'],hi['shape_pt_lon'],hi['shape_pt_sequence']
    for r in rd_:
        if r[SH] in need:
            try: shp_pts[r[SH]].append((int(r[SSQ]),round(float(r[SLA]),5),round(float(r[SLO]),5)))
            except: pass
shapes={sh:[(la,lo) for _,la,lo in sorted(v)] for sh,v in shp_pts.items()}
print('מסלולים שנקראו:',len(shapes))

# ---- המצב הנוכחי לכל וריאנט ----
import hashlib
def h12(s): return hashlib.sha1(s.encode()).hexdigest()[:12]
cur={}
for rid,(t,sh) in rep.items():
    info=routes[rid]
    pts=shapes.get(sh)
    if not pts or len(pts)<2: continue
    sq=[sid for _,sid in sorted(seqs.get(t,[]))]
    codes=[stops[s]['c'] for s in sq if s in stops]
    if len(codes)<2: continue
    mk=info['rd'].split('-')[0].lstrip('0')
    cur[info['rd']]={'line':info['line'],'long':info['long'],'op':agencies.get(info['ag'],''),
                     'ty':linetype.get(mk,''),'pts':pts,'codes':codes,
                     'stopinfo':[[stops[s]['c'],stops[s]['n'],stops[s]['la'],stops[s]['lo']] for s in sq if s in stops],
                     'sh_h':h12(json.dumps(pts)),'st_h':h12('|'.join(codes))}
print('וריאנטים תקינים:',len(cur))

# ---- טעינת מצב קודם ----
os.makedirs(f'{OUTDIR}/lines',exist_ok=True)
os.makedirs(f'{OUTDIR}/changes',exist_ok=True)
def jload(p,dflt):
    try: return json.load(open(p,encoding='utf-8'))
    except Exception: return dflt
prev=jload(f'{OUTDIR}/state-routes.json',{})
prev_stops=jload(f'{OUTDIR}/stops-state.json',{})
first_run=not prev

def dist_m(a_la,a_lo,b_la,b_lo):
    cl=math.cos(math.radians((a_la+b_la)/2))
    return math.hypot((a_la-b_la)*110540,(a_lo-b_lo)*111320*cl)

month=TODAY[:7]
chpath=f'{OUTDIR}/changes/{month}.json'
chm=jload(chpath,{'month':month,'changes':[]})
chm['changes']=[c for c in chm['changes'] if c.get('d')!=TODAY]  # ריצה חוזרת באותו יום

def write_line_version(rdesc,c,kind,note='',extra=None):
    p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    lf=jload(p,{'rd':rdesc,'line':c['line'],'dest':c['long'],'op':c['op'],'ty':c['ty'],'versions':[]})
    lf['line'],lf['dest'],lf['op'],lf['ty']=c['line'],c['long'],c['op'],c['ty']
    lf['versions']=[v for v in lf['versions'] if v.get('d')!=TODAY]
    v={'d':TODAY,'k':kind,'shp':encode_shape(c['pts']),'stops':c['stopinfo']}
    if note: v['note']=note
    if extra: v.update(extra)
    lf['versions'].append(v)
    json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))

n_new=n_geo=n_stops=n_both=n_gone=0
for rdesc,c in cur.items():
    pv=prev.get(rdesc)
    if pv is None:
        write_line_version(rdesc,c,'baseline' if first_run else 'new',
                           '' if first_run else 'וריאנט חדש ברישום')
        if not first_run:
            chm['changes'].append({'d':TODAY,'rd':rdesc,'line':c['line'],'op':c['op'],'k':'new'})
        n_new+=1
        continue
    geo=pv['sh_h']!=c['sh_h']; stp=pv['st_h']!=c['st_h']
    if not geo and not stp: continue
    old_codes=pv['codes']; add=[x for x in c['codes'] if x not in old_codes]
    rem=[x for x in old_codes if x not in c['codes']]
    name={x[0]:x[1] for x in c['stopinfo']}
    oldname=lambda x:(prev_stops.get(x) or [x])[0]   # שם תחנה שירדה — מהמצב הקודם
    if geo and stp:
        kind='route'; n_both+=1
    elif geo:
        kind='redraw'; n_geo+=1   # גאומטריה בלבד — תיקון שרטוט/קידוד
    else:
        kind='stops'; n_stops+=1
    ch={'d':TODAY,'rd':rdesc,'line':c['line'],'op':c['op'],'k':kind}
    if add: ch['add']=[name.get(x,x) for x in add][:15]
    if rem: ch['rem']=[oldname(x) for x in rem][:15]
    chm['changes'].append(ch)
    write_line_version(rdesc,c,kind,extra={'add':ch.get('add'),'rem':ch.get('rem')} if (add or rem) else None)
gone=[rdesc for rdesc in prev if rdesc not in cur]
for rdesc in gone:
    if first_run: break
    chm['changes'].append({'d':TODAY,'rd':rdesc,'line':prev[rdesc].get('line',''),'k':'removed'})
    n_gone+=1
print(f'קווים: חדשים {n_new} | שרטוט-בלבד {n_geo} | תחנות-בלבד {n_stops} | שניהם {n_both} | הוסרו {n_gone}')

# ---- שינויי תחנות (רישום ארצי) ----
cur_stops={}
for s in stops.values():
    lns=sorted(stop_lines.get(s['c'],()))[:MAX_LINES_LIST]
    cur_stops[s['c']]=[s['n'],s['la'],s['lo'],s['t'],lns]
spath=f'{OUTDIR}/changes/stops-{month}.json'
stm=jload(spath,{'month':month,'changes':[]})
stm['changes']=[c for c in stm['changes'] if c.get('d')!=TODAY]
shist=jload(f'{OUTDIR}/stops-hist.json',{})
def sev(code,ev):
    stm['changes'].append({'d':TODAY,'c':code,**ev})
    shist.setdefault(code,[])
    shist[code]=[e for e in shist[code] if not (e['d']==TODAY and e['k']==ev['k'])]
    shist[code].append({'d':TODAY,**ev})
ns=nd=nr=nm=0
if not first_run:
    for c0,v in cur_stops.items():
        pv=prev_stops.get(c0)
        if pv is None:
            sev(c0,{'k':'new','n':v[0],'t':v[3],'la':v[1],'lo':v[2]}); ns+=1; continue
        if pv[0]!=v[0]:
            sev(c0,{'k':'renamed','on':pv[0],'nn':v[0],'t':v[3],'la':v[1],'lo':v[2]}); nr+=1
        d=dist_m(pv[1],pv[2],v[1],v[2])
        if d>MOVE_M:
            sev(c0,{'k':'moved','n':v[0],'t':v[3],'dist':round(d),'ola':pv[1],'olo':pv[2],'la':v[1],'lo':v[2]}); nm+=1
    for c0,pv in prev_stops.items():
        if c0 not in cur_stops:
            sev(c0,{'k':'del','n':pv[0],'t':pv[3],'la':pv[1],'lo':pv[2],'lines':pv[4]}); nd+=1
print(f'תחנות: חדשות {ns} | בוטלו {nd} | שם {nr} | מיקום {nm}')

# ---- אינדקס + מצב ----
idx=[]
for rdesc,c in cur.items():
    lfp=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    nv=len(jload(lfp,{}).get('versions',[]))
    idx.append({'rd':rdesc,'line':c['line'],'dest':c['long'][:80],'op':c['op'],'ty':c['ty'],'v':nv})
idx.sort(key=lambda x:(x['line'],x['rd']))
json.dump({'gen':TODAY,'first':first_run,'lines':idx},
          open(f'{OUTDIR}/lines.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(chm,open(chpath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(stm,open(spath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(shist,open(f'{OUTDIR}/stops-hist.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump({rdesc:{'sh_h':c['sh_h'],'st_h':c['st_h'],'codes':c['codes'],'line':c['line']} for rdesc,c in cur.items()},
          open(f'{OUTDIR}/state-routes.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(cur_stops,open(f'{OUTDIR}/stops-state.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
mons=sorted({f[8:15] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')})
json.dump({'months':sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$',f)},reverse=True),
           'stopMonths':sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')},reverse=True)},
          open(f'{OUTDIR}/months.json','w',encoding='utf-8'),ensure_ascii=False)
print('נכתב הכול תחת',OUTDIR)
