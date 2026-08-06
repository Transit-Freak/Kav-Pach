import{dt as e,et as t,ft as n,gt as r,pt as i}from"./utils-BH7kdYtO.js";import{i as a}from"./useThemeProps-_q0DsjBv.js";import{Rt as o,n as s,t as c,zt as l}from"./PageContainer-CfTPnrR-.js";import{n as u}from"./ThemeContext--M75j2G1.js";import{l as d,n as f}from"./IconButton-DmcneAQY.js";import{n as p}from"./globalState-DL9eupk2.js";import{t as m}from"./Typography-G8qcp5W3.js";import{t as h}from"./TimeSelector-DwYH8EoL.js";import{n as g,t as _}from"./styled-components.browser.esm-Fyl9wwGe.js";import{r as v}from"./dist-BdefjVmq.js";import{Cn as y,Fn as b,In as x,Nn as S,Rn as ee,S as te,_ as ne,h as re,kn as C,m as ie,v as ae,vn as oe,x as se}from"./index-qrrMVO4M.js";import{t as ce}from"./es-CJi0WW0E.js";import{t as le}from"./StopSelector-3ZCCK1y0.js";var ue=r(i(),1),de=e(),w=ce();function fe(e,t){let n=(0,w.computeDestinationPoint)(e,t,0),r=(0,w.computeDestinationPoint)(e,t,180),i=(0,w.computeDestinationPoint)(e,t,90);return{lowerBound:{longitude:(0,w.computeDestinationPoint)(e,t,270).longitude,latitude:r.latitude},upperBound:{longitude:i.longitude,latitude:n.latitude}}}function pe(e,t){return(0,w.findNearest)(e,t)}var me=500;async function he(e,t,n){let r=fe(t.location,me),i=(await d.siriVehicleLocationsListGet({limit:1024,siriRoutesLineRef:e.lineRef.toString(),recordedAtTimeFrom:l(n).subtract(4,`hour`).toDate(),recordedAtTimeTo:l(n).add(4,`hour`).toDate(),latGreaterOrEqual:r.lowerBound.latitude,latLowerOrEqual:r.upperBound.latitude,lonGreaterOrEqual:r.lowerBound.longitude,lonLowerOrEqual:r.upperBound.longitude,orderBy:`distance_from_siri_ride_stop_meters desc`})).reduce((e,t)=>(t.siriRideId&&(e[t.siriRideId.toString()]||=[]).push({...t,longitude:t.lon||0,latitude:t.lat||0}),e),{}),a=Object.values(i).map(e=>pe(t.location,e)),o=e=>Math.abs(n.diff(l(e.recordedAtTime),`second`));return a.sort((e,t)=>o(e)-o(t)).sort((e,t)=>e.recordedAtTime.getTime()-t.recordedAtTime.getTime())}var T=`var(--timeline-neutral, #7393B3)`,E=`#1890ff`,D=`#eb2f96`,O=function(e){return e[e.BOUNDARY=0]=`BOUNDARY`,e[e.GTFS=1]=`GTFS`,e[e.SIRI=2]=`SIRI`,e}({}),k={0:T,1:E,2:D},ge={0:null,1:`timestamp_gtfs`,2:`timestamp_siri`},A=g.div`
  height: ${8}px;
  width: ${8}px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px
    ${({$highlighted:e})=>e?`var(--timeline-highlight-ring, white)`:T};
  background-color: ${({type:e})=>k[e||0]};
  position: absolute;
  top: ${({top:e})=>e}px;
  right: -3px;
  transform: ${({$highlighted:e})=>e?`scale(1.5)`:`scale(1)`};
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease;
  z-index: ${({$highlighted:e})=>e?4:2};
`,j=n(),M=_`
  position: absolute;
  left: 0;
  width: 100%;
  user-select: none;
`,N=g.div`
  ${M};
  top: ${({top:e})=>e+3}px;
  height: 2px;
  background-color: ${T};
  opacity: ${({visible:e})=>e?.4:0};
`,P=g.div`
  ${M};
  top: ${({top:e})=>e-1}px;
  height: 3px;
  background-color: red;
  opacity: 0;
  z-index: 5;
`,_e=e=>{let t=(0,de.c)(13),{top:n,externalVisible:r,onHoverChange:i}=e,a=(0,ue.useRef)(null),o=v(a)||!!r,s;t[0]!==o||t[1]!==n?(s=(0,j.jsx)(N,{top:n,visible:o}),t[0]=o,t[1]=n,t[2]=s):s=t[2];let c,l;t[3]===i?(c=t[4],l=t[5]):(c=()=>i?.(!0),l=()=>i?.(!1),t[3]=i,t[4]=c,t[5]=l);let u;t[6]!==c||t[7]!==l||t[8]!==n?(u=(0,j.jsx)(P,{ref:a,top:n,onMouseEnter:c,onMouseLeave:l}),t[6]=c,t[7]=l,t[8]=n,t[9]=u):u=t[9];let d;return t[10]!==s||t[11]!==u?(d=(0,j.jsxs)(j.Fragment,{children:[s,u]}),t[10]=s,t[11]=u,t[12]=d):d=t[12],d},F=18,I=20,ve=8,L=5-8/2,ye=g.div`
  height: ${({totalHeight:e})=>e+30}px;
  width: 2px;
  background-color: ${T};
`,R=g.div.withConfig({componentId:`sc-boundary-tick`})`
  width: 12px;
  height: 2px;
  background-color: ${T};
  position: absolute;
  top: ${({top:e})=>e}px;
  right: -5px;
`,z=g.div`
  display: flex;
  flex-direction: column;
  align-items: center;
`,be=g.span`
  font-weight: bold;
  background-color: ${({pointType:e})=>k[e]};
  padding: 2px 8px;
  white-space: nowrap;
  font-size: clamp(8px, 2.5vw, 16px);
`,xe=g.div`
  display: flex;
`,B=g.div`
  position: relative;
  width: 2px;
  flex-shrink: 0;
`,V=g.div`
  position: relative;
  margin-inline-start: ${I}px;
`,Se=g.span`
  display: block;
  visibility: hidden;
  pointer-events: none;
  white-space: nowrap;
`,H=g.div`
  position: absolute;
  top: ${({$top:e})=>e-8+1}px;
  inset-inline-start: 0;
  z-index: 2;
  white-space: nowrap;
  font-weight: ${({$highlighted:e})=>e?`bold`:`normal`};
`,U=g.svg`
  position: absolute;
  top: 0;
  left: 0;
  width: 2px;
  height: 100%;
  pointer-events: none;
  overflow: visible;
`;function W(e){if(e.length<=1)return[...e];let t=e.map((e,t)=>({y:e,i:t})).sort((e,t)=>e.y-t.y);for(let e=1;e<t.length;e++){let n=t[e-1].y+21;t[e].y<n&&(t[e]={...t[e],y:n})}for(let e=t.length-2;e>=0;e--){let n=t[e+1].y-21;t[e].y>n&&(t[e]={...t[e],y:n})}let n=Array(e.length);for(let{y:e,i:r}of t)n[r]=e;return n}var G=e=>{let n=(0,de.c)(7),{pointType:r,className:i}=e,{t:a}=t(),o=ge[r],s;n[0]!==a||n[1]!==o?(s=a(o),n[0]=a,n[1]=o,n[2]=s):s=n[2];let c;return n[3]!==i||n[4]!==r||n[5]!==s?(c=(0,j.jsx)(be,{pointType:r,className:i,children:s}),n[3]=i,n[4]=r,n[5]=s,n[6]=c):c=n[6],c},K=e=>{let n=(0,de.c)(39),{className:r,timestamps:i,totalHeight:a,pointType:o,timestampToTop:s,hoveredTimestamp:c}=e,{i18n:u}=t(),d;n[0]===u?d=n[1]:(d=u.dir(),n[0]=u,n[1]=d);let f=d===`rtl`,p,m,h,g,_,v,y;if(n[2]!==r||n[3]!==c||n[4]!==f||n[5]!==o||n[6]!==s||n[7]!==i||n[8]!==a){let e;n[16]!==c||n[17]!==s?(e=(e,t)=>{let n=e.arrivalTime??e.recordedAtTime??e,r=l(n).toISOString();return{i:t,tsKey:r,naturalY:s(l(n)),highlighted:c!==void 0&&r===c,timeDisplay:l(n).format(`HH:mm:ss`)}},n[16]=c,n[17]=s,n[18]=e):e=n[18];let t=i.map(e),u=W(t.map(q));h=z,y=r,m=xe;let d;n[19]===a?d=n[20]:(d=(0,j.jsx)(ye,{totalHeight:a}),n[19]=a,n[20]=d);let b;n[21]===Symbol.for(`react.memo_cache_sentinel`)?(b=(0,j.jsx)(R,{top:-1}),n[21]=b):b=n[21];let x=a+30-1,S;n[22]===x?S=n[23]:(S=(0,j.jsx)(R,{top:x}),n[22]=x,n[23]=S);let ee;n[24]===o?ee=n[25]:(ee=e=>(0,j.jsx)(A,{top:e.naturalY,type:o,$highlighted:e.highlighted,title:e.timeDisplay},`${e.i}_dot`),n[24]=o,n[25]=ee),v=(0,j.jsxs)(B,{children:[d,b,S,(0,j.jsx)(U,{children:t.map(e=>{let t=u[e.i];if(Math.abs(t-e.naturalY)<1)return null;let n=e.naturalY+8/2,r=t-8+1+F/2,i=e.highlighted?k[o]:T,a=e.highlighted?.9:.5,s=f?-20:22;return(0,j.jsx)(`path`,{d:`M ${s} ${r} L ${f?s+ve:s-ve} ${r} L ${L} ${n}`,stroke:i,strokeWidth:1,fill:`none`,opacity:a},`${e.i}_conn`)})}),t.map(ee)]}),p=V,n[26]===Symbol.for(`react.memo_cache_sentinel`)?(g=(0,j.jsx)(Se,{"aria-hidden":!0,children:`00:00:00`}),n[26]=g):g=n[26],_=t.map(e=>(0,j.jsx)(H,{$top:u[e.i],$highlighted:e.highlighted,title:e.timeDisplay,children:e.timeDisplay},`${e.i}_label`)),n[2]=r,n[3]=c,n[4]=f,n[5]=o,n[6]=s,n[7]=i,n[8]=a,n[9]=p,n[10]=m,n[11]=h,n[12]=g,n[13]=_,n[14]=v,n[15]=y}else p=n[9],m=n[10],h=n[11],g=n[12],_=n[13],v=n[14],y=n[15];let b;n[27]!==p||n[28]!==g||n[29]!==_?(b=(0,j.jsxs)(p,{children:[g,_]}),n[27]=p,n[28]=g,n[29]=_,n[30]=b):b=n[30];let x;n[31]!==m||n[32]!==v||n[33]!==b?(x=(0,j.jsxs)(m,{children:[v,b]}),n[31]=m,n[32]=v,n[33]=b,n[34]=x):x=n[34];let S;return n[35]!==h||n[36]!==y||n[37]!==x?(S=(0,j.jsx)(h,{className:y,children:x}),n[35]=h,n[36]=y,n[37]=x,n[38]=S):S=n[38],S};function q(e){return e.naturalY}var Ce=32,J=e=>e.length>0?l(e[e.length-1]).diff(e[0],`second`):0,Y=(e,t)=>e<=t?e:t,X=g.div`
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: ${Ce}px;
  margin-bottom: 16px;
`,we=g(G)`
  display: block;
  text-align: center;
`,Z=g.div`
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: ${Ce}px;
`,Q=g.div`
  display: flex;
  justify-content: center;
`,Te=g.div`
  display: flex;
  flex-direction: column;
  width: 100%;
`,Ee=({className:e,target:t,gtfsTimes:n,siriTimes:r})=>{let{isDarkTheme:i}=u(),[a,o]=(0,ue.useState)(void 0),s=n.map(e=>e.arrivalTime),c=r.map(e=>e.recordedAtTime),d=J(s),f=J(c),p=Y(s[0]??Date.now(),c[0]??Date.now()),m=Math.max(d,f),h=400+Math.max(n.length,r.length)/16*400,g=new Set([t.toDate(),...s,...c]),_=(0,ue.useCallback)(e=>{let t=e.diff(p,`second`)/m;return Math.min(10+t*h,h)},[p,m,h]);return(0,j.jsx)(Q,{className:e,children:(0,j.jsxs)(Te,{style:{"--timeline-neutral":i?`#8c8c8c`:`#bfbfbf`,"--timeline-highlight-ring":i?`white`:`#333`},children:[(0,j.jsxs)(X,{children:[(0,j.jsx)(we,{pointType:O.GTFS}),(0,j.jsx)(we,{pointType:O.SIRI})]}),(0,j.jsxs)(Z,{children:[(0,j.jsx)(K,{timestamps:n,totalHeight:h,pointType:O.GTFS,timestampToTop:_,hoveredTimestamp:a}),(0,j.jsx)(K,{timestamps:r,totalHeight:h,pointType:O.SIRI,timestampToTop:_,hoveredTimestamp:a}),Array.from(g).map((e,t)=>{let n=l(e).toISOString();return(0,j.jsx)(_e,{top:_(l(e)),externalVisible:a===n,onHoverChange:e=>o(e?n:void 0)},t)})]})]})})},De=()=>{let e=(0,de.c)(137),{t:n}=t(),{search:r,setSearch:i}=(0,ue.useContext)(p),{operatorId:u,lineNumber:d,date:g,routeKey:_}=r,v=r.stopKey,ce;e[0]===i?ce=e[1]:(ce=e=>i(t=>({...t,stopKey:e??null})),e[0]=i,e[1]=ce);let w=ce,fe;e[2]===Symbol.for(`react.memo_cache_sentinel`)?(fe={params:{time:l().format(`HH:mm`)},ui:{scrollPosition:0}},e[2]=fe):fe=e[2];let{params:pe,setParams:me}=te(`timeline`,fe),T;if(e[3]!==g||e[4]!==pe.time){let[t,n]=pe.time.split(`:`).map(Number);T=l.tz(g,o).hour(t).minute(n).startOf(`minute`),e[3]=g,e[4]=pe.time,e[5]=T}else T=e[5];let E=T,D;e[6]!==d||e[7]!==u||e[8]!==i||e[9]!==w||e[10]!==E?(D=async()=>{if(u&&d)try{return await x(E,E,u,d)}catch(e){console.error(e),i(Oe),w(void 0)}return null},e[6]=d,e[7]=u,e[8]=i,e[9]=w,e[10]=E,e[11]=D):D=e[11];let O;e[12]===E?O=e[13]:(O=E.valueOf(),e[12]=E,e[13]=O);let k;e[14]!==d||e[15]!==u||e[16]!==O?(k=[`routes`,u,d,O],e[14]=d,e[15]=u,e[16]=O,e[17]=k):k=e[17];let ge;e[18]!==D||e[19]!==k?(ge={queryFn:D,queryKey:k},e[18]=D,e[19]=k,e[20]=ge):ge=e[20];let A=a(ge),M;e[21]!==_||e[22]!==A.data?(M=A.data?.find(e=>e.key===_),e[21]=_,e[22]=A.data,e[23]=M):M=e[23];let N=M,P;e[24]!==N||e[25]!==i||e[26]!==E?(P=async()=>{if(N)try{return await ee(N.routeIds,E)}catch(e){console.error(e),i(ke)}return null},e[24]=N,e[25]=i,e[26]=E,e[27]=P):P=e[27];let _e=N?.lineRef,F;e[28]===E?F=e[29]:(F=E.valueOf(),e[28]=E,e[29]=F);let I;e[30]!==F||e[31]!==_e?(I=[`stops`,_e,F],e[30]=F,e[31]=_e,e[32]=I):I=e[32];let ve;e[33]!==I||e[34]!==P?(ve={queryFn:P,queryKey:I},e[33]=I,e[34]=P,e[35]=ve):ve=e[35];let L=a(ve),ye;e[36]!==v||e[37]!==L.data?(ye=L.data?.find(e=>e.key===v),e[36]=v,e[37]=L.data,e[38]=ye):ye=e[38];let R=ye,z;e[39]!==N||e[40]!==R||e[41]!==E?(z=async()=>{if(R&&N){let[e,t]=await Promise.all([b(R,E),he(N,R,E)]);return{gtfsTime:e,siriTime:t}}return null},e[39]=N,e[40]=R,e[41]=E,e[42]=z):z=e[42];let be=N?.lineRef,xe=R?.stopId,B;e[43]===E?B=e[44]:(B=E.valueOf(),e[43]=E,e[44]=B);let V;e[45]!==be||e[46]!==xe||e[47]!==B?(V=[`hits`,be,xe,B],e[45]=be,e[46]=xe,e[47]=B,e[48]=V):V=e[48];let Se;e[49]!==z||e[50]!==V?(Se={queryFn:z,queryKey:V},e[49]=z,e[50]=V,e[51]=Se):Se=e[51];let H=a(Se),U;e[52]===n?U=e[53]:(U=n(`timeline_page_title`),e[52]=n,e[53]=U);let W;e[54]===U?W=e[55]:(W=(0,j.jsx)(m,{variant:`h4`,gutterBottom:!0,className:`page-title`,children:U}),e[54]=U,e[55]=W);let G;e[56]===n?G=e[57]:(G=n(`timeline_page_description`),e[56]=n,e[57]=G);let K;e[58]===G?K=e[59]:(K=(0,j.jsx)(S,{severity:`info`,variant:`outlined`,icon:!1,children:G}),e[58]=G,e[59]=K);let q;e[60]!==H.data||e[61]!==n?(q=H.data&&H.data.gtfsTime.length>0&&H.data.siriTime.length===0&&(0,j.jsx)(S,{severity:`warning`,variant:`outlined`,children:n(`no_data_from_ETL`)}),e[60]=H.data,e[61]=n,e[62]=q):q=e[62];let Ce;e[63]===Symbol.for(`react.memo_cache_sentinel`)?(Ce={lg:4,md:6,xs:12},e[63]=Ce):Ce=e[63];let J;e[64]===g?J=e[65]:(J=l.tz(g,o),e[64]=g,e[65]=J);let Y;e[66]===i?Y=e[67]:(Y=e=>{e&&i(t=>({...t,date:e.format(`YYYY-MM-DD`)}))},e[66]=i,e[67]=Y);let X;e[68]!==J||e[69]!==Y?(X=(0,j.jsx)(C,{size:Ce,children:(0,j.jsx)(s,{time:J,onChange:Y})}),e[68]=J,e[69]=Y,e[70]=X):X=e[70];let we;e[71]===Symbol.for(`react.memo_cache_sentinel`)?(we={lg:4,md:6,xs:12},e[71]=we):we=e[71];let Z;e[72]===me?Z=e[73]:(Z=e=>{e&&me(t=>({...t,time:e.format(`HH:mm`)}))},e[72]=me,e[73]=Z);let Q;e[74]!==Z||e[75]!==E?(Q=(0,j.jsx)(C,{size:we,children:(0,j.jsx)(h,{time:E,onChange:Z})}),e[74]=Z,e[75]=E,e[76]=Q):Q=e[76];let Te;e[77]===Symbol.for(`react.memo_cache_sentinel`)?(Te={lg:4,md:6,xs:12},e[77]=Te):Te=e[77];let De=u??void 0,Ae;e[78]===i?Ae=e[79]:(Ae=e=>i(t=>({...t,operatorId:e})),e[78]=i,e[79]=Ae);let je;e[80]!==De||e[81]!==Ae?(je=(0,j.jsx)(C,{size:Te,children:(0,j.jsx)(y,{operatorId:De,setOperatorId:Ae,excludeIsraelRailways:!0})}),e[80]=De,e[81]=Ae,e[82]=je):je=e[82];let Me;e[83]===Symbol.for(`react.memo_cache_sentinel`)?(Me={lg:4,md:6,xs:12},e[83]=Me):Me=e[83];let Ne=d??void 0,$;e[84]===i?$=e[85]:($=e=>i(t=>({...t,lineNumber:e})),e[84]=i,e[85]=$);let Pe;e[86]!==Ne||e[87]!==$?(Pe=(0,j.jsx)(C,{size:Me,children:(0,j.jsx)(ae,{lineNumber:Ne,setLineNumber:$})}),e[86]=Ne,e[87]=$,e[88]=Pe):Pe=e[88];let Fe;e[89]===Symbol.for(`react.memo_cache_sentinel`)?(Fe={lg:4,md:6,xs:12},e[89]=Fe):Fe=e[89];let Ie,Le;e[90]===Symbol.for(`react.memo_cache_sentinel`)?(Ie={width:`100%`},Le={width:`100%`},e[90]=Ie,e[91]=Le):(Ie=e[90],Le=e[91]);let Re;e[92]!==_||e[93]!==A.data||e[94]!==i||e[95]!==n?(Re=(0,j.jsx)(`div`,{style:Le,children:A.data?.length===0?(0,j.jsx)(ne,{children:n(`line_not_found`)}):(0,j.jsx)(re,{disabled:!A.data,routes:A.data||[],routeKey:_??void 0,setRouteKey:e=>i(t=>({...t,routeKey:e??null}))})}),e[92]=_,e[93]=A.data,e[94]=i,e[95]=n,e[96]=Re):Re=e[96];let ze;e[97]===A.isLoading?ze=e[98]:(ze=A.isLoading&&(0,j.jsx)(f,{}),e[97]=A.isLoading,e[98]=ze);let Be;e[99]!==Re||e[100]!==ze?(Be=(0,j.jsx)(C,{container:!0,size:Fe,children:(0,j.jsxs)(ie,{style:Ie,children:[Re,ze]})}),e[99]=Re,e[100]=ze,e[101]=Be):Be=e[101];let Ve;e[102]===Symbol.for(`react.memo_cache_sentinel`)?(Ve={lg:4,md:6,xs:12},e[102]=Ve):Ve=e[102];let He,Ue;e[103]===Symbol.for(`react.memo_cache_sentinel`)?(He={width:`100%`},Ue={width:`100%`},e[103]=He,e[104]=Ue):(He=e[103],Ue=e[104]);let We=!L.data,Ge;e[105]===L.data?Ge=e[106]:(Ge=L.data||[],e[105]=L.data,e[106]=Ge);let Ke=v??void 0,qe;e[107]!==w||e[108]!==We||e[109]!==Ge||e[110]!==Ke?(qe=(0,j.jsx)(`div`,{style:Ue,children:(0,j.jsx)(le,{disabled:We,stops:Ge,stopKey:Ke,setStopKey:w})}),e[107]=w,e[108]=We,e[109]=Ge,e[110]=Ke,e[111]=qe):qe=e[111];let Je;e[112]===L.isLoading?Je=e[113]:(Je=L.isLoading&&(0,j.jsx)(f,{}),e[112]=L.isLoading,e[113]=Je);let Ye;e[114]!==qe||e[115]!==Je?(Ye=(0,j.jsx)(C,{container:!0,size:Ve,children:(0,j.jsxs)(ie,{style:He,children:[qe,Je]})}),e[114]=qe,e[115]=Je,e[116]=Ye):Ye=e[116];let Xe;e[117]!==H.data||e[118]!==H.isLoading||e[119]!==N||e[120]!==R||e[121]!==n||e[122]!==E?(Xe=N&&R&&(0,j.jsx)(C,{size:{xs:12},children:(0,j.jsxs)(oe,{marginBottom:!0,children:[H.isLoading&&(0,j.jsxs)(ie,{children:[(0,j.jsx)(se,{text:n(`loading_hits`)}),(0,j.jsx)(f,{})]}),!H.isLoading&&(H.data?.gtfsTime&&H.data.gtfsTime.length>0||H.data?.siriTime&&H.data.siriTime.length>0?(0,j.jsx)(Ee,{target:E,gtfsTimes:H.data.gtfsTime,siriTimes:H.data.siriTime}):(0,j.jsx)(ne,{children:n(`hits_not_found`)}))]})}),e[117]=H.data,e[118]=H.isLoading,e[119]=N,e[120]=R,e[121]=n,e[122]=E,e[123]=Xe):Xe=e[123];let Ze;e[124]!==X||e[125]!==Q||e[126]!==je||e[127]!==Pe||e[128]!==Be||e[129]!==Ye||e[130]!==Xe?(Ze=(0,j.jsxs)(C,{container:!0,spacing:2,children:[X,Q,je,Pe,Be,Ye,Xe]}),e[124]=X,e[125]=Q,e[126]=je,e[127]=Pe,e[128]=Be,e[129]=Ye,e[130]=Xe,e[131]=Ze):Ze=e[131];let Qe;return e[132]!==W||e[133]!==K||e[134]!==q||e[135]!==Ze?(Qe=(0,j.jsxs)(c,{children:[W,K,q,Ze]}),e[132]=W,e[133]=K,e[134]=q,e[135]=Ze,e[136]=Qe):Qe=e[136],Qe};function Oe(e){return{...e,routeKey:null}}function ke(e){return{...e,stopKey:null}}export{De as default};