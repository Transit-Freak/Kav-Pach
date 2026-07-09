# -*- coding: utf-8 -*-
# מפת רשת סכמטית v3 — אינטראקטיבית:
# 1) צמתים אמיתיים בלבד (מפגש/התפצלות)  2) יישור לעמודות/שורות משותפות ->
#    קווים ישרים ארוכים כמו בפוסטר  3) קטע משותף = פסים מקבילים יציבים
# 4) לחיצה על קו מדגישה אותו; מוצגות רק תחנות מפתח (מסוף/רכבת/מרכזית)
import json, math, sys, re
from xml.sax.saxutils import escape
from collections import defaultdict, Counter

SRC=sys.argv[1]
OUT=sys.argv[2]
CLUSTER_M=180
AXIS_TOL=300     # צמתים שקואורדינטת ה-X/Y שלהם קרובה מזה — מיושרים לאותה עמודה/שורה
PAL=['#c2185b','#00acc1','#2e7d32','#f9a825','#1565c0','#d32f2f','#7b1fa2','#00897b','#5d4037','#455a64','#e91e63']

d=json.load(open(SRC,encoding='utf-8'))
best={}
for L in d['lines']:
    k=L['num']
    if k not in best or len(L['stops'])>len(best[k]['stops']): best[k]=L
def numkey(n):
    m=re.match(r'(\d+)',n); return (int(m.group(1)) if m else 999,n)
lines=[best[k] for k in sorted(best,key=numkey)]
la0=sum(s[2] for L in lines for s in L['stops'])/sum(len(L['stops']) for L in lines)
cl=math.cos(math.radians(la0))
def xy(la,lo): return (lo*111320*cl, la*110540)

# ---- קיבוץ תחנות לצמתים ----
# ההשוואה מול העוגן (הנקודה הראשונה) ולא מול הצנטרואיד: צנטרואיד נודד מאחד
# בשרשרת פינות שונות לאשכול אחד ויוצר "חזרות לאותו צומת" שלא קיימות במציאות.
clusters=[]
def add_pt(x,y,nm):
    for i,c in enumerate(clusters):
        if math.hypot(c[3][0]-x,c[3][1]-y)<=CLUSTER_M:
            n=len(c[2]); c[0]=(c[0]*n+x)/(n+1); c[1]=(c[1]*n+y)/(n+1); c[2].append(nm); return i
    clusters.append([x,y,[nm],(x,y)]); return len(clusters)-1
def find_pt(x,y):
    # איתור מקבץ קיים בלי לשנות כלום — לשימוש אחרי שלב הבנייה
    best=None
    for i,c in enumerate(clusters):
        dd=math.hypot(c[0]-x,c[1]-y)
        if dd<=CLUSTER_M and (best is None or dd<best[1]): best=(i,dd)
    return best[0] if best else None
routes={}
for L in lines:
    seq=[]
    for s in L['stops']:
        c=add_pt(*xy(s[2],s[3]),s[0])
        if not seq or seq[-1]!=c: seq.append(c)
    routes[L['num']]=seq

# ---- צמתים אמיתיים ----
hopset=defaultdict(set)
for num,seq in routes.items():
    for a,b in zip(seq,seq[1:]): hopset[frozenset((a,b))].add(num)
inc=defaultdict(set)
for h in hopset:
    a,b=tuple(h); inc[a].add(h); inc[b].add(h)
junction=set()
for c,hs in inc.items():
    hs=list(hs)
    if len(hs)!=2 or hopset[hs[0]]!=hopset[hs[1]]: junction.add(c)
for seq in routes.values(): junction.add(seq[0]); junction.add(seq[-1])

# ---- קידום נקודות סטייה לצמתים ----
# ריצה שתחנות הביניים שלה סוטות הרבה מהמיתר בין שני הצמתים (למשל צלילה של
# 700מ' לתוך שכונה, כמו אבני החושן) — התחנה הסוטה ביותר הופכת לצומת, אחרת
# הציור "חותך את הפינה" ומעלים את הצלילה.
DEV_M=380
_changed=True
while _changed:
    _changed=False
    for num,seq in routes.items():
        i=0
        while i<len(seq)-1:
            j=i+1
            while j<len(seq) and seq[j] not in junction: j+=1
            if j>=len(seq): j=len(seq)-1
            a,b=seq[i],seq[j]
            ax,ay=clusters[a][0],clusters[a][1]; bx,by=clusters[b][0],clusters[b][1]
            L2=(bx-ax)**2+(by-ay)**2 or 1.0
            worst=None
            for m in seq[i+1:j]:
                mx,my=clusters[m][0],clusters[m][1]
                t=max(0.0,min(1.0,((mx-ax)*(bx-ax)+(my-ay)*(by-ay))/L2))
                dev=math.hypot(mx-(ax+(bx-ax)*t), my-(ay+(by-ay)*t))
                if worst is None or dev>worst[0]: worst=(dev,m)
            if worst and worst[0]>DEV_M:
                junction.add(worst[1]); _changed=True
            i=j

# ---- יישור לעמודות/שורות: קיבוץ חד-ממדי של קואורדינטות הצמתים ----
def axis_groups(vals,tol):
    # דליים ברוחב קבוע — כל דלי הופך לעמודה/שורה במרכז הממוצע של חבריו.
    # ריצוד על גבול דלי מתוקן בנפרד, בהצמדת צמתים לשכניהם (ראו תיקון ריצוד).
    from collections import defaultdict as dd
    b=dd(list)
    for v in vals: b[round(v/tol)].append(v)
    return sorted(sum(g)/len(g) for g in b.values())
jx=[clusters[c][0] for c in junction]; jy=[clusters[c][1] for c in junction]
cols=axis_groups(jx,AXIS_TOL); rows=axis_groups(jy,AXIS_TOL)
def nearest(v,arr): return min(range(len(arr)),key=lambda i:abs(arr[i]-v))
node_of={}   # צומת -> (col,row); צמתים שנופלים לאותו תא מתמזגים
cell={}
for c in junction:
    key=(nearest(clusters[c][0],cols),nearest(clusters[c][1],rows))
    if key in cell: node_of[c]=cell[key]
    else: cell[key]=c; node_of[c]=c
U=1000.0  # יחידת תא ברשת האחידה
nidx={}
for c in set(node_of.values()):
    nidx[c]=(nearest(clusters[c][0],cols),nearest(clusters[c][1],rows))
_taken=set(nidx.values())

# ---- תיקון ריצוד גבול-דלי ----
# צומת שנופל שורה/עמודה אחת מחוץ לשני שכניו על הקו, כשמיקומו האמיתי כמעט
# זהה לשלהם — מוצמד אליהם. זה מה שיצר "טיפוס וירידה" מלאכותיים לאורך רחוב ישר.
def _flap_fix():
    fixed=0
    for num,seq in routes.items():
        jj=[]
        for c in seq:
            if c in junction:
                n_=node_of[c]
                if not jj or jj[-1]!=n_: jj.append(n_)
        for A,B,C in zip(jj,jj[1:],jj[2:]):
            for ax_ in (0,1):
                arr=cols if ax_==0 else rows
                a,b,c2=nidx[A][ax_],nidx[B][ax_],nidx[C][ax_]
                if a==c2 and abs(b-a)==1 and abs(clusters[B][ax_]-arr[a])<AXIS_TOL*0.55:
                    cand=(a,nidx[B][1]) if ax_==0 else (nidx[B][0],a)
                    if cand not in _taken:
                        _taken.discard(nidx[B]); nidx[B]=cand; _taken.add(cand); fixed+=1
    return fixed
print('צמתים שהוצמדו לשכניהם (תיקון ריצוד):',_flap_fix()+_flap_fix())

def npos(c):
    # רשת אחידה: העמודה/שורה ה-i-ית יושבת ב-i*U — מרכז צפוף מקבל מרחב כמו הפרברים,
    # מרחקים ארוכים נדחסים (כמו בפוסטרים הרשמיים), ואלכסונים יוצאים 45° מדויק.
    key=nidx.get(node_of.get(c,c))
    if key is None:
        key=(nearest(clusters[c][0],cols),nearest(clusters[c][1],rows))
    return (key[0]*U,key[1]*U)
print('צמתים:',len(junction),'-> אחרי מיזוג תאים:',len(set(node_of.values())),'| עמודות:',len(cols),'שורות:',len(rows))

# ---- ריצות בין צמתים (אחרי מיזוג) ----
runs={}; line_runs=defaultdict(list)
for num,seq in routes.items():
    i=0
    while i<len(seq)-1:
        j=i+1; midc=[]
        while j<len(seq) and seq[j] not in junction: midc.append(seq[j]); j+=1
        a,b=node_of[seq[i]],node_of[seq[j] if j<len(seq) else seq[-1]]
        i=j
        if a==b: continue
        key=(a,b) if str(a)<=str(b) else (b,a)
        rev=(key!=(a,b))
        r=runs.setdefault(key,{'midc':midc,'lines':[]})
        if num not in r['lines']: r['lines'].append(num)
        line_runs[num].append((key,rev))
orderk={L['num']:i for i,L in enumerate(lines)}
for r in runs.values(): r['lines'].sort(key=lambda n:orderk[n])

# ---- גאומטריה אוקטולינארית במרחב תאים ----
EPS=U/2
elbow={}  # ניתוב לכל ריצה: 'd' אלכסון-ואז-ישר, 's' ישר-ואז-אלכסון, 'vh' אנכי-ואז-אופקי, 'hv' אופקי-ואז-אנכי
def octo(a,b):
    (ax,ay),(bx,by)=npos(a),npos(b)
    dx,dy=bx-ax,by-ay; adx,ady=abs(dx),abs(dy)
    if adx<EPS or ady<EPS: return [(ax,ay),(bx,by)]
    key=(a,b) if str(a)<=str(b) else (b,a)
    v=elbow.get(key,'d')
    if v=='vh': return [(ax,ay),(ax,by),(bx,by)]
    if v=='hv': return [(ax,ay),(bx,ay),(bx,by)]
    if abs(adx-ady)<EPS: return [(ax,ay),(bx,by)]
    m=min(adx,ady)
    if v=='s':
        if adx>ady: return [(ax,ay),(bx-(m if dx>0 else -m),ay),(bx,by)]
        return [(ax,ay),(ax,by-(m if dy>0 else -m)),(bx,by)]
    return [(ax,ay),(ax+(m if dx>0 else -m),ay+(m if dy>0 else -m)),(bx,by)]

# ---- בחירת ניתוב לכל ריצה: ממזערים פניות חדות ("זרועות דבוקות") ----
# פנייה חדה בצומת נוצרת כשהריצה היוצאת נצמדת לזרוע הנכנסת; ניתוב מדרגה
# (אנכי/אופקי) מקיף דרך התא הפנוי — כמו שהקו נוסע סביב הבלוק במציאות.
# מעדיפים אלכסון כשאין רווח בעונש — הוא ברירת המחדל האסתטית.
def _variants(key):
    (ax,ay),(bx,by)=npos(key[0]),npos(key[1])
    adx,ady=abs(bx-ax),abs(by-ay)
    if adx<EPS or ady<EPS: return ['d']
    vs=['d','vh','hv']
    if abs(adx-ady)>=EPS: vs.append('s')
    return vs
def _run_dirs(key,rev):
    raw=octo(*key)
    if rev: raw=raw[::-1]
    (x1,y1),(x2,y2)=raw[0],raw[1]
    L1=math.hypot(x2-x1,y2-y1) or 1
    (x3,y3),(x4,y4)=raw[-2],raw[-1]
    L2=math.hypot(x4-x3,y4-y3) or 1
    return ((x2-x1)/L1,(y2-y1)/L1),((x4-x3)/L2,(y4-y3)/L2)
def _vpenalty():
    p=0
    for num_ in line_runs:
        lr_=line_runs[num_]
        for (k1,r1),(k2,r2) in zip(lr_,lr_[1:]):
            _,de=_run_dirs(k1,r1); ds,_=_run_dirs(k2,r2)
            dt=de[0]*ds[0]+de[1]*ds[1]
            if dt<-0.6: p+=2
            elif dt<-0.3: p+=1
            # קנס חזרה-על-עקבות: הריצה הבאה מנותבת דרך הצומת שממנו הקו הרגע הגיע —
            # נוצר קו כפול שטוח שנראה כשפיץ. עדיף ניתוב ישיר.
            a1=k1[0] if not r1 else k1[1]
            pa=npos(a1)
            for vx,vy in octo(*k2)[1:-1]:
                if abs(vx-pa[0])<U*0.3 and abs(vy-pa[1])<U*0.3:
                    p+=5; break
    return p
# רגל שסוגרת לולאת מיני (X->A->B->X, כמו הלוך-ושוב לרחוב צדדי) מצוירת תמיד
# כמלבן: מדרגה שהצלע הראשונה שלה בצד הנגדי לרגל היוצאת — הלולאה נקראת כלולאה.
_forced={}
for num_ in line_runs:
    lr_=line_runs[num_]
    for i2 in range(2,len(lr_)):
        k0,r0=lr_[i2-2]; k2,r2=lr_[i2]
        x0=k0[0] if not r0 else k0[1]      # תחילת הרגל היוצאת
        xe=k2[1] if not r2 else k2[0]      # סוף רגל הסגירה
        if x0!=xe: continue
        (ax,ay),(bx,by)=npos(k2[0]),npos(k2[1])
        if abs(bx-ax)<EPS or abs(by-ay)<EPS: continue
        ka=k0[0] if not r0 else k0[1]; kb=k0[1] if not r0 else k0[0]
        (ox1,oy1),(ox2,oy2)=npos(ka),npos(kb)
        out_vertical=abs(ox2-ox1)<EPS
        X=npos(xe)
        cands=[('vh',(ax,by)),('hv',(bx,ay))]
        good=[v for v,m in cands if (abs(m[0]-X[0])>1 if out_vertical else abs(m[1]-X[1])>1)]
        if good: _forced[k2]=good[0]
        # הריצות שמגיעות אל פתח הלולאה ויוצאות ממנו — בניצב לרגל הצלילה,
        # כך שהכניסה ללולאה היא פנייה של 90° ולא שפיץ
        def _perp_force(idx,at_end):
            if idx<0 or idx>=len(lr_): return
            kk,rr=lr_[idx]
            if kk in _forced: return
            (pax,pay),(pbx,pby)=npos(kk[0]),npos(kk[1])
            if abs(pbx-pax)<EPS or abs(pby-pay)<EPS: return
            touch=(kk[1] if not rr else kk[0]) if at_end else (kk[0] if not rr else kk[1])
            if touch!=x0: return
            canon_start=(kk[0]==touch)
            want_h=out_vertical
            if want_h: _forced[kk]='hv' if canon_start else 'vh'
            else: _forced[kk]='vh' if canon_start else 'hv'
        _perp_force(i2-3,True)
        _perp_force(i2+1,False)
elbow.update(_forced)

_cells={key:abs(npos(key[1])[0]-npos(key[0])[0])/U+abs(npos(key[1])[1]-npos(key[0])[1])/U for key in runs}
def _score():
    # פנייה חדה עולה 4; מדרגה עולה לפי אורכה (2 לכל תא מעבר לראשון) —
    # עיטוף קצר של בלוק משתלם, עיקוף ארוך דרך תאים ריקים לא.
    c=0.0
    for k2,vv in elbow.items():
        if vv in ('vh','hv') and k2 not in _forced: c+=2*max(_cells.get(k2,2)-1,1)
        elif vv=='s': c+=1
    return _vpenalty()*2+c
for _ in range(3):
    _imp=False
    for key in runs:
        if key in _forced: continue
        vs=_variants(key)
        if len(vs)==1: continue
        cur=elbow.get(key,'d')
        best=None
        for v in vs:
            elbow[key]=v
            score=_score()
            if best is None or score<best[0]: best=(score,v)
        elbow[key]=best[1]
        if best[1]!=cur: _imp=True
    if not _imp: break
print('ריצות שנותבו מחדש למניעת זרועות דבוקות:',sum(1 for v in elbow.values() if v!='d'))

allx=[p for key in runs for p in (npos(key[0])[0],npos(key[1])[0])]
ally=[p for key in runs for p in (npos(key[0])[1],npos(key[1])[1])]
minx,maxx,miny,maxy=min(allx),max(allx),min(ally),max(ally)
H=1000; PAD=60
sc=(H-2*PAD)/(maxy-miny)
W=int(2*PAD+(maxx-minx)*sc)
if W>1150:
    W=1150; sc=(W-2*PAD)/(maxx-minx); H=int(2*PAD+(maxy-miny)*sc)
def P(p): return (PAD+(p[0]-minx)*sc, H-PAD-(p[1]-miny)*sc)
OFF=5.0

# ---- קיבוץ גלובלי לפי קטע גאומטרי אלמנטרי ----
# ריצות שונות (בין זוגות צמתים שונים) יכולות לחפוף גאומטרית; היסט פר-ריצה לא מפריד אותן.
# לכן: מפצלים כל קטע אוקטולינארי בנקודות הסריג שהוא חוצה, ולכל תת-קטע שומרים את כל
# הקווים שעוברים בו (מכל הריצות). ההיסט מחושב לפי הקבוצה הזו, בכיוון קנוני קבוע —
# כך כל הקווים באותו תת-קטע מקבלים פסים מקבילים, בלי קשר לכיוון הנסיעה.
def subdiv(p1,p2):
    (x1,y1),(x2,y2)=p1,p2
    if math.hypot(x2-x1,y2-y1)<1: return [p1,p2]
    ts=[]
    if abs(x2-x1)>=1:
        for ci_ in range(len(cols)):
            t=(ci_*U-x1)/(x2-x1)
            if 0.001<t<0.999: ts.append(t)
    else:
        for rj_ in range(len(rows)):
            t=(rj_*U-y1)/(y2-y1)
            if 0.001<t<0.999: ts.append(t)
    return [p1]+[(x1+(x2-x1)*t,y1+(y2-y1)*t) for t in sorted(ts)]+[p2]
def segkey(p1,p2):
    q1=(round(p1[0]),round(p1[1])); q2=(round(p2[0]),round(p2[1]))
    return (q1,q2) if q1<=q2 else (q2,q1)
elem_lines=defaultdict(list)
for key,r in runs.items():
    raw=octo(*key)
    for p1,p2 in zip(raw,raw[1:]):
        sub=subdiv(p1,p2)
        for q1,q2 in zip(sub,sub[1:]):
            k=segkey(q1,q2)
            for n_ in r['lines']:
                if n_ not in elem_lines[k]: elem_lines[k].append(n_)
for v in elem_lines.values(): v.sort(key=lambda n:orderk[n])

# ---- שרשראות מסדרון: קטעים עוקבים עם אותה קבוצת קווים מקבלים מסגרת כיוון אחת ----
# בלי זה "הכיוון הקנוני" של קטע (מיון נקודות קצה) יכול להתהפך בפנייה ביחס לכיוון
# הנסיעה — וקו שהיה בקצה הימני של הצרור קופץ בפינה לקצה השמאלי.
adjs=defaultdict(list)
for k in elem_lines:
    adjs[k[0]].append(k); adjs[k[1]].append(k)
def _chain_break(pt,k1):
    ks=adjs[pt]
    if len(ks)!=2: return True
    k2=ks[0] if ks[1]==k1 else ks[1]
    return elem_lines[k2]!=elem_lines[k1]
chains=[]; cvis=set()
for k0 in list(elem_lines):
    if k0 in cvis: continue
    pts_chain=[k0[0],k0[1]]; cvis.add(k0)
    cur=k0; tail=k0[1]
    while not _chain_break(tail,cur):
        nk=[k for k in adjs[tail] if k!=cur][0]
        if nk in cvis: break
        cvis.add(nk)
        tail=nk[1] if nk[0]==tail else nk[0]
        pts_chain.append(tail); cur=nk
    cur=k0; head=k0[0]
    while not _chain_break(head,cur):
        nk=[k for k in adjs[head] if k!=cur][0]
        if nk in cvis: break
        cvis.add(nk)
        head=nk[1] if nk[0]==head else nk[0]
        pts_chain.insert(0,head); cur=nk
    chains.append(pts_chain)

# כיוון השרשראות לפי המשכיות בפועל: לכל מעבר של קו משרשרת לשרשרת נרשם אם הוא
# נוסע "עם" או "נגד" כל אחת. בוחרים כיוונים שממקסמים מעברים רציפים (איזון גרף
# חתום: יער פורש לפי הקשתות החזקות + שיפור מקומי) — כך קו לא קופץ צד בצומת.
seg2chain={}; segdir0={}
for ci,pc in enumerate(chains):
    for q1,q2 in zip(pc,pc[1:]):
        k=segkey(q1,q2); seg2chain[k]=ci; segdir0[k]=(q1,q2)
WT=defaultdict(float)
for num in line_runs:
    prev=None
    for key,rev in line_runs[num]:
        raw=octo(*key); mpts=[]
        for p1,p2 in zip(raw,raw[1:]):
            sub=subdiv(p1,p2)
            if not mpts: mpts.append(sub[0])
            mpts.extend(sub[1:])
        if rev: mpts=mpts[::-1]
        for p1,p2 in zip(mpts,mpts[1:]):
            k=segkey(p1,p2); ci=seg2chain.get(k)
            if ci is None: continue
            t=1 if (round(p1[0]),round(p1[1]))==segdir0[k][0] else -1
            if prev is not None and prev[0]!=ci:
                a,b=prev[0],ci
                WT[(min(a,b),max(a,b))]+=prev[1]*t
            prev=(ci,t)
n_ch=len(chains); f=[1]*n_ch
nb=defaultdict(list)
for (a,b),w in WT.items():
    if abs(w)<1e-9: continue
    nb[a].append((b,w)); nb[b].append((a,w))
seen=[False]*n_ch
for s in range(n_ch):
    if seen[s]: continue
    seen[s]=True; st=[s]
    while st:
        u=st.pop()
        for v,w in sorted(nb[u],key=lambda t2:-abs(t2[1])):
            if seen[v]: continue
            seen[v]=True
            f[v]=f[u]*(1 if w>0 else -1)
            st.append(v)
for _ in range(80):
    changed=False
    for i in range(n_ch):
        c=sum(w*f[j] for j,w in nb[i])*f[i]
        if c<-1e-9: f[i]=-f[i]; changed=True
    if not changed: break
bad=sum(1 for (a,b),w in WT.items() if w*f[a]*f[b]<0)
print('מעברי-שרשרת סותרים שנותרו:',bad,'מתוך',len(WT))
for ci in range(n_ch):
    if f[ci]<0: chains[ci]=chains[ci][::-1]
segdir={}
for pc in chains:
    for q1,q2 in zip(pc,pc[1:]):
        segdir[segkey(q1,q2)]=(q1,q2)

# ---- מסלול עם פינות מעוגלות: כל קודקוד הופך לקשת קטנה — פנייה, לא שפיץ ----
def rpath(pts,r=5.0):
    if len(pts)<3: return 'M'+' L'.join(f'{x:.1f} {y:.1f}' for x,y in pts)
    out=[f'M{pts[0][0]:.1f} {pts[0][1]:.1f}']
    for i in range(1,len(pts)-1):
        x0,y0=pts[i-1]; x1,y1=pts[i]; x2,y2=pts[i+1]
        l1=math.hypot(x1-x0,y1-y0); l2=math.hypot(x2-x1,y2-y1)
        rr=min(r,l1/2.5,l2/2.5)
        if rr<0.8 or l1<0.1 or l2<0.1:
            out.append(f'L{x1:.1f} {y1:.1f}'); continue
        ax,ay=x1-(x1-x0)/l1*rr, y1-(y1-y0)/l1*rr
        bx,by=x1+(x2-x1)/l2*rr, y1+(y2-y1)/l2*rr
        out.append(f'L{ax:.1f} {ay:.1f}')
        out.append(f'Q{x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}')
    out.append(f'L{pts[-1][0]:.1f} {pts[-1][1]:.1f}')
    return ' '.join(out)

svg=[]; chips=[]; strips=[]; gst={}; chains_all=[]
color={L['num']:PAL[i%len(PAL)] for i,L in enumerate(lines)}
for i,L in enumerate(lines):
    num=L['num']; col=color[num]
    lr=line_runs[num]
    # קטע גאומטרי שהקו עובר בו פעמיים (הלוך-ושוב, שלוחה, או שני רחובות מקבילים
    # שהתיישרו לאותו ציר): שתי הזרועות מוסטות לצדדים מנוגדים — לולאה דקה, לא קו יחיד
    segcnt=Counter()
    for key,rev in lr:
        raw=octo(*key)
        for p1,p2 in zip(raw,raw[1:]):
            sub=subdiv(p1,p2)
            for q1,q2 in zip(sub,sub[1:]):
                segcnt[segkey(q1,q2)]+=1
    # כל המסלול כרצף קודקודים אחד — כך התפרים בין ריצות מקבלים בדיוק את אותו
    # טיפול-פינות כמו קודקודים פנימיים, בלי "תפירה" ישירה שיוצרת זיזים בצמתים.
    allpts=[]; allsegs=[]
    for ri,(key,rev) in enumerate(lr):
        raw=octo(*key); mpts=[]
        for p1,p2 in zip(raw,raw[1:]):
            sub=subdiv(p1,p2)
            if not mpts: mpts.append(sub[0])
            mpts.extend(sub[1:])
        if rev: mpts=mpts[::-1]  # סדר הנסיעה האמיתי — ההיסט וההצטרפויות מחושבים במסגרת הזו
        pts=[P(p) for p in mpts]
        # לכל תת-קטע: כיוון יחידה על המסך, נורמל שמאלי, והיסט חתום ביחס לכיוון הנסיעה
        segs=[]
        for p1,p2 in zip(mpts,mpts[1:]):
            k=segkey(p1,p2)
            grp=elem_lines.get(k) or [num]
            off=(grp.index(num)-(len(grp)-1)/2)*OFF
            fr=segdir.get(k,k)[0]  # כיוון השרשרת (רציף לאורך המסדרון), לא מיון נקודות
            if (round(p1[0]),round(p1[1]))!=fr: off=-off  # נסיעה נגד כיוון השרשרת — אותו נתיב פיזי
            if segcnt[k]>=2: off+=3.2  # בזרוע החוזרת זה יוצא הצד הנגדי — נפתח מרווח בין הזרועות
            (x1,y1),(x2,y2)=P(p1),P(p2)
            Ls=math.hypot(x2-x1,y2-y1) or 1
            dx,dy=(x2-x1)/Ls,(y2-y1)/Ls
            segs.append(((dx,dy),(-dy,dx),off,Ls))
        if not allpts:
            allpts=pts; allsegs=segs
        else:
            if math.hypot(allpts[-1][0]-pts[0][0],allpts[-1][1]-pts[0][1])<0.5:
                allpts.extend(pts[1:])
            else:  # פער נדיר — קטע גישור ניטרלי
                (xg1,yg1),(xg2,yg2)=allpts[-1],pts[0]
                Lg=math.hypot(xg2-xg1,yg2-yg1) or 1
                allsegs.append((((xg2-xg1)/Lg,(yg2-yg1)/Lg),(-(yg2-yg1)/Lg,(xg2-xg1)/Lg),0,Lg))
                allpts.extend(pts)
            allsegs.extend(segs)
    # היסטרזיס נתיב: על קטע ישר לא זזים בגלל ריכוז-מחדש של חצי נתיב — נשארים
    # ישרים עד שינוי של נתיב שלם או פנייה. שומר על מראה שרטוטי של קווים ישרים.
    for si in range(1,len(allsegs)):
        dp,np_,op_,_=allsegs[si-1]; dc,nc,oc,Lc=allsegs[si]
        if abs(dp[0]-dc[0])<1e-6 and abs(dp[1]-dc[1])<1e-6 and 0<abs(oc-op_)<=OFF/2+0.01:
            allsegs[si]=(dc,nc,op_,Lc)
    d0,n0,o0,_=allsegs[0]
    chain=[(allpts[0][0]+n0[0]*o0, allpts[0][1]+n0[1]*o0)]
    for k2 in range(1,len(allpts)-1):
        d1,n1,o1,L1=allsegs[k2-1]; d2,n2,o2,L2=allsegs[k2]
        x,y=allpts[k2]
        a=(x+n1[0]*o1, y+n1[1]*o1); bpt=(x+n2[0]*o2, y+n2[1]*o2)
        dot=d1[0]*d2[0]+d1[1]*d2[1]
        cross=d1[0]*d2[1]-d1[1]*d2[0]
        if dot<-0.85:
            # היפוך כיוון כמעט מלא (הלוך-ושוב אמיתי) — סיבוב מעוגל מעבר לצומת.
            # פניות חדות "רגילות" (עד ~150°) הן פניות של הרשת — מצוירות כפנייה, לא כפרסה.
            mx_,my_=(a[0]+bpt[0])/2,(a[1]+bpt[1])/2
            chain.append(a); chain.append((mx_+d1[0]*8, my_+d1[1]*8)); chain.append(bpt)
        elif math.hypot(a[0]-bpt[0],a[1]-bpt[1])<0.6:
            chain.append(((a[0]+bpt[0])/2,(a[1]+bpt[1])/2))
        elif abs(cross)>0.05:
            # פנייה: חיתוך שני קווי-הנתיב המוסטים — נכון גם כשההיסט משתנה בפנייה;
            # בפינות חדות במיוחד עוברים ל-bevel כדי לא ליצור מחטים
            t=((bpt[0]-a[0])*d2[1]-(bpt[1]-a[1])*d2[0])/cross
            mx,my=a[0]+d1[0]*t, a[1]+d1[1]*t
            if math.hypot(mx-x,my-y)<=max(abs(o1),abs(o2))*1.6+7: chain.append((mx,my))
            else: chain.append(a); chain.append(bpt)
        else:
            # הרכב הקווים בקטע השתנה — מעבר נתיב ברמפה קצרה במקום קפיצה הצידה
            r1=min(9,L1/3); r2=min(9,L2/3)
            chain.append((a[0]-d1[0]*r1, a[1]-d1[1]*r1))
            chain.append((bpt[0]+d2[0]*r2, bpt[1]+d2[1]*r2))
    dL,nL,oL,_=allsegs[-1]
    chain.append((allpts[-1][0]+nL[0]*oL, allpts[-1][1]+nL[1]*oL))
    # קצוות סמוכים אך נפרדים (כמו פולק/שבט מול פולק/טבת): מזיזים את קצה הציור
    # מעט לכיוון תחנת הקצה האמיתית, כדי שלא ייראה שהקו מתחיל ומסתיים באותה נקודה
    def _tip_shift(stop):
        px,py=xy(stop[2],stop[3])
        ci=find_pt(px,py)
        if ci is None: return (0,0)
        nd=node_of.get(ci)
        if nd is None: return (0,0)
        cx,cy=clusters[nd][0],clusters[nd][1]
        ddx,ddy=px-cx,py-cy
        dd2=math.hypot(ddx,ddy)
        if dd2<20: return (0,0)
        f=min(13,dd2*0.3)/dd2
        return (ddx*f,-ddy*f)
    ts0=_tip_shift(L['stops'][0]); ts1=_tip_shift(L['stops'][-1])
    chain[0]=(chain[0][0]+ts0[0],chain[0][1]+ts0[1])
    chain[-1]=(chain[-1][0]+ts1[0],chain[-1][1]+ts1[1])
    dd=rpath(chain)
    chains_all.append(chain)
    svg.append(f'<path class="lnw lnw-{num}" d="{dd}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    svg.append(f'<path class="ln ln-{num}" d="{dd}" stroke="{col}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    # מסלול מרכז — מוצג רק כשהקו נבחר: על ציר הצומת, בלי היסטים ובלי החלפות נתיב
    cchain=[]
    for key,rev in line_runs[num]:
        raw=octo(*key)
        if rev: raw=raw[::-1]
        cpts=[P(p) for p in raw]
        if cchain and math.hypot(cchain[-1][0]-cpts[0][0],cchain[-1][1]-cpts[0][1])<0.5:
            cpts=cpts[1:]
        cchain.extend(cpts)
    if cchain:
        cchain[0]=(cchain[0][0]+ts0[0],cchain[0][1]+ts0[1])
        cchain[-1]=(cchain[-1][0]+ts1[0],cchain[-1][1]+ts1[1])
    ddc=rpath(cchain,7.0)
    svg.append(f'<path class="lncw lncw-{num}" d="{ddc}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    svg.append(f'<path class="lnc lnc-{num}" d="{ddc}" stroke="{col}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
    # תחנות עוגן של הקו — נאספות למאגר גלובלי ומצוירות פעם אחת אחרי כל הקווים
    KEY_RE=re.compile(r'מסוף|רכבת|מרכזית|ת\.מרכזית')
    n=len(L['stops'])
    for j,s in enumerate(L['stops']):
        if not (j==0 or j==n-1 or KEY_RE.search(s[0])): continue
        cid=find_pt(*xy(s[2],s[3]))
        if cid is None: continue
        nd=node_of.get(cid)
        pos=npos(nd) if nd is not None else (nearest(clusters[cid][0],cols)*U,nearest(clusters[cid][1],rows)*U)
        kk=('n',nd) if nd is not None else ('c',cid)
        e=gst.setdefault(kk,{'pos':pos,'name':re.sub(r"/.*$","",s[0])[:24],'lines':set()})
        e['lines'].add(num)
    dest=re.sub(r'-\d+#?$','',L['long']).replace('<->',' ↔ ')
    dest=re.sub(r'-'+re.escape(d['city']),'',dest)[:60]
    chips.append(f'<button class="chip" data-l="{num}" style="--c:{col}"><b>{num}</b><span>{escape(dest)}</span></button>')
    # רצועת התחנות של הקו — כל התחנות לפי סדר הנסיעה
    KEY2=re.compile(r'מסוף|רכבת|מרכזית|ת\.מרכזית')
    items=[]
    for j,st in enumerate(L['stops']):
        nm=escape(st[0][:34]); key='k' if (j==0 or j==len(L['stops'])-1 or KEY2.search(st[0])) else ''
        items.append(f'<div class="srow {key}"><i style="--c:{col}"></i><span>{nm}</span></div>')
    strips.append(f'<div class="strip strip-{num}"><div class="strip-h" style="--c:{col}"><b>{num}</b> {escape(dest)}</div>{"".join(items)}</div>')

# ---- מניעת חפיפות תוויות (משותף לתחנות ולרחובות) ----
occ=[]
def box_ok(x,y,w,h):
    for ox,oy,ow,oh in occ:
        if abs(x-ox)<(w+ow)/2 and abs(y-oy)<(h+oh)/2: return False
    occ.append((x,y,w,h)); return True
def _box_free(x,y,w,h):
    for ox,oy,ow,oh in occ:
        if abs(x-ox)<(w+ow)/2 and abs(y-oy)<(h+oh)/2: return False
    return True
# דגימת גאומטריית הקווים — לתוויות שמחפשות מקום שאינו מכוסה על ידי קו
lpts=[]
for ch in chains_all:
    for (x1,y1),(x2,y2) in zip(ch,ch[1:]):
        Ls2=math.hypot(x2-x1,y2-y1); n2=max(1,int(Ls2//14))
        for t2 in range(n2+1):
            lpts.append((x1+(x2-x1)*t2/n2, y1+(y2-y1)*t2/n2))
def _cover(bx,by,w,h):
    c=0
    for lx,ly in lpts:
        if abs(lx-bx)<w/2+6 and abs(ly-by)<h/2+6: c+=1
    return c

# ---- תחנות עוגן: עיגול + תווית, מוצג תמיד; בבחירת קו — מודגשות רק שלו ----
gels=[]
for kk,e in sorted(gst.items(),key=lambda kv:-len(kv[1]['lines'])):
    x,y=P(e['pos'])
    nm=escape(e['name']); w=len(e['name'])*7.2+12
    lbl=''
    # מחפשים מיקום שגם פנוי מתוויות וגם לא מכוסה על ידי קווים
    cands=[(x+12,y+4,'start'),(x-12,y+4,'end'),(x,y-16,'middle'),(x,y+24,'middle'),
           (x+14,y-16,'start'),(x-14,y-16,'end'),(x+14,y+24,'start'),(x-14,y+24,'end'),
           (x+34,y+4,'start'),(x-34,y+4,'end'),(x,y-36,'middle'),(x,y+44,'middle')]
    best=None
    for ci2,(lx,ly,anch) in enumerate(cands):
        bx=lx+(w/2 if anch=='start' else -w/2 if anch=='end' else 0)
        if not _box_free(bx,ly-5,w,17): continue
        cv=_cover(bx,ly-5,w,17)
        sc2=cv*60+ci2
        if best is None or sc2<best[0]: best=(sc2,lx,ly,anch,bx)
        if cv==0: break
    if best:
        _,lx,ly,anch,bx=best
        occ.append((bx,ly-5,w,17))
        lbl=f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="{anch}" style="direction:ltr">{nm}</text>' 
    cls='gst '+' '.join('gst-'+n_ for n_ in sorted(e['lines']))
    gels.append(f'<g class="{cls}"><circle cx="{x:.0f}" cy="{y:.0f}" r="7" fill="#1e3a8a" stroke="#fff" stroke-width="2.6"/>{lbl}</g>')

# ---- שמות רחובות: הרחוב השכיח בשמות תחנות הביניים של כל מסדרון ----
cand=[]
for key,r in runs.items():
    cnt=Counter()
    for c in r['midc']:
        for nm in clusters[c][2]:
            stn=nm.split('/')[0].strip()
            if len(stn)>=3: cnt[stn]+=1
    if not cnt: continue
    stn,hits=cnt.most_common(1)[0]
    if hits<2: continue
    pts=[P(p) for p in octo(*key)]
    (x1,y1),(x2,y2)=max(zip(pts,pts[1:]),key=lambda ab:math.hypot(ab[1][0]-ab[0][0],ab[1][1]-ab[0][1]))
    seglen=math.hypot(x2-x1,y2-y1)
    cand.append((seglen,stn,(x1,y1),(x2,y2),len(r['lines'])))
stlab=[]; named=set()
for seglen,stn,(x1,y1),(x2,y2),nl in sorted(cand,key=lambda t:-t[0]):
    if stn in named or seglen<60: continue
    mx,my=(x1+x2)/2,(y1+y2)/2
    ang=math.degrees(math.atan2(y2-y1,x2-x1))
    if ang>90: ang-=180
    if ang<=-90: ang+=180
    nx,ny=-(y2-y1)/seglen,(x2-x1)/seglen
    if ny>0: nx,ny=-nx,-ny  # תמיד מעל הצרור
    offd=nl*OFF/2+10
    lx,ly=mx+nx*offd,my+ny*offd
    w=len(stn)*6.3+8
    if not box_ok(lx,ly,w,14): continue
    named.add(stn)
    stlab.append(f'<text class="strt" x="{lx:.0f}" y="{ly:.0f}" transform="rotate({ang:.0f} {lx:.0f} {ly:.0f})" text-anchor="middle" style="direction:ltr">{escape(stn)}</text>')
svg.append('<g>'+''.join(stlab)+'</g>')
svg.append('<g>'+''.join(gels)+'</g>')

# ---- שכבת רקע: שכונות ומקומות מרכזיים מ-OSM (poi.json, אופציונלי) ----
# כל תווית מחפשת נקודה פנויה בסביבתה (בדיקה מול גאומטריית הקווים), מקבלת
# הילה לבנה, ומצוירת מעל הקווים אך מתחת לתוויות התחנות והרחובות.
import os as _os
_poip=_os.environ.get('POI','')
if _poip and _os.path.exists(_poip):
    _poid=json.load(open(_poip,encoding='utf-8'))
    _las=[s[2] for L in lines for s in L['stops']]; _los=[s[3] for L in lines for s in L['stops']]
    la1,la2=min(_las)-0.003,max(_las)+0.003; lo1,lo2=min(_los)-0.003,max(_los)+0.003
    def _interp(v,arr):
        if v<=arr[0]: return 0.0
        if v>=arr[-1]: return float(len(arr)-1)
        for i2 in range(len(arr)-1):
            if arr[i2]<=v<=arr[i2+1]:
                return i2+(v-arr[i2])/((arr[i2+1]-arr[i2]) or 1)
        return 0.0
    _CAND=[(0,0)]+[(dx,dy) for dy in (0,-28,28,-52,52) for dx in (0,-36,36,-68,68) if (dx,dy)!=(0,0)]
    _KINDS={'hood','park','mall','cemetery'}
    # רק מקומות מרכזיים: שכונות תמיד; פארקים רק בשם "פארק" (לא כל גן/גינה),
    # קניונים ובתי עלמין — במכסה קטנה, קרובים למרכז המפה קודם
    _seenp=set(); _cands=[]
    for p in _poid['poi']:
        if p['k'] not in _KINDS or p['n'] in _seenp: continue
        if not re.search(r'[\u05d0-\u05ea]',p['n']): continue  # שמות לועזיים = כפילויות OSM
        if not (la1<p['la']<la2 and lo1<p['lo']<lo2): continue
        if p['k']=='park' and not p['n'].startswith(('פארק','הפארק')): continue
        if p['k']=='mall' and 'קניון' not in p['n']: continue
        if p['k']=='cemetery' and not p['n'].startswith('בית עלמין'): continue
        _seenp.add(p['n']); _cands.append(p)
    _lac,_loc=(la1+la2)/2,(lo1+lo2)/2
    _cands.sort(key=lambda p:(p['k']!='hood', abs(p['la']-_lac)+abs(p['lo']-_loc)))
    _QUOTA={'park':7,'mall':4,'cemetery':2}; _used={}
    bgels=[]
    for p in _cands:
        if p['k']!='hood':
            if _used.get(p['k'],0)>=_QUOTA[p['k']]: continue
            _used[p['k']]=_used.get(p['k'],0)+1
        px,py=xy(p['la'],p['lo'])
        x,y=P((_interp(px,cols)*U,_interp(py,rows)*U))
        if not (PAD-20<x<W-PAD+20 and PAD-20<y<H-PAD+20): continue
        hood=(p['k']=='hood')
        wbox=(len(p['n'])*11+12) if hood else (len(p['n'])*7+24)
        hbox=26 if hood else 16
        best=None
        for ox,oy in _CAND:
            bx,by=x+ox,y+oy
            if not (PAD<bx<W-PAD and PAD<by<H-PAD): continue
            if not _box_free(bx,by-6,wbox,hbox): continue
            cv=_cover(bx,by-6,wbox,hbox)
            sc2=cv*100+abs(ox)+abs(oy)
            if best is None or sc2<best[0]: best=(sc2,bx,by)
            if cv==0: break
        if best is None: continue
        _,bx,by=best
        occ.append((bx,by-6,wbox,hbox))
        nmx=escape(p['n'][:22])
        if hood:
            bgels.append(f'<text x="{bx:.0f}" y="{by:.0f}" text-anchor="middle" font-size="19" font-weight="900" fill="#bcc7d4" letter-spacing="1" stroke="#fff" stroke-width="5" paint-order="stroke" style="direction:ltr">{nmx}</text>')
        else:
            ic={'park':'🌳','mall':'🛍️','cemetery':'🕍'}.get(p['k'],'')
            col2={'park':'#8fb88f','mall':'#a99cc4','cemetery':'#a9b3a9'}.get(p['k'],'#b8c2cc')
            bgels.append(f'<text x="{bx:.0f}" y="{by:.0f}" text-anchor="middle" font-size="12" font-weight="800" fill="{col2}" stroke="#fff" stroke-width="4" paint-order="stroke" style="direction:ltr">{ic} {nmx}</text>')
    svg.insert(len(svg)-2,'<g class="bg">'+''.join(bgels)+'</g>')

html=f'''<!DOCTYPE html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<title>מפת רשת — {escape(d["city"])}</title>
<style>
body{{margin:0;font-family:'Assistant','Heebo',sans-serif;background:#eef1f5}}
.wrap{{max-width:1200px;margin:12px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(0,0,0,.1)}}
.hdr{{background:#1e3a8a;color:#fff;padding:12px 20px;font-weight:900;font-size:19px}}
.hdr small{{font-weight:700;opacity:.75;font-size:12px;margin-right:10px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;padding:10px 14px;background:#f8fafc;border-bottom:1px solid #e2e8f0}}
.chip{{display:flex;align-items:center;gap:7px;border:2px solid var(--c);background:#fff;border-radius:999px;padding:4px 12px 4px 8px;cursor:pointer;font-family:inherit}}
.chip b{{background:var(--c);color:#fff;border-radius:6px;padding:2px 9px;font-size:14px}}
.chip span{{font-size:11.5px;font-weight:700;color:#475569;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.chip.on{{background:var(--c)}} .chip.on span{{color:#fff}}
.main{{display:flex;align-items:stretch}}
.main svg{{flex:none;display:block;margin:0 auto;max-width:100%;height:auto}}
.side{{width:0;overflow:hidden;transition:width .25s;background:#f8fafc;border-right:1px solid #e2e8f0}}
body.sel .side{{width:270px;overflow-y:auto;max-height:760px}}
.strip{{display:none;padding:10px 12px}}
body.sel .strip.on{{display:block}}
.strip-h{{font-weight:900;font-size:14px;color:#0f172a;margin-bottom:8px}}
.strip-h b{{background:var(--c);color:#fff;border-radius:6px;padding:2px 9px;margin-left:6px}}
.srow{{display:flex;align-items:center;gap:9px;font-size:12.5px;font-weight:700;color:#475569;padding:1px 0}}
.srow i{{width:10px;height:10px;border-radius:50%;background:#fff;border:3px solid var(--c);flex:none;position:relative}}
.srow i::after{{content:"";position:absolute;right:1.5px;top:10px;width:2.5px;height:8px;background:var(--c)}}
.srow:last-child i::after{{display:none}}
.srow.k{{color:#1e3a8a;font-weight:900;font-size:13px}}
.srow.k i{{background:#1e3a8a;border-color:#1e3a8a}}
.ln{{stroke-width:3.6;opacity:.96;transition:all .2s;cursor:pointer}}
.lnw{{stroke:#fff;stroke-width:5.8}}
.lnc,.lncw{{display:none;pointer-events:none}}
.gst{{pointer-events:none;transition:opacity .2s}}
.gst text{{font-size:12.5px;font-weight:900;fill:#1e3a8a;stroke:#fff;stroke-width:5;paint-order:stroke}}
.strt{{font-size:11px;font-weight:700;fill:#94a3b8;stroke:#fff;stroke-width:3.5;paint-order:stroke;pointer-events:none}}
body.sel .ln{{opacity:.08}}
body.sel .lnw{{opacity:0}}
body.sel .lnc.on{{display:block;stroke-width:6.5}}
body.sel .lncw.on{{display:block;stroke:#fff;stroke-width:10.5;opacity:.9}}
body.sel .gst{{opacity:.15}}
body.sel .gst.on{{opacity:1}}
body.sel .strt{{opacity:.3}}
</style></head><body>
<div class="wrap">
<div class="hdr">מפת רשת הקווים — {escape(d["city"])} <small>סכמטי · נוצר אוטומטית מ-GTFS · לחצו על קו</small></div>
<div class="chips"><button class="chip" data-l="" style="--c:#0f172a"><b>הכול</b></button>{''.join(chips)}</div>
<div class="main">
<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" xmlns="http://www.w3.org/2000/svg">{''.join(svg)}</svg>
<div class="side">{''.join(strips)}</div>
</div>
</div>
<script>
const b=document.body;
document.querySelectorAll('.chip').forEach(c=>c.onclick=()=>{{
  const l=c.dataset.l;
  document.querySelectorAll('.chip').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.ln,.lnc,.lncw,.gst,.strip').forEach(x=>x.classList.remove('on'));
  if(!l){{b.classList.remove('sel');return}}
  c.classList.add('on'); b.classList.add('sel');
  document.querySelectorAll('.ln-'+CSS.escape(l)+',.lnc-'+CSS.escape(l)+',.lncw-'+CSS.escape(l)+',.gst-'+CSS.escape(l)).forEach(x=>x.classList.add('on'));
  document.querySelectorAll('.strip-'+CSS.escape(l)).forEach(x=>x.classList.add('on'));
}});
document.querySelectorAll('.ln').forEach(p=>p.onclick=()=>{{
  const cls=[...p.classList].find(c=>c.startsWith('ln-'));
  document.querySelector('.chip[data-l="'+cls.slice(3)+'"]').click();
}});
</script></body></html>'''
open(OUT,'w',encoding='utf-8').write(html)
print('נכתב',OUT)
