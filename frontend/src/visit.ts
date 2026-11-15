// "새로 올라옴" 표시용 방문 기록. 이 브라우저에만 저장하고 어디로도 보내지 않는다(2026-11-15 승인).
// 공개 데이터에는 항목이 처음 공개된 시각이 없고 확인 시각은 재확인 때마다 바뀌므로,
// 지난 방문 때 보였던 항목의 지문(원문·URL 없음)과 비교해야 새 항목을 가릴 수 있다.
import type {Benefit} from './benefits.ts';
import {benefitKey} from './favorites.ts';

export const VISIT_KEY='benefit-monitor:visit:v1';
/** 이 시간 안의 재방문은 같은 방문으로 본다. */
export const VISIT_GAP=6*3600000;
const MAX_KEYS=500;
type Store=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
export interface VisitRecord {version:1;at:number;keys:string[];previousAt:number|null;previousKeys:string[];introClosed:boolean}
export interface Visit {record:VisitRecord;first:boolean;previousAt:number|null;fresh:Set<string>}

export function fingerprint(text:string):string {
 let a=2166136261,b=5381;
 for(let n=0;n<text.length;n++){a=Math.imul(a^text.charCodeAt(n),16777619);b=Math.imul(b,33)^text.charCodeAt(n);}
 return (a>>>0).toString(16).padStart(8,'0')+(b>>>0).toString(16).padStart(8,'0');
}
export const visitKey=(item:Pick<Benefit,'source'|'url'>)=>fingerprint(benefitKey(item));
const keyList=(v:unknown):v is string[]=>Array.isArray(v)&&v.length<=MAX_KEYS&&v.every(k=>typeof k==='string'&&/^[0-9a-f]{16}$/.test(k));
const time=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v)&&v>0;
function valid(v:unknown):v is VisitRecord {
 if(!v||typeof v!=='object'||Array.isArray(v))return false;
 const r=v as Record<string,unknown>;
 return Object.keys(r).sort().join(',')==='at,introClosed,keys,previousAt,previousKeys,version'&&r.version===1&&time(r.at)&&keyList(r.keys)&&(r.previousAt===null||time(r.previousAt))&&keyList(r.previousKeys)&&typeof r.introClosed==='boolean';
}
export function loadVisit(storage:Store|null,now:number):VisitRecord|null {
 try{const raw=storage?.getItem(VISIT_KEY);if(!raw||raw.length>50000)return null;const v:unknown=JSON.parse(raw);return valid(v)&&v.at<=now&&(v.previousAt===null||v.previousAt<=v.at)?v:null;}catch{return null;}
}
export function saveVisit(storage:Store|null,record:VisitRecord):boolean {
 try{if(!storage||!valid(record))return false;storage.setItem(VISIT_KEY,JSON.stringify(record));return true;}catch{return false;}
}
export function clearVisit(storage:Store|null):boolean {try{if(!storage)return false;storage.removeItem(VISIT_KEY);return true;}catch{return false;}}

/** 저장된 기록과 지금 보이는 항목으로 이번 방문 상태를 만든다. 지난 방문에 없던 항목만 새 항목이다. */
export function nextVisit(stored:VisitRecord|null,keys:string[],now:number):Visit {
 const current=[...new Set(keys)].slice(-MAX_KEYS);
 if(!stored)return {record:{version:1,at:now,keys:current,previousAt:null,previousKeys:[],introClosed:false},first:true,previousAt:null,fresh:new Set()};
 const returning=now-stored.at>VISIT_GAP;
 const previousAt=returning?stored.at:stored.previousAt,previousKeys=returning?stored.keys:stored.previousKeys;
 const record:VisitRecord={version:1,at:returning?now:stored.at,keys:returning?current:[...new Set([...stored.keys,...current])].slice(-MAX_KEYS),previousAt,previousKeys,introClosed:stored.introClosed};
 const before=new Set(previousKeys);
 return {record,first:previousAt===null,previousAt,fresh:previousAt===null?new Set():new Set(current.filter(k=>!before.has(k)))};
}
