import policy from './source-policy.json' with {type:'json'};
import type {Benefit} from './benefits.ts';
export const DISTRICTS:readonly string[]=policy.districts;
export const TOPICS={local:'내 생활권 소식',night:'저녁 산책·야간 문화',culture:'전시·문화 체험',learning:'배움과 취미',shopping:'생활 할인',vouchers:'서울페이·상품권 알뜰하게',convenience:'편의점 갈 때 챙길 혜택',outdoors:'걷고 뛰며 즐기는 서울',family:'아이와 함께 가볼 곳',housing:'주거·입주 모집 살펴보기',career:'일자리·면접 준비하기',carrier:'내 통신사 관련 혜택',age:'내 연령 관련 안내'} as const;
export type TopicId=keyof typeof TOPICS;
export const INTEREST_IDS:TopicId[]=['night','culture','learning','shopping','vouchers','convenience','outdoors','family','housing','career'];
export const CARRIERS=['','KT','SKT','LG U+','알뜰폰'] as const;
export interface Profile {residence:string;areas:string[];age:number|null;carrier:string;interests:TopicId[]}
export type Action='view'|'click'|'search'|'like'|'hide'|'wrong'|'official';
export interface LocalEvent {topic:TopicId;action:Action;at:number}
export interface BetaState {version:1;profile:Profile;consent:boolean;events:LocalEvent[]}
export interface Topic {id:TopicId;title:string;reason:string;items:Benefit[];pinned:boolean;score:number}
type Store=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
export const BETA_KEY='benefit-monitor:beta:v1';
const DAY=86400000,MAX_EVENTS=500;
const actions:Action[]=['view','click','search','like','hide','wrong','official'];
const isTopic=(x:unknown):x is TopicId=>typeof x==='string'&&Object.hasOwn(TOPICS,x);
export const emptyBeta=():BetaState=>({version:1,profile:{residence:'',areas:[],age:null,carrier:'',interests:[]},consent:false,events:[]});
function object(x:unknown):x is Record<string,unknown>{return !!x&&typeof x==='object'&&!Array.isArray(x);}
function validProfile(p:unknown):p is Profile {
 if(!object(p)||Object.keys(p).sort().join(',')!=='age,areas,carrier,interests,residence')return false;
 return typeof p.residence==='string'&&(!p.residence||DISTRICTS.includes(p.residence))&&Array.isArray(p.areas)&&p.areas.length<=25&&p.areas.every(x=>typeof x==='string'&&DISTRICTS.includes(x))&&new Set(p.areas).size===p.areas.length&&(p.age===null||typeof p.age==='number'&&Number.isInteger(p.age)&&p.age>=14&&p.age<=120)&&typeof p.carrier==='string'&&(CARRIERS as readonly string[]).includes(p.carrier)&&Array.isArray(p.interests)&&p.interests.length<=INTEREST_IDS.length&&p.interests.every(x=>INTEREST_IDS.includes(x))&&new Set(p.interests).size===p.interests.length;
}
function validEvent(e:unknown):e is LocalEvent{return object(e)&&Object.keys(e).sort().join(',')==='action,at,topic'&&isTopic(e.topic)&&actions.includes(e.action as Action)&&typeof e.at==='number'&&Number.isFinite(e.at)&&e.at>0;}
function validState(s:unknown):s is BetaState{return object(s)&&Object.keys(s).sort().join(',')==='consent,events,profile,version'&&s.version===1&&validProfile(s.profile)&&typeof s.consent==='boolean'&&Array.isArray(s.events)&&s.events.length<=MAX_EVENTS&&s.events.every(validEvent);}
export function recentEvents(events:LocalEvent[],now:number):LocalEvent[]{return events.filter(e=>validEvent(e)&&e.at<=now&&e.at>now-30*DAY).slice(-MAX_EVENTS);}
export function loadBeta(storage:Store|null,now=Date.now()):BetaState {
 try {const raw=storage?.getItem(BETA_KEY);if(!raw||raw.length>100000)return emptyBeta();const s:unknown=JSON.parse(raw);if(!validState(s))return emptyBeta();return {...s,events:s.consent?recentEvents(s.events,now):[]};}catch{return emptyBeta();}
}
export function saveBeta(storage:Store|null,state:BetaState):boolean {
 try {if(!storage||!validState(state))return false;storage.setItem(BETA_KEY,JSON.stringify({...state,events:state.consent?state.events:[]}));return true;}catch{return false;}
}
export function clearBeta(storage:Store|null):boolean {try{if(!storage)return false;storage.removeItem(BETA_KEY);return true;}catch{return false;}}
export function recordEvent(state:BetaState,topic:TopicId,action:Action,now:number):BetaState {
 if(!state.consent)return {...state,events:[]};
 const event={topic,action,at:now};if(!validEvent(event))return state;
 return {...state,events:[...recentEvents(state.events,now),event].slice(-MAX_EVENTS)};
}
const keywords:Partial<Record<TopicId,RegExp>>={night:/야간|밤길|밤 산책|저녁|야경|빛 축제/,culture:/전시|공연|문화|체험|축제/,learning:/교육|강좌|수업|학습|클래스/,shopping:/할인|적립|환급|상품권|장보기|세일/,vouchers:/상품권|서울페이/,convenience:/\bCU\b|편의점|이마트24|세븐일레븐|GS25/i,outdoors:/걷기|러너|러닝|둘레길|공원/,family:/가족|어린이|육아/,housing:/입주자|매입임대|분양주택|사회주택/,career:/면접|사무지원|희망돌보미|취업/};
export function searchTopics(query:string):TopicId[]{return INTEREST_IDS.filter(id=>keywords[id]?.test(query));}
export function summarizeEvents(events:LocalEvent[],now:number) {
 const recent=recentEvents(events,now);
 return (Object.keys(TOPICS) as TopicId[]).map(id=>{
  const es=recent.filter(e=>e.topic===id),count=(a:Action)=>es.filter(e=>e.action===a).length;
  const views=count('view'),clicks=count('click'),likes=count('like'),hides=count('hide'),official=count('official'),searches=count('search');
  const decision=views<20?'자료 부족':likes+official>0||clicks/Math.max(views,1)>=0.1?'유지 후보':'교체 검토';
  return {id,views,clicks,likes,hides,official,searches,wrong:count('wrong'),decision};
 });
}
export function isSeoulCandidate(i:Benefit):boolean {
 if(i.regions.some(r=>!/(서울\s*(제외|불가)|전국\s*제외|서울\s*근교)/.test(r)&&(/^(서울(?:특별시|시)?|전국)(?:$|[\s·(])/.test(r)||DISTRICTS.includes(r))))return true;
 return !i.regions.length&&['seoul','culture','seoul_lifelong','kt','retail','convenience','seven','emart24'].includes(i.source);
}
const body=(i:Benefit)=>[i.title,i.summary,i.conditions,...Object.values(i.labels)].join(' ');
function ageCandidate(i:Benefit,age:number|null):boolean {
 if(age===null)return false;
 const ranges=[...i.conditions.matchAll(/(?:만\s*)?(\d{1,3})\s*(?:세\s*)?[~～–-]\s*(?:만\s*)?(\d{1,3})\s*세/g)];
 return ranges.some(m=>age>=Number(m[1])&&age<=Number(m[2]));
}
export function topicsFor(items:Benefit[],profile:Profile,events:LocalEvent[],now:number):Topic[] {
 const eligible=items.filter(isSeoulCandidate),areas=[profile.residence,...profile.areas].filter(Boolean),stats=summarizeEvents(events,now);
 const carrierPattern=profile.carrier==='KT'?/\bKT\b/i:profile.carrier==='SKT'?/\bSKT\b|T멤버십|T 멤버십/i:profile.carrier==='LG U+'?/LG\s*U\+|유플러스/i:null;
 const result:Topic[]=[];
 for(const id of Object.keys(TOPICS) as TopicId[]){
  const rows=eligible.filter(i=>id==='local'?areas.some(a=>i.regions.includes(a)):id==='age'?ageCandidate(i,profile.age):id==='carrier'?!!carrierPattern?.test(body(i)):!!keywords[id]?.test(['vouchers','convenience','outdoors','family','housing','career'].includes(id)?i.summary:body(i)));
  if(!rows.length)continue;
  const pinned=profile.interests.includes(id)||(id==='local'&&areas.length>0)||(id==='carrier'&&!!profile.carrier)||(id==='age'&&profile.age!==null),s=stats.find(x=>x.id===id)!;
  const learned=s.views>=20?Math.min(5,s.likes+s.official+Math.min(2,s.searches/3)+s.clicks/Math.max(1,s.views)*5)-Math.min(5,s.hides)+(s.decision==='교체 검토'?-3:0):0;
  const reason=id==='local'?'선택한 거주·관심 지역과 연결된 안내입니다. 주민 자격은 별도 확인':id==='carrier'?`${profile.carrier} 관련 문구가 있는 안내입니다. 등급·제외 조건 별도 확인`:id==='age'?`${profile.age}세가 원문의 연령 범위에 포함된 후보입니다. 기준일·예외·다른 자격 별도 확인`:pinned?'직접 선택한 관심사와 관련된 문구가 있습니다. 이용 조건 별도 확인':'새로운 관심사를 발견할 수 있는 주제입니다. 이용 조건 별도 확인';
  const title=id==='local'?(profile.residence?`${profile.residence}에서 누릴 혜택`:'관심 지역에서 누릴 혜택'):id==='carrier'?`내 ${profile.carrier} 멤버십 활용하기`:id==='age'?`${profile.age}세인 내가 확인할 혜택`:id==='night'?'저녁 산책에 즐거움 더하기':TOPICS[id];
  result.push({id,title,reason,items:rows,pinned,score:(pinned?100:0)+learned});
 }
 return result.sort((a,b)=>b.score-a.score||Object.keys(TOPICS).indexOf(a.id)-Object.keys(TOPICS).indexOf(b.id));
}
