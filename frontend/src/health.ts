// District public health centre (보건소) notice boards (2026-11-11). A separate, unverified display
// channel: titles and dates exactly as each board lists them. Health-looking titles are only a
// word match; free/eligibility facts come from the official notice or a reviewed benefit card.
export interface HealthNotice{id:string;title:string;url:string;date:string;dept:string;hint:boolean;district:string;center:string}
export interface HealthBoard{district:string;name:string;listUrl:string;homeUrl:string;status:'checked'|'failed'|'unavailable';reason:string|null;checkedAt:string|null;count:number}
export interface HealthProgram{district:string;center:string;name:string;url:string;status:'checked'|'failed'|'pending';checkedAt:string|null;stale:boolean;note:string|null}
export interface HealthBundle{fetchedAt:string;notice:string;boards:HealthBoard[];items:HealthNotice[];programs:HealthProgram[]}

const DATE=/^\d{4}-\d{2}-\d{2}$/;
const STATUSES=['checked','failed','unavailable'];
const BOARD_KEYS=['district','name','list_url','home_url','status','reason','checked_at','items'];
const ITEM_KEYS=['id','title','url','date','dept','hint'];
const PROGRAM_KEYS=['district','center','name','url','status','checked_at'];
const PROGRAM_STALE_MS=10*86400000;
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function exact(v:Record<string,unknown>,keys:string[]):boolean{return Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));}
function https(url:unknown):URL|null{
 if(typeof url!=='string')return null;
 try{const u=new URL(url);return u.protocol==='https:'&&!u.username&&!u.password?u:null;}catch{return null;}
}
function text(v:unknown,max:number):v is string{return typeof v==='string'&&v.length<=max;}

export function parseHealth(raw:unknown,now:number):HealthBundle|null{
 if(!record(raw)||!record(raw.health_notices))return null;
 const h=raw.health_notices;
 if(h.schema_version!==1||h.source!=='health_notices'||typeof h.fetched_at!=='string'||typeof h.notice!=='string'||!Array.isArray(h.boards)||h.boards.length>40)return null;
 const fetched=Date.parse(h.fetched_at);
 if(!Number.isFinite(fetched)||fetched>now+5*60000||now-fetched>30*3600000)return null;
 const boards:HealthBoard[]=[],items:HealthNotice[]=[],seen=new Set<string>();
 for(const b of h.boards){
  if(!record(b)||!exact(b,BOARD_KEYS)||!STATUSES.includes(b.status as string)||!text(b.district,10)||!b.district||seen.has(b.district)||!text(b.name,30))return null;
  const list=https(b.list_url),home=https(b.home_url);
  if(!list||!home||!Array.isArray(b.items)||b.items.length>30)return null;
  if(b.reason!==null&&!text(b.reason,120))return null;
  if(b.checked_at!==null&&(typeof b.checked_at!=='string'||!Number.isFinite(Date.parse(b.checked_at))))return null;
  seen.add(b.district);
  let count=0;
  for(const i of b.items){
   if(!record(i)||!exact(i,ITEM_KEYS)||!text(i.title,160)||!i.title||!text(i.dept,30)||!text(i.id,80)||typeof i.hint!=='boolean'||typeof i.date!=='string'||!DATE.test(i.date))return null;
   const u=https(i.url);
   if(!u||u.hostname!==list.hostname)return null;
   items.push({id:i.id,title:i.title,url:u.href,date:i.date,dept:i.dept,hint:i.hint,district:b.district,center:b.name});count++;
  }
  boards.push({district:b.district,name:b.name,listUrl:list.href,homeUrl:home.href,status:b.status as HealthBoard['status'],reason:b.reason as string|null,checkedAt:b.checked_at as string|null,count});
 }
 const programs:HealthProgram[]=[],urls=new Set<string>(),notes=parseNotes(raw.health_notes,now);
 const rawPrograms=h.programs??[];
 if(!Array.isArray(rawPrograms)||rawPrograms.length>150)return null;
 for(const p of rawPrograms){
  if(!record(p)||!exact(p,PROGRAM_KEYS)||!['checked','failed','pending'].includes(p.status as string)||!text(p.name,40)||!p.name||!text(p.center,30)||typeof p.district!=='string'||!seen.has(p.district))return null;
  const u=https(p.url);if(!u||urls.has(u.href))return null;
  const checked=p.checked_at===null?null:typeof p.checked_at==='string'&&Number.isFinite(Date.parse(p.checked_at))?p.checked_at:undefined;
  if(checked===undefined||(p.status==='checked'&&checked===null))return null;
  urls.add(u.href);
  const stale=!checked||now-Date.parse(checked)>PROGRAM_STALE_MS;
  programs.push({district:p.district,center:p.center as string,name:p.name,url:u.href,status:p.status as HealthProgram['status'],checkedAt:checked,stale,note:p.status==='checked'&&!stale?notes.get(u.href+'\n'+p.district)??null:null});
 }
 // AI 문구가 있는 사업을 먼저 보여준다.
 programs.sort((a,b)=>a.district.localeCompare(b.district,'ko')||Number(!!b.note)-Number(!!a.note)||a.name.localeCompare(b.name,'ko'));
 // 건강 혜택처럼 보이는 공지를 먼저, 그 안에서는 최근 날짜순.
 items.sort((a,b)=>Number(b.hint)-Number(a.hint)||b.date.localeCompare(a.date)||a.district.localeCompare(b.district,'ko'));
 boards.sort((a,b)=>a.district.localeCompare(b.district,'ko'));
 return {fetchedAt:h.fetched_at,notice:h.notice,boards,items,programs};
}

// AI sentences (health_notes), already re-checked by the publisher against the stored page text.
const NOTE_KEYS=['url','district','sentence','generated_at'];
function parseNotes(raw:unknown,now:number):Map<string,string>{
 const out=new Map<string,string>();
 if(!Array.isArray(raw)||raw.length>150)return out;
 for(const n of raw){
  if(!record(n)||!exact(n,NOTE_KEYS)||!text(n.sentence,180)||(n.sentence as string).length<25||/[<>\n\r]|https?:/.test(n.sentence as string)||typeof n.district!=='string'||typeof n.generated_at!=='string')continue;
  const g=Date.parse(n.generated_at),u=https(n.url);
  if(!u||!Number.isFinite(g)||g>now+5*60000||now-g>21*86400000)continue;
  out.set(u.href+'\n'+n.district,n.sentence as string);
 }
 return out;
}

export const boardStatus:Record<HealthBoard['status'],string>={checked:'수집됨',failed:'이번 수집 실패',unavailable:'자동 수집 안 함'};

export function filterHealth(items:HealthNotice[],district:string,hintOnly:boolean,query:string):HealthNotice[]{
 const q=query.trim().toLocaleLowerCase('ko');
 return items.filter(i=>(!district||i.district===district)&&(!hintOnly||i.hint)&&(!q||[i.title,i.dept,i.center].some(v=>v.toLocaleLowerCase('ko').includes(q))));
}
