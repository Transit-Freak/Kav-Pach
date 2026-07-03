# -*- coding: utf-8 -*-
# ניסוי "קווים שמדלגים": מזהה קווים שנוסעים ממש ליד תחנה פעילה — ולא עוצרים בה.
# האות החזק: "סנדוויץ'" — הקו עוצר בתחנה שלפני ובתחנה שאחרי, ומדלג רק על האמצעית.
# קלט (משתני סביבה): STOPS, STOP_TIMES, TRIPS, ROUTES, SHAPES, CLUSTER (ClusterToLine.csv, רשות)
# פלט: הדפסת ממצאים ליומן בלבד — שום דבר לא נכתב לאתר.
import csv, os, re, sys, math
from collections import defaultdict

STOPS=os.environ.get('STOPS','stops.txt')
STOP_TIMES=os.environ.get('STOP_TIMES','stop_times.txt')
TRIPS=os.environ.get('TRIPS','trips.txt')
ROUTES=os.environ.get('ROUTES','routes.txt')
SHAPES=os.environ.get('SHAPES','shapes.txt')
CLUSTER=os.environ.get('CLUSTER','')
CITIES=[c.strip() for c in os.environ.get('CITIES','ירושלים,תל אביב יפו').split(',')]

NEAR_M=25        # תחנה נחשבת "על המסלול" עד מרחק זה מהקו
ALONG_MIN=50     # הקו חייב ללוות את התחנה לאורך לפחות כך (מ׳) — מסנן חציית-צומת
SANDWICH_M=800   # תחנה עצורה לפני ואחרי בטווח זה לאורך המסלול
SANDWICH_MIN=120 # אבל לא צמוד מדי — עצירה 40 מ' משם היא אותו צומת (עמדה סמוכה), לא דילוג
TERMINAL_M=300   # מתעלמים מקצוות המסלול (אזורי מסוף)

def city(d):
    m=re.search(r'עיר:\s*(.*?)\s*רציף:', d or ''); return m.group(1).strip() if m else ''

# ---- תחנות ----
rows=list(csv.reader(open(STOPS,encoding='utf-8-sig')))
ix={h:i for i,h in enumerate(rows[0])}
SN,SD,SC,LA,LO,SI=ix['stop_name'],ix['stop_desc'],ix['stop_code'],ix['stop_lat'],ix['stop_lon'],ix['stop_id']
stops={}
for r in rows[1:]:
    if len(r)<=SD: continue
    c=city(r[SD])
    if c not in CITIES: continue
    try: stops[r[SI]]={'code':r[SC],'name':r[SN],'city':c,'la':float(r[LA]),'lo':float(r[LO])}
    except: pass
print('תחנות בערי הניסוי:',len(stops))

# ---- קווים ----
rroutes={}
for r in csv.DictReader(open(ROUTES,encoding='utf-8-sig')):
    rroutes[r['route_id']]={'num':r.get('route_short_name',''),'desc':r.get('route_desc',''),
                            'long':r.get('route_long_name',''),'agency':r.get('agency_id',''),
                            'rtype':r.get('route_type','3')}   # 3=אוטובוס, 0/2=רכבת/רק"ל
# סוג קו רשמי מהקובץ המצומצם (ClusterToLine): OfficeLineId -> (LineType, תת-סוג)
# LineType: עירוני/בינעירוני/אזורי; תת-הסוג (ClusterSubDesc) מסמן קווי תלמידים וכד'.
linetype={}; linesub={}
if CLUSTER and os.path.exists(CLUSTER):
    with open(CLUSTER,encoding='utf-8-sig',errors='replace') as f:
        rd=csv.DictReader(f)
        cols={k.strip():k for k in (rd.fieldnames or [])}
        kid=next((cols[k] for k in cols if 'officelineid' in k.lower().replace('_','')),None)
        kty=next((cols[k] for k in cols if 'linetype' in k.lower().replace('_','')),None)
        ksub=next((cols[k] for k in cols if 'subdesc' in k.lower().replace('_','')),None)
        print('עמודות הקובץ המצומצם:',rd.fieldnames)
        if kid and kty:
            for r in rd:
                linetype[r[kid].strip()]=r[kty].strip()
                if ksub: linesub[r[kid].strip()]=(r.get(ksub) or '').strip()
    print('סוגי קווים מהקובץ המצומצם:',len(linetype))
    print('ערכי LineType:',sorted(set(linetype.values())))
    print('ערכי תת-סוג:',sorted(set(linesub.values()))[:30])
else:
    print('אזהרה: אין קובץ ClusterToLine — סינון סוג-קו ייעשה לפי שם בלבד')
def _makat(rid):
    return rroutes.get(rid,{}).get('desc','').split('-')[0].strip()
def route_type(rid):
    return linetype.get(_makat(rid),'')
def route_sub(rid):
    return linesub.get(_makat(rid),'')

# ---- נסיעות: נציג אחד לכל (קו, מסלול) ----
trip2route={}; rep={}   # rep[(route_id,shape_id)] = trip_id נציג
for r in csv.DictReader(open(TRIPS,encoding='utf-8-sig')):
    trip2route[r['trip_id']]=r['route_id']
    key=(r['route_id'],r.get('shape_id',''))
    if r.get('shape_id') and key not in rep: rep[key]=r['trip_id']
rep_trips={t:k for k,t in rep.items()}
print('נסיעות-נציג (קו×מסלול):',len(rep))

# ---- עצירות: רצף התחנות של כל נציג + אילו קווים עוצרים בכל תחנת-עיר ----
served=defaultdict(list)          # trip נציג -> [(seq, stop_id)]
stop_lines=defaultdict(set)       # stop_id עירוני -> קווי אוטובוס שעוצרים בו
rail_stops=set()
with open(STOP_TIMES,encoding='utf-8-sig') as f:
    rd=csv.reader(f); hdr=next(rd); hi={h:i for i,h in enumerate(hdr)}
    TI,SIx,SQ=hi['trip_id'],hi['stop_id'],hi['stop_sequence']
    for r in rd:
        t=r[TI]
        if r[SIx] in stops:
            rt=trip2route.get(t)
            if rt and rroutes.get(rt,{}).get('rtype','3')=='3':
                stop_lines[r[SIx]].add(rroutes.get(rt,{}).get('num',''))
            elif rt: rail_stops.add(r[SIx])   # תחנת רכבת/רק"ל — לא מועמדת לדילוג-אוטובוס
        if t in rep_trips:
            try: served[t].append((int(r[SQ]),r[SIx]))
            except: pass
print('תחנות-עיר עם שירות:',len(stop_lines))

# ---- מסלולים (shapes): רק כאלה שנוגעים בערי הניסוי ----
BBOX=[(31.65,35.05,31.92,35.30),(31.98,34.72,32.18,34.90)]  # ירושלים, ת"א רבתי
def inbox(la,lo): return any(a<=la<=c and b<=lo<=d for a,b,c,d in BBOX)
need_shapes={k[1] for k in rep}
shapes={}
with open(SHAPES,encoding='utf-8-sig') as f:
    rd=csv.reader(f); hdr=next(rd); hi={h:i for i,h in enumerate(hdr)}
    SH,SLA,SLO,SSQ=hi['shape_id'],hi['shape_pt_lat'],hi['shape_pt_lon'],hi['shape_pt_sequence']
    cur=None; pts=[]; hit=False
    def flush():
        global cur,pts,hit
        if cur and hit and cur in need_shapes: shapes[cur]=[p[1:] for p in sorted(pts)]
        cur=None; pts=[]; hit=False
    for r in rd:
        sh=r[SH]
        if sh!=cur: flush(); cur=sh
        try:
            la,lo=float(r[SLA]),float(r[SLO]); pts.append((int(r[SSQ]),la,lo))
            if not hit and inbox(la,lo): hit=True
        except: pass
    flush()
print('מסלולים רלוונטיים:',len(shapes))

# ---- גאומטריה ----
def meters(pts,la0):
    cl=math.cos(math.radians(la0))
    return [((lo)*111320*cl,(la)*110540) for la,lo in pts]
def project(shape_m,arc,x,y):
    # המרחק המזערי מהקו + מיקום לאורך המסלול + צד (ימין=True)
    best=None
    for i in range(len(shape_m)-1):
        ax,ay=shape_m[i]; bx,by=shape_m[i+1]
        dx,dy=bx-ax,by-ay
        L2=dx*dx+dy*dy
        if L2==0: continue
        t=max(0.0,min(1.0,((x-ax)*dx+(y-ay)*dy)/L2))
        px,py=ax+t*dx,ay+t*dy
        d=math.hypot(x-px,y-py)
        if best is None or d<best[0]:
            cross=dx*(y-ay)-dy*(x-ax)   # שלילי = מימין לכיוון הנסיעה
            best=(d,arc[i]+t*math.sqrt(L2),cross<0,i)
    return best

# אינדקס-רשת לתחנות העיר — בודקים לכל מסלול רק תחנות שבקרבתו (ולא את כל העיר)
GRID=0.001
sgrid=defaultdict(list)
for sid,s in stops.items():
    sgrid[(int(s['la']/GRID),int(s['lo']/GRID))].append(sid)
def near_stop_ids(pts):
    out=set()
    for la,lo in pts:
        c=(int(la/GRID),int(lo/GRID))
        for dx in (-1,0,1):
            for dy in (-1,0,1): out.update(sgrid.get((c[0]+dx,c[1]+dy),()))
    return out

findings=[]
for (rid,sh),t in rep.items():
    if sh not in shapes: continue
    ty=route_type(rid)
    if ty and ty!='עירוני': continue   # בינעירוני/אזורי מדלגים בצדק — מחוץ לניסוי
    if 'תלמיד' in route_sub(rid): continue   # קווי תלמידים עוצרים רק איפה שצריך — לא דילוג
    if rroutes.get(rid,{}).get('rtype','3')!='3': continue   # בודקים רק קווי אוטובוס
    seq=[s for _,s in sorted(served.get(t,[]))]
    if len(seq)<5: continue
    pts=shapes[sh]
    la0=pts[0][0]
    m=meters(pts,la0)
    arc=[0.0]
    for i in range(len(m)-1): arc.append(arc[-1]+math.hypot(m[i+1][0]-m[i][0],m[i+1][1]-m[i][1]))
    total=arc[-1]
    cl=math.cos(math.radians(la0))
    def xy(s): return (s['lo']*111320*cl, s['la']*110540)
    # מיקומי התחנות העצורות לאורך המסלול
    served_arc=[]
    servedset=set(seq)
    for sid in seq:
        s=stops.get(sid)
        if not s: continue
        p=project(m,arc,*xy(s))
        if p and p[0]<=60: served_arc.append(p[1])
    served_arc.sort()
    if len(served_arc)<3: continue
    info=rroutes.get(rid,{})
    # מועמדות: רק תחנות שבסמוך למסלול (אינדקס רשת), פעילות, שאינן ברצף העצירה
    for sid in near_stop_ids(pts):
        s=stops[sid]
        if sid in servedset or not stop_lines.get(sid): continue
        x,y=xy(s)
        p=project(m,arc,x,y)
        if not p or p[0]>NEAR_M or not p[2]: continue       # רחוק / בצד שמאל
        pos=p[1]
        if pos<TERMINAL_M or pos>total-TERMINAL_M: continue # אזור מסוף
        import bisect
        j=bisect.bisect_left(served_arc,pos)
        before=pos-served_arc[j-1] if j>0 else 1e9
        after=served_arc[j]-pos if j<len(served_arc) else 1e9
        if before>SANDWICH_M or after>SANDWICH_M: continue  # אין סנדוויץ' — אולי מהיר
        if before<SANDWICH_MIN or after<SANDWICH_MIN: continue  # עמדה סמוכה באותו צומת
        if sid in rail_stops: continue                       # תחנת רק"ל/רכבת
        # ליווי לאורך הרחוב: כמה מטרים מהמסלול נשארים קרוב לתחנה
        near=sum(math.hypot(m[i+1][0]-m[i][0],m[i+1][1]-m[i][1]) for i in range(len(m)-1)
                 if min(math.hypot(m[i][0]-x,m[i][1]-y),math.hypot(m[i+1][0]-x,m[i+1][1]-y))<=45)
        if near<ALONG_MIN: continue
        others=stop_lines[sid]-{info.get('num','')}
        if not others: continue
        findings.append({'line':info.get('num',''),'agency':info.get('agency',''),'long':info.get('long',''),
                         'type':ty,'stop':s,'sid':sid,'dist':round(p[0]),'before':round(before),'after':round(after),
                         'others':sorted(others)[:8]})

# איחוד כפילויות (אותו קו ואותה תחנה בכמה חלופות) + דירוג
best={}
for f in findings:
    k=(f['line'],f['sid'])
    if k not in best or f['before']+f['after']<best[k]['before']+best[k]['after']: best[k]=f
skippers=defaultdict(set)
for f in best.values(): skippers[f['sid']].add(f['line'])
ranked=sorted(best.values(),key=lambda f:(len(skippers[f['sid']]),-len(f['others']),f['before']+f['after']))
print()
print('=== ממצאים: קווים עירוניים שחולפים ליד תחנה פעילה בלי לעצור (סנדוויץ׳) ===')
print('סה"כ:',len(ranked))
for f in ranked[:40]:
    s=f['stop']
    print(' קו %s | %s | מדלג על: %s (%s) [%s] | מרחק מהקו %dמ | עוצר %dמ לפני ו-%dמ אחרי | מדלגים על התחנה: %d קווים | עוצרים בה: %s'%(
        f['line'],f['long'][:40],s['name'],s['code'],s['city'],f['dist'],f['before'],f['after'],len(skippers[f['sid']]),','.join(f['others'])))
