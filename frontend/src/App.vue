<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import BenefitCard from './BenefitCard.vue';
import FestivalSection from './FestivalSection.vue';
import HealthSection from './HealthSection.vue';
import GrocerySection from './GrocerySection.vue';
import SubscriptionSection from './SubscriptionSection.vue';
import {parseSubscriptions} from './subscriptions';
import {parseGroceries,parsePick,parseBaselines,parseDiscounts,featuredRows} from './groceries';
import {parseFestivals} from './festivals';
import {parseHealth} from './health';
import {DISTRICTS,isSeoulCandidate,matchesHome,topicsFor,TOPIC_ICONS,TOPIC_ICON_FALLBACK,MAJOR_TOPIC_COUNT} from './topics';
import {parseBenefitPick} from './picks';
import {loadVisit,saveVisit,clearVisit,nextVisit,visitKey} from './visit';
import type {Visit} from './visit';
// 탭(2026-11-10): 혜택·장보기·축제, 2026-11-11 보건소 추가. 주소의 #groceries·#festivals·#health로 바로 열고, 바꿀 때 검색 조건은 그대로 둔다.
type Tab='benefits'|'groceries'|'festivals'|'health';
const TABS:{id:Tab;label:string}[]=[{id:'benefits',label:'혜택'},{id:'groceries',label:'장보기'},{id:'festivals',label:'축제'},{id:'health',label:'보건소'}];
const tabFromHash=(hash:string):Tab=>hash==='#groceries'?'groceries':hash==='#festivals'?'festivals':hash==='#health'?'health':'benefits';
const tab=ref<Tab>(tabFromHash(location.hash));
function setTab(next:Tab,scroll=false){
 tab.value=next;
 const url=new URL(location.href);url.hash=next==='benefits'?'':next;
 if(url.href!==location.href)history.replaceState(history.state,'',url);
 if(scroll)nextTick(()=>document.getElementById('site-tabs')?.scrollIntoView({block:'start'}));
}
function tabKey(event:KeyboardEvent,index:number){
 const step=event.key==='ArrowRight'?1:event.key==='ArrowLeft'?-1:0;if(!step)return;
 event.preventDefault();const next=TABS[(index+step+TABS.length)%TABS.length].id;setTab(next);
 nextTick(()=>document.getElementById('tab-'+next)?.focus());
}
import type {Benefit} from './benefits';
import {benefitKey,loadFavorites,saveFavorites,clearFavorites,visibleFavorites} from './favorites';
import {loadInterests,saveInterests,clearInterests,initialInterests} from './preferences';
import { adapt, select, timing, coverageLabels, readFilters, filterUrl, formatDate, updatedLabel } from './benefits';
const raw=ref<unknown>(undefined),loading=ref(true),error=ref(''),now=ref(Date.now());
// Parsed once per minute, not on every 1-second tick. Rounding down stays within the 5-minute
// future tolerance, so data collected minutes ago is not mistaken for future data (an hour key did that).
const groceryMinute=computed(()=>Math.floor(now.value/60000)*60000);
const groceries=computed(()=>parseGroceries(raw.value,groceryMinute.value));
const basket=computed(()=>parseBaselines(raw.value,groceryMinute.value));
const discounts=computed(()=>parseDiscounts(raw.value,groceryMinute.value));
const groceryPick=computed(()=>groceries.value?parsePick(raw.value,groceries.value):null);
// 서울·경기 청약 일정(2026-11-17): 혜택 탭 칩 하나로 열고, 목록 자리에 보여 준다.
const subs=computed(()=>parseSubscriptions(raw.value,groceryMinute.value));
// 페이지를 연 채 묶음이 오래되면 칩이 사라지므로 선택도 전체로 되돌린다.
watch(subs,value=>{if(!value&&chip.value==='home')chip.value='all';});
function pageFilters(search:string){const value=readFilters(search);return {...value,category:'',region:DISTRICTS.includes(value.region)?value.region:''};}
const filters=reactive(pageFilters(location.search));
let localStore:Storage|null=null;
try{localStore=window.localStorage;}catch{/* Storage may be unavailable in private/restricted contexts. */}
// 2026-11-15 개편으로 없앤 개인화 설정·행동 기록은 남겨 두지 않고 지운다.
try{localStore?.removeItem('benefit-monitor:beta:v1');}catch{/* 지우지 못해도 화면은 그대로 쓴다. */}
// 한 줄 필터: 전체·곧 끝남·새로 올라옴·추천·저장한 것·주제(t:<id>) 가운데 하나만 고른다.
const chip=ref<string>(filters.status==='urgent'?'urgent':'all'),showTopics=ref(false);
const favorites=ref(loadFavorites(localStore)),favoriteNotice=ref('');
async function toggleFavorite(item:Benefit){
 const id=benefitKey(item),removing=favorites.value.includes(id);
 const next=removing?favorites.value.filter(value=>value!==id):[...favorites.value,id];
 if(!saveFavorites(localStore,next)){favoriteNotice.value='저장하지 못했습니다. 최대 200개 한도와 브라우저 저장소 설정을 확인하세요.';return;}
 favorites.value=next;favoriteNotice.value=removing?'즐겨찾기에서 해제했습니다.':'이 브라우저의 즐겨찾기에 저장했습니다.';
 if(removing&&chip.value==='saved'){await nextTick();document.getElementById('results')?.focus();}
}
function clearSaved(){
 if(clearFavorites(localStore)){favorites.value=[];favoriteNotice.value='이 브라우저의 즐겨찾기를 모두 해제했습니다.';}
 else favoriteNotice.value='즐겨찾기를 삭제하지 못했습니다. 브라우저 저장소 설정을 확인하세요.';
}
function toggleSaved(){chip.value=chip.value==='saved'?'all':'saved';setTab('benefits');}
// 내 지역: 주소의 조건이 먼저이고, 없으면 이 브라우저에 기억한 구를 쓴다. 바꾸면 바로 기억한다.
const initial=initialInterests(location.search,loadInterests(localStore));
if(initial)Object.assign(filters,{region:DISTRICTS.includes(initial.region)?initial.region:'',category:''});
const storageNotice=ref('');
function forgetAll(){
 const ok=[clearFavorites(localStore),clearInterests(localStore),clearVisit(localStore)].every(Boolean);
 favorites.value=[];visit.value=null;if(chip.value==='saved'||chip.value==='new')chip.value='all';
 storageNotice.value=ok?'이 브라우저에 저장한 즐겨찾기·내 지역·방문 기록을 지웠습니다.':'일부를 지우지 못했습니다. 브라우저 사이트 데이터를 삭제해 주세요.';
}
const draft=ref(filters.q);let debounce:ReturnType<typeof setTimeout>|undefined;
let interval:ReturnType<typeof setInterval>|undefined;let controller:AbortController|undefined;let navigation=false;
const data=computed(()=>{if(raw.value===undefined)return null;try{return adapt(raw.value,now.value);}catch{return null;}});
const all=computed(()=>(data.value?.items||[]).filter(isSeoulCandidate));
const pool=computed(()=>all.value.filter(item=>matchesHome(item,filters.region)));
const savedItems=computed(()=>visibleFavorites(all.value,favorites.value));
const regions=DISTRICTS;
const isUrgent=(item:Benefit)=>timing(item,now.value).urgent;
const urgent=computed(()=>pool.value.filter(isUrgent).length);
// 이번 주 추천: 줄마다 카드에 붙이고, 요약 문장은 목록 위에 한 번 보인다.
const benefitPick=computed(()=>parseBenefitPick(raw.value,all.value));
const pickOf=computed(()=>new Map((benefitPick.value?.picks||[]).map(p=>[benefitKey(p.item),{source:benefitPick.value!.source,line:p.line}])));
const picked=computed(()=>pool.value.filter(item=>pickOf.value.has(benefitKey(item))).length);
// 방문 기록은 유효한 목록을 처음 받았을 때 한 번만 갱신한다.
const visit=ref<Visit|null>(null);let visitDone=false;
watch(data,value=>{
 if(visitDone||value?.state!=='partial')return;visitDone=true;
 const next=nextVisit(loadVisit(localStore,now.value),all.value.map(visitKey),now.value);
 saveVisit(localStore,next.record);visit.value=next;
});
const isFresh=(item:Benefit)=>Boolean(visit.value?.fresh.has(visitKey(item)));
const freshCount=computed(()=>pool.value.filter(isFresh).length);
const showIntro=computed(()=>Boolean(visit.value?.first&&!visit.value.record.introClosed));
function closeIntro(){if(!visit.value)return;visit.value={...visit.value,record:{...visit.value.record,introClosed:true}};saveVisit(localStore,visit.value.record);}
const since=computed(()=>{const at=visit.value?.previousAt;if(!at)return '';const d=new Date(at+9*3600000);return `${d.getUTCMonth()+1}월 ${d.getUTCDate()}일`;});
function goChip(value:string){chip.value=value;setTab('benefits');}
const topics=computed(()=>topicsFor(raw.value,pool.value,groceryMinute.value));
const majorTopics=computed(()=>topics.value.filter(t=>t.items.length>=MAJOR_TOPIC_COUNT));
const minorTopics=computed(()=>topics.value.filter(t=>t.items.length<MAJOR_TOPIC_COUNT));
const selectedTopic=computed(()=>chip.value.startsWith('t:')?topics.value.find(t=>'t:'+t.id===chip.value)||null:null);
const topicLabel=(t:{id:keyof typeof TOPIC_ICONS;title:string})=>(TOPIC_ICONS[t.id]||TOPIC_ICON_FALLBACK)+' '+t.title;
function foldTopics(){showTopics.value=false;if(minorTopics.value.some(t=>'t:'+t.id===chip.value))chip.value='all';}
const results=computed(()=>{
 const c=chip.value,keys=selectedTopic.value?new Set(selectedTopic.value.items.map(benefitKey)):null;
 const base=c==='saved'?savedItems.value:c==='new'?pool.value.filter(isFresh):c==='pick'?pool.value.filter(item=>pickOf.value.has(benefitKey(item))):keys?pool.value.filter(item=>keys.has(benefitKey(item))):pool.value;
 return select(base,{...filters,region:'',category:''},now.value);
});
// Collection/publication time differs from human approval time.
const updated=computed(()=>data.value?.sourceReportAt||data.value?.generatedAt||null);
const failed=computed(()=>data.value?.sources.filter(s=>s.status==='failed').length||0);
const active=computed(()=>Boolean(filters.q||filters.status||filters.sort!=='deadline'||chip.value!=='all'));
const heading=computed(()=>selectedTopic.value?selectedTopic.value.title:({urgent:'곧 끝나는 혜택',home:'서울·경기 청약 일정',saved:'저장한 혜택',new:'새로 올라온 혜택',pick:'이번 주 추천 혜택'} as Record<string,string>)[chip.value]||'발견한 혜택');
const state=computed(()=>error.value?'load_error':raw.value!==undefined&&!data.value?'invalid':data.value?.state||'loading');
const notices:Record<string,{title:string;body:string}>={
 load_error:{title:'공개 데이터를 불러오지 못했습니다',body:'연결 상태를 확인한 뒤 다시 시도하세요. 이전 자료를 현재 혜택으로 대신 표시하지 않습니다.'},
 invalid:{title:'공개 데이터 확인이 필요합니다',body:'데이터 형식 또는 기준 시각을 확인할 수 없어 혜택을 표시하지 않았습니다.'},
 stale:{title:'최신 브리핑을 기다리고 있어요',body:'파일의 표시기한이 지났습니다. 이전 항목을 오늘의 유효한 혜택으로 표시하지 않습니다.'},
 collection_failed:{title:'이번 수집을 완료하지 못했습니다',body:'수집 실패 또는 연결 미완료 상태입니다. 유효한 최신 목록을 확인할 수 없습니다.'},
 awaiting_verification:{title:'검증된 공개 혜택을 준비하고 있어요',body:'공개 승인된 검증 항목이 아직 없습니다. 실제 혜택이 없다는 뜻은 아닙니다.'},
};
// 만료 안내에는 마지막으로 갱신된 시각을 함께 보여 준다. 지난 항목 자체는 계속 숨긴다.
const notice=computed(()=>{
 const n=notices[state.value];
 if(!n||state.value!=='stale'||!updated.value)return n;
 return {...n,body:`마지막 갱신은 ${formatDate(updated.value)}입니다. 새 브리핑이 올라오면 자동으로 채워지니 잠시 뒤 다시 불러와 보세요. 이전 항목을 오늘의 유효한 혜택으로 표시하지 않습니다.`};
});
// 탭 옆 건수. 각 탭이 처음 보여 주는 목록의 건수와 같다.
const counts=computed<Record<Tab,number|null>>(()=>({benefits:all.value.length,groceries:groceries.value?featuredRows(groceries.value.rows).length:null,festivals:parseFestivals(raw.value,groceryMinute.value)?.items.length??null,health:parseHealth(raw.value,groceryMinute.value)?.items.length??null}));
// 보건소 탭의 지역은 내 지역과 함께 움직인다. 서울 25개 구가 아닌 곳(성남시)은 그 탭 안에서만 쓴다.
const healthDistrict=ref(filters.region);
watch(()=>filters.region,value=>{healthDistrict.value=value;});
watch(healthDistrict,value=>{if(value===''||DISTRICTS.includes(value))filters.region=value;});
const statusIcon:Record<string,string>={failed:'⚠️ ',not_connected:'🔌 '};
async function load(){
 controller?.abort();const request=new AbortController();controller=request;loading.value=true;error.value='';raw.value=undefined;
 const timeout=setTimeout(()=>request.abort(),15000);
 try{const response=await fetch(import.meta.env.BASE_URL+'briefing.json',{signal:request.signal,cache:'no-store',credentials:'omit'});if(!response.ok)throw new Error('HTTP');const body=await response.text();if(body.length>2*1024*1024)throw new Error('Size');const parsed:unknown=JSON.parse(body);if(controller!==request)return;raw.value=parsed;now.value=Date.now();}
 catch{if(controller===request)error.value='공개 데이터를 불러오지 못했습니다';}
 finally{clearTimeout(timeout);if(controller===request)loading.value=false;}
}
// 초기화는 검색·필터만 되돌린다. 기억해 둔 내 지역은 그대로 둔다.
function reset(){chip.value='all';clearTimeout(debounce);draft.value='';Object.assign(filters,{...pageFilters(''),region:filters.region});}
function pop(){const next=pageFilters(location.search);if(Object.entries(next).every(([key,value])=>filters[key as keyof typeof filters]===value))return;navigation=true;clearTimeout(debounce);Object.assign(filters,pageFilters(location.search));draft.value=filters.q;queueMicrotask(()=>navigation=false);}
function tick(){now.value=Date.now();}
watch(draft,value=>{clearTimeout(debounce);if(value===filters.q)return;debounce=setTimeout(()=>filters.q=value,200);});
watch(filters,()=>{if(navigation)return;const url=filterUrl(new URL(location.href),filters);if(url.href!==location.href)history.pushState(null,'',url);});
watch(chip,value=>{filters.status=value==='urgent'?'urgent':'';});
watch(()=>filters.status,value=>{if(value==='urgent')chip.value='urgent';else if(chip.value==='urgent')chip.value='all';});
watch(()=>filters.region,value=>{if(!navigation)saveInterests(localStore,{region:value,category:''});});
watch(topics,()=>{if(chip.value.startsWith('t:')&&!selectedTopic.value&&!loading.value)chip.value='all';});
onMounted(()=>{history.replaceState(null,'',filterUrl(new URL(location.href),filters));void load();interval=setInterval(tick,1000);window.addEventListener('popstate',pop);window.addEventListener('focus',tick);document.addEventListener('visibilitychange',tick);});
onUnmounted(()=>{controller?.abort();clearInterval(interval);clearTimeout(debounce);window.removeEventListener('popstate',pop);window.removeEventListener('focus',tick);document.removeEventListener('visibilitychange',tick);});
</script>
<template>
  <a class="skip-link" href="#results">혜택 목록으로 건너뛰기</a>
  <header class="site-header"><div class="header-inner"><a class="brand" href="./" aria-label="Benefit Monitor 홈"><span class="brand-mark" aria-hidden="true">b<span>m</span></span>Benefit Monitor</a><span v-if="!loading&&updated" class="updated">{{ updatedLabel(updated,now) }}</span><button type="button" class="saved-button" :aria-pressed="chip==='saved'" :aria-label="'즐겨찾기만 보기 '+savedItems.length" @click="toggleSaved"><span aria-hidden="true">{{ chip==='saved'?'★':'☆' }} 저장 <b>{{ savedItems.length }}</b></span></button></div></header>
  <main class="container">
    <h1 id="hero-title" class="sr-only">Benefit Monitor · 서울 생활 혜택</h1>
    <section v-if="showIntro" class="intro" aria-label="서비스 소개"><div><strong>서울에서 챙길 수 있는 생활 혜택을 매일 모아 드려요</strong><p>서울시·구청·보건소 같은 공식 출처에서 혜택, 장보기 시세, 축제, 보건소 소식을 가져옵니다. 로그인 없이 바로 볼 수 있어요.</p></div><button type="button" @click="closeIntro">닫기</button></section>
    <p v-else-if="since&&(freshCount||urgent)" class="since"><span>{{ since }} 방문 이후</span><button v-if="freshCount" type="button" class="chip" @click="goChip('new')">새 혜택<small>{{ freshCount }}</small></button><button v-if="urgent" type="button" class="chip" @click="goChip('urgent')">곧 끝남<small>{{ urgent }}</small></button></p>
    <nav id="site-tabs" class="site-tabs" aria-label="보기 전환"><div role="tablist"><button v-for="(t,n) in TABS" :id="'tab-'+t.id" :key="t.id" type="button" role="tab" :aria-selected="tab===t.id" :aria-controls="'panel-'+t.id" :tabindex="tab===t.id?0:-1" @click="setTab(t.id)" @keydown="tabKey($event,n)">{{ t.label }}<span v-if="!loading&&counts[t.id]!==null" class="tab-count">{{ counts[t.id] }}</span></button></div></nav>
    <div id="panel-benefits" v-show="tab==='benefits'" role="tabpanel" aria-labelledby="tab-benefits" class="panel">
    <section class="tools" aria-label="혜택 검색 및 필터">
      <div class="field grow"><label for="search">검색</label><input id="search" v-model="draft" type="search" maxlength="200" placeholder="혜택, 기관, 지역" autocomplete="off" aria-controls="results"></div>
      <div class="field"><label for="region">내 지역</label><select id="region" v-model="filters.region"><option value="">서울 전체</option><option v-for="region in regions" :key="region">{{ region }}</option></select></div>
      <div class="field"><label for="sort">정렬</label><select id="sort" v-model="filters.sort"><option value="deadline">곧 끝나는 순</option><option value="verified">최근 확인 순</option><option value="title">이름 순</option></select></div>
    </section>
    <div class="chips" role="group" aria-label="혜택 고르기">
      <button type="button" class="chip" :aria-pressed="chip==='all'" @click="chip='all'">전체<small>{{ pool.length }}</small></button>
      <button type="button" class="chip" :aria-pressed="chip==='urgent'" @click="chip=chip==='urgent'?'all':'urgent'">곧 끝남<small>{{ urgent }}</small></button>
      <button v-if="subs" type="button" class="chip home-chip" :aria-pressed="chip==='home'" aria-controls="results" @click="chip=chip==='home'?'all':'home'">🏠 청약 일정<small>{{ subs.items.length }}</small></button>
      <button v-if="since&&freshCount" type="button" class="chip" :aria-pressed="chip==='new'" @click="chip=chip==='new'?'all':'new'">새로 올라옴<small>{{ freshCount }}</small></button>
      <button v-if="picked" type="button" class="chip" :aria-pressed="chip==='pick'" @click="chip=chip==='pick'?'all':'pick'">이번 주 추천<small>{{ picked }}</small></button>
      <button v-if="savedItems.length||chip==='saved'" type="button" class="chip" :aria-pressed="chip==='saved'" @click="chip=chip==='saved'?'all':'saved'">저장한 것<small>{{ savedItems.length }}</small></button>
      <button v-for="t in majorTopics" :key="t.id" type="button" class="chip topic-chip" :data-topic="t.id" :aria-pressed="chip==='t:'+t.id" aria-controls="results" @click="chip=chip==='t:'+t.id?'all':'t:'+t.id">{{ topicLabel(t) }}<small>{{ t.items.length }}</small></button>
      <button v-if="minorTopics.length&&!showTopics" type="button" class="chip" aria-expanded="false" @click="showTopics=true">주제 더보기<small>{{ minorTopics.length }}</small></button>
      <template v-if="showTopics"><button v-for="t in minorTopics" :key="t.id" type="button" class="chip topic-chip" :data-topic="t.id" :aria-pressed="chip==='t:'+t.id" aria-controls="results" @click="chip=chip==='t:'+t.id?'all':'t:'+t.id">{{ topicLabel(t) }}<small>{{ t.items.length }}</small></button><button v-if="minorTopics.length" type="button" class="chip" aria-expanded="true" @click="foldTopics">주제 접기</button></template>
      <button v-if="active" class="reset" type="button" @click="reset">필터 초기화</button>
    </div>
    <p v-if="filters.region" class="region-hint">{{ filters.region }} 혜택과 서울·전국 공통 혜택을 함께 보여줘요. 지역은 안내 범위이며 개인 자격을 보장하지 않습니다.</p>
    <div v-if="benefitPick?.summary&&chip==='all'&&!filters.q&&!filters.region" class="lead benefit-pick"><span class="badge ai">🤖 AI 작성</span><div><p class="pick-summary">{{ benefitPick.summary }}</p><p class="fine-print">개인 프로필 없이 AI가 공개된 혜택 안에서 고른 공통 추천이에요. 마감일과 비용은 공개 데이터 그대로 카드에 보여드려요.</p></div></div>

    <div v-if="loading" class="notice" role="status"><span class="status-dot" aria-hidden="true"></span><div><strong>공개 데이터를 확인하고 있어요</strong><p>검증 시각과 표시기한을 함께 확인합니다.</p></div></div>
    <div v-else-if="notice" class="notice warning" role="status"><span aria-hidden="true">!</span><div><strong>{{ notice.title }}</strong><p>{{ notice.body }}</p><button type="button" @click="load">다시 불러오기</button></div></div>
    <section id="results" class="results" aria-labelledby="results-title" tabindex="-1" :aria-busy="loading">
      <h2 id="results-title" class="sr-only">{{ heading }} <span v-if="!(chip==='home'&&subs)" aria-live="polite" aria-atomic="true">{{ results.length }}건</span></h2>
      <p v-if="chip==='saved'" class="fine-print">이 브라우저에만 저장됩니다. 현재 표시 가능한 {{ savedItems.length }}건 · 현재 유효성을 확인할 수 없는 저장 항목 {{ Math.max(0,favorites.length-savedItems.length) }}건. 종료를 뜻하지 않습니다. <button v-if="favorites.length" type="button" class="link-button" @click="clearSaved">즐겨찾기 모두 해제</button></p>
      <p role="status" aria-live="polite" class="action-notice">{{ favoriteNotice }}</p>
      <SubscriptionSection v-if="chip==='home'&&subs" :bundle="subs" :now="groceryMinute" :region="filters.region" :query="filters.q" />
      <div v-else-if="results.length" class="card-grid"><BenefitCard v-for="item in results" :key="item.source+'\n'+item.url" :item="item" :now="now" :saved="favorites.includes(benefitKey(item))" :failures="data?.sourceFailures" :pick="pickOf.get(benefitKey(item))" :fresh="isFresh(item)" @toggle-favorite="toggleFavorite(item)" /></div>
      <div v-else-if="!loading" class="empty-state"><span class="empty-symbol" aria-hidden="true">⌕</span><h3>{{ chip==='saved'?'현재 조건에 맞는 즐겨찾기가 없어요':all.length?'조건에 맞는 검증 항목이 없어요':state==='partial'?'현재 표시 가능한 검증 항목이 없어요':'확인된 목록이 준비되면 여기에 표시됩니다' }}</h3><p>{{ all.length?'다른 검색어나 지역으로 찾아보세요.':'개별 표시기한 경과 또는 검증 보류일 수 있습니다. 실제 혜택이 없거나 행사가 종료됐다는 뜻은 아닙니다.' }}</p><button v-if="active" type="button" class="primary-button" @click="reset">필터 초기화</button></div>
    </section>
    </div>
    <div id="panel-groceries" v-show="tab==='groceries'" role="tabpanel" aria-labelledby="tab-groceries">
      <GrocerySection v-if="groceries" :bundle="groceries" :weekly="groceryPick" :basket="basket" :discounts="discounts" @more="setTab('benefits',true)" />
      <p v-else-if="!loading" class="empty-state">이번 실행에서 장보기 시세를 가져오지 못했어요.</p>
    </div>
    <div id="panel-festivals" v-show="tab==='festivals'" role="tabpanel" aria-labelledby="tab-festivals">
      <FestivalSection :raw="raw" :now="now" :query="''" />
    </div>
    <div id="panel-health" v-show="tab==='health'" role="tabpanel" aria-labelledby="tab-health">
      <HealthSection v-if="!loading" v-model:district="healthDistrict" :raw="raw" :now="groceryMinute" />
    </div>
    <section class="trust-section" aria-labelledby="trust-title"><h2 id="trust-title" class="sr-only">수집 범위와 한계</h2>
      <p class="trust-note">공식 출처에 올라온 내용을 옮긴 것이며, 공식 확인과 신청 자격은 별개입니다. 개인 자격·잔여석·재고·조기 마감은 확인하지 않았으니 비용·최소 지출·결제 조건과 함께 신청 전 공식 안내를 확인하세요. 검증 시각은 수집 시각과 다르고, 전체 지역·모든 혜택을 수집한 서비스가 아닙니다.</p>
      <div class="collection-details"><details><summary>어디서 가져오나요? <span>{{ data?.sources.length||0 }}개 출처<template v-if="failed"> · ⚠️ 못 가져온 곳 {{ failed }}</template></span></summary><div class="coverage-body"><p v-if="data">생성 {{ formatDate(data.generatedAt) }}<br>수집 기준 {{ formatDate(data.sourceReportAt) }}<br>파일 표시기한 {{ formatDate(data.validThrough) }}<br>{{ data.runLabel }}</p><p>재검증 대기 {{ data?.pending||0 }}건 · 화면 검증에서 제외 {{ data?.withheldCount||0 }}건</p><p v-if="data">AI 원문 대조: 최근 실행 {{ data.aiQuality.checked ?? '–' }}건 확인 · 불일치로 보류 {{ data.aiQuality.held }}건 · 끝남·혜택 아님으로 대기 제외 {{ data.aiQuality.dismissed }}건 · 진행 중 우선 확인 {{ data.aiQuality.prioritized }}건</p><ul v-if="data?.aiQuality.findings.length" class="ai-findings"><li v-for="f in data.aiQuality.findings" :key="f.title+f.url"><strong><a v-if="f.url" :href="f.url" target="_blank" rel="noopener noreferrer">{{ f.title }}</a><template v-else>{{ f.title }}</template></strong><small v-for="c in f.claims" :key="c.claim">저장된 조건 “{{ c.claim }}” · 공식 원문 “{{ c.quotes.join(' / ') }}”</small></li></ul><p>표시기한 경과는 행사 종료나 잔여석 소진과 다릅니다. 0건은 실제 혜택이 없다는 뜻이 아닙니다.</p><ul><li v-for="row in data?.sources||[]" :key="row.source"><strong>{{ row.name }}</strong><span>{{ (statusIcon[row.status]||'')+(coverageLabels[row.status]||'상태 미확인') }}</span><small v-if="row.scope">{{ row.scope }}</small></li></ul><h3 v-if="data?.districts.length">서울 자치구 수집 범위</h3><p>{{ data?.scope||'수집 범위 확인 필요' }}</p><ul><li v-for="row in data?.districts||[]" :key="row.name"><strong>{{ row.name }}</strong><span>{{ (statusIcon[row.status]||'')+(coverageLabels[row.status]||'상태 미확인') }}</span></li></ul></div></details></div>
      <p class="fine-print">즐겨찾기·내 지역·지난 방문 때 보인 항목 표시는 이 브라우저에만 저장하고 서버로 보내지 않습니다. <button type="button" class="link-button" @click="forgetAll">저장한 것 모두 지우기</button> <span role="status" aria-live="polite">{{ storageNotice }}</span></p>
    </section>
    <div id="collection-notice" v-if="!loading&&!notice" class="notice" role="status"><span class="status-dot" aria-hidden="true"></span><div><strong>부분 수집 결과입니다<span v-if="failed"> · 수집 실패 {{ failed }}곳</span></strong><p>미검증 후보 제외 · 자격·재고·잔여석은 공식 안내에서 확인하세요.</p></div></div>
  </main>
  <footer class="site-footer"><div class="container footer-inner"><div><strong>Benefit Monitor</strong><p>로그인 없이 발견하는 생활 혜택.</p></div><nav aria-label="데이터 내보내기"><a href="./briefing.json">공개 JSON ↗</a><a href="./briefing.md">텍스트 브리핑 ↗</a></nav><p class="cost-note">이 화면에서는 유료 API를 호출하지 않습니다. ChatGPT/Codex 및 기존 실행 환경의 요금은 이 프로젝트가 보장하지 않습니다.</p></div></footer>
</template>
