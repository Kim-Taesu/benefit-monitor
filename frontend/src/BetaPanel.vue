<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue';
import type {Benefit} from './benefits';
import {DISTRICTS,TOPICS,INTEREST_IDS,CARRIERS,BETA_KEY,emptyBeta,loadBeta,saveBeta,clearBeta,recordEvent,recentEvents,topicsFor,summarizeEvents,searchTopics} from './beta';
import type {Action,BetaState,TopicId,Profile,Topic} from './beta';
const props=defineProps<{items:Benefit[];now:number;query:string}>();
const emit=defineEmits<{selectTopic:[topic:Topic|null]}>();
const icons:Record<TopicId,string>={local:'🏡',night:'🌙',culture:'🎨',learning:'📚',shopping:'🛍️',carrier:'📱',age:'🎯',vouchers:'🎟️',convenience:'🏪',outdoors:'👟',family:'🧸',housing:'🔑',career:'💼'};
const descriptions:Record<TopicId,string>={local:'지역 프로그램·행사·생활 지원',night:'야간 개장·빛 축제·야외 문화 행사',culture:'이번 주 둘러볼 전시와 문화 체험',learning:'새로 시작하는 교육·강좌·취미',shopping:'장보기·결제 할인·적립 안내',carrier:'멤버십 등급·요일·결제 조건 확인',age:'연령 조건이 있는 지원·교육·문화 안내',vouchers:'상품권 할인·결제 페이백',convenience:'멤버십 할인·포인트 적립',outdoors:'걷기 챌린지·러너 공간·공원',family:'어린이 관람·가족 체험',housing:'임대·분양·사회주택 모집',career:'채용 공고·면접 지원 공간'};
let storage:Storage|null=null;try{storage=window.localStorage;}catch{}
const state=ref(loadBeta(storage,props.now));
let consentStopped=false;
function stored(){const value=loadBeta(storage,props.now);return consentStopped?{...value,consent:false,events:[]}:value;}
const form=ref<Profile>(JSON.parse(JSON.stringify(state.value.profile))),ageInput=ref(state.value.profile.age===null?'':String(state.value.profile.age));
const selected=ref<TopicId|null>(null),notice=ref(''),root=ref<HTMLElement|null>(null);
const topics=computed(()=>topicsFor(props.items,state.value.profile,state.value.consent?state.value.events:[],props.now));
// Explicit interests stay visible; discovery slots rank by local aggregate evidence.
const showAll=ref(false);
const displayed=computed(()=>{const pinned=topics.value.filter(t=>t.pinned);return [...pinned,...topics.value.filter(t=>!t.pinned).slice(0,showAll.value?undefined:Math.max(0,8-pinned.length))];});
const current=computed(()=>topics.value.find(t=>t.id===selected.value));
const stats=computed(()=>summarizeEvents(state.value.events,props.now).filter(s=>s.views||s.clicks||s.likes||s.hides||s.searches||s.wrong||s.official));
function persist(next:BetaState):boolean {
 if(!saveBeta(storage,next)){notice.value='저장하지 못했습니다. 브라우저 저장소를 확인하세요. 기본 탐색은 계속 사용할 수 있습니다.';return false;}
 state.value=next;return true;
}
function saveProfile(){
 const age=String(ageInput.value).trim()===''?null:Number(ageInput.value);
 if(age!==null&&(!Number.isInteger(age)||age<14||age>120)){notice.value='만 나이는 14~120 사이 정수로 입력하거나 비워 주세요.';return;}
 const profile={...form.value,areas:[...form.value.areas],interests:[...form.value.interests],age};
 if(persist({...stored(),profile})){notice.value='이 브라우저에 설정을 저장했습니다. 신청 자격은 공식 조건을 확인하세요.';selected.value=null;}
}
function event(topic:TopicId,action:Action){
 if(!state.value.consent)return false;
 const latest=stored();
 if(!latest.consent){state.value=latest;return false;}
 return persist(recordEvent(latest,topic,action,props.now));
}
function consentChange(e:Event){
 const enabled=(e.target as HTMLInputElement).checked;
 if(!enabled){
  consentStopped=true;
  state.value={...state.value,consent:false,events:[]};observer?.disconnect();seen.clear();
  const saved=saveBeta(storage,state.value)||clearBeta(storage);
  notice.value=saved?'행동 기록을 중단하고 저장된 기록을 삭제했습니다.':'기록은 중단했지만 저장소 삭제에 실패했습니다. 브라우저 사이트 데이터를 삭제해 주세요.';
  return;
 }
 if(persist({...loadBeta(storage,props.now),consent:true,events:[]})){consentStopped=false;seen.clear();notice.value='이 기기의 행동 기록을 시작합니다. 외부로 전송하지 않습니다.';void observe();}
 else (e.target as HTMLInputElement).checked=state.value.consent;
}
function reset(){
 // Stop learning in memory even if the browser refuses deletion.
 consentStopped=true;state.value=emptyBeta();form.value=JSON.parse(JSON.stringify(state.value.profile));ageInput.value='';selected.value=null;seen.clear();
 notice.value=clearBeta(storage)?'개인화 설정과 기록을 삭제했습니다.':'기록은 중단했지만 저장소 삭제에 실패했습니다. 브라우저 사이트 데이터를 삭제해 주세요.';
}
async function choose(id:TopicId){selected.value=id;event(id,'click');await nextTick();document.getElementById('results')?.focus();document.getElementById('results')?.scrollIntoView({block:'start',behavior:'smooth'});}
function feedback(action:Action){
 if(!current.value)return;
 if(!state.value.consent){notice.value='피드백을 기록하려면 선택 사항인 행동 기록에 동의해 주세요. 혜택은 계속 볼 수 있습니다.';return;}
 if(event(current.value.id,action))notice.value='이 기기에만 피드백을 기록했습니다. 운영자에게 전달되거나 혜택의 검증 상태가 변경되지는 않습니다.';
}
let observer:IntersectionObserver|undefined;
const seen=new Set<TopicId>();
async function observe(){
 await nextTick();observer?.disconnect();
 if(!state.value.consent||document.visibilityState!=='visible')return;
 observer=new IntersectionObserver(entries=>{for(const entry of entries){
  const id=(entry.target as HTMLElement).dataset.topic as TopicId;
  if(entry.isIntersecting&&entry.intersectionRatio>=0.5&&!seen.has(id)&&document.visibilityState==='visible'&&state.value.consent){seen.add(id);event(id,'view');}
 }},{threshold:0.5});
 root.value?.querySelectorAll('[data-topic]').forEach(el=>observer!.observe(el));
}
function clearSelection(){selected.value=null;}
function officialClick(){if(current.value)event(current.value.id,'official');}
defineExpose({clearSelection,officialClick});
watch([selected,current],()=>emit('selectTopic',selected.value?(current.value||{id:selected.value,title:TOPICS[selected.value],reason:'현재 표시 가능한 항목이 없습니다.',items:[],pinned:false,score:0}):null),{immediate:true});
watch(()=>displayed.value.map(t=>t.id).join(','),()=>void observe());
watch(()=>props.query,(query)=>{if(state.value.consent)for(const id of searchTopics(query))event(id,'search');});
// Purge expired local records on access and as time advances, not merely from aggregates.
watch(()=>Math.floor(props.now/60000),()=>{
 const latest=stored();const events=latest.consent?recentEvents(latest.events,props.now):[];
 if(events.length!==state.value.events.length){state.value={...latest,events};if(storage)saveBeta(storage,state.value);}
});
function syncStorage(e:StorageEvent){
 if(e.key!==null&&e.key!==BETA_KEY)return;
 state.value=stored();form.value=JSON.parse(JSON.stringify(state.value.profile));ageInput.value=state.value.profile.age===null?'':String(state.value.profile.age);
 void observe();
}
onMounted(()=>{if(storage?.getItem){try{if(storage.getItem(BETA_KEY))persist(loadBeta(storage,props.now));}catch{}}
 window.addEventListener('storage',syncStorage);
 document.addEventListener('visibilitychange',observe);void observe();
});
onUnmounted(()=>{window.removeEventListener('storage',syncStorage);observer?.disconnect();document.removeEventListener('visibilitychange',observe);});
</script>
<template>
<section id="beta" ref="root" class="beta-panel" aria-labelledby="topics-title">
 <div class="topics-heading"><div><p class="eyebrow">나를 위한 발견</p><h2 id="topics-title">어떤 혜택을 찾아볼까요?</h2></div><button v-if="selected" type="button" class="reset" @click="clearSelection">전체 주제 보기</button></div>
 <div v-if="displayed.length" class="topic-grid">
  <button v-for="topic in displayed" :key="topic.id" :data-topic="topic.id" type="button" class="topic-button" :class="'topic-'+topic.id" :aria-pressed="selected===topic.id" aria-controls="results" @click="choose(topic.id)"><span class="topic-icon" aria-hidden="true">{{icons[topic.id]}}</span><strong>{{topic.title}}</strong><small>{{descriptions[topic.id]}}</small><span class="topic-count">{{topic.items.length}}개 혜택 <span aria-hidden="true">↗</span></span></button>
 </div>
 <p v-else class="fine-print">현재 표시할 수 있는 주제가 없습니다. 수집·검증 대기일 수 있으며 실제 혜택이 없다는 뜻은 아닙니다.</p>
 <button v-if="topics.length>8" class="topic-more" type="button" :aria-expanded="showAll" @click="showAll=!showAll">{{showAll?'주제 접기':'다른 주제 더 보기'}} <span aria-hidden="true">{{showAll?'−':'+'}}</span></button>
 <div v-if="current" class="beta-feedback" aria-label="선택한 주제 피드백"><span>이 주제가 마음에 드나요?</span><button type="button" @click="feedback('like')">관심 있어요</button><button type="button" @click="feedback('hide')">관심 없어요</button><button type="button" @click="feedback('wrong')">주제·정보가 맞지 않아요</button></div>
 <p v-if="notice" class="action-notice" role="status" aria-live="polite">{{notice}}</p>
 <details class="beta-settings"><summary>내 지역·통신사·관심사 설정</summary>
 <div class="beta-body">
  <p>선택한 정보로 주제를 구성합니다. 설정은 이 브라우저에만 저장되며, 신청 자격을 확정하지 않습니다.</p>
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
  <details class="beta-stats"><summary>이 기기의 주제 반응 확인</summary><p>전체 사용자 통계가 아닙니다. 화면에 보이는 주제만 방문당 한 번 노출로 기록하며, 20회 미만은 자료 부족으로 처리합니다. 직접 선택한 주제는 유지하고 자동 주제 순위를 반응에 따라 조정합니다. 클릭은 실제 이용이나 절약을 의미하지 않습니다.</p><div class="beta-table"><table><caption>최근 30일 로컬 반응 · 시험 기준</caption><thead><tr><th scope="col">주제</th><th scope="col">노출</th><th scope="col">클릭</th><th scope="col">검색</th><th scope="col">판단</th></tr></thead><tbody><tr v-for="s in stats" :key="s.id"><th scope="row">{{TOPICS[s.id]}}</th><td>{{s.views}}</td><td>{{s.clicks}}</td><td>{{s.searches}}</td><td>{{s.decision}}</td></tr></tbody></table></div><p v-if="!stats.length">저장된 행동 기록이 없습니다.</p></details>
 </div></details>
</section>
</template>
