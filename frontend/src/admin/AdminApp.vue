<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';
import {DeployError,NOTE_MAX,REPO,readTakedowns,restore,takeDown,validToken,type Takedown} from './github';

type Doc={url:string;title:string};
type AutoItem={candidateId:string;titleKey:string;title:string;source:string;url:string;conditions:string;validityKind:string;
 validFrom:string;validUntil:string;deadlineAt:string;documentCount:number;documents:Doc[];checkedAt:string};
type AiStatus={state:string;lastSuccessDay:string|null}|null;

const STORAGE_KEY='benefit-monitor.admin-token';
const text=(v:unknown)=>typeof v==='string'?v:'';
const record=(v:unknown)=>v&&typeof v==='object'&&!Array.isArray(v)?v as Record<string,unknown>:{};
function https(url:string){try{const u=new URL(url);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}}
function when(v:string){const t=Date.parse(v);return Number.isFinite(t)?new Date(t).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' (KST)':'기록 없음';}

function parseItems(raw:unknown):AutoItem[]{
 const items=record(raw).items;
 if(!Array.isArray(items))return [];
 return items.flatMap(value=>{
  const row=record(value),review=record(row.review);
  if(review.kind!=='ai_auto'||!/^[0-9a-f]{24}$/.test(text(review.candidate_id))||!text(review.title_key))return [];
  const documents=(Array.isArray(review.documents)?review.documents:[]).map(record).map(d=>({url:text(d.url),title:text(d.title)||text(d.url)})).filter(d=>https(d.url));
  return [{candidateId:text(review.candidate_id),titleKey:text(review.title_key),title:text(row.title),source:text(row.source),
   url:https(text(row.url))?text(row.url):'',conditions:text(row.conditions),validityKind:text(row.validity_kind),validFrom:text(row.valid_from),
   validUntil:text(row.valid_until),deadlineAt:text(row.deadline_at),documentCount:typeof review.document_count==='number'?review.document_count:0,
   documents,checkedAt:text(review.checked_at)}];
 });
}
function parseStatus(raw:unknown):AiStatus{
 const s=record(record(raw).ai_status);
 return ['ok','credit_exhausted','failed'].includes(text(s.state))?{state:text(s.state),lastSuccessDay:text(s.last_success_day)||null}:null;
}

function storedToken(){try{return localStorage.getItem(STORAGE_KEY)||'';}catch{return '';}}
function storeToken(value:string){try{value?localStorage.setItem(STORAGE_KEY,value):localStorage.removeItem(STORAGE_KEY);}catch{/* works for this tab only */}}

const token=ref(''),draft=ref(''),items=ref<AutoItem[]>([]),aiStatus=ref<AiStatus>(null),briefingError=ref(false);
const takedowns=ref<Takedown[]|null>(null),takedownError=ref(''),message=ref(''),busy=ref(false);
const notes=ref<Record<string,string>>({});

const statusLine=computed(()=>{
 const s=aiStatus.value;
 if(!s)return {label:'AI 조사 상태 정보 없음',day:''};
 const day=s.lastSuccessDay?`마지막 성공 ${s.lastSuccessDay}`:'마지막 성공 기록 없음';
 const label=s.state==='credit_exhausted'?'AI 조사 중지: 크레딧 소진':s.state==='failed'?'AI 조사 최근 실행 실패':'AI 조사 정상';
 return {label,day};
});
const downIds=computed(()=>new Set((takedowns.value||[]).map(t=>t.candidate_id)));
const periodLabel=(i:AutoItem)=>{
 const kind=i.validityKind==='ongoing'?'상시':i.validityKind==='fixed'?'기간형':i.validityKind||'미확인';
 const range=i.validFrom||i.validUntil?`${i.validFrom||'?'} ~ ${i.validUntil||'?'}`:'기간 표기 없음';
 return `${kind} · ${range}`+(i.deadlineAt?` · 마감 ${when(i.deadlineAt)}`:'');
};

async function loadBriefing(){
 try{
  const response=await fetch(import.meta.env.BASE_URL+'briefing.json',{cache:'no-store',credentials:'omit'});
  if(!response.ok)throw new Error('HTTP');
  const raw:unknown=await response.json();
  items.value=parseItems(raw);aiStatus.value=parseStatus(raw);
 }catch{briefingError.value=true;}
}
async function loadTakedowns(){
 if(!token.value){takedowns.value=null;return;}
 try{takedowns.value=(await readTakedowns(token.value)).list;takedownError.value='';}
 catch(e){takedowns.value=null;takedownError.value=e instanceof Error?e.message:'내림 목록을 읽지 못했습니다';}
}
async function saveToken(){
 const value=draft.value.trim();
 if(!validToken(value)){message.value='토큰 형식이 올바르지 않습니다. github_pat_으로 시작하는 토큰을 그대로 붙여 넣으세요.';return;}
 token.value=value;draft.value='';storeToken(value);message.value='토큰을 이 브라우저에 저장했습니다.';
 await loadTakedowns();
}
function deleteToken(){token.value='';draft.value='';storeToken('');takedowns.value=null;takedownError.value='';message.value='토큰을 삭제했습니다.';}

async function run(action:()=>Promise<void>,done:string){
 if(!token.value||busy.value)return;
 busy.value=true;message.value='처리 중입니다.';
 try{await action();message.value=done;}
 catch(e){
  message.value=e instanceof DeployError?'내림 목록은 저장됐지만 재배포 요청이 실패했습니다('+e.message+'). 다음 공개 실행에서 반영됩니다.'
   :(e instanceof Error?e.message:'요청이 실패했습니다');
 }
 finally{busy.value=false;await loadTakedowns();}
}
const down=(i:AutoItem)=>run(()=>takeDown(token.value,{candidate_id:i.candidateId,title_key:i.titleKey},notes.value[i.candidateId]||''),
 '내렸습니다. 반영까지 2~3분 걸립니다.');
const revive=(t:Takedown)=>run(()=>restore(token.value,t.candidate_id),
 '되살렸습니다. 다음 공개 실행에서 기준을 다시 통과하면 다시 공개됩니다.');

onMounted(async()=>{token.value=storedToken();await Promise.all([loadBriefing(),loadTakedowns()]);});
</script>

<template>
 <main class="admin">
  <h1>자동 공개 항목 관리</h1>
  <p role="status" class="message">{{message}}</p>

  <section aria-labelledby="token-heading">
   <h2 id="token-heading">인증</h2>
   <p v-if="token">토큰이 이 브라우저에 저장되어 있습니다.</p>
   <form v-else @submit.prevent="saveToken">
    <label for="token">GitHub 토큰</label>
    <input id="token" v-model="draft" type="password" autocomplete="off" spellcheck="false">
    <button type="submit">토큰 저장</button>
   </form>
   <button v-if="token" type="button" @click="deleteToken">토큰 삭제</button>
   <details :open="!token">
    <summary>토큰 만드는 법</summary>
    <ol>
     <li>GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.</li>
     <li>Repository access는 Only select repositories에서 <code>{{REPO}}</code> 하나만 고릅니다.</li>
     <li>Permissions는 Contents: Read and write, Actions: Read and write 두 개만 줍니다. 만료일은 짧게 둡니다.</li>
    </ol>
    <p>토큰은 이 브라우저(localStorage)에만 저장하고 api.github.com 호출에만 씁니다. 사이트 서버나 로그로 보내지 않습니다. 다 쓰면 토큰 삭제를 누르세요.</p>
   </details>
  </section>

  <p class="ai-status" :class="aiStatus?.state" data-ai-status><strong>{{statusLine.label}}</strong> <span v-if="statusLine.day">({{statusLine.day}})</span></p>

  <section aria-labelledby="auto-heading">
   <h2 id="auto-heading">자동 공개 항목</h2>
   <p v-if="briefingError">공개 브리핑을 불러오지 못했습니다.</p>
   <p v-else-if="!items.length">지금 공개된 자동 항목이 없습니다.</p>
   <article v-for="i in items" :key="i.candidateId" :data-candidate="i.candidateId" class="card">
    <h3><a v-if="i.url" :href="i.url" target="_blank" rel="noopener noreferrer">{{i.title}}</a><template v-else>{{i.title}}</template></h3>
    <dl>
     <dt>출처</dt><dd>{{i.source}}</dd>
     <dt>기간 근거</dt><dd>{{periodLabel(i)}}</dd>
     <dt>확인 시각</dt><dd>{{when(i.checkedAt)}}</dd>
     <dt>판정 기준</dt><dd>공식 원문 {{i.documentCount}}건이 같은 내용으로 대조됨</dd>
     <dt>조건</dt><dd>{{i.conditions||'표기 없음'}}</dd>
    </dl>
    <p>대조한 원문</p>
    <ul><li v-for="d in i.documents" :key="d.url"><a :href="d.url" target="_blank" rel="noopener noreferrer">{{d.title}}</a></li></ul>
    <p v-if="downIds.has(i.candidateId)" class="pending">내림 목록에 있음. 반영을 기다리는 중입니다.</p>
    <div class="row">
     <label :for="'note-'+i.candidateId">메모</label>
     <input :id="'note-'+i.candidateId" v-model="notes[i.candidateId]" :maxlength="NOTE_MAX" placeholder="내리는 이유(선택)">
     <button type="button" :disabled="!token||busy||downIds.has(i.candidateId)" @click="down(i)">내리기</button>
    </div>
   </article>
  </section>

  <section aria-labelledby="down-heading">
   <h2 id="down-heading">내린 항목</h2>
   <p v-if="!token">내린 항목 목록은 토큰을 넣어야 볼 수 있습니다.</p>
   <p v-else-if="takedownError">{{takedownError}}</p>
   <p v-else-if="takedowns&&!takedowns.length">내린 항목이 없습니다.</p>
   <article v-for="t in takedowns||[]" :key="t.candidate_id+t.taken_down_at" :data-taken-down="t.candidate_id" class="card">
    <h3>{{t.title_key}}</h3>
    <p>내린 시각 {{when(t.taken_down_at)}}<template v-if="t.note"> · 메모: {{t.note}}</template></p>
    <button type="button" :disabled="busy" @click="revive(t)">되살리기</button>
   </article>
  </section>
 </main>
</template>

<style>
body{margin:0;background:#f6f7f9;color:#1b1f24;font:16px/1.55 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}
.admin{max-width:860px;margin:0 auto;padding:24px 16px 48px}
.admin h1{font-size:1.5rem;margin:0 0 8px}
.admin h2{font-size:1.15rem;margin:28px 0 10px}
.admin h3{font-size:1rem;margin:0 0 8px;overflow-wrap:anywhere}
.admin .message:empty{display:none}
.admin .message{background:#eef4ff;border:1px solid #c7d7f5;border-radius:8px;padding:8px 12px}
.admin .card{background:#fff;border:1px solid #dde1e6;border-radius:10px;padding:14px 16px;margin:0 0 12px}
.admin dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 12px;margin:0 0 8px}
.admin dt{color:#59636e}.admin dd{margin:0;overflow-wrap:anywhere}
.admin ul{margin:4px 0 8px;padding-left:20px}
.admin a{color:#0b57d0;overflow-wrap:anywhere}
.admin .row,.admin form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.admin input{flex:1 1 200px;min-width:0;padding:7px 9px;border:1px solid #b8bfc7;border-radius:6px;font:inherit}
.admin button{padding:7px 14px;border-radius:6px;border:1px solid #1b1f24;background:#1b1f24;color:#fff;font:inherit;cursor:pointer}
.admin button:disabled{opacity:.45;cursor:not-allowed}
.admin details{margin-top:12px}
.admin .ai-status{margin:20px 0 0;padding:10px 12px;border-radius:8px;background:#fff;border:1px solid #dde1e6}
.admin .ai-status.credit_exhausted,.admin .ai-status.failed{background:#fff3f0;border-color:#f1b5a6}
.admin .pending{color:#8a4b00}
</style>
