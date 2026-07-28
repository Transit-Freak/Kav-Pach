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
CALENDAR=os.environ.get('CALENDAR','calendar.txt')
MAIN=os.environ.get('MAIN','data-main.json')
OUTDIR=os.environ.get('OUTDIR','line-history/data')
TODAY=os.environ.get('TODAY') or datetime.date.today().isoformat()
# מצב יישור חד-פעמי: מתקן גאומטריות שנבחרו מנציג לא-מסונן (תבנית עתידית)
# בלי לרשום אירועי שינוי — ההבדל אינו שינוי אמיתי שנכנס לתוקף.
REBASE=os.environ.get('REBASE')=='1'
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

# ---- שירותים שבתוקף היום ----
# ה-GTFS מכיל גם תבניות מסלול עתידיות (שירותים עם start_date קדימה). האתר
# מציג רק שינויים שנכנסו לתוקף, אז הנציג חייב להיבחר מנסיעה שרצה בפועל.
# מסננים לפי חלון התוקף בלבד (בלי דגלי ימי-השבוע — קו של שישי/שבת נשאר
# קיים גם כשבודקים ביום ראשון).
active=None
if os.path.exists(CALENDAR):
    ymd=TODAY.replace('-','')
    active=set()
    for r in csv.DictReader(open(CALENDAR,encoding='utf-8-sig')):
        if (r.get('start_date') or '00000000')<=ymd<=(r.get('end_date') or '99999999'):
            active.add(r['service_id'])
    print('שירותים בתוקף היום:',len(active))
else:
    print('אזהרה: אין calendar.txt — בלי סינון תבניות עתידיות',file=sys.stderr)

# ---- trips: נציג לכל route_id (רק מנסיעות שבתוקף) ----
rep={}          # route_id -> (trip_id, shape_id)
registered=set()   # וריאנטים שקיימים ברישום (יש להם נסיעות בקובץ, גם אם לא בתוקף היום)
for r in csv.DictReader(open(TRIPS,encoding='utf-8-sig')):
    rid=r['route_id']
    if rid in routes: registered.add(routes[rid]['rd'])
    if active is not None and r.get('service_id') not in active: continue
    if rid in routes and rid not in rep and r.get('shape_id'):
        rep[rid]=(r['trip_id'],r['shape_id'])
rep_trips={t:(rid,sh) for rid,(t,sh) in rep.items()}
print('נסיעות נציג:',len(rep),'| וריאנטים רשומים:',len(registered))

# ---- stops ----
stops={}
rows=list(csv.reader(open(STOPS,encoding='utf-8-sig')))
ix={h:i for i,h in enumerate(rows[0])}
SN,SD,SC,LA,LO,SI=ix['stop_name'],ix['stop_desc'],ix['stop_code'],ix['stop_lat'],ix['stop_lon'],ix['stop_id']
LT=ix.get('location_type')
for r in rows[1:]:
    if len(r)<=SD: continue
    # לא מדלגים על location_type!=0 — משרד התחבורה מסמן כך חלק מהמסופים
    # למרות שנסיעות עוצרות בהם ישירות (למשל מסוף כרמי גת/הורדה), והסינון
    # השמיט תחנות קצה מרצפי הקווים. הם רק מוחרגים מהרישום הארצי (בהמשך).
    lt='0'
    if LT is not None and len(r)>LT and r[LT] not in ('','0'): lt=r[LT]
    try: stops[r[SI]]={'c':r[SC],'n':' '.join(r[SN].split()),'t':city(r[SD]),
                       'la':round(float(r[LA]),5),'lo':round(float(r[LO]),5),'lt':lt}
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

# סיווג עדין של שינוי (בקשת המשתמש: קטגוריות לכל סוגי השינויים):
# redraw=שרטוט בלבד · terminal=שונה קצה המסלול · extend/shorten=הארכה/קיצור
# stops-add/stops-del=רק נוספו/רק ירדו · route=מסלול+תחנות · stops=שינוי תחנות
def classify(old_codes,new_codes,geo,stp):
    if geo and not stp: return 'redraw'
    add=[x for x in new_codes if x not in old_codes]
    rem=[x for x in old_codes if x not in new_codes]
    term=bool(old_codes and new_codes and (old_codes[0]!=new_codes[0] or old_codes[-1]!=new_codes[-1]))
    d=len(new_codes)-len(old_codes)
    if term and d>=3: return 'extend'
    if term and d<=-3: return 'shorten'
    if term: return 'terminal'
    if add and rem: return 'route' if geo else 'stops'
    if add: return 'stops-add'
    if rem: return 'stops-del'
    return 'route' if geo else 'stops'

PAUSE_MAX_D=35   # ביטול שחזר תוך עד ~חודש = הפסקת חג/פגרה, לא מעניין (בקשת המשתמש)
def days_between(a,b):
    return (datetime.date.fromisoformat(b)-datetime.date.fromisoformat(a)).days

n_new=n_changed=n_gone=n_resumed=0
kinds_count={}
for rdesc,c in cur.items():
    pv=prev.get(rdesc)
    if pv is None:
        # אולי חזרה מהפסקה קצרה: אם הגרסה האחרונה בקובץ היא removed טרי — מוחקים
        # אותה בשקט וממשיכים כאילו לא נעלם; שינוי אמיתי ביחס ללפני-ההפסקה עדיין מדווח
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=jload(p,None)
        if lf and lf.get('versions') and lf['versions'][-1].get('k')=='removed' \
           and days_between(lf['versions'][-1]['d'],TODAY)<=PAUSE_MAX_D:
            lf['versions'].pop()
            json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
            n_resumed+=1
            base=next((v for v in reversed(lf['versions']) if v.get('shp')),None)
            if base is not None:
                old_codes=[s[0] for s in base.get('stops',[])]
                geo=base.get('shp')!=encode_shape(c['pts']); stp=old_codes!=c['codes']
                if not geo and not stp:
                    continue   # חזר בדיוק כמו שהיה — אין אירוע
                pv={'codes':old_codes,'op':lf.get('op',''),'_resumed':True,'geo':geo,'stp':stp}
            else:
                continue
        else:
            write_line_version(rdesc,c,'baseline' if first_run else 'new',
                               '' if first_run else 'וריאנט חדש ברישום')
            if not first_run:
                chm['changes'].append({'d':TODAY,'rd':rdesc,'line':c['line'],'op':c['op'],'k':'new'})
            n_new+=1
            continue
    if pv.get('_resumed'):
        geo,stp=pv['geo'],pv['stp']
    else:
        geo=pv['sh_h']!=c['sh_h']; stp=pv['st_h']!=c['st_h']
    op_changed=pv.get('op') is not None and pv.get('op')!=c['op']
    if not geo and not stp and not op_changed: continue
    old_codes=pv['codes']; add=[x for x in c['codes'] if x not in old_codes]
    rem=[x for x in old_codes if x not in c['codes']]
    name={x[0]:x[1] for x in c['stopinfo']}
    oldname=lambda x:(prev_stops.get(x) or [x])[0]   # שם תחנה שירדה — מהמצב הקודם
    if REBASE:
        # יישור: מעדכנים את הגרסה האחרונה-עם-גאומטריה במקומה, בלי אירוע —
        # ההבדל נובע מבחירת נציג לא-מסוננת בריצה קודמת, לא משינוי בפועל
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=jload(p,None)
        if lf and lf.get('versions'):
            lf['versions']=[v for v in lf['versions'] if v.get('d')!=TODAY or v.get('k')=='removed']
            tgt=next((v for v in reversed(lf['versions']) if v.get('shp')),None)
            if tgt is not None:
                tgt['shp']=encode_shape(c['pts']); tgt['stops']=c['stopinfo']
                tgt.pop('add',None); tgt.pop('rem',None)
                lf['line'],lf['dest'],lf['op'],lf['ty']=c['line'],c['long'],c['op'],c['ty']
                json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
                n_changed+=1
                continue
        write_line_version(rdesc,c,'baseline')
        n_changed+=1
        continue
    if not geo and not stp:
        kind='operator'
    else:
        kind=classify(old_codes,c['codes'],geo,stp)
    kinds_count[kind]=kinds_count.get(kind,0)+1; n_changed+=1
    note=''
    if op_changed: note=f"המפעיל הוחלף: {pv.get('op','')} ← {c['op']}"
    ch={'d':TODAY,'rd':rdesc,'line':c['line'],'op':c['op'],'k':kind}
    if add: ch['add']=[name.get(x,x) for x in add][:15]
    if rem: ch['rem']=[oldname(x) for x in rem][:15]
    chm['changes'].append(ch)
    extra={'add':ch.get('add'),'rem':ch.get('rem')} if (add or rem) else None
    write_line_version(rdesc,c,kind,note,extra)
gone=[rdesc for rdesc in prev if rdesc not in cur]
carry={}     # וריאנטים רשומים בלי נסיעות פעילות כרגע — נשמרים במצב, לא "בוטלו"
n_carry=0
for rdesc in gone:
    if first_run: break
    # ביטול = היעלמות מהרישום עצמו. וריאנט שעדיין רשום (למשל חלופת תגבור
    # שתחזור בתאריך עתידי) נגרר קדימה במצב בלי אירוע — בקשת המשתמש: קו נב
    # מראה שהחלופה קיימת, אז אצלנו היא לא "בוטלה".
    if rdesc in registered:
        carry[rdesc]=prev[rdesc]
        n_carry+=1
        continue
    if REBASE:
        # וריאנט שכל התיעוד שלו הוא baseline מהנציג הלא-מסונן = תבנית עתידית
        # שמעולם לא רצה — מוחקים את הקובץ; הוא יירשם כ'new' כשייכנס לתוקף.
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=jload(p,None)
        if lf is not None and all(v.get('k')=='baseline' for v in lf.get('versions',[])):
            os.remove(p)
            n_gone+=1
            continue
    chm['changes'].append({'d':TODAY,'rd':rdesc,'line':prev[rdesc].get('line',''),'k':'removed'})
    # רושמים removed גם בקובץ הקו — אם יחזור תוך חודש הרשומה תימחק בשקט (למעלה)
    p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    lf=jload(p,None)
    if lf is not None:
        lf['versions']=[v for v in lf['versions'] if not (v.get('d')==TODAY and v.get('k')=='removed')]
        lf['versions'].append({'d':TODAY,'k':'removed','shp':'','stops':[],
                               'note':'הווריאנט נעלם מהרישום'})
        json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
    n_gone+=1
# ריפוי עצמי: וריאנט שעדיין רשום אבל נפלט מהמצב וסומן 'removed' בטעות
# (גל סינון ה-calendar של 26-27.07) — רשומת הביטול נמחקת והוא חוזר למצב.
def dec_shape(s):
    pts=[];i=0;la=0;lo=0
    while i<len(s):
        for w in (0,1):
            sh=0;res=0
            while True:
                b=ord(s[i])-63;i+=1;res|=(b&0x1f)<<sh;sh+=5
                if b<0x20: break
            d2=~(res>>1) if res&1 else res>>1
            if w==0: la+=d2
            else: lo+=d2
        pts.append((la/1e5,lo/1e5))
    return pts
n_heal=0
for rdesc in registered:
    if rdesc in cur or rdesc in prev or rdesc in carry: continue
    p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    lf=jload(p,None)
    if not lf or not lf.get('versions'): continue
    if lf['versions'][-1].get('k')=='removed':
        dd=lf['versions'][-1]['d']
        lf['versions'].pop()
        chm['changes']=[c for c in chm['changes'] if not (c.get('rd')==rdesc and c.get('k')=='removed' and c.get('d')==dd)]
        json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
        n_heal+=1
    base=next((v for v in reversed(lf.get('versions',[])) if v.get('shp')),None)
    if base is not None:
        codes=[s0[0] for s0 in base.get('stops',[])]
        carry[rdesc]={'sh_h':h12(json.dumps(dec_shape(base['shp']))),'st_h':h12('|'.join(codes)),
                      'codes':codes,'line':lf.get('line',''),'op':lf.get('op','')}
print(f'קווים: חדשים {n_new} | שינויים {n_changed} {kinds_count} | הוסרו {n_gone} | חזרו מהפסקה {n_resumed} | רשומים בהמתנה {n_carry} | רופאו {n_heal}')

# ---- שינויי תחנות (רישום ארצי) ----
# כולל גם תחנות שמסומנות location_type!=0 — אלה תחנות אמיתיות עם קוד
# ברישום (מסופים וכד'), ושינויים בהן מעניינים כמו בכל תחנה.
cur_stops={}
for s in stops.values():
    lns=sorted(stop_lines.get(s['c'],()))[:MAX_LINES_LIST]
    cur_stops[s['c']]=[s['n'],s['la'],s['lo'],s['t'],lns]
spath=f'{OUTDIR}/changes/stops-{month}.json'
stm=jload(spath,{'month':month,'changes':[]})
if not REBASE:   # ביישור מצב-התחנות כבר עדכני — מחיקה הייתה מאבדת את אירועי היום
    stm['changes']=[c for c in stm['changes'] if c.get('d')!=TODAY]
shist=jload(f'{OUTDIR}/stops-hist.json',{})
def sev(code,ev):
    stm['changes'].append({'d':TODAY,'c':code,**ev})
    shist.setdefault(code,[])
    shist[code]=[e for e in shist[code] if not (e['d']==TODAY and e['k']==ev['k'])]
    shist[code].append({'d':TODAY,**ev})
ns=nd=nr=nm=0
# ביישור: מצב-התחנות רק מתרענן בשקט (למשל קליטת המסופים שסוננו בעבר) —
# בלי לרשום אירועי "חדשה", כי אלה לא תחנות שבאמת נוספו היום.
if not first_run and not REBASE:
    for c0,v in cur_stops.items():
        pv=prev_stops.get(c0)
        if pv is None:
            # תחנה שנעלמה וחזרה תוך עד ~חודש — מוחקים את הביטול בשקט
            hc=shist.get(c0) or []
            if hc and hc[-1].get('k')=='del' and days_between(hc[-1]['d'],TODAY)<=PAUSE_MAX_D:
                dd=hc[-1]['d']
                shist[c0]=hc[:-1]
                if not shist[c0]: shist.pop(c0)
                if dd[:7]==month:
                    stm['changes']=[x for x in stm['changes'] if not (x.get('c')==c0 and x.get('k')=='del' and x.get('d')==dd)]
                else:
                    mp=f'{OUTDIR}/changes/stops-{dd[:7]}.json'
                    mm=jload(mp,None)
                    if mm:
                        mm['changes']=[x for x in mm['changes'] if not (x.get('c')==c0 and x.get('k')=='del' and x.get('d')==dd)]
                        json.dump(mm,open(mp,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
                continue
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
# האינדקס כולל את כל הווריאנטים שיש להם קובץ — גם כאלה שכבר לא ברישום
# (קווים מבוטלים חייבים להישאר ניתנים לחיפוש ולסינון לפי קטגוריה).
# ks = סוגי השינויים שיש לקו, lk/ld = הרשומה האחרונה (לסטטוס "מבוטל").
def idx_entry(rdesc, line, dest, op, ty):
    vs = jload(f'{OUTDIR}/lines/{fsafe(rdesc)}.json', {}).get('versions', [])
    e = {'rd': rdesc, 'line': line, 'dest': dest[:80], 'op': op, 'ty': ty, 'v': len(vs)}
    ks = {v['k'] for v in vs if v['k'] != 'baseline'}
    # גרסאות ארכיון שהועשרו בהפרשי תחנות (enrich_stop_diffs) נספרות גם
    # בקטגוריות התחנות — אחרת ההיסטוריה של 2022–2026 לא מופיעה שם בכלל
    for v in vs:
        if v.get('src') == 'ob' and v.get('k') != 'removed':
            a, r = v.get('add'), v.get('rem')
            if a and r: ks.add('stops')
            elif a: ks.add('stops-add')
            elif r: ks.add('stops-del')
    ks = sorted(ks)
    if ks: e['ks'] = ks
    if vs: e['lk'] = vs[-1]['k']; e['ld'] = vs[-1]['d']
    return e

idx=[]
for rdesc,c in cur.items():
    idx.append(idx_entry(rdesc, c['line'], c['long'], c['op'], c['ty']))
seen_rd={e['rd'] for e in idx}
for fn in os.listdir(f'{OUTDIR}/lines'):
    if not fn.endswith('.json'): continue
    lf=jload(f'{OUTDIR}/lines/{fn}',{})
    rdesc=lf.get('rd')
    if not rdesc or rdesc in seen_rd: continue
    # קובץ שאין לו מצב: אם הווריאנט נעלם מהרישום לגמרי ועוד לא סומן מבוטל —
    # רושמים ביטול. אם הוא עדיין רשום (בלי נסיעות פעילות) הוא נשאר חי.
    vs=lf.get('versions',[])
    if not first_run and rdesc not in registered and rdesc not in carry \
       and vs and vs[-1].get('k')!='removed':
        vs.append({'d':TODAY,'k':'removed','shp':'','stops':[],'note':'הווריאנט נעלם מהרישום'})
        json.dump(lf,open(f'{OUTDIR}/lines/{fn}','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
        chm['changes'].append({'d':TODAY,'rd':rdesc,'line':lf.get('line',''),'k':'removed'})
    idx.append(idx_entry(rdesc, lf.get('line',''), lf.get('dest') or '', lf.get('op',''), lf.get('ty','')))
idx.sort(key=lambda x:(x['line'],x['rd']))
json.dump({'gen':TODAY,'first':first_run,'lines':idx},
          open(f'{OUTDIR}/lines.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(chm,open(chpath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(stm,open(spath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(shist,open(f'{OUTDIR}/stops-hist.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
state_out={rdesc:{'sh_h':c['sh_h'],'st_h':c['st_h'],'codes':c['codes'],'line':c['line'],'op':c['op']} for rdesc,c in cur.items()}
state_out.update(carry)   # רשומים ללא נסיעות פעילות — נגררים קדימה
json.dump(state_out,
          open(f'{OUTDIR}/state-routes.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(cur_stops,open(f'{OUTDIR}/stops-state.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
mons=sorted({f[8:15] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')})
json.dump({'months':sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$',f)},reverse=True),
           'stopMonths':sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')},reverse=True)},
          open(f'{OUTDIR}/months.json','w',encoding='utf-8'),ensure_ascii=False)
print('נכתב הכול תחת',OUTDIR)
