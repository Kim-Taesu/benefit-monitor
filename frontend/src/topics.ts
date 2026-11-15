// 혜택 주제 묶음. 2026-11-15 개편으로 개인화(프로필·행동 기록·피드백)를 없앴다.
// 공개 승인된 주제 카드가 있으면 그것만 쓰고, 없으면 제목 단어 규칙으로 묶는다.
import policy from './source-policy.json' with {type:'json'};
import titles from './topic-titles.json' with {type:'json'};
import type {Benefit} from './benefits.ts';
import {timestamp} from './benefits.ts';
import {benefitKey} from './favorites.ts';

export const DISTRICTS:readonly string[]=policy.districts;
export type TopicId=keyof typeof titles;
export interface Topic {id:TopicId;title:string;items:Benefit[]}
export const TOPIC_ICONS:Record<TopicId,string>={local:'🏡',night:'🌙',culture:'🎨',learning:'📚',shopping:'🛍️',carrier:'📱',age:'🎯',vouchers:'🎟️',convenience:'🏪',outdoors:'👟',family:'🧸',housing:'🔑',career:'💼'};
/** 딱 맞는 이모지가 없는 주제에 쓰는 대표 이모지. */
export const TOPIC_ICON_FALLBACK='🎁';
/** 이 건수 미만인 주제는 "주제 더보기" 뒤로 접는다. */
export const MAJOR_TOPIC_COUNT=2;
const ORDER=Object.keys(titles) as TopicId[];
const isTopic=(x:unknown):x is TopicId=>typeof x==='string'&&Object.hasOwn(titles,x);

export function isSeoulCandidate(i:Benefit):boolean {
 if(i.regions.some(r=>!/(서울\s*(제외|불가)|전국\s*제외|서울\s*근교)/.test(r)&&(/^(서울(?:특별시|시)?|전국)(?:$|[\s·(])/.test(r)||DISTRICTS.includes(r))))return true;
 return !i.regions.length&&['seoul','culture','seoul_lifelong','kt','retail','convenience','seven','emart24'].includes(i.source);
}
/** 내 지역: 그 구의 안내와, 특정 구에 묶이지 않은 서울·전국 공통 안내를 함께 보인다(2026-11-15 승인). */
export function matchesHome(i:Benefit,district:string):boolean {
 return !district||i.regions.includes(district)||!i.regions.some(r=>DISTRICTS.includes(r));
}

const keywords:Partial<Record<TopicId,RegExp>>={night:/야간|밤길|밤 산책|저녁|야경|빛 축제/,culture:/전시|공연|문화|체험|축제/,learning:/교육|강좌|수업|학습|클래스/,shopping:/할인|적립|환급|상품권|장보기|세일/,vouchers:/상품권|서울페이/,convenience:/\bCU\b|편의점|이마트24|세븐일레븐|GS25/i,outdoors:/걷기|러너|러닝|둘레길|공원/,family:/가족|어린이|육아/,housing:/입주자|매입임대|분양주택|사회주택/,career:/면접|사무지원|희망돌보미|취업/};
const SUBJECT_ONLY:TopicId[]=['vouchers','convenience','outdoors','family','housing','career'];
const body=(i:Benefit)=>[i.title,i.summary,i.conditions,...Object.values(i.labels)].join(' ');
/** 규칙 묶음: 공개 주제 카드가 없을 때만 쓴다. 지역·통신사·연령 주제는 프로필이 없어 만들지 않는다. */
export function ruleTopics(items:Benefit[]):Topic[] {
 const eligible=items.filter(isSeoulCandidate),result:Topic[]=[];
 for(const id of ORDER){
  const pattern=keywords[id];if(!pattern)continue;
  const rows=eligible.filter(i=>pattern.test(SUBJECT_ONLY.includes(id)?i.summary:body(i)));
  if(rows.length)result.push({id,title:titles[id],items:rows});
 }
 return result;
}

function object(value:unknown):value is Record<string,unknown>{return value!==null&&typeof value==='object'&&!Array.isArray(value);}
function canonical(value:unknown):string {
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(object(value))return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
 return JSON.stringify(value)??'';
}
/** 공개 승인된 주제 카드. 지금 화면에 나올 수 있는 혜택만 잇고, 사실이 바뀐 항목은 잇지 않는다. */
export function publishedTopics(raw:unknown,items:Benefit[],now:number):Topic[]|null {
 if(!object(raw)||!object(raw.topic_cards)||!Array.isArray(raw.items))return null;
 const bundle=raw.topic_cards;
 if(bundle.schema_version!==1||!Array.isArray(bundle.topics)||bundle.topics.length>13||!Number.isFinite(timestamp(bundle.generated_at))||timestamp(bundle.generated_at)>now||!(timestamp(bundle.valid_until)>now))return null;
 const current=new Map(items.map(i=>[benefitKey(i),i]));
 const facts=new Map(raw.items.filter(object).filter(i=>typeof i.source==='string'&&typeof i.url==='string').map(i=>[String(i.source)+'\n'+String(i.url),i]));
 const result:Topic[]=[],seen=new Set<string>();
 for(const row of bundle.topics){
  if(!object(row)||!isTopic(row.id)||seen.has(row.id)||!Array.isArray(row.items)||row.items.length>2000)return null;
  const id=row.id;
  if(row.title!==titles[id])return null;
  seen.add(id);
  const linked:Benefit[]=[],added=new Set<string>();
  for(const ref of row.items){
   if(!object(ref)||typeof ref.source!=='string'||typeof ref.url!=='string'||!object(ref.facts))return null;
   const key=ref.source+'\n'+ref.url,item=current.get(key);
   if(item&&!added.has(key)&&canonical(ref.facts)===canonical(facts.get(key))){linked.push(item);added.add(key);}
  }
  if(linked.length)result.push({id,title:titles[id],items:linked});
 }
 return result.length?result:null;
}
/** 화면에 보일 주제. 혜택이 많은 주제부터, 같으면 고정 순서. */
export function topicsFor(raw:unknown,items:Benefit[],now:number):Topic[] {
 return [...(publishedTopics(raw,items,now)??ruleTopics(items))].sort((a,b)=>b.items.length-a.items.length||ORDER.indexOf(a.id)-ORDER.indexOf(b.id));
}
