# -*- coding: utf-8 -*-
# מסווג את תחנות ה-GTFS לקטגוריות אי-התאמה ומפיק next-station/data.json.
# קלט (נתיבים דרך משתני סביבה, ברירת מחדל = תיקייה נוכחית):
#   STOPS=stops.txt  POI=poi.json  ROADS=roads.json  ACTIVE=active_stops.txt
#   PREV=<data.json קודם> — אם קיים, מעתיק ממנו זמני-הליכה (rt) כדי לא לאבד אותם בריצה שבועית
#   OUT=next-station/data.json
import csv, re, json, math, time, os, datetime, hashlib
t0=time.time()
STOPS=os.environ.get('STOPS','stops.txt'); POI=os.environ.get('POI','poi.json')
ROADS=os.environ.get('ROADS','roads.json'); ACTIVE_PATH=os.environ.get('ACTIVE','active_stops.txt')
PREV=os.environ.get('PREV',''); OUT=os.environ.get('OUT','next-station/data.json')
# תחנות שאושרו ידנית כ"לא תקלה" (מדיווחי משתמשים) — המסווג מדלג עליהן
OVR={}
_ovr=os.environ.get('OVERRIDES','next-station/overrides.json')
if os.path.exists(_ovr):
    try:
        for k,v in json.load(open(_ovr)).items():
            if k.startswith('_'): continue
            OVR[k]=v if isinstance(v,dict) else {'note':v}
    except Exception as e: print('overrides load failed:',e)

PREF=['שדרות','שדרת',"שד'",'שד','רחוב',"רח'",'רח','דרך','סמטת','סמטה',"סמ'",'שכונת',"שכ'",'כיכר','ככר','מחלף','כביש']
TITLES={'הרב','רב','דר','דוקטור','פרופ','השר','ראל','אלוף','סרן','הנשיא','מר','גנרל','בי"ס','ביה"ס','בית','ספר','גן','קניון'}
# מוקדים "מרכזיים" שראויים לשמש שם תחנה (עד 100 מ׳)
MAJOR_POI={'train','busstation','mall','health','academia','gov','culture','cemetery','hood'}
# "הצעות כלליות": הרחוב המצטלב בשם רחוק מהתחנה (>=CLOSER_FAR מ׳ / לא נמצא בקרבת מקום),
# בעוד רחוב אחר עובר ממש לידה (<=CLOSER_CAP מ׳) ובהפרש מוחשי (>=CLOSER_GAP מ׳).
CLOSER_CAP=24
CLOSER_FAR=45
CLOSER_GAP=30
def sp(t):
    t=t.strip()
    for p in PREF:
        if t.startswith(p+' '): return t[len(p):].strip()
    return t
def nl(t):
    # מקף ≡ רווח ("ג'יסר א-נסף" ↔ "ג'סר א נסף") — אחרת ההשוואה מתפרקת על המקף
    t=(t or '').strip().replace('-',' ').replace('–',' ')
    t=sp(t).replace('׳',"'").replace('״','"').replace("'",'').replace('"','')
    return re.sub(r'\s+',' ',t).strip()
def nf(t): return nl(t).replace('יי','י').replace('וו','ו')
def tk(s): return [w for w in s.split() if w not in TITLES and len(w)>1]
def lev(a,b):
    if abs(len(a)-len(b))>2: return 9
    pv=list(range(len(b)+1))
    for i,ca in enumerate(a,1):
        cur=[i]
        for j,cb in enumerate(b,1): cur.append(min(pv[j]+1,cur[-1]+1,pv[j-1]+(ca!=cb)))
        pv=cur
    return pv[-1]
# ראשי-תיבות: קק"ל ↔ קרן קיימת לישראל — הטוקן (עם גרשיים במקור) שווה לראשי המילים.
# זיהוי גנרי, בלי מילון: אותיות הר"ת (בנרמול סופיות) == אות ראשונה של כל מילה בביטוי.
_FIN=str.maketrans('םןץףך','מנצפכ')
def _initials(phrase):
    # שתי גרסאות: כמו-שהוא, וגם בדילוג על ה' הידיעה בראש מילה
    # (קק"ל ↔ "הקרן הקיימת לישראל": ק-ק-ל אחרי הסרת ה-ה)
    ws=[w for w in re.sub('[\"׳״\'-]',' ',phrase).split() if len(w)>=2]
    if len(ws)<2: return ()
    strict=''.join(w[0] for w in ws)
    noart=''.join((w[1] if w[0]=='ה' and len(w)>=3 else w[0]) for w in ws)
    return {strict.translate(_FIN),noart.translate(_FIN)}
def acr_same(a,b):
    for t in re.split(r'[\s/]+',a or ''):
        if not re.search('[\"׳״\']',t): continue  # ר"ת אמיתי מכיל גרשיים/גרש
        t2=re.sub('[\"׳״\']','',t).translate(_FIN)
        if 3<=len(t2)<=5 and t2 in _initials(b or ''): return True
    return False
def rel(tok,act):
    if not tok or not act: return None
    if nl(tok)==nl(act): return 'exact'
    if acr_same(tok,act) or acr_same(act,tok): return 'exact'
    if nf(tok)==nf(act): return 'spelling'
    if any(len(t)>=3 for t in set(tk(nl(tok)))&set(tk(nl(act)))): return 'exact'
    if nl(tok) in nl(act) or nl(act) in nl(tok): return 'exact'
    a2,b2=tk(nf(tok)),tk(nf(act))
    # definite article ה ("מעפילים" vs "המעפילים") is a grammatical variant, not a spelling error
    if a2 and b2 and (a2[-1]=='ה'+b2[-1] or b2[-1]=='ה'+a2[-1]): return 'exact'
    if a2 and b2 and lev(a2[-1],b2[-1])<=2 and max(len(a2[-1]),len(b2[-1]))>=4: return 'spelling'
    return None
def fuzzy_in(t,toks):
    for b in toks:
        if t==b or (max(len(t),len(b))>=4 and lev(t,b)<=1): return True
    return False
def same_street(a,b):
    ta=tk(nf(a)); tb=tk(nf(b))
    if not ta or not tb or len(ta)==len(tb): return False
    short,lng=(ta,tb) if len(ta)<len(tb) else (tb,ta)
    return all(fuzzy_in(t,lng) for t in short)
def ktiv_only(a,b):
    sa=re.sub('[יו]','',nf(a)); sb=re.sub('[יו]','',nf(b))
    return sa==sb and len(sa)>=3
def abbrev_pair(a,b):
    # קיצור, לא טעות כתיב: "לדזינסקי" מול "עובד לדיז'נסקי" — פסק ה'spelling'
    # הגיע מהשוואת המילה האחרונה בלבד, אבל צד אחד השמיט מילים מהשם המלא.
    # טעות כתיב אמיתית = אותו מספר מילים והבדל אות; מספר מילים שונה = קיצור -> ספק
    return len(tk(nf(a)))!=len(tk(nf(b)))
def cn(s): return re.sub(r'\s*/\s*',' / ',re.sub(r'\s+',' ',(s or '').strip()))  # שם-תחנה מנורמל להשוואה
# שם על-שם מוסד/ציון-דרך (מרפאה, בית ספר, הישיבה...) — שם תחנה תקין, לא טעות "היפוך".
LANDMARK_WORDS=('מרכז','בית ','בית ספר','ביהס','ביס','גן ','גן ילדים','מרפאה','קופח','קופ','קופת חולים',
  'מקווה','מקוה','בית כנסת','בית הכנסת','ביהכנס','ביכ','בית מדרש','ביהמד','ישיבה','הישיבה','ישיבת',
  'תלמוד תורה','תת ','חיידר','כולל','מתנס','מתנ','מתחם','צרכני','מכולת','מכלל','מועצה','מזכירות',
  'קניון','תחנה מרכזית','ת מרכזית','תחנת','בית חולים','ביהח','אולפנה','סמינר','מסגד','כנסי','היכל',
  'בריכה','אצטדיון','מוזיאון','תיכון','חטב','בית אבות','מעון','פנימי','אולם ספורט',
  'שכונה','שכונת','צומת','מסוף','מסעף','פארק','חוף','מועדון','מלון','מפעל','אזור','קרית','קריית','מגדל',
  'מגרש','מכון','מחנה','תמרכזית','עיריה','עירייה','עירית','עיריית','שוק','רמת','גבעת',
  'עלמין','העלמין','בית עלמין','בית קברות','הקברות','קבר ','הר ','מעבר ','מחסום')
def landmark_name(s):
    # מקף הופך לרווח ("בית-עלמין" ≡ "בית עלמין"); גרשיים/נקודות נמחקים.
    # מחזירה את מילת ציון-הדרך שנמצאה (למשל "צומת") — לתצוגה מדויקת באתר
    s=re.sub(r'\s+',' ',re.sub('[\"׳״.]','',(s or '')).replace('-',' ').replace("'",'')).strip()
    for w in LANDMARK_WORDS:
        if s==w.strip() or s.startswith(w) or (' '+w) in (' '+s): return w.strip()
    return None
# השוואת רחובות עמידה למקפים/גרשיים/כתיב מלא (לזיהוי "הצעות כלליות" בלבד)
def streets_match(a,b):
    a=(a or '').replace('-',' '); b=(b or '').replace('-',' ')
    return rel(a,b) in ('exact','spelling') or same_street(a,b) or ktiv_only(a,b)
# כתובות תיאוריות (מחלף/יציאה/מסוף…) אינן רחוב — לא מציעים להן רחוב חלופי
LANDMARKISH=('מחלף','יציאה','כניסה','מסוף','צומת','כביש ','מגרש','מיתחם','מתחם','פארק','פאתי','תחנת','ת. ')
_AR=re.compile(r'[؀-ۿ]')  # שם רחוב בכתב ערבי — לא ניתן להשוות מול שם עברי ב-GTFS
# שם שאינו עברית שמישה (כתב ערבי / לטיני / מספרי) — לא מציעים אותו כשם תחנה
# "רחוב מוזר" — לא מציעים אותו לעולם כשם: כתב ערבי/לטיני, מספרי בלבד,
# או כביש ממוספר ("כביש 411") — האחרון משמש לזיהוי בלבד, לא כהצעת שינוי
def odd_road(nm): return bool(_AR.search(nm or '')) or bool(re.search(r'[A-Za-z]',nm or '')) or bool(re.fullmatch(r'[\d/ ]+',(nm or '').strip())) or bool(re.fullmatch(r'כביש \d+',(nm or '').strip()))
def acronymish(s): return bool(re.search(r'["׳״]|\x27\x27', s or ''))  # ר"ת (קק"ל) ש-OSM נוטה לפענח
# שם רחוב ערבי בתעתיק עברי (אל-/אבו/ואדי…): אותו רחוב מתועתק אחרת ב-GTFS ובמפה,
# ולכן השוואת רחובות אינה אמינה — לא מציעים "רחוב קרוב יותר" במקרים אלה.
_ARTOK={'אל','אבו','אום','ביר','ואדי','דיר','אא'}
def arabic_translit(s):
    s=(s or '').strip()
    if not s: return False
    if s.startswith(('אל-','א-','אל ')): return True
    t=s.split()
    return bool(t) and t[0] in _ARTOK
def street(d):
    m=re.search(r'רחוב:\s*(.*?)\s*עיר:', d or ''); return re.sub(r'\s+\d+[א-ת]?$','',m.group(1).strip()).strip() if m else ''
def city(d):
    m=re.search(r'עיר:\s*(.*?)\s*רציף:', d or ''); return m.group(1).strip() if m else ''
def named_after_city(name,c):
    if not c or len(c)<3: return False
    return nl(c).replace('-',' ') in nl(name).replace('-',' ')
_poisrc=json.load(open(POI)); poi=_poisrc['poi']; GP={}
for p in poi: GP.setdefault((round(p['la']/0.001),round(p['lo']/0.001)),[]).append(p)
def hav(a,b,c,d):
    Rr=6371000; pr=math.pi/180
    return 2*Rr*math.asin(math.sqrt(math.sin((c-a)*pr/2)**2+math.cos(a*pr)*math.cos(c*pr)*math.sin((d-b)*pr/2)**2))
def nearby(la,lo,rad=500):
    if la is None: return []
    rng=int(rad/110)+1  # תאי-רשת של ~110 מ׳ — מכסים את הרדיוס המבוקש
    res=[]; ck=(round(la/0.001),round(lo/0.001)); R=range(-rng,rng+1)
    for dx in R:
        for dy in R:
            for p in GP.get((ck[0]+dx,ck[1]+dy),[]):
                dd=hav(la,lo,p['la'],p['lo'])
                if dd<=rad: res.append((round(dd),p))
    res.sort(key=lambda x:x[0]); return res
# שטחים גדולים (בית עלמין, פארק, שכונה) — המרחק נמדד למרכז השטח, לכן תחנה
# בשולי בית העלמין בהר הזיתים יוצאת "549 מ׳" ממנו; להם מותר רדיוס גדול יותר
_AREA_POI={'cemetery','park','hood'}
def name_matches_poi(name,plist):
    nt=[t for t in tk(nf(name)) if len(t)>=3]
    for dist,p in plist:
        if dist>(800 if p['k'] in _AREA_POI else 500): continue
        for a in nt:
            for b in [t for t in tk(nf(p['n'])) if len(t)>=3]:
                if a==b or (max(len(a),len(b))>=4 and lev(a,b)<=1): return p
    return None
_rdsrc=json.load(open(ROADS)); RD=_rdsrc['roads']; CELL=0.003; GR={}
for ri,rd in enumerate(RD):
    g=rd['g']
    for i in range(len(g)-1):
        for pt in (g[i],g[i+1]): GR.setdefault((int(pt[0]/CELL),int(pt[1]/CELL)),[]).append((ri,i))
def segdist(plat,plon,a,b):
    cl=math.cos(math.radians(plat))
    ax=(a[1]-plon)*111320*cl; ay=(a[0]-plat)*110540; bx=(b[1]-plon)*111320*cl; by=(b[0]-plat)*110540
    dx=bx-ax; dy=by-ay
    if dx==0 and dy==0: return math.hypot(ax,ay)
    tt=max(0.0,min(1.0,-(ax*dx+ay*dy)/(dx*dx+dy*dy)))
    return math.hypot(ax+tt*dx, ay+tt*dy)
def nearest_roads(la,lo,topn=4):
    if la is None: return []
    ck=(int(la/CELL),int(lo/CELL)); cands={}; seen=set()
    for dx in(-1,0,1):
        for dy in(-1,0,1):
            for ri,i in GR.get((ck[0]+dx,ck[1]+dy),[]):
                if (ri,i) in seen: continue
                seen.add((ri,i)); g=RD[ri]['g']; d=segdist(la,lo,g[i],g[i+1]); nm=RD[ri]['n']; key=nf(nm)
                if key not in cands or d<cands[key][0]: cands[key]=(d,nm)
    return [(nm,round(d)) for d,nm in sorted(cands.values())[:topn]]
def road_near(la,lo,name,rad=150):
    # גאומטריית הרחוב (קטע סמוך לתחנה) + הנקודה הקרובה ביותר — לסימון על המפה
    key=nf(name); best=None; ck=(int(la/CELL),int(lo/CELL))
    for dx in(-1,0,1):
        for dy in(-1,0,1):
            for ri,i in GR.get((ck[0]+dx,ck[1]+dy),[]):
                if nf(RD[ri]['n'])!=key: continue
                g=RD[ri]['g']; d=segdist(la,lo,g[i],g[i+1])
                if best is None or d<best[1]: best=(ri,d)
    if best is None: return None
    ri,d=best; g=RD[ri]['g']
    pts=[[round(p[0],5),round(p[1],5)] for p in g if hav(la,lo,p[0],p[1])<=rad]
    npt=min(g,key=lambda p:hav(la,lo,p[0],p[1]))
    if len(pts)<2: pts=[[round(npt[0],5),round(npt[1],5)]]
    return {'n':RD[ri]['n'],'d':round(d),'pt':[round(npt[0],5),round(npt[1],5)],'g':pts}
print('indexes built %.1fs'%(time.time()-t0))
rows=list(csv.reader(open(STOPS,encoding='utf-8-sig')))
ix={h:i for i,h in enumerate(rows[0])}
SN,SD,SC,LA,LO,SI=ix['stop_name'],ix['stop_desc'],ix['stop_code'],ix['stop_lat'],ix['stop_lon'],ix['stop_id']
ACTIVE=None
if os.path.exists(ACTIVE_PATH):
    ACTIVE=set(l.strip() for l in open(ACTIVE_PATH) if l.strip()); print('active stop_ids:',len(ACTIVE))
PREVRT={}; PREVRW={}; PREVERR={}
ERRCATS=('mismatch','reversal','spelling','streetvar')
if PREV and os.path.exists(PREV):
    try:
        pd=json.load(open(PREV))
        for s in pd.get('stops',[]):
            for p in s.get('p',[]):
                if p.get('rt'): PREVRT[(s['c'],p['n'])]=p['rt']
            if s.get('k')=='closer' and s.get('rw'): PREVRW[s['c']]=s['rw']
            # תחנות שסומנו כשגיאה בריצה הקודמת — לזיהוי תיקונים אמיתיים במקור
            if s.get('k') in ERRCATS: PREVERR[s['c']]={'n':s['n'],'s':s['s'],'t':s.get('t',''),'k':s['k']}
        print('carried-forward rt:',len(PREVRT),'| closer rw:',len(PREVRW),'| prev errors:',len(PREVERR))
    except Exception as e: print('prev load failed:',e)
from collections import defaultdict, Counter
def norm_ref(part):
    t=part.replace('-',' ').replace('.',' ').replace('׳',"'").replace('״','"').replace("'",'').replace('"','')
    return sp(re.sub(r'\s+',' ',t).strip()).strip()
def strip_seg(s): return re.sub(r'\s[א-ת]$','',s).strip()
def seg_diff(a,b):
    sa,sb=strip_seg(a),strip_seg(b)
    return (sa!=a or sb!=b) and nl(sa)==nl(sb)
_grp=defaultdict(list)
for r in rows[1:]:
    if len(r)<=SD: continue
    nm=r[SN]; stt=street(r[SD]); cc=city(r[SD])
    if not stt or re.fullmatch(r'[\d ]+',stt) or not cc: continue
    for p in re.split(r'[\\/]',nm):
        if rel(p,stt) in ('exact','spelling'):
            _grp[(cc,nf(stt))].append((r[SC],re.sub(r'\s+',' ',p).strip(),norm_ref(p))); break
STREETVAR={}
for key,lst in _grp.items():
    c2=Counter(ref for _,_,ref in lst)
    if len(c2)<2: continue
    top,topn=c2.most_common(1)[0]
    if topn==c2.most_common(2)[1][1]: continue
    maj_raw=Counter(raw for _,raw,ref in lst if ref==top).most_common(1)[0][0]
    tt=len(top.split())
    for code2,raw,ref in lst:
        if ref==top or seg_diff(ref,top): continue
        if abs(len(ref.split())-tt)<=1 or nf(ref)==nf(top): STREETVAR[code2]=(raw,maj_raw,topn)
print('street-variance flags:',len(STREETVAR))
cnt={'exact':0,'settlement':0,'spelling':0,'streetvar':0,'uncertain':0,'reversal':0,'mismatch':0,'landmark':0,'mapok':0,'noaddr':0,'closer':0}
suspects=[]; closer_cands=[]
EXIST=defaultdict(set)  # שמות-תחנות קיימים לכל עיר — לבדיקת התנגשות שמות מוצעים
CURINFO={}  # code -> (name, street) נוכחיים — לזיהוי תיקונים אמיתיים מול הריצה הקודמת
for r in rows[1:]:
    if len(r)<=SD: continue
    name,desc,code=r[SN],r[SD],r[SC]; st=street(desc); c=city(desc)
    CURINFO[code]=(name,st)
    if c: EXIST[c].add(cn(name))
    _ov=OVR.get(code)
    # האישור מותנה בשם: השתנה שם התחנה ב-GTFS — האישור פג והיא נבדקת מחדש
    if _ov and _ov.get('n')==name: cnt['exact']+=1; continue
    try: la=round(float(r[LA]),5); lo=round(float(r[LO]),5)
    except: la=lo=None
    realstreet=st and not re.fullmatch(r'[\d ]+',st)
    if not realstreet:
        cnt['settlement' if named_after_city(name,c) else 'noaddr']+=1; continue
    parts=re.split(r'[\\/]',name); prim,cross=parts[0],(parts[1] if len(parts)>1 else '')
    sv=STREETVAR.get(code)
    samestreet=rel(prim,st)=='exact' or same_street(prim,st) or (cross and same_street(cross,st))
    if samestreet and not sv:
        # הצעות כלליות: הרחוב המצטלב בשם התחנה ("ראשי/מצטלב") אינו הרחוב הקרוב ביותר —
        # יש רחוב אחר שעובר קרוב יותר לתחנה, וכדאי שהוא יופיע בשם במקומו.
        nr8=nearest_roads(la,lo,8)
        if (la is not None and nr8 and not any(w in st for w in LANDMARKISH)
                and not acronymish(st) and not arabic_translit(st)):
            # הרחוב הקרוב ביותר שאינו הרחוב הראשי (prim) ואינו רעש (ערבית/מספרי)
            best=None
            for nm2,dd in nr8:
                if (not odd_road(nm2) and not arabic_translit(nm2)
                        and not streets_match(nm2,prim)):
                    best=(nm2,dd); break
            # מרחק הרחוב המצטלב שבשם (None אם אין בשם / אינו בין הרחובות הסמוכים)
            cross_d=None
            if cross and not arabic_translit(cross):
                for nm2,dd in nr8:
                    if streets_match(nm2,cross): cross_d=dd; break
            # מציעים רק כשיש רחוב מצטלב בשם והוא שגוי באופן מובהק: רחוב אחר עובר ממש
            # ליד התחנה (<=CLOSER_CAP), בעוד המצטלב שבשם רחוק (לא נמצא, או >=CLOSER_FAR
            # ובהפרש >=CLOSER_GAP מהרחוב הקרוב).
            flag=False
            if cross and best and best[1]<=CLOSER_CAP and not streets_match(best[0],cross):
                if cross_d is None: flag=best[1]<=20
                else: flag=cross_d>=CLOSER_FAR and (cross_d-best[1])>=CLOSER_GAP
            if flag:
                near_name,near_d=best
                primc=parts[0].strip()
                # פורמט שמות התחנות בישראל: "X/Y" בלי רווחים סביב הלוכסן
                sugname=primc+'/'+near_name
                nb=nearby(la,lo)
                pois=[]
                for dist,p in nb:
                    if dist>300: continue
                    if len(pois)>=3: break
                    pr={'n':p['n'],'k':p['k'],'d':dist,'la':p['la'],'lo':p['lo']}
                    rt=PREVRT.get((code,p['n']))
                    if rt: pr['rt']=rt
                    pois.append(pr)
                # שם מוצע לפי מבנה ציבור מרכזי סמוך (עד 100 מ׳); לא מציעים שם בכתב ערבי
                psug=psugd=None
                for dist,p in nb:
                    if dist>100: break
                    if p['k'] in MAJOR_POI and nf(p['n']) not in nf(name) and not odd_road(p['n']):
                        psug=p['n']; psugd=dist; break
                # גאומטריית הרחובות לסימון על המפה: ראשי, מצטלב נוכחי, ומוצע
                roads={}
                rp=road_near(la,lo,primc)
                if rp: roads['prim']=rp
                if cross:
                    rc=road_near(la,lo,parts[1].strip())
                    if rc: roads['cur']=rc
                rsug=road_near(la,lo,near_name)
                if rsug: roads['sug']=rsug
                rec={'c':code,'n':name,'s':st,'t':c,'la':la,'lo':lo,'k':'closer',
                     'p':pois,'ms':near_name,'md':near_d,'sug':sugname,
                     'cur':(parts[1].strip() if cross else None),'curd':cross_d,'roads':roads}
                if psug: rec['psug']=psug; rec['psugd']=psugd
                if ACTIVE is not None and r[SI] not in ACTIVE: rec['act']=False
                # מאומת לפי הליכה אמיתית בשלב שאחרי הלולאה (לא חוסם את הסיווg)
                closer_cands.append(rec); continue
        cnt['exact']+=1; continue
    if samestreet: cat='streetvar'
    elif rel(prim,st)=='spelling': cat='uncertain' if (ktiv_only(prim,st) or abbrev_pair(prim,st)) else 'spelling'
    elif cross and rel(cross,st) in ('exact','spelling'):
        cat='uncertain' if rel(cross,st)=='spelling' and ktiv_only(cross,st) else 'reversal'
    elif named_after_city(name,c): cnt['settlement']+=1; continue
    else: cat='mismatch'
    if sv and cat in ('spelling','uncertain'): cat='streetvar'
    nr=nearest_roads(la,lo,4); ms,md=(nr[0] if nr else (None,None))
    # השם תואם כביש/רחוב שעובר ליד התחנה (עד 120 מ׳, לאו דווקא הקרוב ביותר,
    # כולל "כביש 411" ממוספר) — השם תקין, לא מוצגת
    if cat in ('reversal','mismatch') and any(dd<=120 and rel(prim,nm2) in ('exact','spelling') for nm2,dd in nr):
        cnt['mapok']+=1; continue
    nb=nearby(la,lo,800)  # רדיוס רחב — לשטחים גדולים; הסינונים בהמשך (100/300 מ׳) לא מושפעים
    # קרויה על-שם מקום אמיתי סמוך (POI) — שם תקין, לא מוצגת כלל
    if cat in ('reversal','mismatch') and name_matches_poi(prim,nb): cnt['landmark']+=1; continue
    # שם על-שם מוסד/ציון-דרך ("מרפאה", "הישיבה/רמב''ם") בלי POI תואם — לספק, בלי הצעת-שינוי.
    # רץ אחרי בדיקת ה-POI, כדי ש"מרכז ביג קסטינה" ליד הקניון ייעלם ולא יסומן בכלל.
    lm=landmark_name(prim) if cat in ('reversal','mismatch') else None
    if lm: cat='uncertain'
    cnt[cat]+=1
    sug=None
    # לא מציעים שם שאינו עברית (כתב ערבי/מספרי): אם הרחוב הקרוב ביותר כזה — אין הצעה
    if nr and cat not in ('uncertain','streetvar') and not odd_road(nr[0][0]):
        s1=nr[0][0]; s2=None
        for nm2,dd in nr[1:]:
            if dd<=60 and nf(nm2)!=nf(s1) and not odd_road(nm2): s2=nm2; break
        cand=(s1+'/'+s2) if s2 else s1
        if nf(cand)!=nf(name): sug=cand
    # שם מוצע לפי מוקד מרכזי (POI גדול) עד 100 מ׳ — תחנות נקראות לעיתים ע"ש מוסד סמוך
    psug=psugd=None
    for dist,p in nb:
        if dist>100: break  # nb ממויין לפי מרחק
        if p['k'] in MAJOR_POI and nf(p['n']) not in nf(name) and not odd_road(p['n']):
            psug=p['n']; psugd=dist; break
    pois=[]
    for dist,p in nb:
        if dist>300: continue
        if len(pois)>=3: break
        pr={'n':p['n'],'k':p['k'],'d':dist,'la':p['la'],'lo':p['lo']}
        rt=PREVRT.get((code,p['n']))
        if rt: pr['rt']=rt
        pois.append(pr)
    rec={'c':code,'n':name,'s':st,'t':c,'la':la,'lo':lo,'k':cat,'p':pois,'ms':ms,'md':md}
    if lm: rec['lm']=1; rec['lmw']=lm  # ספק מסוג "שם-מוסד/ציון-דרך" + המילה שזוהתה (צומת, שכונה...)
    if sug: rec['sug']=sug
    if psug: rec['psug']=psug; rec['psugd']=psugd
    if sv: rec['sv']={'use':sv[0],'maj':sv[1],'n':sv[2]}
    if ACTIVE is not None and r[SI] not in ACTIVE: rec['act']=False
    suspects.append(rec)

# הצעות כלליות: שם מוצע חדש שחוזר על עצמו (כמו 12 תחנות → אותו שם) הוא חסר-תועלת,
# כי הוא לא מבדיל בין התחנות — לכן בקטגוריה הזו בלבד מסירים הצעה כפולה. בקטגוריות
# השגיאה משאירים הכל כפי שהוא (זה בסדר ששתי תחנות חולקות שם).
csug=Counter((rec['t'],cn(rec['sug'])) for rec in closer_cands)
carried=0
for rec in closer_cands:
    if csug[(rec['t'],cn(rec['sug']))]>1 or cn(rec['sug']) in EXIST.get(rec['t'],()):
        cnt['exact']+=1; continue
    rw=PREVRW.get(rec['c'])
    if rw: rec['rw']=rw; carried+=1
    suspects.append(rec); cnt['closer']+=1
print('closer kept:',cnt['closer'],'| rw carried:',carried)
if OVR: print('manual overrides applied:',len(OVR))
print('classification:',cnt)
print('suspects:',len(suspects),'| %.1fs'%(time.time()-t0))
os.makedirs(os.path.dirname(OUT) or '.',exist_ok=True)
json.dump({'generated':datetime.date.today().isoformat(),
  'osm':{'poi':_poisrc.get('generated'),'roads':_rdsrc.get('generated')},
  'counts':cnt,'stops':suspects},
  open(OUT,'w'), ensure_ascii=False, separators=(',',':'))
print('wrote',OUT)
# מעקב "תוקן!": תחנה שסומנה כשגיאה, יצאה מהרשימה, *והטקסט שלה השתנה ב-GTFS* —
# תוקנה באמת במקור (שינוי כללי-סיווג אצלנו לא נספר, כי הטקסט נשאר זהה).
CHANGES=os.environ.get('CHANGES','')
if CHANGES and PREVERR:
    curflag={s['c'] for s in suspects if s['k'] in ERRCATS}
    fixed=[]
    for c0,pv in PREVERR.items():
        if c0 in curflag: continue
        ci=CURINFO.get(c0)
        if not ci: continue  # התחנה הוסרה מה-GTFS — לא "תיקון"
        nm2,st2=ci
        if nm2!=pv['n'] or st2!=pv['s']:
            fixed.append({'c':c0,'t':pv['t'],'k':pv['k'],'on':pv['n'],'os':pv['s'],'nn':nm2,'ns':st2})
    try: ch=json.load(open(CHANGES))
    except Exception: ch=[]
    today=datetime.date.today().isoformat()
    ch=[e for e in ch if e.get('d')!=today]
    if fixed: ch.append({'d':today,'fixed':fixed})
    json.dump(ch[-60:],open(CHANGES,'w'),ensure_ascii=False,separators=(',',':'))
    print('source fixes detected:',len(fixed))

# היסטוריית ספירות — רשומה אחת ליום (ריצה אחרונה באותו יום גוברת), למעקב מגמות באתר
HIST=os.environ.get('HISTORY','')
if HIST:
    try: hist=json.load(open(HIST))
    except Exception: hist=[]
    today=datetime.date.today().isoformat()
    hist=[h for h in hist if h.get('d')!=today]
    # v = טביעת-אצבע של קובץ זה; המגמה באתר מושווית רק בין ריצות עם אותם כללים,
    # כדי ששינויי-סיווג שלנו לא ייראו כאילו משרד התחבורה תיקן/קלקל.
    rv=hashlib.sha1(open(__file__,'rb').read()).hexdigest()[:8]
    hist.append({'d':today,'c':cnt,'v':rv})
    json.dump(hist,open(HIST,'w'),ensure_ascii=False,separators=(',',':'))
    print('history entries:',len(hist))
