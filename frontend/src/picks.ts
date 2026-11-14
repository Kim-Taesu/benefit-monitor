// Weekly AI/rule picks for the festival and benefit tabs. Display only: every date, fee and link is
// drawn from the already-parsed data; the model contributes only the short summary and per-line note.
import type {Festival,FestivalBundle} from './festivals';
import type {Benefit} from './benefits';
import {fees} from './benefits.ts';

export interface FestivalPick{source:'ai'|'rule';summary:string|null;picks:{festival:Festival;line:string|null}[]}
export interface BenefitPick{source:'ai'|'rule';summary:string|null;picks:{item:Benefit;line:string|null}[]}

const MAX_PICKS=10;
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function text(v:unknown,limit:number):v is string{return typeof v==='string'&&v.length>0&&v.length<=limit&&!/[<>\u0000-\u001f]/.test(v);}
function head(p:Record<string,unknown>):boolean{
 if(p.schema_version!==1||(p.source!=='ai'&&p.source!=='rule')||!Array.isArray(p.picks)||p.picks.length>MAX_PICKS)return false;
 return p.source==='ai'?text(p.summary,220):p.summary===null;
}
function line(source:unknown,v:unknown):string|null|undefined{
 if(v===null)return null;
 if(!text(v,80))return undefined;
 return source==='rule'?null:v;
}

export function parseFestivalPick(raw:unknown,bundle:FestivalBundle):FestivalPick|null{
 if(!record(raw)||!record(raw.festival_pick))return null;
 const p=raw.festival_pick;
 if(!head(p))return null;
 const byId=new Map(bundle.items.map(f=>[f.id,f] as const));
 const picks:FestivalPick['picks']=[],seen=new Set<string>();
 for(const x of p.picks as unknown[]){
  if(!record(x)||typeof x.id!=='string')continue;
  const festival=byId.get(x.id),l=line(p.source,x.line);
  if(festival&&l!==undefined&&!seen.has(x.id)){seen.add(x.id);picks.push({festival,line:l});}
 }
 return picks.length?{source:p.source as 'ai'|'rule',summary:p.source==='ai'?p.summary as string:null,picks}:null;
}

export function parseBenefitPick(raw:unknown,items:Benefit[]):BenefitPick|null{
 if(!record(raw)||!record(raw.benefit_pick))return null;
 const p=raw.benefit_pick;
 if(!head(p))return null;
 const key=(source:string,url:string)=>source+'\n'+url;
 const bySource=new Map(items.map(i=>[key(i.source,i.url),i] as const));
 const picks:BenefitPick['picks']=[],seen=new Set<string>();
 for(const x of p.picks as unknown[]){
  if(!record(x)||typeof x.source!=='string'||typeof x.url!=='string')continue;
  const k=key(x.source,x.url),item=bySource.get(k),l=line(p.source,x.line);
  if(item&&l!==undefined&&!seen.has(k)){seen.add(k);picks.push({item,line:l});}
 }
 return picks.length?{source:p.source as 'ai'|'rule',summary:p.source==='ai'?p.summary as string:null,picks}:null;
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
