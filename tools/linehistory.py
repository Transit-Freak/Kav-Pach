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
import sys, os as _os
sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from compact_lines import materialize

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

def route_cities(long):
    """ערי המוצא והיעד משם המסלול "תחנה-עיר<->תחנה-עיר-מק"."""
    out=[]
    for side in (long or '').split('<->'):
        side=re.sub(r'(-\d+[א-ת]?#?\s*)+$','',side).strip()
        out.append(side.rsplit('-',1)[1].strip() if '-' in side else '')
    return ' ← '.join(out) if len(out)==2 and all(out) else ''

def hs_fmt(h):
    # trip_headsign בפורמט "עיר_תחנה" — לתצוגה: "תחנה, עיר"
    p=(h or '').split('_',1)
    return f'{p[1]}, {p[0]}' if len(p)==2 and p[0] and p[1] else (h or '')

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

# סוג התחבורה לפי route_type. עד כה נסרקו אוטובוסים בלבד וכל השאר נזרק;
# רכבת ישראל, מוניות השירות, הרכבת הקלה, הכרמלית והקווים לפי דרישה נושאים
# route_desc באותו פורמט בדיוק, ולכן נכנסים לאותו מבנה נתונים ללא שינוי.
# אוטובוס אינו מסומן — כך אף קובץ קיים לא משתנה.
# route_type=0 מכסה את שתי הרכבות הקלות: ירושלים (מפעיל "כפיר", מק"ט 73001)
# ותל אביב (מפעיל "תבל" בפיד — דנקל הוא הזכיין; מק"טים 79001, 65002, 86003).
# זו של תל אביב נפתחה ב-2023, כלומר אחרי סוף ארכיון TransitFeeds, ולכן היא
# יכולה להיכנס לאתר רק דרך הסריקה הזו.
# route_type בפיד הארצי אינו רק 0-7: במרץ 2023 פורסמו 3,046 קווים כ-707
# ("אוטובוס לצרכים מיוחדים" בתקן המורחב), ואחר כך הם חזרו ל-3. סוג שלא
# הכרנו נדלג עליו — ואז מצב הקו נתקע על הערך הישן, וכשהוא חזר ל-3 נרשם
# "שינוי סיווג" שלא היה. כל טווח ה-70x הוא אוטובוס, מלבד 715 שהוא שירות
# לפי דרישה.
BUSX = {'700', '701', '702', '703', '704', '705', '706', '707', '708', '709',
        '710', '711', '712', '713', '714', '716'}
import unknown_values as unk
TT={'2':'rail','8':'taxi','0':'lightrail','5':'cable','715':'demand'}

# ---- routes: route_id -> (desc, line, dest, agency) ----
routes={}
for r in csv.DictReader(open(ROUTES,encoding='utf-8-sig')):
    rt=(r.get('route_type') or '3').strip()
    if rt in BUSX: rt='3'                   # כל טווח ה-70x הוא אוטובוס
    if rt!='3' and rt not in TT:
        # לא מנחשים — אבל גם לא שותקים: ערך לא מוכר נרשם ומתריע
        unk.note('route_type',rt,TODAY,(r.get('route_desc') or '').strip()); continue
    rd=(r.get('route_desc') or '').strip()
    if not rd: continue
    routes[r['route_id']]={'rd':rd,'line':r.get('route_short_name',''),
                           'long':r.get('route_long_name',''),'ag':r.get('agency_id',''),
                           'tt':TT.get(rt)}
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
# הכלל הקודם היה "הנסיעה הראשונה בקובץ שיש לה שרטוט", והוא נשען על סדר
# השורות ב-trips.txt. הסדר אינו יציב בין פרסומים: בקו 548 היו בשני ימים
# רצופים אותן 23 נסיעות בתבנית של 21 תחנות ו-7 בתבנית של 25, ורק הסדר
# התחלף — ונרשם "ירדו ארבע תחנות" על נתונים שלא זזו.
#
# הבחירה כאן אינה תלויה בסדר: התבנית שרוב הנסיעות רצות בה, ובתוכה מזהה
# הנסיעה הקטן ביותר. שוויון נשבר לפי מזהה השרטוט.
rep={}          # route_id -> (trip_id, shape_id)
_wa={}          # route_id -> נגישות (1/2)
_hs={}          # route_id -> תחנת היעד לפרסום (trip_headsign)
_cnt={}         # route_id -> {shape_id: כמה נסיעות}
_first={}       # (route_id, shape_id) -> מזהה הנסיעה הקטן ביותר
_ntr={}         # rd -> מספר הנסיעות שבתוקף היום
registered=set()   # וריאנטים שקיימים ברישום (יש להם נסיעות בקובץ, גם אם לא בתוקף היום)
for r in csv.DictReader(open(TRIPS,encoding='utf-8-sig')):
    rid=r['route_id']
    if rid in routes: registered.add(routes[rid]['rd'])
    if active is not None and r.get('service_id') not in active: continue
    # כמה נסיעות בפועל יש לוריאנט. הפיד מפרסם קווים הרבה לפני הפתיחה, ואז
    # "קיים בפיד" אינו "פועל": הקו הירוק בירושלים (93003) נכנס עם נסיעה
    # אחת בכל כיוון, פעם בשבוע, בעוד הקו הירוק של דנקל (86003) מפרסם 680.
    # המספר עצמו עובדה מהפיד, והוא מבדיל בין השניים בלי לנחש.
    if rid in routes: _ntr[routes[rid]['rd']] = _ntr.get(routes[rid]['rd'], 0) + 1
    if rid in routes and r.get('shape_id'):
        sh=r['shape_id']; t=r['trip_id']
        d=_cnt.setdefault(rid,{}); d[sh]=d.get(sh,0)+1
        if (rid,sh) not in _first or t<_first[(rid,sh)]: _first[(rid,sh)]=t
        # נגישות לכיסא גלגלים: 1 = נגיש, 2 = לא. השדה אחיד לכל הנסיעות של
        # אותו קו (נבדק על הפיד המלא — אפס קווים עם ערכים מעורבים), ולכן
        # הוא תכונה של הקו ולא של הנסיעה.
        wa=(r.get('wheelchair_accessible') or '').strip()
        if wa in ('1','2'): _wa[rid]=wa
        if rid not in _hs:
            _hh=(r.get('trip_headsign') or '').strip()
            if _hh: _hs[rid]=_hh
        elif wa not in ('','0'): unk.note('wheelchair_accessible',wa,TODAY,rid)
for rid,shapes in _cnt.items():
    sh=min(shapes,key=lambda x:(-shapes[x],x))
    rep[rid]=(_first[(rid,sh)],sh)
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
    PU,DO=hi.get('pickup_type'),hi.get('drop_off_type')
    for r in rd_:
        t=r[TI]
        if t in rep_trips:
            # 1 = העלאה בלבד, 2 = הורדה בלבד, 3 = לא עוצר לנוסעים.
            # אחת מכל תשע עצירות בפיד מוגבלת כך, וזה לא מופיע בשום מקום.
            pd=0
            try:
                if PU is not None and len(r)>PU:
                    if r[PU]=='1': pd+=2
                    elif r[PU] not in ('','0'): unk.note('pickup_type',r[PU],TODAY,r[SIx])
                if DO is not None and len(r)>DO:
                    if r[DO]=='1': pd+=1
                    elif r[DO] not in ('','0'): unk.note('drop_off_type',r[DO],TODAY,r[SIx])
            except Exception: pd=0
            try: seqs[t].append((int(r[SQ]),r[SIx],pd))
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
    _rows=sorted(seqs.get(t,[]))
    sq=[x[1] for x in _rows]
    pdm={x[1]:(x[2] if len(x)>2 else 0) for x in _rows}
    codes=[stops[s]['c'] for s in sq if s in stops]
    if len(codes)<2: continue
    mk=info['rd'].split('-')[0].lstrip('0')
    cur[info['rd']]={'line':info['line'],'long':info['long'],'op':agencies.get(info['ag'],''),
                     'ty':linetype.get(mk,''),'tt':info.get('tt'),'pts':pts,'codes':codes,
                     'wa':_wa.get(rid,''),'ntr':_ntr.get(info['rd'],0),
                     'hs':_hs.get(rid,''),'ct':route_cities(info['long']),
                     # איבר חמישי בתחנה = מגבלת עלייה/ירידה; 0 נשמר כרשימה
                     # קצרה כדי שקבצים ישנים וחדשים ייראו זהים כשאין מגבלה
                     'stopinfo':[[stops[s]['c'],stops[s]['n'],stops[s]['la'],stops[s]['lo']]
                                 + ([pdm.get(s,0)] if pdm.get(s,0) else [])
                                 for s in sq if s in stops],
                     'sh_h':h12(json.dumps(pts)),'st_h':h12('|'.join(codes)),
                     'pd_h':h12('|'.join(f"{stops[s]['c']}:{pdm.get(s,0)}" for s in sq
                                        if s in stops and pdm.get(s,0)))}
print('וריאנטים תקינים:',len(cur))

# ---- טעינת מצב קודם ----
os.makedirs(f'{OUTDIR}/lines',exist_ok=True)
os.makedirs(f'{OUTDIR}/changes',exist_ok=True)
def jload(p,dflt):
    try: return json.load(open(p,encoding='utf-8'))
    except Exception: return dflt
prev=jload(f'{OUTDIR}/state-routes.json',{})


def prev_pd_of(rdesc):
    """מגבלות העלייה/ירידה כפי שהיו בגרסה האחרונה — לניסוח ההפרש.

    המצב היומי שומר חתימה בלבד (pd_h) כדי להישאר קטן, ולכן כשצריך לומר מה
    בדיוק השתנה קוראים את הגרסה מקובץ הקו עצמו.
    """
    lf=materialize(jload(f'{OUTDIR}/lines/{fsafe(rdesc)}.json',None))
    if not lf: return {}
    v=next((x for x in reversed(lf.get('versions') or []) if x.get('stops')),None)
    return {x[0]:x[4] for x in (v or {}).get('stops',[]) if len(x)>4}
prev_stops=jload(f'{OUTDIR}/stops-state.json',{})
first_run=not prev

def dist_m(a_la,a_lo,b_la,b_lo):
    cl=math.cos(math.radians((a_la+b_la)/2))
    return math.hypot((a_la-b_la)*110540,(a_lo-b_lo)*111320*cl)

n_tyfix=0
month=TODAY[:7]
chpath=f'{OUTDIR}/changes/{month}.json'
chm=jload(chpath,{'month':month,'changes':[]})
chm['changes']=[c for c in chm['changes'] if c.get('d')!=TODAY]  # ריצה חוזרת באותו יום

def write_line_version(rdesc,c,kind,note='',extra=None):
    p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    lf=jload(p,{'rd':rdesc,'line':c['line'],'dest':c['long'],'op':c['op'],'ty':c['ty'],'versions':[]})
    lf['line'],lf['dest'],lf['op'],lf['ty']=c['line'],c['long'],c['op'],c['ty']
    if c.get('tt'): lf['tt']=c['tt']      # אוטובוס נשאר בלי סימון
    # נגישות היא תכונה של הקו ולא של הגרסה, ולכן היא יושבת על הקובץ עצמו
    if c.get('wa'): lf['wa']=c['wa']
    lf['versions']=[v for v in lf['versions'] if v.get('d')!=TODAY]
    v={'d':TODAY,'k':kind,'shp':encode_shape(c['pts']),'stops':c['stopinfo']}
    if note: v['note']=note
    if extra: v.update(extra)
    lf['versions'].append(v)
    json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))

# סיווג עדין של שינוי (בקשת המשתמש: קטגוריות לכל סוגי השינויים):
# redraw=שרטוט בלבד · terminal=שונה קצה המסלול · extend/shorten=הארכה/קיצור
# stops-add/stops-del=רק נוספו/רק ירדו · route=מסלול+תחנות · stops=שינוי תחנות
def classify(old_codes,new_codes,geo,stp,nm=None):
    if geo and not stp: return 'redraw'
    add=[x for x in new_codes if x not in old_codes]
    rem=[x for x in old_codes if x not in new_codes]
    # קצה נחשב "שונה" רק כשגם שם התחנה שונה: משרד התחבורה מחליף לפעמים
    # רק את המק"ט של תחנת הקצה (אותו שם, אותו מיקום), וההשוואה לפי מספר
    # בלבד סיווגה שינוי-מסלול כ"הארכת קו" (קו 80 כפר חב"ד, 25.08.2026)
    def same(a,b):
        if a==b: return True
        na,nb=(nm(a),nm(b)) if nm else (None,None)
        return bool(na) and na==nb
    term=bool(old_codes and new_codes and
              not (same(old_codes[0],new_codes[0]) and same(old_codes[-1],new_codes[-1])))
    d=len(new_codes)-len(old_codes)
    if term and d>=3: return 'extend'
    if term and d<=-3: return 'shorten'
    if term: return 'terminal'
    if add and rem: return 'route' if geo else 'stops'
    if add: return 'stops-add'
    if rem: return 'stops-del'
    return 'route' if geo else 'stops'

# ---- שרטוט "חדש" שחופף לגמרי לישן = פרסום מחדש בצפיפות אחרת, לא תיקון ----
def _dec_pts(s):
    pts=[];i=0;la=0;lo=0
    while i<len(s):
        for ref in (0,1):
            sh=0;res=0
            while True:
                b=ord(s[i])-63;i+=1
                res|=(b&0x1f)<<sh;sh+=5
                if b<0x20:break
            d=~(res>>1) if res&1 else res>>1
            if ref==0:la+=d
            else:lo+=d
        pts.append((la/1e5,lo/1e5))
    return pts
def shapes_overlap(sa,sb):
    """True כשכל נקודה בכל שרטוט בתוך ~40 מ' מהשני — אותו מסלול בפועל."""
    try:
        a,b=_dec_pts(sa),_dec_pts(sb)
    except Exception:
        return False
    if not a or not b: return False
    def cells(pts):
        cs=set()
        for la,lo in pts:
            ci,cj=round(la*4000),round(lo*4000)
            for di in (-1,0,1):
                for dj in (-1,0,1): cs.add((ci+di,cj+dj))
        return cs
    ca,cb=cells(a),cells(b)
    if any((round(p[0]*4000),round(p[1]*4000)) not in ca for p in b): return False
    if any((round(p[0]*4000),round(p[1]*4000)) not in cb for p in a): return False
    return True

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
        lf=materialize(jload(p,None))
        if lf and lf.get('versions') and lf['versions'][-1].get('k')=='removed' \
           and days_between(lf['versions'][-1]['d'],TODAY)<=PAUSE_MAX_D:
            lf['versions'].pop()
            json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
            n_resumed+=1
            # הבסיס להשוואה: התיעוד האחרון עם רצף תחנות, לא רק עם שרטוט.
            # כשהרשומות האחרונות היו ריקות, ההשוואה נעשתה מול שרטוט בן שנים
            # — קו 80 כפר חב"ד חזר באוגוסט עם מסלול-הקיץ הישן, נמצא "זהה
            # לתיעוד" (של 2020!), והאירוע נבלע. ההצגה מחדש של המסלול הנוכחי
            # ב-25.08 נראתה אז כשינוי שממציא תחנות (דיווח שלמה)
            base=next((v for v in reversed(lf['versions'])
                       if v.get('stops') or v.get('shp')),None)
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
    if op_changed:
        # הרישום "חזר" עם תווית מפעיל ישנה ותוקן בחזרה — לא החלפה: אם
        # המפעיל המתועד בקובץ כבר זהה לחדש, האירוע כבר נרשם בזמן אמת
        # (קו 774 ירושלים: אגד←אקסטרה תועד ב-12.2023, ושוב "הוחלף" ב-2026)
        _lfop=(jload(f'{OUTDIR}/lines/{fsafe(rdesc)}.json',None) or {}).get('op')
        if _lfop==c['op']:
            op_changed=False
    # שינוי בהגדרת הקו עצמו: קו רגיל שהפך ל"שירות לפי דרישה", או להפך.
    # אין לו ביטוי בתחנות או בשרטוט, ולכן בלי בדיקה מפורשת הוא היה עובר
    # בשקט — ומבחינת הנוסע זה שינוי מהותי יותר מהזזת תחנה.
    tt_changed=('tt' in pv) and pv.get('tt')!=c.get('tt')
    # סיווג הקו (עירוני/בינעירוני/אזורי) יכול להשתנות בלי שום שינוי במסלול —
    # בלי בדיקה מפורשת הוא היה עובר בשקט והעמוד היה מציג סיווג ישן לנצח
    ty_changed=('ty' in pv) and pv.get('ty')!=c.get('ty')
    # נגישות לכיסא גלגלים ומגבלות עלייה/ירידה: שניהם אינם נראים בתחנות
    # ובשרטוט, ולכן בלי בדיקה מפורשת הם עוברים בשקט — ולנוסע שתלוי בהם
    # אלה השינויים החשובים ביותר בקו.
    wa_changed=bool(pv.get('wa')) and bool(c.get('wa')) and pv['wa']!=c['wa']
    pd_changed=('pd_h' in pv) and pv.get('pd_h')!=c.get('pd_h')
    # תחנת היעד לפרסום (שלט האוטובוס) ועיר המוצא/יעד — שניהם בלתי נראים
    # בתחנות ובשרטוט; נבדקים רק כששני הצדדים קיימים (שדה חדש במצב ישן)
    hs_changed=bool(pv.get('hs')) and bool(c.get('hs')) and pv['hs']!=c['hs']
    ct_changed=bool(pv.get('ct')) and bool(c.get('ct')) and pv['ct']!=c['ct']
    if not geo and not stp and not op_changed and not tt_changed \
       and not wa_changed and not pd_changed and not ty_changed:
        # תיקון עבר: קבצים שהסיווג בהם התיישן לפני שנוסף המעקב — מרעננים
        # בשקט את המטא-נתונים בלי להמציא אירוע על שינוי שקרה מזמן
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=jload(p,None)
        if lf and lf.get('ty')!=c.get('ty'):
            lf['ty']=c.get('ty','')
            json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
            n_tyfix+=1
        continue
    old_codes=pv['codes']; add=[x for x in c['codes'] if x not in old_codes]
    rem=[x for x in old_codes if x not in c['codes']]
    name={x[0]:x[1] for x in c['stopinfo']}
    # מק"ט שכבר נמחק מהרישום הארצי אין לו שם במצב-התחנות — משלימים
    # מהתיעוד של הקו עצמו; בלי זה כרטיס השינוי הציג מספר חשוף בלי שם
    fentries={}
    if rem:
        lf0=jload(f'{OUTDIR}/lines/{fsafe(rdesc)}.json',None) or {}
        for s in (lf0.get('pool') or []):
            if isinstance(s,list) and len(s)>=4: fentries.setdefault(str(s[0]),[s[1],s[2],s[3]])
            elif isinstance(s,list) and len(s)>=2: fentries.setdefault(str(s[0]),[s[1],None,None])
        for v0 in (lf0.get('versions') or []):
            for s in (v0.get('stops') or []):
                if isinstance(s,list) and len(s)>=4: fentries.setdefault(str(s[0]),[s[1],s[2],s[3]])
                elif isinstance(s,list) and len(s)>=2: fentries.setdefault(str(s[0]),[s[1],None,None])
    oldname=lambda x:(prev_stops.get(x) or fentries.get(x) or [x])[0]   # שם תחנה שירדה
    # החלפת מק"ט לתחנה (אותו שם, אותו מיקום) היא אירוע של רישום התחנות,
    # לא של הקו: הזוג לא נספר כ"ירדה"+"נוספה" (בקשת שלמה, קו 80 כפר חב"ד)
    codes_eff=c['codes']
    if add and rem:
        sinfo={s[0]:s for s in c['stopinfo']}
        ren={}   # מק"ט חדש -> המק"ט הישן שהוא מחליף
        for x in list(rem):
            ent=prev_stops.get(x) or fentries.get(x)
            if not ent or ent[1] is None: continue
            for y in add:
                if y in ren: continue
                sy=sinfo.get(y)
                if sy and sy[1]==ent[0] and abs(sy[2]-ent[1])<0.005 and abs(sy[3]-ent[2])<0.005:
                    ren[y]=x; rem.remove(x); break
        add=[y for y in add if y not in ren]
        if ren:
            codes_eff=[ren.get(y,y) for y in c['codes']]
            if codes_eff==old_codes and not geo and not (op_changed or tt_changed
               or ty_changed or wa_changed or pd_changed):
                # רק מספרי תחנות הוחלפו — מרעננים בשקט את הרשימה בגרסה
                # האחרונה, בלי להמציא אירוע-קו על החלפת רישום
                p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
                lf=materialize(jload(p,None))
                if lf and lf.get('versions'):
                    tgt=next((v for v in reversed(lf['versions']) if v.get('stops')),None)
                    if tgt is not None:
                        tgt['stops']=c['stopinfo']
                        json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
                continue
            stp=codes_eff!=old_codes
    if REBASE:
        # יישור: מעדכנים את הגרסה האחרונה-עם-גאומטריה במקומה, בלי אירוע —
        # ההבדל נובע מבחירת נציג לא-מסוננת בריצה קודמת, לא משינוי בפועל
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=materialize(jload(p,None))
        if lf and lf.get('versions'):
            lf['versions']=[v for v in lf['versions'] if v.get('d')!=TODAY or v.get('k')=='removed']
            tgt=next((v for v in reversed(lf['versions']) if v.get('shp')),None)
            if tgt is not None:
                tgt['shp']=encode_shape(c['pts']); tgt['stops']=c['stopinfo']
                tgt.pop('add',None); tgt.pop('rem',None)
                lf['line'],lf['dest'],lf['op'],lf['ty']=c['line'],c['long'],c['op'],c['ty']
                if c.get('tt'): lf['tt']=c['tt']
                json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
                n_changed+=1
                continue
        write_line_version(rdesc,c,'baseline')
        n_changed+=1
        continue
    if tt_changed and not geo and not stp:
        kind='mode'
    elif ty_changed and not geo and not stp and not op_changed:
        kind='mode'
    elif wa_changed and not geo and not stp and not op_changed:
        kind='access'
    elif pd_changed and not geo and not stp and not op_changed:
        kind='board'
    elif not geo and not stp:
        kind='operator'
    else:
        kind=classify(old_codes,codes_eff,geo,stp,
                      lambda x: name.get(x) or (prev_stops.get(x) or fentries.get(x) or [None])[0])
    if kind=='redraw':
        # "תיקון שרטוט" שחופף לגמרי לשרטוט המתועד = פרסום מחדש בצפיפות
        # נקודות אחרת, לא תיקון (55 כאלה נרשמו 19-25.08). מרעננים בשקט
        # את השרטוט בגרסה האחרונה — בלי אירוע
        p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
        lf=materialize(jload(p,None))
        base=next((v for v in reversed((lf or {}).get('versions') or []) if v.get('shp')),None)
        if base is not None and shapes_overlap(base['shp'],encode_shape(c['pts'])):
            base['shp']=encode_shape(c['pts'])
            json.dump(lf,open(p,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
            continue
    kinds_count[kind]=kinds_count.get(kind,0)+1; n_changed+=1
    note=''
    if op_changed: note=f"המפעיל הוחלף: {pv.get('op','')} ← {c['op']}"
    if tt_changed:
        lbl={'rail':'רכבת','taxi':'מונית שירות','lightrail':'רכבת קלה',
             'cable':'רכבל/כרמלית','demand':'שירות לפי דרישה',None:'קו אוטובוס רגיל'}
        t=f"סוג הקו שוּנה: {lbl.get(pv.get('tt'),pv.get('tt'))} ← {lbl.get(c.get('tt'),c.get('tt'))}"
        note=(note+' · '+t) if note else t
    if ty_changed:
        t=f"סיווג הקו שוּנה: {pv.get('ty') or '—'} ← {c.get('ty') or '—'}"
        note=(note+' · '+t) if note else t
    if wa_changed:
        lblw={'1':'נגיש לכיסא גלגלים','2':'אינו נגיש לכיסא גלגלים'}
        t=f"הנגישות שוּנתה: {lblw.get(pv['wa'],pv['wa'])} ← {lblw.get(c['wa'],c['wa'])}"
        note=(note+' · '+t) if note else t
    if pd_changed:
        # 1 = אין הורדה (העלאה בלבד), 2 = אין העלאה (הורדה בלבד) — המיפוי
        # היה הפוך וכתב "העלאה בלבד" על תחנות סופיות (דיווח שלמה, קו 12 טבריה)
        # ניסוח אנושי ומקובץ (בקשת שלמה): "איסוף והורדה" במקום "רגילה",
        # וכשכמה תחנות עברו אותו שינוי — רשימה אחת ומשפט אחד
        PDT={0:'איסוף והורדה',1:'איסוף בלבד',2:'הורדה בלבד',3:'ללא עצירה לנוסעים'}
        now={x[0]:x[4] for x in c['stopinfo'] if len(x)>4}
        was=prev_pd_of(rdesc)
        groups={}
        for k,v in sorted(now.items()):
            o=was.get(k,0)
            if o!=v:
                groups.setdefault((o,v),[]).append(name.get(k,k))
        for k,v in sorted(was.items()):
            if k not in now and k in c['codes']:
                groups.setdefault((v,0),[]).append(oldname(k))
        chg=[]
        for (o,v),nms in groups.items():
            nms=nms[:8]
            verb='השתנתה' if len(nms)==1 else 'השתנו'
            chg.append(f"{', '.join(nms)} — {verb} מ{PDT[o]} ל{PDT[v]}")
        if chg:
            t='שינוי בהגדרות האיסוף וההורדה: '+' · '.join(chg)
            note=(note+' · '+t) if note else t
    if hs_changed:
        t=f"תחנת היעד לפרסום שוּנתה: {hs_fmt(pv['hs'])} ← {hs_fmt(c['hs'])}"
        note=(note+' · '+t) if note else t
    if ct_changed:
        t=f"שינוי עיר: {pv['ct']} ← {c['ct']}"
        note=(note+' · '+t) if note else t
    ch={'d':TODAY,'rd':rdesc,'line':c['line'],'op':c['op'],'k':kind}
    if add: ch['add']=[name.get(x,x) for x in add][:15]
    if rem: ch['rem']=[oldname(x) for x in rem][:15]
    chm['changes'].append(ch)
    extra={'add':ch.get('add'),'rem':ch.get('rem')} if (add or rem) else None
    if extra:
        # הזיהוי הוא לפי מספר תחנה והשם רק תצוגה (בקשת שלמה): המק"טים
        # נשמרים מיושרים אחד-לאחד עם רשימות השמות — האתר לא מנחש כלום
        if add: extra['ac']=add[:15]
        if rem: extra['rc']=rem[:15]
    if extra and rem:
        # המק"ט של כל תחנה שירדה ידוע כאן במדויק — נשמר לצד השם (v.nc),
        # כדי שהאתר לא ינחש אותו בחיפוש-שם שנשבר כשהשם ברישום השתנה
        # ("דוד רמז/הכרם" בקו 20, ששמור אצלנו בשמו הישן "מסוף רמז/דוד רמז")
        nc={}
        for x in rem[:15]:
            pvs=prev_stops.get(x) or fentries.get(x)
            nc.setdefault(oldname(x),[x,pvs[1],pvs[2]] if pvs and pvs[1] is not None else x)
        extra['nc']=nc
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
        lf=materialize(jload(p,None))
        if lf is not None and all(v.get('k')=='baseline' for v in lf.get('versions',[])):
            os.remove(p)
            n_gone+=1
            continue
    chm['changes'].append({'d':TODAY,'rd':rdesc,'line':prev[rdesc].get('line',''),'k':'removed'})
    # רושמים removed גם בקובץ הקו — אם יחזור תוך חודש הרשומה תימחק בשקט (למעלה)
    p=f'{OUTDIR}/lines/{fsafe(rdesc)}.json'
    lf=materialize(jload(p,None))
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
    lf=materialize(jload(p,None))
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
print(f'קווים: חדשים {n_new} | שינויים {n_changed} {kinds_count} | הוסרו {n_gone} | חזרו מהפסקה {n_resumed} | רשומים בהמתנה {n_carry} | רופאו {n_heal} | סיווג רוענן {n_tyfix}')

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
ns=nd=nr=nm=ncty=npd_t=0
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
        # עיר הרישום של התחנה השתנתה (בקשת שלמה) — אירוע תחנה, לא קו
        if len(pv)>3 and pv[3] and v[3] and pv[3]!=v[3]:
            sev(c0,{'k':'city','n':v[0],'oc':pv[3],'nc':v[3],'la':v[1],'lo':v[2]}); ncty+=1
        d=dist_m(pv[1],pv[2],v[1],v[2])
        if d>MOVE_M:
            sev(c0,{'k':'moved','n':v[0],'t':v[3],'dist':round(d),'ola':pv[1],'olo':pv[2],'la':v[1],'lo':v[2]}); nm+=1
    for c0,pv in prev_stops.items():
        if c0 not in cur_stops:
            sev(c0,{'k':'del','n':pv[0],'t':pv[3],'la':pv[1],'lo':pv[2],'lines':pv[4]}); nd+=1
print(f'תחנות: חדשות {ns} | בוטלו {nd} | שם {nr} | מיקום {nm} | שינוי עיר {ncty} | יעד-לפרסום {npd_t}')

# ---- אינדקס + מצב ----
# האינדקס כולל את כל הווריאנטים שיש להם קובץ — גם כאלה שכבר לא ברישום
# (קווים מבוטלים חייבים להישאר ניתנים לחיפוש ולסינון לפי קטגוריה).
# ks = סוגי השינויים שיש לקו, lk/ld = הרשומה האחרונה (לסטטוס "מבוטל").
def idx_entry(rdesc, line, dest, op, ty, tt=None):
    vs = materialize(jload(f'{OUTDIR}/lines/{fsafe(rdesc)}.json', {})).get('versions', [])
    e = {'rd': rdesc, 'line': line, 'dest': dest[:80], 'op': op, 'ty': ty, 'v': len(vs)}
    if tt: e['tt'] = tt      # סוג תחבורה שאינו אוטובוס — לסינון באתר
    ks = {v['k'] for v in vs if v['k'] != 'baseline'}
    # גרסאות ארכיון שהועשרו בהפרשי תחנות (enrich_stop_diffs) נספרות גם
    # בקטגוריות התחנות — אחרת ההיסטוריה של 2022–2026 לא מופיעה שם בכלל
    for v in vs:
        if (v.get('src') == 'ob' or v.get('gd')) and v.get('k') != 'removed':
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
    idx.append(idx_entry(rdesc, c['line'], c['long'], c['op'], c['ty'], c.get('tt')))
seen_rd={e['rd'] for e in idx}
for fn in os.listdir(f'{OUTDIR}/lines'):
    if not fn.endswith('.json'): continue
    lf=materialize(jload(f'{OUTDIR}/lines/{fn}',{}))
    rdesc=lf.get('rd')
    if not rdesc or rdesc in seen_rd: continue
    # קובץ שאין לו מצב: אם הווריאנט נעלם מהרישום לגמרי ועוד לא סומן מבוטל —
    # רושמים ביטול. אם הוא עדיין רשום (בלי נסיעות פעילות) הוא נשאר חי.
    vs=lf.get('versions',[])
    # רק על מה שהסורק היומי באמת ראה חי הוא יכול להעיד שנעלם. קווים
    # שנוצרו ממילוי הארכיון (רכבת, מוניות, וריאנטים היסטוריים) מעולם לא
    # היו במצב היומי — סימונם "בוטל היום" היה קובע תאריך ביטול שגוי בשנים,
    # במקום התאריך שבו הם באמת נעלמו מהפיד.
    if not first_run and rdesc in prev and rdesc not in registered \
       and rdesc not in carry and vs and vs[-1].get('k')!='removed':
        vs.append({'d':TODAY,'k':'removed','shp':'','stops':[],'note':'הווריאנט נעלם מהרישום'})
        json.dump(lf,open(f'{OUTDIR}/lines/{fn}','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
        chm['changes'].append({'d':TODAY,'rd':rdesc,'line':lf.get('line',''),'k':'removed'})
    idx.append(idx_entry(rdesc, lf.get('line',''), lf.get('dest') or '', lf.get('op',''), lf.get('ty',''), lf.get('tt')))
idx.sort(key=lambda x:(x['line'],x['rd']))
json.dump({'gen':TODAY,'first':first_run,'lines':idx},
          open(f'{OUTDIR}/lines.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(chm,open(chpath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
# ---- תחנות יעד לפרסום (בקשת שלמה): התחנה שכתובה על שלט האוטובוס.
# הזיהוי לפי מק"ט התחנה האחרונה של כל מסלול פעיל — לא לפי השוואת שמות
# (שם השלט מקוצר מול שם הרישום, ורק 14% תאמו). אירוע נרשם על התחנה
# עצמה כשהיא הופכת/חדלה להיות יעד. בריצה הראשונה רק נשמר מצב.
_pdst_path=f'{OUTDIR}/pubdest-state.json'
_pdraw=jload(_pdst_path,None)
if isinstance(_pdraw,dict) and _pdraw.get('v')==2:
    _pdst_prev=_pdraw.get('stops'); _prd_prev=_pdraw.get('rds') or {}
else:
    _pdst_prev=_pdraw; _prd_prev={}
    if _pdst_prev and any('|' in k for k in list(_pdst_prev)[:5]):
        _pdst_prev=None   # פורמט ישן (מפתח שם) — בסיס חדש בלי אירועי-סרק
_pdst={}; _prd={}
for _rd,_c in cur.items():
    if _c.get('codes'):
        _pdst.setdefault(str(_c['codes'][-1]),set()).add(_c['line'])
        _prd[_rd]=[str(_c['codes'][-1]),_c['line']]
_pdst={k:sorted(v)[:12] for k,v in _pdst.items()}
if _pdst_prev is not None and not first_run and not REBASE:
    # מה השינוי בפועל (בקשת שלמה): לכל מסלול שהיעד שלו זז — מאיפה לאן
    _sname=lambda c0:(cur_stops.get(c0) or (prev_stops.get(c0) if isinstance(prev_stops.get(c0),list) else None) or [''])[0]
    _mvin={};_mvout={}
    for _rd,_v2 in _prd.items():
        _o=_prd_prev.get(_rd)
        if not _o or _o[0]==_v2[0]: continue
        _p=[_v2[1],_sname(_o[0])]
        if _p not in _mvin.setdefault(_v2[0],[]): _mvin[_v2[0]].append(_p)
        _p=[_v2[1],_sname(_v2[0])]
        if _p not in _mvout.setdefault(_o[0],[]): _mvout[_o[0]].append(_p)
    for _c0 in _pdst.keys()-_pdst_prev.keys():
        _v=cur_stops.get(_c0)
        if _v:
            _e={'k':'pubdest','n':_v[0],'t':_v[3],'la':_v[1],'lo':_v[2],
                'st':'in','ln':_pdst[_c0][:8]}
            if _mvin.get(_c0): _e['mv']=_mvin[_c0][:6]
            sev(_c0,_e); npd_t+=1
    for _c0 in _pdst_prev.keys()-_pdst.keys():
        _v=cur_stops.get(_c0) or (prev_stops.get(_c0) if isinstance(prev_stops.get(_c0),list) else None)
        if _v:
            _e={'k':'pubdest','n':_v[0],'t':_v[3] if len(_v)>3 else '','la':_v[1],'lo':_v[2],
                'st':'out','ln':(_pdst_prev.get(_c0) or [])[:8]}
            if _mvout.get(_c0): _e['mv']=_mvout[_c0][:6]
            sev(_c0,_e); npd_t+=1
json.dump({'v':2,'stops':_pdst,'rds':_prd},open(_pdst_path,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))

json.dump(stm,open(spath,'w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(shist,open(f'{OUTDIR}/stops-hist.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
# 'tt' נשמר כדי שאפשר יהיה לזהות שינוי בסוג הקו. במצב שנוצר לפני השדה הזה
# הוא פשוט חסר, ולכן ההשוואה מדלגת בשקט בריצה הראשונה ולא ממציאה אירוע.
state_out={rdesc:{'sh_h':c['sh_h'],'st_h':c['st_h'],'codes':c['codes'],'line':c['line'],
                  'op':c['op'],'tt':c.get('tt'),'ty':c.get('ty',''),'wa':c.get('wa',''),'pd_h':c.get('pd_h',''),
                  'hs':c.get('hs',''),'ct':c.get('ct','')}
           for rdesc,c in cur.items()}
state_out.update(carry)   # רשומים ללא נסיעות פעילות — נגררים קדימה
json.dump(state_out,
          open(f'{OUTDIR}/state-routes.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
json.dump(cur_stops,open(f'{OUTDIR}/stops-state.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
# מספר הנסיעות משתנה מיום ליום, ולכן הוא יושב בקובץ צדדי אחד ולא בתוך
# 13,000 קובצי הקווים — אחרת כל ריצה יומית הייתה משנה את כולם.
json.dump({k:v for k,v in sorted(_ntr.items()) if k.count('-')>=2},
          open(f'{OUTDIR}/line-trips.json','w',encoding='utf-8'),ensure_ascii=False,separators=(',',':'))
mons=sorted({f[8:15] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')})
json.dump({'months':sorted({f[:7] for f in os.listdir(f'{OUTDIR}/changes') if re.match(r'^\d{4}-\d{2}\.json$',f)},reverse=True),
           'stopMonths':sorted({f[6:13] for f in os.listdir(f'{OUTDIR}/changes') if f.startswith('stops-')},reverse=True)},
          open(f'{OUTDIR}/months.json','w',encoding='utf-8'),ensure_ascii=False)
# ערכים שלא הכרנו — מתריעים ברעש. דילוג שקט על סוג חדש הוא בדיוק מה
# שהקפיא את הסיווג של 3,046 קווים במרץ 2023.
new_unk=unk.flush()
if new_unk:
    for kind,vals in new_unk.items():
        for v,d in vals.items():
            print(f'::warning::ערך לא מוכר ב-{kind}: {v} ({d["n"]} פעמים, למשל {d["ex"][:2]})')
    print('פירוט מלא:',f'{OUTDIR}/unknown-values.json')
print('נכתב הכול תחת',OUTDIR)
