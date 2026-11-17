<script setup lang="ts">
import { computed, ref } from 'vue';
import { CALENDAR_PAGE, KIND_LABELS, badge, filterSubs, formatArea, formatPrice, groupByDay, isMine, kstDate, priceOne, specialSummary, timeline, tradeText, typeSplit } from './subscriptions';
import type { KindFilter, Subscription, SubscriptionBundle } from './subscriptions';
import { formatDate } from './benefits';
import { DISTRICTS } from './topics';
// 청약 탭(2026-11-17). 내 지역은 혜택 탭과 함께 쓰고(App이 기억한다), 검색어는 이 탭 것만.
const props=defineProps<{bundle:SubscriptionBundle;now:number}>();
const region=defineModel<string>('region',{default:''});
const area=ref<''|'서울'|'경기'>(''),kind=ref<KindFilter>(''),query=ref('');
const today=computed(()=>kstDate(props.now));
const byQuery=computed(()=>filterSubs(props.bundle.items,{area:'',kind:'',q:query.value}));
const areaCount=(a:'서울'|'경기')=>filterSubs(byQuery.value,{area:a,kind:kind.value,q:''}).length;
const kindCount=(k:KindFilter)=>filterSubs(byQuery.value,{area:area.value,kind:k,q:''}).length;
const filtered=computed(()=>filterSubs(byQuery.value,{area:area.value,kind:kind.value,q:''}));
// 카드마다 배지·단계를 한 번만 계산한다.
const groups=computed(()=>groupByDay(filtered.value,today.value,region.value)
 .map(g=>({...g,cards:g.items.map(i=>({i,badge:badge(i,today.value),steps:timeline(i,today.value),mine:isMine(i,region.value)}))})));
const KINDS=Object.entries(KIND_LABELS) as [Exclude<KindFilter,''>,string][];
const MARK={done:'✓',now:'●',next:'○'},SPOKEN={done:'지남',now:'진행 중',next:'예정'};
const TYPE_ROWS=3,open=ref(new Set<string>());
function toggle(id:string){const next=new Set(open.value);if(next.has(id))next.delete(id);else next.add(id);open.value=next;}
const md=(d:string)=>`${Number(d.slice(5,7))}/${Number(d.slice(8,10))}`;
function facts(i:Subscription){
 // 주택형 표가 있으면 표가 면적·금액을 보여 주므로 요약 줄은 세대수·공고일만.
 if(i.types.length)return [i.units?`총 ${i.units.toLocaleString('ko-KR')}세대`:null,i.noticeDate?`공고 ${md(i.noticeDate)}`:null].filter(Boolean).join(' · ');
 const price=formatPrice(i.priceMin,i.priceMax);
 return [i.units?`${i.units.toLocaleString('ko-KR')}세대`:null,formatArea(i.areaMin,i.areaMax),price?price+'*':null].filter(Boolean).join(' · ');
}
const hasSplit=(i:Subscription)=>i.types.some(t=>typeSplit(t));
const hasPyeong=(i:Subscription)=>i.types.some(t=>t.pyeong!==null);
const hasTrade=(i:Subscription)=>i.types.some(t=>t.trade);
function extra(i:Subscription){return [...i.regulation,i.moveIn?`입주 ${i.moveIn.replace('-','.')}`:null].filter(Boolean).join(' · ');}
</script>
<template>
  <section class="subs" aria-labelledby="subs-title">
    <div class="sec-title"><h2 id="subs-title">🏠 서울·경기 청약 일정 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}곳</span></h2></div>
    <p class="subs-lede">앞으로 {{ bundle.windowDays }}일 안에 접수하는 단지예요. 청약홈 일정을 옮겼고, 신청 자격·당첨 가능성은 확인하지 않았어요. <span class="subs-time">수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></span></p>
    <div class="tools festival-filters">
      <div class="field"><label for="subs-region">내 지역</label><select id="subs-region" v-model="region"><option value="">서울 전체</option><option v-for="d in DISTRICTS" :key="d">{{ d }}</option></select></div>
      <div class="field grow"><label for="subs-q">검색</label><input id="subs-q" v-model="query" type="search" maxlength="60" placeholder="단지명, 지역 (예: 분당)" autocomplete="off"></div>
    </div>
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
        <dt>무순위(사후접수) · 임의공급</dt><dd>청약 뒤 남거나 계약되지 않은 세대를 다시 모집해요. 청약통장이 필요 없는 경우가 많지만 거주지·무주택 조건은 공고마다 달라요.</dd>
        <dt>계약취소 재공급</dt><dd>계약이 취소된 세대를 다시 공급해요. 해당 지역 거주·무주택 같은 조건이 붙는 경우가 많아요.</dd>
        <dt>공고일(모집공고일)</dt><dd>거주지·무주택 여부 같은 자격은 보통 이 날짜를 기준으로 따져요.</dd>
        <dt>오피스텔·임대</dt><dd>아파트 청약과 접수 방식·자격이 달라요.</dd>
      </dl>
      <p class="fine-print">내가 신청할 수 있는지는 이 화면이 판단하지 않아요. 모집공고문에서 확인하세요.</p>
    </details>
    <template v-for="g in groups" :key="g.key">
      <h3 class="subs-day">{{ g.label }} <span>{{ g.items.length }}곳</span></h3>
      <ul class="subs-grid">
        <li v-for="{i,badge:b,steps,mine} in g.cards" :key="i.id" class="benefit-card subs-card" :class="{mine}">
          <p class="bcard-top"><span class="badge timing" :class="{urgent:b.tone==='urgent',soon:b.tone==='soon'}">{{ b.text }}</span><span class="badge supply-badge">{{ i.supply }}</span><span class="category">{{ i.district?`${i.area} ${i.district}`:i.area }}</span><span v-if="mine" class="badge mine-badge">📍 내 지역</span></p>
          <h4 class="subs-name">{{ i.name }}</h4>
          <p v-if="facts(i)" class="subs-facts">{{ facts(i) }}</p>
          <p v-else class="subs-facts muted">세대수·면적·금액은 공고에서 확인하세요</p>
          <table v-if="i.types.length" class="subs-types">
            <caption class="sr-only">{{ i.name }} 주택형별 면적과 분양가</caption>
            <thead><tr><th v-if="hasSplit(i)" scope="col">구분</th><th scope="col">전용㎡</th><th v-if="hasPyeong(i)" scope="col">평형</th><th scope="col">분양가*</th><th v-if="hasTrade(i)" scope="col">실거래†</th></tr></thead>
            <tbody><tr v-for="t in (open.has(i.id)?i.types:i.types.slice(0,TYPE_ROWS))" :key="t.label">
              <td v-if="hasSplit(i)">{{ typeSplit(t) }}</td><th scope="row">{{ t.label }}</th><td v-if="hasPyeong(i)">{{ t.pyeong!==null?t.pyeong+'평':'' }}</td><td class="price">{{ priceOne(t.price) }}</td><td v-if="hasTrade(i)" class="price trade"><template v-if="tradeText(t.trade)">{{ tradeText(t.trade)!.price }}<small>{{ tradeText(t.trade)!.note }}</small></template><template v-else>—</template></td>
            </tr></tbody>
          </table>
          <button v-if="i.types.length>TYPE_ROWS" type="button" class="link-button subs-more" :aria-expanded="open.has(i.id)" @click="toggle(i.id)">{{ open.has(i.id)?'접기':`주택형 ${i.types.length-TYPE_ROWS}개 더 보기` }}</button>
          <p v-if="i.types.length&&i.tradeStatus==='checked'&&!hasTrade(i)" class="subs-extra">같은 단지 최근 12개월 실거래 없음</p>
          <p v-if="i.specialKinds.length" class="subs-special">{{ specialSummary(i.specialKinds) }}</p>
          <ol class="subs-steps" aria-label="청약 단계">
            <li v-for="s in steps" :key="s.label" :class="s.state"><span aria-hidden="true">{{ MARK[s.state] }}</span>{{ s.label }} <b>{{ s.text }}</b><span class="sr-only"> ({{ SPOKEN[s.state] }})</span></li>
          </ol>
          <p v-if="extra(i)" class="subs-extra">{{ extra(i) }}</p>
          <div class="subs-links">
            <a v-if="i.noticePdf" class="official-link" :href="i.noticePdf" target="_blank" rel="noopener noreferrer">모집공고문 PDF <small>자격·전매·실거주</small> <span aria-hidden="true">↓</span><span class="sr-only"> (파일 내려받기, {{ i.name }})</span></a>
            <a class="official-link" :href="i.url" target="_blank" rel="noopener noreferrer">{{ i.url===CALENDAR_PAGE?'청약홈 달력에서 보기':'청약홈 공고 보기' }} <span aria-hidden="true">↗</span><span class="sr-only"> (새 창, {{ i.name }})</span></a>
          </div>
        </li>
      </ul>
    </template>
    <div v-if="!groups.length" class="empty-state"><h3>{{ bundle.items.length?'조건에 맞는 단지가 없어요':`앞으로 ${bundle.windowDays}일 안에 서울·경기 접수 일정이 없어요` }}</h3><p>{{ bundle.items.length?'지역이나 종류, 검색어를 바꿔 보세요.':'0곳은 청약이 없다는 뜻일 수도, 수집 범위 밖이라는 뜻일 수도 있어요.' }}</p><a class="official-link" :href="CALENDAR_PAGE" target="_blank" rel="noopener noreferrer">청약홈 달력 보기 <span aria-hidden="true">↗</span></a></div>
    <p class="fine-print">* 분양가는 주택형별 최고가 기준이고, 평형은 공급면적÷3.3058(소수점 버림)이에요. 층·호별 금액, 거주지·무주택·청약통장 조건, 전매제한·실거주의무, 계약금 일정은 모집공고문에서 확인하세요. † 실거래는 국토교통부 실거래가(공공데이터포털)에서 같은 단지·같은 전용면적(㎡ 정수)의 최근 12개월 거래 중 가장 최근 1건이에요(해제 거래 제외, 계약월 기준, 법적 효력 없는 참고용). 주변 단지 시세로 대신하지 않고, 경쟁률은 보여 주지 않아요. 무순위·오피스텔 공고는 청약홈에서 바로 열리지 않아 달력으로 연결해요.</p>
  </section>
</template>
