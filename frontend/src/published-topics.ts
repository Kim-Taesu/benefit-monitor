import type {Benefit} from './benefits.ts';
import {timestamp} from './benefits.ts';
import {TOPICS,topicsFor} from './beta.ts';
import type {Profile,Topic,TopicId} from './beta.ts';
import {benefitKey} from './favorites.ts';
import titles from './topic-titles.json' with {type:'json'};

function object(value:unknown):value is Record<string,unknown>{return value!==null&&typeof value==='object'&&!Array.isArray(value);}
function canonical(value:unknown):string {
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(object(value))return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value)??'';
}
export function publishedTopics(raw:unknown,items:Benefit[],profile:Profile,now:number):Topic[]|null {
 if(!object(raw)||!object(raw.topic_cards)||!Array.isArray(raw.items))return null;
 const bundle=raw.topic_cards;
 if(bundle.schema_version!==1||!Array.isArray(bundle.topics)||bundle.topics.length>13||!Number.isFinite(timestamp(bundle.generated_at))||timestamp(bundle.generated_at)>now||!(timestamp(bundle.valid_until)>now))return null;
 const current=new Map(items.map(i=>[benefitKey(i),i]));
 const facts=new Map(raw.items.filter(object).filter(i=>typeof i.source==='string'&&typeof i.url==='string').map(i=>[String(i.source)+'\n'+String(i.url),i]));
 const local=topicsFor(items,profile,[],now),result:Topic[]=[],seen=new Set<string>();
 for(const row of bundle.topics){
  if(!object(row)||typeof row.id!=='string'||!Object.hasOwn(TOPICS,row.id)||seen.has(row.id)||!Array.isArray(row.items)||row.items.length>2000)return null;
  const id=row.id as TopicId;
  if(row.title!==titles[id])return null;
  seen.add(id);
  let linked:Benefit[]=[];const added=new Set<string>();
  for(const ref of row.items){
   if(!object(ref)||typeof ref.source!=='string'||typeof ref.url!=='string'||!object(ref.facts))return null;
   const key=ref.source+'\n'+ref.url,item=current.get(key);
   if(item&&!added.has(key)&&canonical(ref.facts)===canonical(facts.get(key))){linked.push(item);added.add(key);}
  }
  if(id==='age'&&profile.age!==null||id==='carrier'&&!!profile.carrier||id==='local'&&!!(profile.residence||profile.areas.length)){
   const allowed=new Set(local.find(t=>t.id===id)?.items.map(benefitKey)||[]);
   linked=linked.filter(i=>allowed.has(benefitKey(i)));
  }
  if(linked.length){const pinned=profile.interests.includes(id)||!!local.find(t=>t.id===id)?.pinned;
   result.push({id,title:row.title as string,items:linked,pinned,score:pinned?100:0,reason:'공개 승인된 항목을 묶은 주제입니다. 이용 조건은 별도 확인하세요.'});}
 }
 for(const topic of local)if(topic.pinned&&!result.some(t=>t.id===topic.id))result.push(topic);
 return result.length?result.sort((a,b)=>Number(b.pinned)-Number(a.pinned)):null;
}
