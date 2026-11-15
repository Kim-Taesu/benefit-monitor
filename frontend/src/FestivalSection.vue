<script setup lang="ts">
import { computed, ref } from 'vue';
import { parseFestivals, festivalStatus, festivalPeriod, festivalFees, provinces } from './festivals';
import { formatDate } from './benefits';
import { parseFestivalPick } from './picks';
const props=defineProps<{raw:unknown;now:number;query:string}>();
const PAGE=12;
const bundle=computed(()=>parseFestivals(props.raw,props.now));
const province=ref(''),status=ref<''|'ongoing'|'upcoming'|'pick'>(''),shown=ref(PAGE);
// 이번 주말 추천: 줄마다 카드에 붙이고, 요약 문장은 목록 위에 한 번 보인다. 요금으로 거르거나 순서를 바꾸지 않는다.
const pick=computed(()=>bundle.value?parseFestivalPick(props.raw,bundle.value):null);
const pickOf=computed(()=>new Map((pick.value?.picks||[]).map(p=>[p.festival.id,p.line])));
const regions=computed(()=>provinces(bundle.value?.items??[]));
const filtered=computed(()=>{
 const q=props.query.trim().toLowerCase();
 return (bundle.value?.items??[]).filter(item=>{
  const s=festivalStatus(item,props.now);
  if(province.value&&item.province!==province.value)return false;
  if(status.value==='pick'){if(!pickOf.value.has(item.id))return false;}
  else if(status.value&&(status.value==='ongoing')!==s.ongoing)return false;
  return !q||[item.name,item.region,item.place,item.organizer,item.summary,item.programs].some(v=>v.toLowerCase().includes(q));
 });
});
const visible=computed(()=>filtered.value.slice(0,shown.value));
function setStatus(value:''|'ongoing'|'upcoming'|'pick'){status.value=status.value===value?'':value;shown.value=PAGE;}
</script>
<template>
  <section v-if="bundle" id="festivals" class="festivals panel" aria-labelledby="festivals-title">
    <div class="sec-title"><h2 id="festivals-title">전국 축제 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}건</span></h2></div>
    <p class="festival-notice">{{ bundle.notice }} 수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></p>
    <div class="tools festival-filters">
      <div class="field"><label for="festival-region">시·도</label><select id="festival-region" v-model="province" @change="shown=PAGE"><option value="">전국</option><option v-for="name in regions" :key="name">{{ name }}</option></select></div>
    </div>
    <div class="chips" role="group" aria-label="축제 개최 상태">
      <button type="button" class="chip" :aria-pressed="status===''" @click="status='';shown=PAGE">전체</button>
      <button type="button" class="chip" :aria-pressed="status==='ongoing'" @click="setStatus('ongoing')">개최중</button>
      <button type="button" class="chip" :aria-pressed="status==='upcoming'" @click="setStatus('upcoming')">개최예정</button>
      <button v-if="pick" type="button" class="chip" :aria-pressed="status==='pick'" @click="setStatus('pick')">이번 주말 추천<small>{{ pick.picks.length }}</small></button>
    </div>
    <p v-if="query.trim()" class="fine-print festival-query">위 검색어 "{{ query.trim() }}"도 함께 적용됩니다.</p>
    <div v-if="pick?.summary&&!status&&!province" class="lead festival-pick"><span class="badge ai">🤖 AI 작성</span><div><p class="pick-summary">{{ pick.summary }}</p><p class="fine-print">AI가 공개 정보 안에서 쓴 문장이에요. 날짜·요금은 공개 전에 코드가 원본과 대조했어요.</p></div></div>
    <p v-else-if="pick&&pick.source==='rule'&&!province" class="fine-print festival-pick-note">추천 표시는 수도권 먼저, 가까운 날짜 순으로 자동 선정했어요.</p>
    <div v-if="visible.length" class="card-grid">
      <article v-for="item in visible" :key="item.id" class="benefit-card festival-card bcard">
        <p class="bcard-top"><span class="category">{{ item.culture_tourism?'문화관광축제':'축제' }}</span><span class="badge timing" :class="{urgent:festivalStatus(item,now).ongoing}">{{ festivalStatus(item,now).label }}</span><span v-if="pickOf.has(item.id)" class="badge pick-badge" :class="pick!.source==='ai'&&pickOf.get(item.id)?'ai':''">{{ pick!.source==='ai'&&pickOf.get(item.id)?'AI 작성':'자동 선정' }}</span></p>
        <h3 class="bcard-title">{{ item.name }}</h3>
        <p v-if="pickOf.get(item.id)" class="bcard-lead pick-line">{{ pickOf.get(item.id) }}</p>
        <p class="bcard-facts">{{ festivalPeriod(item) }}<span aria-hidden="true"> · </span>{{ item.region||'지역 미확인' }}<span aria-hidden="true"> · </span>{{ festivalFees[item.fee_status] }}</p>
        <p v-if="item.fee_text&&item.fee_text!==festivalFees[item.fee_status]" class="festival-fee">요금: {{ item.fee_text }}</p>
        <p v-if="item.discount" class="festival-fee">할인: {{ item.discount }}</p>
        <details v-if="item.summary||item.programs||item.place||item.organizer" class="card-details">
          <summary>축제 소개 <span aria-hidden="true">+</span></summary>
          <div class="details-body">
            <p v-if="item.organizer">주최: {{ item.organizer }}</p>
            <p v-if="item.place">장소: {{ item.place }}</p>
            <p v-if="item.summary" class="full-conditions">{{ item.summary }}</p>
            <p v-if="item.programs" class="full-conditions">프로그램: {{ item.programs }}</p>
            <p v-if="item.modified" class="fine-print">관광공사 정보 수정일 {{ item.modified.replaceAll('-','.') }}</p>
          </div>
        </details>
        <p class="festival-links"><a class="official-link" :href="item.url" target="_blank" rel="noopener noreferrer">대한민국 구석구석 안내 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
        <a v-if="item.homepage" class="festival-homepage" :href="item.homepage" target="_blank" rel="noopener noreferrer nofollow">축제 홈페이지 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창, 외부 사이트)</span></a></p>
      </article>
    </div>
    <div v-else class="empty-state"><h3>조건에 맞는 축제가 없어요</h3><p>시·도나 개최 상태를 바꿔 보세요.</p></div>
    <button v-if="filtered.length>visible.length" type="button" class="festival-more" @click="shown+=PAGE">축제 더 보기 ({{ filtered.length-visible.length }}건 남음)</button>
  </section>
</template>
