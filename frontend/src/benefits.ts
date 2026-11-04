import policy from './source-policy.json' with { type: 'json' };

export const categories=['할인·적립','생활지원','문화·체험','교육·강좌','공모·참여','기타'];
export const fees: Record<string,string>={free:'무료',paid:'유료',mixed:'일부 유료',unknown:'비용 미확인'};
export const coverageLabels: Record<string,string>={checked:'목록 수집 성공 · 본문 검증 별도',cached:'6시간 내 목록 캐시 · 본문 검증 별도',failed:'이번 수집 실패',not_connected:'자동 수집 미연결',not_checked:'이번 실행 미확인'};
export interface Filters { q:string; region:string; category:string; sort:string; status:string }
export const valueLabels={discount_rate:'% 할인',discount_amount:'원 할인',grant_amount:'원 지원',refund_amount:'원 환급',reward_points:'포인트 적립'};
export interface BenefitValue {kind:keyof typeof valueLabels;value:number;qualifier:'exact'|'up_to';conditions:string;evidence_url:string;evidence_quote:string}
export interface Benefit {
 source:string; sourceName:string; url:string; title:string; summary:string; conditions:string;
 districts:string[]; regions:string[]; category:string; labels:Record<string,string>;
 verified_at:string; display_until:string; valid_from:string|null; valid_until:string|null;
 deadline_at:string|null; validity_kind:string; fee_status:string; payment_terms:Record<string,string>; benefitValue:BenefitValue|null;
}
export interface Coverage { name:string; source?:string; status:string; scope?:string; verified_count?:number }
export interface Briefing {
 state:string; items:Benefit[]; generatedAt:string; sourceReportAt:string|null; validThrough:string|null;
 sources:Coverage[]; districts:Coverage[]; scope:string; runLabel:string; pending:number; withheldCount:number;
}
const sources=policy.sources as Record<string,{name:string;domains:string[]}>;
const object=(v:unknown):Record<string,unknown> => v!==null && typeof v==='object' && !Array.isArray(v)?v as Record<string,unknown>:{};
const text=(v:unknown):string => typeof v==='string'?v:'';
const strings=(v:unknown):string[] => Array.isArray(v)?v.filter((x):x is string=>typeof x==='string'):[];
const DAY=86400000;
export function timestamp(v:unknown):number {
 if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/.test(v)) return NaN;
 if(!Number.isFinite(dateValue(v.slice(0,10)))||Number(v.slice(11,13))>23)return NaN;
 return Date.parse(v);
}
function dateValue(v:unknown):number {
 if(typeof v!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(v)) return NaN;
 const n=Date.parse(v+'T00:00:00+09:00');
 return Number.isFinite(n)&&new Date(n+9*3600000).toISOString().slice(0,10)===v?n:NaN;
}
const kstDay=(n:number)=>Math.floor((n+9*3600000)/DAY);
export function formatDate(v:string|null|undefined):string {
 if(!v)return '공식 안내 확인 필요';
 const n=v.includes('T')?timestamp(v):dateValue(v);
 if(!Number.isFinite(n))return '공식 안내 확인 필요';
 const local=new Date(n+9*3600000).toISOString();
 return local.slice(0,10).replaceAll('-','.')+(v.includes('T')?' '+local.slice(11,16)+' (KST)':'');
}
export function safeOfficial(url:unknown,source:string):boolean {
 try {const u=new URL(text(url));return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!!sources[source]?.domains.includes(u.hostname);}
 catch{return false;}
}
function parseBenefitValue(value:unknown,source:string,target:string):BenefitValue|null {
 if(value===undefined)return null;
 if(!value||typeof value!=='object'||Array.isArray(value))throw new Error('Invalid benefit_value');
 const v=object(value),keys=['kind','value','qualifier','conditions','evidence_url','evidence_quote'];
 if(Object.keys(v).length===0)return null;
 if(Object.keys(v).length!==keys.length||!keys.every(k=>Object.hasOwn(v,k))||typeof v.kind!=='string'||!Object.hasOwn(valueLabels,v.kind)||!['exact','up_to'].includes(text(v.qualifier)))throw new Error('Invalid value contract');
 const rate=v.kind==='discount_rate',amount=v.value;
 if(typeof amount!=='number'||!Number.isFinite(amount)||amount<=0||amount>(rate?100:999999999999)||(rate?Number(amount.toFixed(2))!==amount:!Number.isSafeInteger(amount)))throw new Error('Invalid benefit number');
 for(const [key,limit]of [['conditions',1000],['evidence_quote',500],['evidence_url',4096]] as const)if(typeof v[key]!=='string'||!v[key].trim()||v[key].length>limit)throw new Error('Missing value evidence');
 if(!safeOfficial(v.evidence_url,source)||v.evidence_url!==target||[...new URL(text(v.evidence_url)).searchParams.keys()].some(key=>/token|secret|password|auth|session|api.?key/i.test(key)))throw new Error('Unobserved value evidence');
 const unit=rate?'%':v.kind==='reward_points'?'포인트':'원';
 const numbers=[0,1,2].filter(d=>Number(amount.toFixed(d))===amount).flatMap(d=>[amount.toFixed(d),new Intl.NumberFormat('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}).format(amount)]);
 const escape=(s:string)=>s.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
 const literal=numbers.map(n=>escape(n+unit)).join('|'),quote=text(v.evidence_quote).replace(/\s/g,'');
 if(!quote.includes(valueLabels[v.kind as BenefitValue['kind']].split(' ').at(-1)!)||!new RegExp('(?<![0-9.,])(?:'+literal+')(?![0-9.])').test(quote)||quote.includes('최대')!==(v.qualifier==='up_to'))throw new Error('Quoted number or qualifier mismatch');
 return {kind:v.kind as BenefitValue['kind'],value:amount,qualifier:v.qualifier as BenefitValue['qualifier'],conditions:text(v.conditions),evidence_url:text(v.evidence_url),evidence_quote:text(v.evidence_quote)};
}
export function benefitValueLabel(value:BenefitValue):string {
 return (value.qualifier==='up_to'?'최대 ':'')+new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(value.value)+valueLabels[value.kind];
}
export function timing(item:Record<string,unknown>|Benefit,now:number) {
 const application=timestamp(item.deadline_at);
 const end=dateValue(item.valid_until);
 const start=dateValue(item.valid_from);
 // Application close is separate from event start; a future start does not hide an open application.
 const cutoff=Math.min(Number.isFinite(application)?application:Infinity,Number.isFinite(end)?end+DAY:Infinity);
 const days=Number.isFinite(application)?kstDay(application)-kstDay(now):Number.isFinite(end)?kstDay(end)-kstDay(now):null;
 const upcoming=Number.isFinite(start)&&start>now;
 const label=Number.isFinite(application)?(days===0?'오늘 신청 마감':`신청 마감 D-${days}`):upcoming?`시작 전 D-${kstDay(start)-kstDay(now)}`:Number.isFinite(end)?(days===0?'오늘 종료':`종료 D-${days}`):item.validity_kind==='ongoing'?'상시 안내':'기간 미확인';
 return {label,days,cutoff,urgent:days!==null&&days>=0&&days<=7&&(!upcoming||Number.isFinite(application)),upcoming};
}
function coverageRows(value:unknown):Coverage[] {
 if(!Array.isArray(value))return [];
 return value.map(object).filter(v=>text(v.name)&&text(v.status)).map(v=>({name:text(v.name),source:text(v.source),status:text(v.status),scope:text(v.scope),verified_count:typeof v.verified_count==='number'?v.verified_count:0}));
}
export function adapt(value:unknown,now=Date.now()):Briefing {
 const d=object(value); const generated=timestamp(d.generated_at),report=timestamp(d.source_report_at),until=timestamp(d.valid_through);
 if(d.schema_version!==1||!['partial','awaiting_verification','collection_failed'].includes(text(d.status))||!Array.isArray(d.items)||!Number.isFinite(generated)||generated>now)throw new Error('공개 데이터 형식을 확인할 수 없습니다.');
 if(d.status!=='collection_failed'&&(!Number.isFinite(until)||!Number.isFinite(report)||report>generated))throw new Error('공개 데이터 기준 시각을 확인할 수 없습니다.');
 const state=d.status==='collection_failed'?'collection_failed':until<=now?'stale':text(d.status);
 const cov=object(d.coverage);const context=object(d.run_context);
 const result:Briefing={state,items:[],generatedAt:text(d.generated_at),sourceReportAt:text(d.source_report_at)||null,validThrough:text(d.valid_through)||null,sources:coverageRows(cov.sources),districts:coverageRows(cov.districts),scope:text(cov.scope),runLabel:({scheduled_refresh:'정기 실행에서 생성',manual_refresh:'수동 갱신 · 정기 실행 성공과 별도',pre_schedule_snapshot:'정기 수집 예정시각 이전 결과',unavailable:'수집 실행 결과 확인 불가'} as Record<string,string>)[text(context.status)]||'실행 유형 미확인',pending:Math.max(0,Number(object(d.withheld).pending)||0),withheldCount:0};
 if(state!=='partial')return result;
 const seen=new Set<string>();
 for(const raw of d.items) {
  const i=object(raw);const source=text(i.source);const verified=timestamp(i.verified_at),display=timestamp(i.display_until);
  let benefitValue:BenefitValue|null;
  try{benefitValue=parseBenefitValue(i.benefit_value,source,text(object(i.payment_terms).evidence_url)||text(i.url));}
  catch{result.withheldCount++;continue;}
  const info=timing(i,now);
  const badDate=['valid_from','valid_until'].some(k=>i[k]!=null&&!Number.isFinite(dateValue(i[k]))) || i.deadline_at!=null&&!Number.isFinite(timestamp(i.deadline_at));
  const valid= i.needs_recheck===false && !i.excluded_reason && text(i.title).trim() && text(i.summary).trim() && typeof i.conditions==='string' && Array.isArray(i.districts) && i.districts.every(v=>typeof v==='string') && safeOfficial(i.url,source) && Number.isFinite(verified)&&verified<=now&&now<verified+policy.maxAgeDays*DAY&&Number.isFinite(display)&&display>now&&info.cutoff>now&&!badDate && Object.hasOwn(fees,text(i.fee_status)) && ['fixed','ongoing'].includes(text(i.validity_kind)) && (i.validity_kind==='ongoing' || i.valid_until!=null || i.deadline_at!=null);
  const id=source+'\n'+text(i.url);
  if(!valid||seen.has(id)){result.withheldCount++;continue;}
  seen.add(id);
  const labels=Object.fromEntries(Object.entries(object(i.labels)).filter(([,v])=>typeof v==='string')) as Record<string,string>;
  const districts=strings(i.districts);
  const regions=[...new Set([...districts,...(labels.region?[labels.region]:[])])];
  if(!regions.length&&['seoul','gangseo','eunpyeong','seongnam'].includes(source))regions.push({seoul:'서울',gangseo:'강서구',eunpyeong:'은평구',seongnam:'성남시'}[source]!);
  const payment=object(i.payment_terms);const paymentTerms:Record<string,string>={};
  for(const k of ['method','funding_source','excluded_methods','minimum_spend','limit'])if(typeof payment[k]==='string')paymentTerms[k]=payment[k];
  if(safeOfficial(payment.evidence_url,source))paymentTerms.evidence_url=text(payment.evidence_url);
  result.items.push({benefitValue,source,sourceName:sources[source].name,url:text(i.url),title:text(i.title),summary:text(i.summary),conditions:text(i.conditions),districts,regions,category:categories.includes(labels.category)?labels.category:'기타',labels,verified_at:text(i.verified_at),display_until:text(i.display_until),valid_from:text(i.valid_from)||null,valid_until:text(i.valid_until)||null,deadline_at:text(i.deadline_at)||null,validity_kind:text(i.validity_kind),fee_status:text(i.fee_status),payment_terms:paymentTerms});
 }
 return result;
}
export function matchesRegion(i:Benefit,region:string):boolean {
 if(!region)return true;
 if(region==='서울')return i.source==='seoul'||i.regions.some(r=>r==='서울'||r==='서울시'||r==='서울 전체'||policy.districts.includes(r));
 return i.regions.includes(region);
}
export function select(items:Benefit[],f:Filters,now=Date.now()):Benefit[] {
 const terms=f.q.toLocaleLowerCase('ko').trim().split(/\s+/).filter(Boolean);
 return items.filter(i=>matchesRegion(i,f.region)&&(!f.category||i.category===f.category)&&(!f.status||(f.status==='urgent'?timing(i,now).urgent:now-timestamp(i.verified_at)<=DAY))&&terms.every(t=>[i.title,i.summary,i.conditions,i.sourceName,...i.regions,...Object.values(i.labels)].join(' ').toLocaleLowerCase('ko').includes(t))).sort((a,b)=>{
  // The card headline is summary; title is the original official notice headline.
  const title=a.summary.localeCompare(b.summary,'ko');
  if(f.sort==='title')return title;
  if(f.sort==='verified')return timestamp(b.verified_at)-timestamp(a.verified_at)||title;
  const x=timing(a,now).cutoff,y=timing(b,now).cutoff;
  return (x===y?0:x<y?-1:1)||timestamp(b.verified_at)-timestamp(a.verified_at)||title;
 });
}
export function readFilters(search:string):Filters {
 const p=new URLSearchParams(search);
 return {q:(p.get('q')||'').slice(0,200),region:p.get('region')||'',category:p.get('category')||'',sort:['deadline','verified','title'].includes(p.get('sort')||'')?p.get('sort')!:'deadline',status:['urgent','new'].includes(p.get('status')||'')?p.get('status')!:''};
}
export function filterUrl(current:URL,filters:Filters):URL {
 const url=new URL(current);
 for(const [key,value]of Object.entries(filters))if(value && !(key==='sort'&&value==='deadline'))url.searchParams.set(key,value);else url.searchParams.delete(key);
 return url;
}
export function regionOptions(items:Benefit[]):string[] {
 return [...new Set(items.flatMap(i=>i.regions).concat(items.some(i=>matchesRegion(i,'서울'))?['서울']:[]))].sort((a,b)=>a.localeCompare(b,'ko'));
}
