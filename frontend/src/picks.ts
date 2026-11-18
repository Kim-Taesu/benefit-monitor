// Weekly AI/rule picks for the festival and benefit tabs. Display only: every date, fee and link is
// drawn from the already-parsed data; the model contributes only the short summary and per-line note.
import type {Festival,FestivalBundle} from './festivals';
import type {Benefit} from './benefits';
import {fees} from './benefits.ts';
import type {Subscription,SubscriptionBundle} from './subscriptions';

export interface FestivalPick{source:'ai'|'rule';summary:string|null;picks:{festival:Festival;line:string|null}[]}
export interface BenefitPick{source:'ai'|'rule';summary:string|null;picks:{item:Benefit;line:string|null}[]}
export interface SubscriptionPick{source:'ai'|'rule';summary:string|null;picks:{item:Subscription;line:string|null}[]}

const MAX_PICKS=10;
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function text(v:unknown,limit:number):v is string{return typeof v==='string'&&v.length>0&&v.length<=limit&&!/[<>\u0000-\u001f]/.test(v);}
function head(p:Record<string,unknown>):boolean{
 if(p.schema_version!==1||(p.source!=='ai'&&p.source!=='rule')||!Array.isArray(p.picks)||p.picks.length>MAX_PICKS)return false;
 // An ai pick may have lost its summary when a re-check dropped a line; its lines stay.
 return p.source==='ai'?p.summary===null||text(p.summary,220):p.summary===null;
}
function line(source:unknown,v:unknown):string|null|undefined{
 if(v===null)return null;
 if(!text(v,80))return undefined;
 return source==='rule'?null:v;
}

/** The pick's lines whose key finds a current item, first occurrence only, plus whether any line was dropped
 *  (unknown key, bad line). `id` turns a raw line into the lookup key, or null when it has the wrong shape. */
function lines<T>(p:Record<string,unknown>,id:(x:Record<string,unknown>)=>string|null,byId:Map<string,T>){
 const picks:{item:T;line:string|null}[]=[],seen=new Set<string>();
 for(const x of p.picks as unknown[]){
  if(!record(x))continue;
  const k=id(x),item=k===null?undefined:byId.get(k),l=line(p.source,x.line);
  if(k!==null&&item&&l!==undefined&&!seen.has(k)){seen.add(k);picks.push({item,line:l});}
 }
 return {picks,dropped:picks.length<(p.picks as unknown[]).length};
}
function pickOf(raw:unknown,key:string):Record<string,unknown>|null{
 if(!record(raw)||!record(raw[key]))return null;
 return head(raw[key] as Record<string,unknown>)?raw[key] as Record<string,unknown>:null;
}
const source=(p:Record<string,unknown>)=>p.source as 'ai'|'rule';
const byStringId=(x:Record<string,unknown>)=>typeof x.id==='string'?x.id:null;

/** Festival: the summary stays when a line is dropped (it was always shown that way). */
export function parseFestivalPick(raw:unknown,bundle:FestivalBundle):FestivalPick|null{
 const p=pickOf(raw,'festival_pick');if(!p)return null;
 const {picks}=lines(p,byStringId,new Map(bundle.items.map(f=>[f.id,f] as const)));
 return picks.length?{source:source(p),summary:p.source==='ai'?p.summary as string|null:null,picks:picks.map(x=>({festival:x.item,line:x.line}))}:null;
}

export function parseBenefitPick(raw:unknown,items:Benefit[]):BenefitPick|null{
 const p=pickOf(raw,'benefit_pick');if(!p)return null;
 const key=(source:string,url:string)=>source+'\n'+url;
 // Items here are Seoul-filtered, the backend picked from all public items: a summary may name a dropped line.
 const {picks,dropped}=lines(p,x=>typeof x.source==='string'&&typeof x.url==='string'?key(x.source,x.url):null,
  new Map(items.map(i=>[key(i.source,i.url),i] as const)));
 const total=(p.picks as unknown[]).length;
 if(!picks.length||picks.length<Math.min(3,total))return null;
 return {source:source(p),summary:p.source==='ai'&&!dropped?p.summary as string|null:null,picks};
}

/** 청약 pick (2026-11-18). A complex that closed since publication drops its line and, like benefits, the summary. */
export function parseSubscriptionPick(raw:unknown,bundle:SubscriptionBundle):SubscriptionPick|null{
 const p=pickOf(raw,'subscription_pick');if(!p)return null;
 const {picks,dropped}=lines(p,byStringId,new Map(bundle.items.map(i=>[i.id,i] as const)));
 return picks.length?{source:source(p),summary:p.source==='ai'&&!dropped?p.summary as string|null:null,picks}:null;
}

const md=(date:string)=>`${Number(date.slice(5,7))}/${Number(date.slice(8,10))}`;
export function festivalLine(f:Festival):string{
 const period=f.start===f.end?md(f.start):`${md(f.start)}~${md(f.end)}`;
 return `${f.name} (${period} · ${f.region||'지역 미확인'})`;
}
/** `~M/D` from the application deadline (KST) or the validity end; empty when neither exists. */
export function benefitDeadline(i:Benefit):string{
 if(i.deadline_at){
  const t=Date.parse(i.deadline_at);
  if(Number.isFinite(t))return '~'+md(new Date(t+9*3600000).toISOString().slice(0,10));
 }
 return i.valid_until&&/^\d{4}-\d{2}-\d{2}$/.test(i.valid_until)?'~'+md(i.valid_until):'';
}
export function benefitFeeLabel(i:Benefit):string{
 return i.fee_status==='paid'?'유료·구매 필요':fees[i.fee_status]??fees.unknown;
}
