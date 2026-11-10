// Grocery reference prices (KAMIS·축산물품질평가원) and buying guides. A separate, unverified display
// channel like festivals: never mixed into verified benefits, favorites or topic cards.
import {kstDate} from './festivals.ts';
import guide from './grocery-guide.json' with {type:'json'};

export type Basis='kamis_wiki'|'grading'|'general';
export interface Guide{basis:Basis;wiki?:string;updated?:string;good:string[];avoid?:string[];keep?:string;tip?:string;origin?:string;grade?:string}
export interface PriceRow{
 id:string;kind:'produce'|'meat';name:string;detail:string;unit:string;category:string;guideKey:string;
 current:number;currentLabel:string;normal:number|null;yearAgo:number|null;weekAgo:number|null;
 range:{min:number;minRegion:string;max:number;maxRegion:string}|null;seoul:number|null;featured:number;
}
export interface GroceryBundle{fetchedAt:string;notice:string;produceDate:string|null;meatDate:string|null;missing:string[];rows:PriceRow[]}
export interface Verdict{level:'cheap'|'normal'|'pricey';base:'평년'|'1년전';pct:number;label:string}

export const KAMIS_SOURCE='https://www.kamis.or.kr/customer/price/agricultureRetail/catalogue.do';
export const EKAPE_SOURCE='https://www.ekapepia.com/v3/hereMeat/regionAvgPrice.do';
export const CATEGORIES:string[]=guide.categories;
export const BASIS_LABEL:Record<Basis,string>=guide.basis as Record<Basis,string>;
const ITEMS=guide.items as Record<string,Guide>;
const MEAT=guide.meat as Record<string,Guide>;
const CATEGORY_OF=guide.category_of as Record<string,string>;
const FEATURED_ORDER=new Map<string,number>(guide.featured.map((name,i)=>[name,i]));
const MEAT_KEYS=Object.keys(MEAT).sort((a,b)=>b.length-a.length);
const PRICE_KEYS=['today','day_ago','week_ago','two_weeks_ago','year_ago','normal'] as const;
const PRODUCE_KEYS=['id','item','kind','unit','grade',...PRICE_KEYS];
const MEAT_FIELDS=['id','cut','label','unit','national','seoul','min','min_region','max','max_region'];
const REGIONS=new Set(['서울','부산','대구','인천','전남광주','대전','울산','세종','경기','강원','충북','충남','전북','경북','경남','제주']);
const UNITS=new Set(['원/100g','원/kg','원/30구','원/10구','원/마리']);
const DATE=/^\d{4}-\d{2}-\d{2}$/;
const DAY=86400000,MAX_SURVEY_AGE=7,MAX_PRICE=10_000_000;

function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function exact(v:Record<string,unknown>,keys:string[]):boolean{return Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));}
function text(v:unknown,limit:number,allowEmpty=false):v is string{
 return typeof v==='string'&&(allowEmpty||v.length>0)&&v.length<=limit&&!/[<>\u0000-\u001f]/.test(v);
}
function price(v:unknown):v is number|null{return v===null||(Number.isInteger(v)&&(v as number)>0&&(v as number)<=MAX_PRICE);}
function fresh(date:unknown,now:number):date is string{
 if(typeof date!=='string'||!DATE.test(date))return false;
 const age=(Date.parse(kstDate(now))-Date.parse(date))/DAY;
 return age>=0&&age<=MAX_SURVEY_AGE;
}
function meatKey(cut:string):string{return MEAT_KEYS.find(k=>cut.startsWith(k))??'';}

function produceRow(v:unknown):PriceRow|null{
 if(!record(v)||!exact(v,PRODUCE_KEYS))return null;
 if(!text(v.item,40)||!text(v.kind,60)||!text(v.unit,20)||!text(v.grade,10,true))return null;
 if(v.id!==[v.item,v.kind,v.unit,v.grade].join('|')||!PRICE_KEYS.every(k=>price(v[k])))return null;
 const today=v.today as number|null,dayAgo=v.day_ago as number|null;
 const current=today??dayAgo;
 if(current===null)return null;
 const item=v.item,kind=v.kind;
 const detail=[kind!==item?kind:'',v.grade&&v.grade!=='-'?v.grade:''].filter(Boolean).join(' · ');
 const guideKey=ITEMS[kind]?kind:item;
 return {id:v.id as string,kind:'produce',name:item,detail,unit:v.unit,category:CATEGORY_OF[item]??'기타',guideKey,
  current,currentLabel:today!==null?'당일':'1일전',normal:v.normal as number|null,yearAgo:v.year_ago as number|null,
  weekAgo:v.week_ago as number|null,range:null,seoul:null,featured:FEATURED_ORDER.get(item)??FEATURED_ORDER.get(kind)??-1};
}
function meatRow(v:unknown):PriceRow|null{
 if(!record(v)||!exact(v,MEAT_FIELDS))return null;
 if(!text(v.cut,30)||!text(v.label,40)||typeof v.unit!=='string'||!UNITS.has(v.unit))return null;
 if(typeof v.id!=='string'||!/^\d{4}-\d{2}-.+$/.test(v.id)||!v.id.endsWith('-'+v.label))return null;
 if(typeof v.min_region!=='string'||!REGIONS.has(v.min_region)||typeof v.max_region!=='string'||!REGIONS.has(v.max_region))return null;
 if(!price(v.seoul)||![v.national,v.min,v.max].every(x=>price(x)&&x!==null)||(v.min as number)>(v.max as number))return null;
 const cut=v.cut,label=v.label;
 // '돼지 삼겹살' + '삼겹살' -> no detail; '한우 등심' + '등심 1++등급' -> '1++등급'.
 const part=cut.split(' ').pop()??'';
 const detail=label.startsWith(part)?label.slice(part.length).trim():label;
 return {id:v.id,kind:'meat',name:cut,detail,unit:v.unit,category:'육류·계란',guideKey:meatKey(cut),
  current:v.national as number,currentLabel:'전국 평균',normal:null,yearAgo:null,weekAgo:null,
  range:{min:v.min as number,minRegion:v.min_region,max:v.max as number,maxRegion:v.max_region},
  seoul:v.seoul as number|null,featured:FEATURED_ORDER.get(cut)??-1};
}

export function parseGroceries(raw:unknown,now:number):GroceryBundle|null{
 if(!record(raw)||!record(raw.groceries))return null;
 const g=raw.groceries;
 if(g.schema_version!==1||g.source!=='groceries'||typeof g.fetched_at!=='string'||typeof g.notice!=='string')return null;
 const fetched=Date.parse(g.fetched_at);
 if(!Number.isFinite(fetched)||fetched>now+5*60000||now-fetched>30*3600000)return null;
 const rows:PriceRow[]=[],seen=new Set<string>();
 const add=(row:PriceRow|null)=>{if(row&&!seen.has(row.kind+row.id)){seen.add(row.kind+row.id);rows.push(row);}};
 let produceDate:string|null=null,meatDate:string|null=null,missing:string[]=[];
 const p=g.produce,m=g.meat;
 if(record(p)&&Array.isArray(p.items)&&p.items.length<=400&&fresh(p.survey_date,now)){produceDate=p.survey_date;p.items.forEach(r=>add(produceRow(r)));}
 if(record(m)&&Array.isArray(m.items)&&m.items.length<=100&&fresh(m.survey_date,now)){
  meatDate=m.survey_date;m.items.forEach(r=>add(meatRow(r)));
  if(Array.isArray(m.missing))missing=m.missing.filter((x):x is string=>text(x,30)).slice(0,20);
 }
 if(!rows.length)return null;
 return {fetchedAt:g.fetched_at,notice:g.notice,produceDate,meatDate,missing,rows};
}

/** Price level against 평년 (or 1년전 when 평년 is missing); within ±10% counts as normal. */
export function verdict(current:number,normal:number|null,yearAgo:number|null):Verdict|null{
 const baseValue=normal??yearAgo;
 if(!baseValue||current<=0)return null;
 const base=normal?'평년':'1년전';
 const pct=Math.round((current/baseValue-1)*100);
 const word=pct<0?`${-pct}% 쌈`:`${pct}% 비쌈`;
 if(pct<=-10)return {level:'cheap',base,pct,label:`${base}보다 ${word}`};
 if(pct>=10)return {level:'pricey',base,pct,label:`${base}보다 ${word}`};
 return {level:'normal',base,pct,label:pct===0?`${base}과 같음`:`${base} 수준 (${word})`};
}

export interface Unit{amount:number;base:string;label:string}
/** '1kg'→1000g, '원/100g'→100g, '10개'→10개; units that cannot be compared on a shelf return null. */
export function parseUnit(unit:string):Unit|null{
 const raw=unit.replace(/^원\//,'');
 const m=/^(\d+(?:\.\d+)?)?\s*(kg|g|개|포기|손|마리|봉|장|구|단|송이)$/i.exec(raw);
 if(!m)return null;
 const n=m[1]?Number(m[1]):1,u=m[2].toLowerCase();
 if(u==='kg')return {amount:n*1000,base:'g',label:`${n}kg`};
 if(u==='g')return {amount:n,base:'g',label:`${n}g`};
 return {amount:n,base:u,label:`${n}${u}`};
}

export interface ShelfResult{perUnit:number;unitLabel:string;vsCurrent:number;verdict:Verdict|null}
/** Convert a shelf price for qty (in qtyUnit) to the reference unit and compare. */
export function compareShelf(ref:{unit:string;current:number;normal:number|null;yearAgo:number|null},shelfPrice:number,qty:number,qtyUnit:string):ShelfResult|null{
 const unit=parseUnit(ref.unit);
 if(!unit||!(shelfPrice>0)||!(qty>0)||!Number.isFinite(shelfPrice)||!Number.isFinite(qty))return null;
 const amount=qtyUnit==='kg'?qty*1000:qty,base=qtyUnit==='kg'?'g':qtyUnit;
 if(base!==unit.base)return null;
 const perUnit=Math.round(shelfPrice*unit.amount/amount);
 return {perUnit,unitLabel:unit.label,vsCurrent:Math.round((perUnit/ref.current-1)*100),verdict:verdict(perUnit,ref.normal,ref.yearAgo)};
}

export type FeaturedRow=PriceRow&{others:{detail:string;current:number}[]};
/** 자주 사는 품목: one card per meat cut (1+등급 first, other grades/kinds listed on the card) and one
 * representative row (상품 grade first) per listed produce item, in the guide's order. */
export function featuredRows(rows:PriceRow[]):FeaturedRow[]{
 const best=new Map<string,PriceRow>(),meatRows=new Map<string,PriceRow[]>();
 const score=(r:PriceRow)=>r.kind==='meat'?(r.detail==='1+등급'?0:1):r.detail.endsWith('상품')||!r.detail.includes('품')?0:1;
 for(const r of rows){
  if(r.featured<0&&r.kind!=='meat')continue;
  const key=r.kind+'|'+r.name,prev=best.get(key);
  if(r.kind==='meat')meatRows.set(key,[...(meatRows.get(key)??[]),r]);
  if(!prev||score(r)<score(prev))best.set(key,r);
 }
 const rank=(r:PriceRow)=>r.featured<0?1e9:r.featured;
 return [...best.entries()].map(([key,r])=>({...r,others:(meatRows.get(key)??[]).filter(x=>x!==r).map(x=>({detail:x.detail,current:x.current}))}))
  .sort((a,b)=>rank(a)-rank(b));
}
export function guideFor(row:PriceRow):Guide|null{
 return (row.kind==='meat'?MEAT[row.guideKey]:ITEMS[row.guideKey]??ITEMS[row.name])??null;
}
export function wikiLink(g:Guide):string|null{return g.wiki&&/^\d+$/.test(g.wiki)?guide.wiki_url+g.wiki:null;}
export function won(n:number):string{return n.toLocaleString('ko-KR')+'원';}

export interface WeeklyPick{source:'ai'|'rule';summary:string|null;surveyDate:string;picks:{row:PriceRow;menu:string|null}[]}
/** The weekly pick (grocery_pick), already re-checked by the publisher; prices come from the bundle rows. */
export function parsePick(raw:unknown,bundle:GroceryBundle):WeeklyPick|null{
 if(!record(raw)||!record(raw.grocery_pick))return null;
 const p=raw.grocery_pick;
 if(p.schema_version!==1||(p.source!=='ai'&&p.source!=='rule')||p.survey_date!==bundle.produceDate||!Array.isArray(p.picks)||p.picks.length>5)return null;
 if(p.source==='ai'?!text(p.summary,220):p.summary!==null)return null;
 // Produce ids (item|kind|unit|grade) and meat ids (species-part-label) never collide.
 const rows=new Map(bundle.rows.map(r=>[r.id,r] as const));
 const picks:{row:PriceRow;menu:string|null}[]=[];
 for(const x of p.picks){
  if(!record(x)||typeof x.id!=='string')continue;
  const row=rows.get(x.id),menu=x.menu===null?null:text(x.menu,16)?x.menu:undefined;
  if(row&&menu!==undefined)picks.push({row,menu:p.source==='rule'?null:menu});
 }
 return picks.length?{source:p.source,summary:p.source==='ai'?p.summary as string:null,surveyDate:bundle.produceDate as string,picks}:null;
}

export interface BasketBaseline{avg:number;months:number;from:string;to:string;unit:string}
export interface BasketItem{id:string;name:string;aliases:string[];group:'고기·알'|'채소'|'기타';rowKey:string;baseline:BasketBaseline|null}
const BASKET_GROUPS=new Set(['고기·알','채소','기타']);
const MONTH=/^\d{4}-\d{2}$/,MAX_BASELINE_AGE=30;

function basketBaseline(v:unknown,now:number):BasketBaseline|null{
 if(!record(v))return null;
 const {avg,months,from,to,unit,checked_at}=v;
 if(!Number.isInteger(avg)||(avg as number)<=0||(avg as number)>MAX_PRICE)return null;
 if(!Number.isInteger(months)||(months as number)<=0||(months as number)>120)return null;
 if(typeof from!=='string'||!MONTH.test(from)||typeof to!=='string'||!MONTH.test(to)||!text(unit,20))return null;
 if(typeof checked_at!=='string'||!DATE.test(checked_at))return null;
 const age=(Date.parse(kstDate(now))-Date.parse(checked_at))/DAY;
 if(!Number.isFinite(age)||age<0||age>MAX_BASELINE_AGE)return null;
 return {avg:avg as number,months:months as number,from,to,unit};
}
/** Basket items with their multi-month average (baseline=null when stale or malformed). */
export function parseBaselines(raw:unknown,now:number):BasketItem[]{
 if(!record(raw)||!record(raw.grocery_baselines))return [];
 const g=raw.grocery_baselines;
 if(g.schema_version!==1||g.source!=='grocery_baselines'||!Array.isArray(g.items)||g.items.length>100)return [];
 const out:BasketItem[]=[],seen=new Set<string>();
 for(const x of g.items){
  if(!record(x)||!text(x.id,40)||!text(x.name,40)||!Array.isArray(x.aliases)||!x.aliases.every(a=>text(a,40)))continue;
  if(typeof x.group!=='string'||!BASKET_GROUPS.has(x.group)||!record(x.row)||(x.row.kind!=='produce'&&x.row.kind!=='meat')||!text(x.row.id,80))continue;
  if(seen.has(x.id))continue;
  seen.add(x.id);
  out.push({id:x.id,name:x.name,aliases:x.aliases as string[],group:x.group as BasketItem['group'],rowKey:x.row.kind+x.row.id,baseline:basketBaseline(x.baseline,now)});
 }
 return out;
}

const squash=(s:string)=>s.replace(/\s+/g,'').toLowerCase();
/** 0 exact, 1 prefix, 2 partial; null when the query does not hit the item's name or aliases. */
function matchRank(q:string,item:BasketItem):number|null{
 let best:number|null=null;
 for(const t of [item.name,...item.aliases].map(squash)){
  const r=t===q?0:t.startsWith(q)?1:t.includes(q)?2:null;
  if(r!==null&&(best===null||r<best))best=r;
 }
 return best;
}
/** Search the basket: exact > prefix > partial, ties keep basket order. others = other hits, then same-group fillers (max 3). */
export function quickMatch(q:string,basket:BasketItem[]):{best:BasketItem;others:BasketItem[]}|null{
 const key=squash(q);
 if(!key)return null;
 const hits=basket.map((item,i)=>({item,i,r:matchRank(key,item)})).filter((h):h is {item:BasketItem;i:number;r:number}=>h.r!==null)
  .sort((a,b)=>a.r-b.r||a.i-b.i).map(h=>h.item);
 if(!hits.length)return null;
 const best=hits[0];
 const others=hits.slice(1);
 for(const item of basket)if(others.length<3&&item!==best&&item.group===best.group&&!others.includes(item))others.push(item);
 return {best,others:others.slice(0,3)};
}

/** Badge of today's price against the item's multi-month average (±10% is normal). Null when the row/unit does not match. */
export function baselineBadge(row:PriceRow,item:BasketItem):{level:'cheap'|'normal'|'pricey';pct:number;label:string}|null{
 const b=item.baseline;
 if(!b||b.months<=0||!(b.avg>0)||!(row.current>0)||row.kind+row.id!==item.rowKey)return null;
 const a=parseUnit(row.unit),c=parseUnit(b.unit);
 if(a&&c?a.base!==c.base||a.amount!==c.amount:row.unit!==b.unit)return null;
 const pct=Math.round((row.current/b.avg-1)*100),span=`${Math.min(b.months,12)}개월 평균`;
 const level=pct<=-10?'cheap':pct>=10?'pricey':'normal';
 const label=pct===0?`${span}과 같음`:pct<0?`▼ ${span}보다 ${-pct}% 쌈`:`▲ ${span}보다 ${pct}% 비쌈`;
 return {level,pct,label};
}
