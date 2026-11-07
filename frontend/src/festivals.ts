// Nationwide festival listings (한국관광공사 대한민국 구석구석). A separate, unverified display
// channel: never mixed into verified benefits, favorites or topic cards.
export const FESTIVAL_DETAIL='https://korean.visitkorea.or.kr/kfes/detail/fstvlDetail.do?fstvlCntntsId=';
export const festivalFees:Record<string,string>={free:'무료',paid:'유료',mixed:'일부 유료',unknown:'요금 미확인'};
const KEYS=['id','name','start','end','region','place','organizer','fee_status','fee_text','discount','summary','programs','homepage','culture_tourism','url','modified'] as const;
const LIMITS:Record<string,number>={name:120,region:60,place:160,organizer:80,fee_text:200,discount:300,summary:400,programs:400,homepage:300};
const DATE=/^\d{4}-\d{2}-\d{2}$/,ID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export interface Festival{id:string;name:string;start:string;end:string;region:string;place:string;organizer:string;fee_status:string;fee_text:string;discount:string;summary:string;programs:string;homepage:string;culture_tourism:boolean;url:string;modified:string|null;province:string}
export interface FestivalBundle{fetchedAt:string;notice:string;items:Festival[]}

function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
export function kstDate(now:number):string{return new Date(now+9*3600000).toISOString().slice(0,10);}
function safeHttps(url:string):boolean{
 try{const u=new URL(url);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}
}
function parseItem(v:unknown):Festival|null{
 if(!record(v)||Object.keys(v).length!==KEYS.length||!KEYS.every(k=>Object.hasOwn(v,k)))return null;
 for(const [key,limit] of Object.entries(LIMITS))if(typeof v[key]!=='string'||(v[key] as string).length>limit)return null;
 const id=v.id,start=v.start,end=v.end,modified=v.modified;
 if(typeof id!=='string'||!ID.test(id)||v.url!==FESTIVAL_DETAIL+id)return null;
 if(typeof start!=='string'||typeof end!=='string'||!DATE.test(start)||!DATE.test(end)||end<start)return null;
 if(modified!==null&&(typeof modified!=='string'||!DATE.test(modified)))return null;
 if(typeof v.fee_status!=='string'||!Object.hasOwn(festivalFees,v.fee_status)||typeof v.culture_tourism!=='boolean')return null;
 const homepage=v.homepage as string;
 if(!(v.name as string).trim()||(homepage&&!safeHttps(homepage)))return null;
 const region=v.region as string;
 return {...(v as unknown as Festival),modified:modified as string|null,province:region.split(' ')[0]||'지역 미확인'};
}
export function parseFestivals(raw:unknown,now:number):FestivalBundle|null{
 if(!record(raw)||!record(raw.festivals))return null;
 const f=raw.festivals;
 if(f.schema_version!==1||f.source!=='kfes'||typeof f.fetched_at!=='string'||typeof f.notice!=='string'||!Array.isArray(f.items)||f.items.length>200)return null;
 const fetched=Date.parse(f.fetched_at);
 if(!Number.isFinite(fetched)||fetched>now+5*60000||now-fetched>30*3600000)return null;
 const today=kstDate(now),seen=new Set<string>(),items:Festival[]=[];
 for(const row of f.items){const item=parseItem(row);if(item&&item.end>=today&&!seen.has(item.id)){seen.add(item.id);items.push(item);}}
 items.sort((a,b)=>(a.start<=today?a.end:a.start).localeCompare(b.start<=today?b.end:b.start)||a.name.localeCompare(b.name));
 return {fetchedAt:f.fetched_at,notice:f.notice,items};
}
export function festivalStatus(item:Festival,now:number):{ongoing:boolean;label:string}{
 const today=kstDate(now),days=(a:string,b:string)=>Math.round((Date.parse(b)-Date.parse(a))/86400000);
 if(item.start<=today){const left=days(today,item.end);return {ongoing:true,label:left===0?'개최중 · 오늘 종료':`개최중 · ${left}일 남음`};}
 return {ongoing:false,label:`${days(today,item.start)}일 후 시작`};
}
export function festivalPeriod(item:Festival):string{
 const d=(s:string)=>s.replaceAll('-','.');
 return item.start===item.end?d(item.start):`${d(item.start)} ~ ${d(item.end)}`;
}
export function provinces(items:Festival[]):string[]{return [...new Set(items.map(i=>i.province))].sort((a,b)=>a.localeCompare(b,'ko'));}
