import type {Benefit,Filters} from './benefits.ts';
import {filterUrl,safeOfficial} from './benefits.ts';
export const FAVORITES_KEY='benefit-monitor:favorites:v1';
type FavoriteStorage=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
export const benefitKey=(item:Pick<Benefit,'source'|'url'>)=>item.source+'\n'+item.url;
function validIds(ids:unknown):ids is string[]{
 return Array.isArray(ids)&&ids.length<=200&&ids.every(id=>{
  if(typeof id!=='string'||id.length>4096)return false;
  const parts=id.split('\n');return parts.length===2&&safeOfficial(parts[1],parts[0]);
 });
}
export function loadFavorites(storage:FavoriteStorage|null):string[]{
 try{const v=JSON.parse(storage?.getItem(FAVORITES_KEY)||'null');return v&&Object.keys(v).length===2&&v.version===1&&validIds(v.ids)?[...new Set<string>(v.ids)]:[];}catch{return [];}
}
export function saveFavorites(storage:FavoriteStorage|null,ids:string[]):boolean{
 try{if(!storage||!validIds(ids))return false;storage.setItem(FAVORITES_KEY,JSON.stringify({version:1,ids:[...new Set(ids)]}));return true;}catch{return false;}
}
export function clearFavorites(storage:FavoriteStorage|null):boolean{
 try{if(!storage)return false;storage.removeItem(FAVORITES_KEY);return true;}catch{return false;}
}
export function visibleFavorites(items:Benefit[],ids:string[]):Benefit[]{const saved=new Set(ids);return items.filter(item=>saved.has(benefitKey(item)));}
export function searchShareUrl(current:URL,filters:Filters):URL{
 const url=filterUrl(new URL(current.pathname,current.origin),filters);
 // An explicit default sort keeps a recipient's remembered interests from changing an all-regions link.
 url.searchParams.set('sort',filters.sort);return url;
}
