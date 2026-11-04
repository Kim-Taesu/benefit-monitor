<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue';
import BenefitCard from './BenefitCard.vue';
import type {Benefit} from './benefits';
import {DISTRICTS,TOPICS,INTEREST_IDS,CARRIERS,emptyBeta,loadBeta,saveBeta,clearBeta,recordEvent,recentEvents,topicsFor,summarizeEvents,searchTopics} from './beta';
import type {Action,BetaState,TopicId} from './beta';
const props=defineProps<{items:Benefit[];now:number;query:string}>();
let storage:Storage|null=null;try{storage=window.localStorage;}catch{}
const state=ref(loadBeta(storage,props.now));
const form=ref(JSON.parse(JSON.stringify(state.value.profile))),ageInput=ref(state.value.profile.age===null?'':String(state.value.profile.age));
const opened=ref(false),selected=ref<TopicId|null>(null),notice=ref(''),root=ref<HTMLElement|null>(null);
const topics=computed(()=>topicsFor(props.items,state.value.profile,state.value.consent?state.value.events:[],props.now));
// Explicit profile interests stay visible; up to two discovery topics rotate by local aggregate evidence.
const displayed=computed(()=>[...topics.value.filter(t=>t.pinned),...topics.value.filter(t=>!t.pinned).slice(0,2)]);
const current=computed(()=>topics.value.find(t=>t.id===selected.value));
const stats=computed(()=>summarizeEvents(state.value.events,props.now).filter(s=>s.views||s.clicks||s.likes||s.hides||s.searches||s.wrong||s.official));
function persist(next:BetaState):boolean {
 if(!saveBeta(storage,next)){notice.value='저장하지 못했습니다. 브라우저 저장소를 확인하세요. 기본 탐색은 계속 사용할 수 있습니다.';return false;}
 state.value=next;return true;
}
function saveProfile(){
 const age=ageInput.value.trim()===''?null:Number(ageInput.value);
 if(age!==null&&(!Number.isInteger(age)||age<14||age>120)){notice.value='만 나이는 14~120 사이 정수로 입력하거나 비워 주세요.';return;}
 const profile={...form.value,areas:[...form.value.areas],interests:[...form.value.interests],age};
 if(persist({...state.value,profile})){notice.value='이 브라우저에 설정을 저장했습니다. 신청 자격은 공식 조건을 확인하세요.';selected.value=null;}
}
function event(topic:TopicId,action:Action){
 if(!state.value.consent)return false;
 return persist(recordEvent(state.value,topic,action,props.now));
}
function consentChange(e:Event){
 const enabled=(e.target as HTMLInputElement).checked;
 if(persist({...state.value,consent:enabled,events:[]})){seen.clear();notice.value=enabled?'이 기기의 행동 기록을 시작합니다. 외부로 전송하지 않습니다.':'행동 기록을 중단하고 저장된 기록을 삭제했습니다.';void observe();}
 else (e.target as HTMLInputElement).checked=state.value.consent;
}
function reset(){
 // Stop learning in memory even if the browser refuses deletion.
 state.value=emptyBeta();form.value=JSON.parse(JSON.stringify(state.value.profile));ageInput.value='';selected.value=null;seen.clear();
 notice.value=clearBeta(storage)?'개인화 설정과 기록을 삭제했습니다.':'기록은 중단했지만 저장소 삭제에 실패했습니다. 브라우저 사이트 데이터를 삭제해 주세요.';
}
async function choose(id:TopicId){selected.value=id;event(id,'click');await nextTick();document.getElementById('beta-related')?.focus();}
function feedback(action:Action){
 if(!current.value)return;
 if(!state.value.consent){notice.value='피드백을 기록하려면 선택 사항인 행동 기록에 동의해 주세요. 혜택은 계속 볼 수 있습니다.';return;}
 if(event(current.value.id,action))notice.value='이 기기에만 피드백을 기록했습니다. 운영자에게 전달되거나 혜택의 검증 상태가 변경되지는 않습니다.';
}
let observer:IntersectionObserver|undefined;
const seen=new Set<TopicId>();
async function observe(){
 await nextTick();observer?.disconnect();
 if(!opened.value||!state.value.consent||document.visibilityState!=='visible')return;
 observer=new IntersectionObserver(entries=>{for(const entry of entries){
  const id=(entry.target as HTMLElement).dataset.topic as TopicId;
  if(entry.isIntersecting&&entry.intersectionRatio>=0.5&&!seen.has(id)&&opened.value&&document.visibilityState==='visible'&&state.value.consent){seen.add(id);event(id,'view');}
 }},{threshold:0.5});
 root.value?.querySelectorAll('[data-topic]').forEach(el=>observer!.observe(el));
}
function toggle(e:Event){opened.value=(e.target as HTMLDetailsElement).open;void observe();}
watch(()=>displayed.value.map(t=>t.id).join(','),()=>void observe());
watch(()=>props.query,(query)=>{if(state.value.consent)for(const id of searchTopics(query))event(id,'search');});
// Purge expired local records on access and as time advances, not merely from aggregates.
watch(()=>Math.floor(props.now/60000),()=>{
 const events=state.value.consent?recentEvents(state.value.events,props.now):[];
 if(events.length!==state.value.events.length)persist({...state.value,events});
});
onMounted(()=>{if(storage?.getItem){try{if(storage.getItem('benefit-monitor:beta:v1'))persist(state.value);}catch{}}
 document.addEventListener('visibilitychange',observe);
});
onUnmounted(()=>{observer?.disconnect();document.removeEventListener('visibilitychange',observe);});
</script>
<template>
<section id="beta" ref="root" class="beta-panel" aria-label="서울 개인화 베타">
 <details @toggle="toggle"><summary>서울 개인화 베타 · 나에게 맞는 주제 찾기</summary>
 <div class="beta-body">
  <h2>내 생활에 맞는 서울 혜택</h2>
  <p>서울 25개 구와 서울에서 이용할 수 있는 공통 안내를 탐색합니다. AI 연결 전 규칙 기반 시험이며, 모든 구의 혜택을 빠짐없이 수집한 것은 아닙니다.</p>
  <form @submit.prevent="saveProfile">
   <div class="beta-fields">
    <label>거주 자치구<select v-model="form.residence"><option value="">선택 안 함</option><option v-for="area in DISTRICTS" :key="area">{{area}}</option></select></label>
    <label>현재 만 나이<input v-model="ageInput" type="number" min="14" max="120" step="1" placeholder="선택 사항"></label>
    <label>이용 통신사<select v-model="form.carrier"><option v-for="carrier in CARRIERS" :key="carrier" :value="carrier">{{carrier||'선택 안 함'}}</option></select></label>
   </div>
   <p class="fine-print">만 14세 이상 설정을 시험합니다. 생년월일은 저장하지 않으며 나이는 직접 갱신해 주세요. 알뜰폰은 망 제공 통신사의 멤버십으로 간주하지 않습니다.</p>
   <details class="beta-areas"><summary>관심 자치구 선택 · {{form.areas.length}}곳</summary><fieldset><legend>방문하고 싶은 지역 · 주민 자격과 별개</legend><div class="beta-checks"><label v-for="area in DISTRICTS" :key="area"><input v-model="form.areas" type="checkbox" :value="area" :aria-label="'관심 자치구 '+area">{{area}}</label></div></fieldset></details>
   <fieldset><legend>관심사 · 직접 선택한 주제는 우선 유지</legend><div class="beta-checks"><label v-for="id in INTEREST_IDS" :key="id"><input v-model="form.interests" type="checkbox" :value="id" :aria-label="'관심사 '+TOPICS[id]">{{TOPICS[id]}}</label></div></fieldset>
   <button type="submit" class="primary-button">개인화 설정 저장</button>
  </form>
  <div class="beta-privacy">
   <label><input type="checkbox" :checked="state.consent" @change="consentChange">이 기기의 행동 기록에 동의</label>
   <p class="fine-print">선택 사항입니다. 주제 노출·클릭·검색 주제·피드백·공식 링크 이동과 시각을 이 브라우저에 최대 30일·500건 저장합니다. 검색어 원문과 프로필은 행동 기록에 넣지 않으며 서버·AI로 전송하지 않습니다. 동의를 해제하면 기록을 삭제합니다. 방문하지 않는 동안 남은 기록은 다음 방문 시 정리됩니다.</p>
   <button type="button" @click="reset">개인화 설정·기록 삭제</button>
  </div>
  <p class="action-notice" role="status" aria-live="polite">{{notice}}</p>
  <div v-if="displayed.length" class="topic-grid">
   <button v-for="topic in displayed" :key="topic.id" :data-topic="topic.id" type="button" class="topic-button" :aria-pressed="selected===topic.id" aria-controls="beta-related" @click="choose(topic.id)"><strong>{{topic.title}} · {{topic.items.length}}건</strong><span>{{topic.pinned?'내 설정으로 선택':'새로운 발견'}}</span><small>{{topic.reason}}</small></button>
  </div>
  <p v-else>현재 표시할 수 있는 주제가 없습니다. 수집·검증 대기일 수 있으며 실제 혜택이 없다는 뜻은 아닙니다.</p>
  <section id="beta-related" tabindex="-1" aria-label="선택한 주제의 혜택">
   <template v-if="current"><h3>{{current.title}}</h3><p>{{current.reason}}</p><p class="fine-print">원문 문구를 기준으로 연결한 후보입니다. 제외 조건·기준일·소득·거주 요건 등을 모두 판정한 결과가 아닙니다.</p>
    <div class="beta-feedback"><button type="button" @click="feedback('like')">관심 있어요</button><button type="button" @click="feedback('hide')">관심 없어요</button><button type="button" @click="feedback('wrong')">주제·정보가 맞지 않아요</button></div>
    <div class="card-grid"><BenefitCard v-for="item in current.items" :key="item.source+item.url" :item="item" :now="now" :hide-favorite="true" @official-click="event(current!.id,'official')" /></div>
   </template><p v-else-if="selected">선택한 주제의 표시 가능한 항목이 없어졌습니다. 다른 주제를 선택하세요.</p>
  </section>
  <details class="beta-stats"><summary>이 기기의 주제 반응 확인</summary><p>전체 사용자 통계가 아닙니다. 보이는 주제만 방문당 한 번 노출로 기록하며, 20회 미만은 자료 부족으로 처리합니다. 반응이 적은 자동 주제는 순위를 낮추고 다른 주제를 보여줍니다. 직접 선택한 주제는 유지합니다. 클릭은 실제 이용이나 절약을 의미하지 않습니다.</p><div class="beta-table"><table><caption>최근 30일 로컬 반응 · 시험 기준</caption><thead><tr><th scope="col">주제</th><th scope="col">노출</th><th scope="col">클릭</th><th scope="col">검색</th><th scope="col">판단</th></tr></thead><tbody><tr v-for="s in stats" :key="s.id"><th scope="row">{{TOPICS[s.id]}}</th><td>{{s.views}}</td><td>{{s.clicks}}</td><td>{{s.searches}}</td><td>{{s.decision}}</td></tr></tbody></table></div><p v-if="!stats.length">저장된 행동 기록이 없습니다.</p></details>
 </div></details>
</section>
</template>
