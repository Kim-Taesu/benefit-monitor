// Admin-only GitHub calls. The token goes only to api.github.com in the Authorization header:
// never into URLs, error messages or logs.
export const REPO='Kim-Taesu/benefit-monitor';
const API='https://api.github.com';
const FILE=`${API}/repos/${REPO}/contents/ai-takedowns.json`;
const DISPATCH=`${API}/repos/${REPO}/actions/workflows/briefing-pages.yml/dispatches`;
export const NOTE_MAX=200;
const CID=/^[0-9a-f]{24}$/;
const TOKEN=/^[A-Za-z0-9_]{20,255}$/;

export type Takedown={candidate_id:string;title_key:string;taken_down_at:string;note:string};
type Fetch=(url:string,init:RequestInit)=>Promise<Response>;
export type Options={fetch?:Fetch;now?:()=>Date};
type Listing={list:Takedown[];sha:string|null};

export class GitHubError extends Error {
 status:number;
 constructor(status:number,what:string){super(`GitHub ${what} 실패 (HTTP ${status})`);this.status=status;}
}

export function validToken(token:string):boolean{return TOKEN.test(token);}
function checkToken(token:string){if(!validToken(token))throw new Error('토큰 형식이 올바르지 않습니다');}

function request(token:string,options:Options,url:string,method:string,body?:unknown){
 const f=options.fetch||((u:string,i:RequestInit)=>fetch(u,i));
 return f(url,{method,cache:'no-store',credentials:'omit',referrerPolicy:'no-referrer',
  headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28',Authorization:`Bearer ${token}`,
   ...(body===undefined?{}:{'Content-Type':'application/json'})},
  ...(body===undefined?{}:{body:JSON.stringify(body)})});
}

function utf8ToBase64(text:string){let bin='';for(const b of new TextEncoder().encode(text))bin+=String.fromCharCode(b);return btoa(bin);}
function base64ToUtf8(value:string){return new TextDecoder().decode(Uint8Array.from(atob(value.replace(/\s/g,'')),c=>c.charCodeAt(0)));}

function wellFormed(t:unknown):t is Takedown{
 if(!t||typeof t!=='object'||Array.isArray(t))return false;
 const v=t as Record<string,unknown>;
 return typeof v.candidate_id==='string'&&typeof v.title_key==='string'&&typeof v.taken_down_at==='string'&&typeof v.note==='string';
}

async function read(token:string,options:Options):Promise<Listing&{raw:unknown[]}>{
 const response=await request(token,options,FILE+'?ref=briefing-data','GET');
 if(response.status===404)return {list:[],raw:[],sha:null};
 if(!response.ok)throw new GitHubError(response.status,'내림 목록 읽기');
 const envelope=await response.json() as {encoding?:string;content?:string;sha?:string};
 if(envelope.encoding!=='base64'||typeof envelope.content!=='string'||typeof envelope.sha!=='string')throw new Error('내림 목록 형식이 올바르지 않습니다');
 const value:unknown=JSON.parse(base64ToUtf8(envelope.content));
 if(!Array.isArray(value))throw new Error('내림 목록이 배열이 아닙니다');
 return {list:value.filter(wellFormed),raw:value,sha:envelope.sha};
}

export async function readTakedowns(token:string,options:Options={}):Promise<Listing>{
 checkToken(token);const {list,sha}=await read(token,options);return {list,sha};
}

// One read for the admin page: item takedowns and grocery text mutes come from the same file.
export async function readAdminState(token:string,options:Options={}):Promise<{list:Takedown[];mutes:string[];healthMutes:string[];festivalMutes:string[];benefitMutes:string[]}>{
 checkToken(token);const {list,raw}=await read(token,options);
 return {list,mutes:mutesIn(raw),healthMutes:healthMutesIn(raw),festivalMutes:pickMutesIn(raw,'festival_pick_text'),benefitMutes:pickMutesIn(raw,'benefit_pick_text')};
}

// Read, change, write with the sha precondition; on 409/422 re-read once and re-apply the change.
// Entries the page does not understand are kept as they are (the backend reads any dict).
async function update(token:string,options:Options,change:(raw:unknown[])=>unknown[]|null,message:string){
 for(let attempt=0;attempt<2;attempt++){
  const {raw,sha}=await read(token,options);
  const next=change(raw);
  if(next===null)return;
  const response=await request(token,options,FILE,'PUT',{message,branch:'briefing-data',
   content:utf8ToBase64(JSON.stringify(next,null,2)+'\n'),...(sha?{sha}:{})});
  if(response.ok)return;
  if(response.status!==409&&response.status!==422)throw new GitHubError(response.status,'내림 목록 저장');
 }
 throw new Error('내림 목록이 저장 중에 두 번 바뀌었습니다. 다시 시도하세요');
}

// The list change is already saved when this fails; every public path reads the list on its next run.
export class DeployError extends GitHubError {}

async function redeploy(token:string,options:Options){
 const response=await request(token,options,DISPATCH,'POST',{ref:'main',inputs:{apply_takedowns:true}});
 if(response.status!==204&&!response.ok)throw new DeployError(response.status,'재배포 요청');
}

const sameCandidate=(cid:string)=>(t:unknown)=>!!t&&typeof t==='object'&&(t as Record<string,unknown>).candidate_id===cid;

export async function takeDown(token:string,item:{candidate_id:string;title_key:string},note:string,options:Options={}):Promise<void>{
 checkToken(token);
 const memo=note.trim();
 if(!CID.test(item.candidate_id)||typeof item.title_key!=='string'||!item.title_key)throw new Error('항목 식별자가 올바르지 않습니다');
 if(memo.length>NOTE_MAX)throw new Error(`메모는 ${NOTE_MAX}자 이하로 적으세요`);
 const entry:Takedown={candidate_id:item.candidate_id,title_key:item.title_key,taken_down_at:(options.now?.()||new Date()).toISOString(),note:memo};
 await update(token,options,raw=>raw.some(sameCandidate(entry.candidate_id))?null:[...raw,entry],'Take down '+entry.candidate_id);
 await redeploy(token,options);
}

// The backend hides an item when either id matches, so restoring removes both kinds of entry.
export async function restore(token:string,item:{candidate_id:string;title_key:string},options:Options={}):Promise<void>{
 checkToken(token);
 if(typeof item.candidate_id!=='string'||!CID.test(item.candidate_id)||typeof item.title_key!=='string')throw new Error('항목 식별자가 올바르지 않습니다');
 const {candidate_id,title_key}=item;
 const match=(t:unknown)=>sameCandidate(candidate_id)(t)||(!!title_key&&!!t&&typeof t==='object'&&(t as Record<string,unknown>).title_key===title_key);
 await update(token,options,raw=>raw.some(match)?raw.filter(t=>!match(t)):null,'Restore '+candidate_id);
 await redeploy(token,options);
}

// Weekly grocery pick: mute the AI summary/menus for one survey day (the card falls back to prices only).
const GROCERY_KIND='grocery_pick_text';
const DAY=/^\d{4}-\d{2}-\d{2}$/;
const sameMute=(day:string)=>(t:unknown)=>!!t&&typeof t==='object'&&(t as Record<string,unknown>).kind===GROCERY_KIND&&(t as Record<string,unknown>).survey_date===day;

function mutesIn(raw:unknown[]):string[]{
 return raw.flatMap(t=>{const v=t as Record<string,unknown>;return v&&typeof v==='object'&&v.kind===GROCERY_KIND&&typeof v.survey_date==='string'&&DAY.test(v.survey_date)?[v.survey_date]:[];});
}
export async function readGroceryMutes(token:string,options:Options={}):Promise<string[]>{
 checkToken(token);return mutesIn((await read(token,options)).raw);
}

export async function muteGroceryText(token:string,surveyDay:string,note:string,options:Options={}):Promise<void>{
 checkToken(token);
 const memo=note.trim();
 if(!DAY.test(surveyDay))throw new Error('조사일 형식이 올바르지 않습니다');
 if(memo.length>NOTE_MAX)throw new Error(`메모는 ${NOTE_MAX}자 이하로 적으세요`);
 const entry={kind:GROCERY_KIND,survey_date:surveyDay,taken_down_at:(options.now?.()||new Date()).toISOString(),note:memo};
 await update(token,options,raw=>raw.some(sameMute(surveyDay))?null:[...raw,entry],'Mute grocery pick text '+surveyDay);
 await redeploy(token,options);
}

export async function unmuteGroceryText(token:string,surveyDay:string,options:Options={}):Promise<void>{
 checkToken(token);
 if(!DAY.test(surveyDay))throw new Error('조사일 형식이 올바르지 않습니다');
 await update(token,options,raw=>raw.some(sameMute(surveyDay))?raw.filter(t=>!sameMute(surveyDay)(t)):null,'Unmute grocery pick text '+surveyDay);
 await redeploy(token,options);
}

// Festival / benefit pick AI summary: mute one public pick day (the card keeps its rule-based picks).
export type PickKind='festival_pick_text'|'benefit_pick_text';
const samePick=(kind:PickKind,day:string)=>(t:unknown)=>!!t&&typeof t==='object'&&(t as Record<string,unknown>).kind===kind&&(t as Record<string,unknown>).day===day;
function pickMutesIn(raw:unknown[],kind:PickKind):string[]{
 return raw.flatMap(t=>{const v=t as Record<string,unknown>;return v&&typeof v==='object'&&v.kind===kind&&typeof v.day==='string'&&DAY.test(v.day)?[v.day]:[];});
}

export async function mutePickText(token:string,kind:PickKind,day:string,note:string,options:Options={}):Promise<void>{
 checkToken(token);
 const memo=note.trim();
 if(!DAY.test(day))throw new Error('추천 날짜 형식이 올바르지 않습니다');
 if(memo.length>NOTE_MAX)throw new Error(`메모는 ${NOTE_MAX}자 이하로 적으세요`);
 const entry={kind,day,taken_down_at:(options.now?.()||new Date()).toISOString(),note:memo};
 await update(token,options,raw=>raw.some(samePick(kind,day))?null:[...raw,entry],`Mute ${kind} ${day}`);
 await redeploy(token,options);
}

export async function unmutePickText(token:string,kind:PickKind,day:string,options:Options={}):Promise<void>{
 checkToken(token);
 if(!DAY.test(day))throw new Error('추천 날짜 형식이 올바르지 않습니다');
 await update(token,options,raw=>raw.some(samePick(kind,day))?raw.filter(t=>!samePick(kind,day)(t)):null,`Unmute ${kind} ${day}`);
 await redeploy(token,options);
}

// Health-programme AI sentence: mute one programme page (its link stays; only the AI sentence is hidden).
const HEALTH_KIND='health_note_text';
const httpsUrl=(u:unknown)=>{if(typeof u!=='string'||u.length>500)return false;try{const v=new URL(u);return v.protocol==='https:'&&!v.username&&!v.password;}catch{return false;}};
const sameHealth=(url:string)=>(t:unknown)=>!!t&&typeof t==='object'&&(t as Record<string,unknown>).kind===HEALTH_KIND&&(t as Record<string,unknown>).url===url;

function healthMutesIn(raw:unknown[]):string[]{
 return raw.flatMap(t=>{const v=t as Record<string,unknown>;return v&&typeof v==='object'&&v.kind===HEALTH_KIND&&httpsUrl(v.url)?[v.url as string]:[];});
}

export async function muteHealthNote(token:string,url:string,note:string,options:Options={}):Promise<void>{
 checkToken(token);
 const memo=note.trim();
 if(!httpsUrl(url))throw new Error('페이지 주소가 올바르지 않습니다');
 if(memo.length>NOTE_MAX)throw new Error(`메모는 ${NOTE_MAX}자 이하로 적으세요`);
 const entry={kind:HEALTH_KIND,url,taken_down_at:(options.now?.()||new Date()).toISOString(),note:memo};
 await update(token,options,raw=>raw.some(sameHealth(url))?null:[...raw,entry],'Mute health note '+url);
 await redeploy(token,options);
}

export async function unmuteHealthNote(token:string,url:string,options:Options={}):Promise<void>{
 checkToken(token);
 if(!httpsUrl(url))throw new Error('페이지 주소가 올바르지 않습니다');
 await update(token,options,raw=>raw.some(sameHealth(url))?raw.filter(t=>!sameHealth(url)(t)):null,'Unmute health note '+url);
 await redeploy(token,options);
}
