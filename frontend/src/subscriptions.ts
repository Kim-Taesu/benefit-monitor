// Seoul·Gyeonggi 청약 schedule (2026-11-17), a section of the benefits tab. Facts copied from 청약홈
// (dates, district, units, area and top-price ranges). Eligibility and win chances are never judged here.
export type SubKind='apt'|'remain'|'officetel'|'rental';
export interface SubStep{label:string;start:string;end:string}
export interface SubTrade{amount:number;month:string;kind:'입주권'|'분양권'|'매매'}
export interface SubType{label:string;area:number;pyeong:number|null;general:number|null;special:number|null;price:number|null;trade:SubTrade|null}
export interface SubKindCount{name:string;count:number}
export interface Subscription{id:string;name:string;area:'서울'|'경기';district:string|null;kind:SubKind;supply:string;units:number|null;
 noticeDate:string|null;types:SubType[];specialKinds:SubKindCount[];noticePdf:string|null;tradeStatus:'checked'|'unavailable';
 areaMin:number|null;areaMax:number|null;priceMin:number|null;priceMax:number|null;moveIn:string|null;regulation:string[];
 steps:SubStep[];announce:string|null;contractStart:string|null;contractEnd:string|null;url:string;detail:'checked'|'failed';checkedAt:string|null}
export interface SubscriptionBundle{fetchedAt:string;notice:string;windowDays:number;items:Subscription[]}
export interface TimelineStep{label:string;text:string;state:'done'|'now'|'next'}
export interface SubGroup{key:string;label:string;items:Subscription[]}
export type KindFilter=''|'apt'|'remain'|'etc';

const KEYS=['id','name','area','district','kind','supply','units','notice_date','types','special_kinds','notice_pdf','trade_status','area_min','area_max','price_min','price_max','move_in','regulation','steps',
 'announce','contract_start','contract_end','url','detail','checked_at'];
const KINDS:SubKind[]=['apt','remain','officetel','rental'];
const DATE=/^\d{4}-\d{2}-\d{2}$/;
export const CALENDAR_PAGE='https://www.applyhome.co.kr/ai/aib/selectSubscrptCalenderView.do';
export const KIND_LABELS:Record<Exclude<KindFilter,''>,string>={apt:'아파트 분양',remain:'무순위·잔여',etc:'오피스텔·임대'};

function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function num(v:unknown,max:number):v is number|null{return v===null||(typeof v==='number'&&Number.isFinite(v)&&v>0&&v<max);}
function count(v:unknown):v is number|null{return v===null||(typeof v==='number'&&Number.isInteger(v)&&v>=0&&v<100000);}
function day(v:unknown):v is string|null{return v===null||(typeof v==='string'&&DATE.test(v));}
export function kstDate(now:number):string{return new Date(now+9*3600000).toISOString().slice(0,10);}

function parseItem(v:unknown):Subscription|null{
 if(!record(v)||Object.keys(v).length!==KEYS.length||!KEYS.every(k=>Object.hasOwn(v,k)))return null;
 if(typeof v.id!=='string'||!/^\d{6,12}$/.test(v.id)||typeof v.name!=='string'||!v.name||v.name.length>80)return null;
 if((v.area!=='서울'&&v.area!=='경기')||!KINDS.includes(v.kind as SubKind)||(v.detail!=='checked'&&v.detail!=='failed'))return null;
 if(v.district!==null&&(typeof v.district!=='string'||!v.district||v.district.length>20))return null;
 if(!num(v.units,100000)||!num(v.area_min,1000)||!num(v.area_max,1000)||!num(v.price_min,1e7)||!num(v.price_max,1e7))return null;
 if(v.move_in!==null&&(typeof v.move_in!=='string'||!/^\d{4}-\d{2}$/.test(v.move_in)))return null;
 if(!Array.isArray(v.regulation)||v.regulation.some(r=>typeof r!=='string'||r.length>20))return null;
 if(!Array.isArray(v.steps)||!v.steps.length||v.steps.length>12)return null;
 const steps:SubStep[]=[];
 for(const s of v.steps){
  if(!record(s)||Object.keys(s).length!==3||typeof s.label!=='string'||!s.label||s.label.length>20||!day(s.start)||!day(s.end)||!s.start||!s.end||s.start>s.end)return null;
  steps.push({label:s.label,start:s.start,end:s.end});
 }
 if(!day(v.announce)||!day(v.contract_start)||!day(v.contract_end)||!day(v.notice_date))return null;
 if(typeof v.supply!=='string'||!v.supply||v.supply.length>20)return null;
 if(v.trade_status!=='checked'&&v.trade_status!=='unavailable')return null;
 if(!Array.isArray(v.types)||v.types.length>40||!Array.isArray(v.special_kinds)||v.special_kinds.length>12)return null;
 const types:SubType[]=[];
 for(const x of v.types){
  if(!record(x)||Object.keys(x).length!==7||typeof x.label!=='string'||!/^\d{1,3}[A-Z]{0,4}$/.test(x.label)||typeof x.area!=='number'||!num(x.area,1000)||!num(x.pyeong,400)||!num(x.price,1e7))return null;
  if(!count(x.general)||!count(x.special))return null;
  let trade:SubTrade|null=null;
  if(x.trade!==null){
   const r=x.trade;
   if(!record(r)||Object.keys(r).length!==3||typeof r.amount!=='number'||!num(r.amount,1e7)||typeof r.month!=='string'||!/^\d{4}-(0[1-9]|1[0-2])$/.test(r.month)||!['입주권','분양권','매매'].includes(r.kind as string))return null;
   trade={amount:r.amount,month:r.month,kind:r.kind as SubTrade['kind']};
  }
  types.push({label:x.label,area:x.area,pyeong:x.pyeong,general:x.general,special:x.special,price:x.price,trade});
 }
 const specialKinds:SubKindCount[]=[];
 for(const x of v.special_kinds){
  if(!record(x)||Object.keys(x).length!==2||typeof x.name!=='string'||!x.name||x.name.length>10||typeof x.count!=='number'||!num(x.count,100000))return null;
  specialKinds.push({name:x.name,count:x.count});
 }
 let pdf:string|null=null;
 if(v.notice_pdf!==null){
  try{const u=new URL(String(v.notice_pdf));if(u.protocol!=='https:'||u.hostname!=='static.applyhome.co.kr'||u.pathname!=='/ai/aia/getAtchmnfl.do'||u.username||u.password)return null;pdf=u.href;}catch{return null;}
 }
 if(v.checked_at!==null&&(typeof v.checked_at!=='string'||!Number.isFinite(Date.parse(v.checked_at))))return null;
 let url:URL;
 try{url=new URL(String(v.url));}catch{return null;}
 if(url.protocol!=='https:'||url.hostname!=='www.applyhome.co.kr'||url.username||url.password)return null;
 return {id:v.id,name:v.name,area:v.area,district:v.district as string|null,kind:v.kind as SubKind,supply:v.supply,units:v.units,
  noticeDate:v.notice_date,types,specialKinds,noticePdf:pdf,tradeStatus:v.trade_status,areaMin:v.area_min,areaMax:v.area_max,
  priceMin:v.price_min,priceMax:v.price_max,moveIn:v.move_in as string|null,regulation:[...v.regulation as string[]],steps,announce:v.announce,
  contractStart:v.contract_start,contractEnd:v.contract_end,url:url.href,detail:v.detail,checkedAt:v.checked_at as string|null};
}

export function parseSubscriptions(raw:unknown,now:number):SubscriptionBundle|null{
 if(!record(raw)||!record(raw.subscriptions))return null;
 const b=raw.subscriptions;
 if(b.schema_version!==1||b.source!=='subscriptions'||typeof b.fetched_at!=='string'||typeof b.notice!=='string'||!Array.isArray(b.items)||b.items.length>120)return null;
 const fetched=Date.parse(b.fetched_at);
 if(!Number.isFinite(fetched)||fetched>now+5*60000||now-fetched>30*3600000)return null;
 const today=kstDate(now),items:Subscription[]=[],seen=new Set<string>();
 for(const raw of b.items){
  const item=parseItem(raw);
  if(!item||seen.has(item.id))return null;
  seen.add(item.id);
  if(item.steps.some(s=>s.end>=today))items.push(item);
 }
 return {fetchedAt:b.fetched_at,notice:b.notice,windowDays:typeof b.window_days==='number'?b.window_days:14,items};
}

const md=(d:string)=>`${Number(d.slice(5,7))}/${Number(d.slice(8,10))}`;
export function range(start:string,end:string):string{
 if(start===end)return md(start);
 return start.slice(0,7)===end.slice(0,7)?`${md(start)}~${Number(end.slice(8,10))}`:`${md(start)}~${md(end)}`;
}
const WEEKDAYS='일월화수목금토';
const dayOf=(d:string)=>new Date(d+'T00:00:00Z').getUTCDay();
const addDays=(d:string,n:number)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
export function weekday(d:string):string{return `${md(d)}(${WEEKDAYS[dayOf(d)]})`;}

function state(start:string,end:string,today:string):TimelineStep['state']{return end<today?'done':start<=today?'now':'next';}
export function timeline(item:Subscription,today:string):TimelineStep[]{
 const out=item.steps.map(s=>({label:s.label,text:range(s.start,s.end),state:state(s.start,s.end,today)}));
 if(item.announce)out.push({label:'당첨 발표',text:md(item.announce),state:state(item.announce,item.announce,today)});
 if(item.contractStart)out.push({label:'계약',text:range(item.contractStart,item.contractEnd||item.contractStart),state:state(item.contractStart,item.contractEnd||item.contractStart,today)});
 return out;
}

/** The receipt step that matters now: the one in progress, else the next one. */
export function nextStep(item:Subscription,today:string):SubStep{
 return item.steps.find(s=>s.end>=today)||item.steps[item.steps.length-1];
}
export function badge(item:Subscription,today:string):{text:string;tone:'urgent'|'soon'|'plain'}{
 const s=nextStep(item,today),base=s.label.replace(/ 접수$/,'');
 if(s.start<=today){
  if(s.start===s.end)return {text:`${base} 오늘 접수`,tone:'urgent'};
  if(s.end===today)return {text:`${base} 오늘 마감`,tone:'urgent'};
  return {text:`${base} 접수 중 · ${md(s.end)}까지`,tone:'urgent'};
 }
 if(s.start===addDays(today,1))return {text:`${base} 내일 접수`,tone:'soon'};
 const days=Math.round((Date.parse(s.start)-Date.parse(today))/86400000);
 return {text:`${s.label} D-${days}`,tone:'plain'};
}

/** Map search words: the district's last 시·군·구 word (not a 택지 '지구') or the area, then the name before any
 *  parenthesis ('더샵 분당센트로(7차)' in '성남시 분당구' -> '분당구 더샵 분당센트로'). The page only links; it calls no map API. */
export function mapQuery(item:Subscription):string{
 const place=(item.district||'').trim().split(/\s+/).filter(w=>/[시군구]$/.test(w)&&!/지구$/.test(w)).pop()||item.area;
 const name=item.name.split('(')[0].trim()||item.name;
 return `${place} ${name}`;
}
export function kakaoMapUrl(item:Subscription):string{return 'https://map.kakao.com/link/search/'+encodeURIComponent(mapQuery(item));}
export function naverMapUrl(item:Subscription):string{return 'https://map.naver.com/p/search/'+encodeURIComponent(mapQuery(item));}

/** '서울 중랑구', or just the area when the district is unknown. */
export function placeLabel(item:Subscription):string{return item.district?`${item.area} ${item.district}`:item.area;}
export function isMine(item:Subscription,region:string):boolean{return !!region&&item.area==='서울'&&item.district===region;}

export function groupByDay(items:Subscription[],today:string,region:string):SubGroup[]{
 const tomorrow=addDays(today,1),sunday=addDays(today,(7-dayOf(today))%7),nextSunday=addDays(sunday,7);
 const groups=new Map<string,SubGroup>();
 const sorted=[...items].map(i=>({i,at:nextStep(i,today).start<today?today:nextStep(i,today).start}))
  .sort((a,b)=>a.at.localeCompare(b.at)||a.i.name.localeCompare(b.i.name,'ko'));
 for(const {i,at} of sorted){
  const [key,label]=at===today?['today',`오늘 · ${weekday(today)}`]:at===tomorrow?['tomorrow',`내일 · ${weekday(tomorrow)}`]
   :at<=sunday?['week','이번 주']:at<=nextSunday?['next','다음 주']:['later','그 후'];
  if(!groups.has(key))groups.set(key,{key,label,items:[]});
  groups.get(key)!.items.push(i);
 }
 // 같은 묶음 안에서는 내 지역 단지를 맨 위로.
 for(const g of groups.values())g.items.sort((a,b)=>Number(isMine(b,region))-Number(isMine(a,region)));
 return [...groups.values()];
}

function won(manwon:number):string{
 if(manwon<10000)return manwon.toLocaleString('ko-KR')+'만';
 const eok=Math.round(manwon/1000)/10;
 return (Number.isInteger(eok)?String(eok):eok.toFixed(1))+'억';
}
export function formatPrice(min:number|null,max:number|null):string|null{
 if(min===null&&max===null)return null;
 const lo=min??max!,hi=max??min!;
 return lo===hi?won(lo):`${won(lo)}~${won(hi)}`;
}
export function formatArea(min:number|null,max:number|null):string|null{
 if(min===null&&max===null)return null;
 const lo=Math.round(min??max!),hi=Math.round(max??min!);
 return lo===hi?`전용 ${lo}㎡`:`전용 ${lo}~${hi}㎡`;
}
export function filterSubs(items:Subscription[],f:{area:''|'서울'|'경기';kind:KindFilter;q:string}):Subscription[]{
 const q=f.q.trim();
 return items.filter(i=>(!f.area||i.area===f.area)
  &&(!f.kind||(f.kind==='etc'?i.kind==='officetel'||i.kind==='rental':i.kind===f.kind))
  &&(!q||i.name.includes(q)||(i.district||'').includes(q)||i.area.includes(q)));
}

/** 표 한 줄의 '구분': 일반·특공 세대수가 있으면 보이고, 없으면 빈칸. */
export function typeSplit(t:SubType):string{
 if(t.general===null||t.special===null)return '';
 return [t.general?`일반 ${t.general}`:'',t.special?`특공 ${t.special}`:''].filter(Boolean).join(' · ');
}
export function specialSummary(kinds:SubKindCount[],max=4):string{
 if(!kinds.length)return '';
 const total=kinds.reduce((a,k)=>a+k.count,0),shown=kinds.slice(0,max).map(k=>`${k.name} ${k.count}`);
 return `특공 ${total}세대: ${shown.join(' · ')}${kinds.length>max?` 외 ${kinds.length-max}종`:''}`;
}
export function priceOne(manwon:number|null):string{return manwon===null?'문의':formatPrice(manwon,manwon)!;}
/** 실거래 칸: '43.0억' + '입주권 26.07'. */
export function tradeText(t:SubTrade|null):{price:string;note:string}|null{
 if(!t)return null;
 return {price:formatPrice(t.amount,t.amount)!,note:`${t.kind} ${t.month.slice(2,4)}.${t.month.slice(5,7)}`};
}
