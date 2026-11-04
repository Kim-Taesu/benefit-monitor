import {categories} from './benefits.ts';
export const INTERESTS_KEY='benefit-monitor:interests:v1';
export interface Interests {region:string;category:string}
type InterestStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
function valid(value:unknown):value is Interests & {version:number} {
 if(!value||typeof value!=='object'||Array.isArray(value))return false;
 const v=value as Record<string,unknown>;
 return Object.keys(v).length===3&&v.version===1&&typeof v.region==='string'&&v.region.length<=80&&typeof v.category==='string'&&(v.category===''||categories.includes(v.category));
}
export function loadInterests(storage:InterestStorage|null):Interests|null {
 try{const value:unknown=JSON.parse(storage?.getItem(INTERESTS_KEY)||'null');return valid(value)?{region:value.region,category:value.category}:null;}catch{return null;}
}
export function saveInterests(storage:InterestStorage|null,value:Interests):boolean {
 try{if(!storage)return false;const record={version:1,region:value.region,category:value.category};if(!valid(record))return false;storage.setItem(INTERESTS_KEY,JSON.stringify(record));return true;}catch{return false;}
}
export function clearInterests(storage:InterestStorage|null):boolean {
 try{if(!storage)return false;storage.removeItem(INTERESTS_KEY);return true;}catch{return false;}
}
export function initialInterests(search:string,stored:Interests|null):Interests|null {
 const query=new URLSearchParams(search);
 return ['q','region','category','sort','status'].some(key=>query.has(key))?null:stored;
}
