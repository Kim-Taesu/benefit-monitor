<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import BenefitCard from './BenefitCard.vue';
import {loadInterests,saveInterests,clearInterests,initialInterests} from './preferences';
import { adapt, select, timing, categories, coverageLabels, readFilters, filterUrl, formatDate, timestamp, regionOptions } from './benefits';
const raw=ref<unknown>(undefined),loading=ref(true),error=ref(''),now=ref(Date.now());
const filters=reactive(readFilters(location.search));
let interestStorage:Storage|null=null;
try{interestStorage=window.localStorage;}catch{/* Storage may be unavailable in private/restricted contexts. */}
const remembered=ref(loadInterests(interestStorage)),preferenceNotice=ref('');
const initial=initialInterests(location.search,remembered.value);
if(initial)Object.assign(filters,initial);
function remember(){
 const value={region:filters.region,category:filters.category};
 if(saveInterests(interestStorage,value)){remembered.value=value;preferenceNotice.value='이 브라우저에 지역·분야를 저장했습니다.';}
 else preferenceNotice.value='저장하지 못했습니다. 브라우저 저장소 설정을 확인하세요. 혜택 탐색은 계속 사용할 수 있습니다.';
}
function forget(){
 if(clearInterests(interestStorage)){remembered.value=null;preferenceNotice.value='저장값을 삭제했습니다. 현재 검색 필터는 유지됩니다.';}
 else preferenceNotice.value='저장값을 삭제하지 못했습니다. 브라우저 저장소 설정을 확인하세요.';
}
const draft=ref(filters.q);let debounce:ReturnType<typeof setTimeout>|undefined;
let interval:ReturnType<typeof setInterval>|undefined;let controller:AbortController|undefined;let navigation=false;
const data=computed(()=>{if(raw.value===undefined)return null;try{return adapt(raw.value,now.value);}catch{return null;}});
const all=computed(()=>data.value?.items||[]);
const results=computed(()=>select(all.value,filters,now.value));
const regions=computed(()=>regionOptions(all.value));
const availableCategories=computed(()=>categories.filter(c=>all.value.some(i=>i.category===c)));
const urgent=computed(()=>all.value.filter(i=>timing(i,now.value).urgent).length);
const newest=computed(()=>all.value.length?all.value.reduce((a,b)=>timestamp(a.verified_at)>timestamp(b.verified_at)?a:b).verified_at:null);
const failed=computed(()=>data.value?.sources.filter(s=>s.status==='failed').length||0);
const active=computed(()=>Boolean(filters.q||filters.region||filters.category||filters.status||filters.sort!=='deadline'));
const state=computed(()=>error.value?'load_error':raw.value!==undefined&&!data.value?'invalid':data.value?.state||'loading');
const notices:Record<string,{title:string;body:string}>={
 load_error:{title:'공개 데이터를 불러오지 못했습니다',body:'연결 상태를 확인한 뒤 다시 시도하세요. 이전 자료를 현재 혜택으로 대신 표시하지 않습니다.'},
 invalid:{title:'공개 데이터 확인이 필요합니다',body:'데이터 형식 또는 기준 시각을 확인할 수 없어 혜택을 표시하지 않았습니다.'},
 stale:{title:'최신 브리핑을 기다리고 있어요',body:'파일의 표시기한이 지났습니다. 이전 항목을 오늘의 유효한 혜택으로 표시하지 않습니다.'},
 collection_failed:{title:'이번 수집을 완료하지 못했습니다',body:'수집 실패 또는 연결 미완료 상태입니다. 유효한 최신 목록을 확인할 수 없습니다.'},
 awaiting_verification:{title:'검증된 공개 혜택을 준비하고 있어요',body:'공개 승인된 검증 항목이 아직 없습니다. 실제 혜택이 없다는 뜻은 아닙니다.'},
};
const notice=computed(()=>notices[state.value]);
async function load(){
 controller?.abort();const request=new AbortController();controller=request;loading.value=true;error.value='';raw.value=undefined;
 const timeout=setTimeout(()=>request.abort(),15000);
 try{const response=await fetch(import.meta.env.BASE_URL+'briefing.json',{signal:request.signal,cache:'no-store',credentials:'omit'});if(!response.ok)throw new Error('HTTP');const body=await response.text();if(body.length>2*1024*1024)throw new Error('Size');const parsed:unknown=JSON.parse(body);if(controller!==request)return;raw.value=parsed;now.value=Date.now();}
 catch{if(controller===request)error.value='공개 데이터를 불러오지 못했습니다';}
 finally{clearTimeout(timeout);if(controller===request)loading.value=false;}
}
function reset(){clearTimeout(debounce);draft.value='';Object.assign(filters,readFilters(''));}
function pop(){navigation=true;clearTimeout(debounce);Object.assign(filters,readFilters(location.search));draft.value=filters.q;queueMicrotask(()=>navigation=false);}
function tick(){now.value=Date.now();}
watch(draft,value=>{clearTimeout(debounce);if(value===filters.q)return;debounce=setTimeout(()=>filters.q=value,200);});
watch(filters,()=>{if(navigation)return;const url=filterUrl(new URL(location.href),filters);if(url.href!==location.href)history.pushState(null,'',url);});
onMounted(()=>{if(initial)history.replaceState(null,'',filterUrl(new URL(location.href),filters));void load();interval=setInterval(tick,1000);window.addEventListener('popstate',pop);window.addEventListener('focus',tick);document.addEventListener('visibilitychange',tick);});
onUnmounted(()=>{controller?.abort();clearInterval(interval);clearTimeout(debounce);window.removeEventListener('popstate',pop);window.removeEventListener('focus',tick);document.removeEventListener('visibilitychange',tick);});
</script>
<template>
  <a class="skip-link" href="#results">혜택 목록으로 건너뛰기</a>
  <header class="site-header"><div class="header-inner"><a class="brand" href="./" aria-label="Benefit Monitor 홈"><span class="brand-mark" aria-hidden="true">b<span>m</span></span>Benefit Monitor<span class="version">2.0</span></a><span class="login-note">가입 없이, 바로 발견</span></div></header>
  <main class="container">
    <section class="hero" aria-labelledby="hero-title"><p class="eyebrow"><span aria-hidden="true">●</span> 공식 출처에서 확인한 생활 혜택</p><h1 id="hero-title">오늘의 혜택,<br class="mobile-break"> <span>한눈에.</span></h1><p class="hero-description">내 지역의 지원부터 일상의 할인까지.<br class="mobile-break"> 필요한 조건을 확인하고 공식 안내로 이동하세요.</p></section>
    <section class="discovery" aria-label="혜택 검색 및 필터">
      <div class="search-box"><span aria-hidden="true" class="search-icon">⌕</span><label for="search" class="sr-only">혜택·조건·지역·기관 검색</label><input id="search" v-model="draft" type="search" maxlength="200" placeholder="혜택·조건·지역·기관을 검색하세요" autocomplete="off" aria-controls="results"></div>
      <div class="filter-row"><div class="filter-field"><label for="region">지역</label><select id="region" v-model="filters.region"><option value="">전체 지역</option><option v-if="filters.region&&!regions.includes(filters.region)" :value="filters.region">{{ filters.region }} (현재 항목 없음)</option><option v-for="region in regions" :key="region">{{ region }}</option></select></div><div class="filter-field"><label for="category">분야</label><select id="category" v-model="filters.category"><option value="">전체 분야</option><option v-if="filters.category&&!availableCategories.includes(filters.category)" :value="filters.category">{{ filters.category }} (현재 항목 없음)</option><option v-for="category in availableCategories" :key="category">{{ category }}</option></select></div><div class="quick-filters" aria-label="상태 필터"><button type="button" :aria-pressed="filters.status==='urgent'" @click="filters.status=filters.status==='urgent'?'':'urgent'">마감 임박 <span>{{ urgent }}</span></button><button type="button" :aria-pressed="filters.status==='new'" @click="filters.status=filters.status==='new'?'':'new'">24시간 내 확인</button></div><button v-if="active" class="reset" type="button" @click="reset">필터 초기화</button></div>
    </section>
    <p class="region-hint">지역은 안내 범위이며 개인 자격을 보장하지 않습니다.</p>
    <section class="overview" aria-label="브리핑 요약"><div><span class="metric-label">표시 가능한 공개 혜택</span><strong>{{ loading?'—':all.length }}<small>건</small></strong></div><div><span class="metric-label">7일 내 마감</span><strong>{{ loading?'—':urgent }}<small>건</small></strong></div><div class="last-verified"><span class="metric-label">마지막 공식 확인</span><strong>{{ formatDate(newest) }}</strong></div></section>
    <div v-if="loading" class="notice" role="status"><span class="status-dot" aria-hidden="true"></span><div><strong>공개 데이터를 확인하고 있어요</strong><p>검증 시각과 표시기한을 함께 확인합니다.</p></div></div>
    <div v-else-if="notice" class="notice warning" role="status"><span aria-hidden="true">!</span><div><strong>{{ notice.title }}</strong><p>{{ notice.body }}</p><button type="button" @click="load">다시 불러오기</button></div></div>
    <div v-else class="notice" role="status"><span class="status-dot" aria-hidden="true"></span><div><strong>부분 수집 결과입니다<span v-if="failed"> · 수집 실패 {{ failed }}곳</span></strong><p>미검증 후보 제외 · 자격·재고·잔여석은 공식 안내에서 확인하세요.</p></div></div>
    <section id="results" class="results" aria-labelledby="results-title" tabindex="-1" :aria-busy="loading"><div class="results-heading"><h2 id="results-title">{{ filters.status==='urgent'?'마감 임박 혜택':'발견한 혜택' }} <span aria-live="polite" aria-atomic="true">{{ results.length }}건</span></h2><div class="sort-field"><label for="sort" class="sr-only">혜택 정렬</label><select id="sort" v-model="filters.sort"><option value="deadline">마감 임박순</option><option value="verified">최근 확인순</option><option value="title">제목 가나다순</option></select></div></div>
      <div v-if="results.length" class="card-grid"><BenefitCard v-for="item in results" :key="item.source+'\n'+item.url" :item="item" :now="now" /></div>
      <div v-else-if="!loading" class="empty-state"><span class="empty-symbol" aria-hidden="true">⌕</span><h3>{{ all.length?'조건에 맞는 검증 항목이 없어요':state==='partial'?'현재 표시 가능한 검증 항목이 없어요':'확인된 목록이 준비되면 여기에 표시됩니다' }}</h3><p>{{ all.length?'다른 검색어나 지역·분야로 찾아보세요.':'개별 표시기한 경과 또는 검증 보류일 수 있습니다. 실제 혜택이 없거나 행사가 종료됐다는 뜻은 아닙니다.' }}</p><button v-if="active" type="button" class="primary-button" @click="reset">필터 초기화</button></div>
    </section>
    <section class="trust-section" aria-labelledby="trust-title"><div class="trust-intro"><p class="eyebrow">확인 가능한 정보, 명확한 한계</p><h2 id="trust-title">혜택의 근거까지 살펴보세요.</h2><p>공식 확인과 신청 자격은 별개입니다.<br>비용·최소 지출·결제 조건은 각 항목의 상세 조건과 원문을 확인하세요.</p></div><div class="collection-details"><details><summary>수집·검증 현황 <span>{{ data?.sources.length||0 }}개 출처</span></summary><div class="coverage-body"><p v-if="data">생성 {{ formatDate(data.generatedAt) }}<br>수집 기준 {{ formatDate(data.sourceReportAt) }}<br>파일 표시기한 {{ formatDate(data.validThrough) }}<br>{{ data.runLabel }}</p><p>재검증 대기 {{ data?.pending||0 }}건 · 화면 검증에서 제외 {{ data?.withheldCount||0 }}건</p><p>표시기한 경과는 행사 종료나 잔여석 소진과 다릅니다. 0건은 실제 혜택이 없다는 뜻이 아닙니다.</p><ul><li v-for="row in data?.sources||[]" :key="row.source"><strong>{{ row.name }}</strong><span>{{ coverageLabels[row.status]||'상태 미확인' }}</span><small v-if="row.scope">{{ row.scope }}</small></li></ul><h3 v-if="data?.districts.length">서울 자치구 수집 범위</h3><p>{{ data?.scope||'수집 범위 확인 필요' }}</p><ul><li v-for="row in data?.districts||[]" :key="row.name"><strong>{{ row.name }}</strong><span>{{ coverageLabels[row.status]||'상태 미확인' }}</span></li></ul></div></details><details class="interest-settings"><summary>관심 지역·분야 기억하기</summary><div class="coverage-body"><p>이 브라우저에만 저장합니다. 로그인이나 개인정보 입력이 필요하지 않습니다. 공유 링크의 필터가 우선하며, 저장값 삭제는 현재 검색 필터를 바꾸지 않습니다.</p><p>현재 선택: {{ filters.region || '전체 지역' }} · {{ filters.category || '전체 분야' }}</p><p v-if="remembered">저장한 관심 설정: {{ remembered.region || '전체 지역' }} · {{ remembered.category || '전체 분야' }}</p><p v-else>저장한 관심 설정이 없습니다.</p><div class="preference-actions"><button type="button" @click="remember">현재 지역·분야 저장</button><button v-if="remembered" type="button" @click="forget">저장값 삭제</button></div><p role="status" aria-live="polite">{{ preferenceNotice }}</p></div></details><p class="fine-print">검증 시각은 수집 시각과 다릅니다. 구 선택 시 전국·서울 공통 안내는 함께 포함하지 않습니다. 전체 지역·모든 혜택을 수집한 서비스가 아닙니다.</p></div></section>
  </main>
  <footer class="site-footer"><div class="container footer-inner"><div><strong>Benefit Monitor</strong><p>로그인 없이 발견하는 생활 혜택.</p></div><nav aria-label="데이터 내보내기"><a href="./briefing.json">공개 JSON ↗</a><a href="./briefing.md">텍스트 브리핑 ↗</a></nav><p class="cost-note">추가 유료 API·서버·분석기를 사용하지 않습니다. ChatGPT/Codex 및 기존 실행 환경의 요금은 이 프로젝트가 보장하지 않습니다.</p></div></footer>
</template>
