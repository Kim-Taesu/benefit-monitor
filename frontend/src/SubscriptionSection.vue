<script setup lang="ts">
import { computed, ref } from 'vue';
import { CALENDAR_PAGE, KIND_LABELS, badge, filterSubs, formatArea, formatPrice, groupByDay, isMine, kstDate, timeline } from './subscriptions';
import type { KindFilter, Subscription, SubscriptionBundle } from './subscriptions';
import { formatDate } from './benefits';
// 혜택 탭 안의 청약 일정(2026-11-17). 검색어와 내 지역은 혜택 탭의 것을 그대로 쓴다.
const props=defineProps<{bundle:SubscriptionBundle;now:number;region:string;query:string}>();
const area=ref<''|'서울'|'경기'>(''),kind=ref<KindFilter>('');
const today=computed(()=>kstDate(props.now));
const byQuery=computed(()=>filterSubs(props.bundle.items,{area:'',kind:'',q:props.query}));
const areaCount=(a:'서울'|'경기')=>filterSubs(byQuery.value,{area:a,kind:kind.value,q:''}).length;
const kindCount=(k:KindFilter)=>filterSubs(byQuery.value,{area:area.value,kind:k,q:''}).length;
const filtered=computed(()=>filterSubs(byQuery.value,{area:area.value,kind:kind.value,q:''}));
// 카드마다 배지·단계를 한 번만 계산한다.
const groups=computed(()=>groupByDay(filtered.value,today.value,props.region)
 .map(g=>({...g,cards:g.items.map(i=>({i,badge:badge(i,today.value),steps:timeline(i,today.value),mine:isMine(i,props.region)}))})));
const KINDS=Object.entries(KIND_LABELS) as [Exclude<KindFilter,''>,string][];
const MARK={done:'✓',now:'●',next:'○'},SPOKEN={done:'지남',now:'진행 중',next:'예정'};
function facts(i:Subscription){
 const price=formatPrice(i.priceMin,i.priceMax);
 return [i.units?`${i.units.toLocaleString('ko-KR')}세대`:null,formatArea(i.areaMin,i.areaMax),price?price+'*':null].filter(Boolean).join(' · ');
}
function extra(i:Subscription){return [...i.regulation,i.moveIn?`입주 ${i.moveIn.replace('-','.')}`:null].filter(Boolean).join(' · ');}
</script>
<template>
  <section class="subs" aria-labelledby="subs-title">
    <div class="sec-title"><h2 id="subs-title">🏠 서울·경기 청약 일정 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}곳</span></h2></div>
    <p class="subs-lede">앞으로 {{ bundle.windowDays }}일 안에 접수하는 단지예요. 청약홈 일정을 옮겼고, 신청 자격·당첨 가능성은 확인하지 않았어요. <span class="subs-time">수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></span></p>
    <div class="chips" role="group" aria-label="지역 고르기">
      <button type="button" class="chip" :aria-pressed="area===''" @click="area=''">서울·경기<small>{{ areaCount('서울')+areaCount('경기') }}</small></button>
      <button v-for="a in (['서울','경기'] as const)" :key="a" type="button" class="chip" :aria-pressed="area===a" @click="area=area===a?'':a">{{ a }}<small>{{ areaCount(a) }}</small></button>
    </div>
    <div class="chips" role="group" aria-label="주택 종류 고르기">
      <button v-for="[k,label] in KINDS" :key="k" type="button" class="chip" :aria-pressed="kind===k" @click="kind=kind===k?'':k">{{ label }}<small>{{ kindCount(k) }}</small></button>
    </div>
    <details class="subs-glossary">
      <summary>특별공급·1순위·무순위가 뭐예요?</summary>
      <dl>
        <dt>특별공급</dt><dd>신혼부부·다자녀·생애최초·노부모 부양처럼 정해진 대상만 신청하는 물량이에요.</dd>
        <dt>1순위 · 2순위</dt><dd>일반공급 접수 순서예요. 순위 조건(청약통장 가입 기간·납입 횟수 등)은 공고마다 달라요.</dd>
        <dt>무순위·잔여</dt><dd>계약되지 않았거나 남은 세대를 다시 모집해요. 신청 자격은 공고마다 달라요.</dd>
        <dt>오피스텔·임대</dt><dd>아파트 청약과 접수 방식·자격이 달라요.</dd>
      </dl>
      <p class="fine-print">내가 신청할 수 있는지는 이 화면이 판단하지 않아요. 모집공고문에서 확인하세요.</p>
    </details>
    <template v-for="g in groups" :key="g.key">
      <h3 class="subs-day">{{ g.label }} <span>{{ g.items.length }}곳</span></h3>
      <ul class="subs-grid">
        <li v-for="{i,badge:b,steps,mine} in g.cards" :key="i.id" class="benefit-card subs-card" :class="{mine}">
          <p class="bcard-top"><span class="badge timing" :class="{urgent:b.tone==='urgent',soon:b.tone==='soon'}">{{ b.text }}</span><span class="category">{{ i.district?`${i.area} ${i.district}`:i.area }}</span><span v-if="mine" class="badge mine-badge">📍 내 지역</span></p>
          <h4 class="subs-name">{{ i.name }}</h4>
          <p v-if="facts(i)" class="subs-facts">{{ facts(i) }}</p>
          <p v-else class="subs-facts muted">세대수·면적·금액은 공고에서 확인하세요</p>
          <ol class="subs-steps" aria-label="청약 단계">
            <li v-for="s in steps" :key="s.label" :class="s.state"><span aria-hidden="true">{{ MARK[s.state] }}</span>{{ s.label }} <b>{{ s.text }}</b><span class="sr-only"> ({{ SPOKEN[s.state] }})</span></li>
          </ol>
          <p v-if="extra(i)" class="subs-extra">{{ extra(i) }}</p>
          <a class="official-link" :href="i.url" target="_blank" rel="noopener noreferrer">{{ i.url===CALENDAR_PAGE?'청약홈 달력에서 보기':'청약홈 공고 보기' }} <span aria-hidden="true">↗</span><span class="sr-only"> (새 창, {{ i.name }})</span></a>
        </li>
      </ul>
    </template>
    <div v-if="!groups.length" class="empty-state"><h3>{{ bundle.items.length?'조건에 맞는 단지가 없어요':`앞으로 ${bundle.windowDays}일 안에 서울·경기 접수 일정이 없어요` }}</h3><p>{{ bundle.items.length?'지역이나 종류, 검색어를 바꿔 보세요.':'0곳은 청약이 없다는 뜻일 수도, 수집 범위 밖이라는 뜻일 수도 있어요.' }}</p><a class="official-link" :href="CALENDAR_PAGE" target="_blank" rel="noopener noreferrer">청약홈 달력 보기 <span aria-hidden="true">↗</span></a></div>
    <p class="fine-print">* 금액은 주택형별 최고가 기준이에요. 층·호별 금액, 신청 자격, 경쟁률은 모집공고문에서 확인하세요. 무순위·오피스텔 공고는 청약홈에서 바로 열리지 않아 달력으로 연결해요.</p>
  </section>
</template>
