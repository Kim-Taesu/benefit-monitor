<script setup lang="ts">
import { computed, ref } from 'vue';
import { featuredRows, verdict, guideFor, wikiLink, won, CATEGORIES, BASIS_LABEL, KAMIS_SOURCE, EKAPE_SOURCE, type PriceRow, type FeaturedRow, type GroceryBundle, type WeeklyPick } from './groceries';
import GroceryCalc from './GroceryCalc.vue';
import { formatDate } from './benefits';
const props=defineProps<{bundle:GroceryBundle;weekly:WeeklyPick|null}>();
const PAGE=12,FEATURED='자주 사는 품목';
const bundle=computed(()=>props.bundle);
const q=ref(''),category=ref(FEATURED),cheapOnly=ref(false),shown=ref(PAGE);
const tabs=computed(()=>{
 const present=new Set((bundle.value?.rows??[]).map(r=>r.category));
 return [FEATURED,...CATEGORIES.filter(c=>present.has(c)),...(present.has('기타')?['기타']:[])];
});
const level=(r:PriceRow)=>verdict(r.current,r.normal,r.yearAgo);
const filtered=computed(()=>{
 const term=q.value.trim().toLowerCase(),all=bundle.value?.rows??[];
 const base=term?all.filter(r=>[r.name,r.detail,r.category].some(v=>v.toLowerCase().includes(term)))
  :category.value===FEATURED?featuredRows(all)
  // Within a category, frequently bought items first; the rest keep the official order (stable sort).
  :all.filter(r=>r.category===category.value).sort((a,b)=>(a.featured<0?1e9:a.featured)-(b.featured<0?1e9:b.featured));
 const rows=base.filter(r=>!cheapOnly.value||level(r)?.level==='cheap');
 // Cheapest against 평년 first when filtering for bargains; otherwise keep the official order.
 return cheapOnly.value?[...rows].sort((a,b)=>(level(a)?.pct??0)-(level(b)?.pct??0)):rows;
});
// 자주 사는 품목 shows every meat cut/grade and popular vegetable at once (user request 2026-11-09).
const paged=computed(()=>!!q.value.trim()||category.value!==FEATURED);
const visible=computed(()=>paged.value?filtered.value.slice(0,shown.value):filtered.value);
const md=(d:string|null)=>d?d.slice(5).replace('-','.'):'';
// 자주 사는 품목 folds a cut's other grades (or kinds, e.g. 동물복지 계란) into one line on its card.
function othersLine(r:PriceRow):string{
 const others=(r as Partial<FeaturedRow>).others??[];
 if(!others.length)return '';
 const word=others.every(o=>o.detail.endsWith('등급'))?'다른 등급':'다른 종류';
 return `${word}: ${others.map(o=>`${o.detail} ${won(o.current)}`).join(' · ')}`;
}
function pick(c:string){category.value=c;q.value='';shown.value=PAGE;}
</script>
<template>
  <section v-if="bundle" id="groceries" class="groceries" aria-labelledby="groceries-title">
    <div class="results-heading"><h2 id="groceries-title">장보기 시세 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}개</span></h2></div>
    <p class="festival-notice">{{ bundle.notice }}
      <template v-if="bundle.produceDate"> 농·수산물 {{ md(bundle.produceDate) }} 조사</template><template v-if="bundle.meatDate"> · 육류·계란 {{ md(bundle.meatDate) }} 조사</template>
      · 수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></p>
    <p v-if="bundle.missing.length" class="fine-print">일부 품목 미수집: {{ bundle.missing.join(', ') }}</p>
    <article v-if="weekly" class="grocery-pick" aria-labelledby="grocery-pick-title">
      <div class="card-meta"><h3 id="grocery-pick-title">이번 주 장보기 추천</h3><span class="grocery-badge" :class="weekly.source==='ai'?'ai':'normal'">{{ weekly.source==='ai'?'AI 작성':'자동 선정' }}</span></div>
      <p v-if="weekly.summary" class="grocery-pick-summary">{{ weekly.summary }}</p>
      <ul>
        <li v-for="p in weekly.picks" :key="p.row.kind+p.row.id">
          <strong>{{ p.row.name }}</strong> {{ won(p.row.current) }}<small> / {{ p.row.unit.replace(/^원\//,'') }}</small>
          <span v-if="level(p.row)" class="grocery-badge" :class="level(p.row)!.level">{{ level(p.row)!.label }}</span>
          <span v-if="p.menu" class="grocery-pick-menu">→ {{ p.menu }}</span>
        </li>
      </ul>
      <p class="fine-print">{{ weekly.source==='ai'?'AI가 공식 조사값 안에서 쓴 문장이에요. 문장 속 숫자와 품목은 공개 전에 코드가 원본과 대조했어요.':'평년보다 많이 싼 순서로 자동 선정했어요.' }}</p>
    </article>
    <div class="filter-row grocery-filters">
      <div class="filter-field grocery-search"><label for="grocery-q">품목 찾기</label><input id="grocery-q" v-model="q" type="search" placeholder="예: 양파, 삼겹살, 고등어" autocomplete="off" @input="shown=PAGE"></div>
      <div class="quick-filters"><button type="button" :aria-pressed="cheapOnly" @click="cheapOnly=!cheapOnly;shown=PAGE">평년보다 싼 것만</button></div>
    </div>
    <div class="quick-filters grocery-tabs" role="group" aria-label="부류">
      <button v-for="c in tabs" :key="c" type="button" :aria-pressed="!q.trim()&&category===c" @click="pick(c)">{{ c }}</button>
    </div>
    <p class="fine-print grocery-legend">배지: 평년(최근 5년 중 최고·최저 해를 뺀 3년 평균)보다 10% 이상 싸면 <span class="grocery-badge cheap">쌈</span>, 10% 이상 비싸면 <span class="grocery-badge pricey">비쌈</span>. 평년이 없으면 1년전과 비교해요. 육류는 2026-07 조사 방식 변경으로 평년이 없어 지역 범위로 보여줘요.</p>
    <div v-if="visible.length" class="card-grid">
      <article v-for="row in visible" :key="row.kind+row.id" class="benefit-card grocery-card">
        <div class="card-meta"><span class="category">{{ row.category }}</span><span v-if="level(row)" class="grocery-badge" :class="level(row)!.level">{{ level(row)!.label }}</span></div>
        <h3>{{ row.name }}<small v-if="row.detail"> {{ row.detail }}</small></h3>
        <p class="grocery-price"><strong>{{ won(row.current) }}</strong><span> / {{ row.unit.replace(/^원\//,'') }} · {{ row.currentLabel }}</span></p>
        <p v-if="row.kind==='produce'" class="grocery-compare">
          <span v-if="row.normal">평년 {{ won(row.normal) }}</span><span v-if="row.yearAgo">1년전 {{ won(row.yearAgo) }}</span><span v-if="row.weekAgo">1주전 {{ won(row.weekAgo) }}</span>
        </p>
        <p v-else-if="row.range" class="grocery-compare">
          <span>지역별 {{ won(row.range.min) }}({{ row.range.minRegion }}) ~ {{ won(row.range.max) }}({{ row.range.maxRegion }})</span><span v-if="row.seoul">서울 {{ won(row.seoul) }}</span>
        </p>
        <p v-if="othersLine(row)" class="grocery-compare grocery-others">{{ othersLine(row) }}</p>
        <details class="card-details">
          <summary>이 가격 싼가요? <span aria-hidden="true">+</span></summary>
          <div class="details-body"><GroceryCalc :row="row" /></div>
        </details>
        <details v-if="guideFor(row)" class="card-details">
          <summary>좋은 품질 · 고르는 법 <span aria-hidden="true">+</span></summary>
          <div class="details-body grocery-guide">
            <p v-if="guideFor(row)!.grade"><strong>등급 뜻</strong> {{ guideFor(row)!.grade }}</p>
            <p><strong>좋은 것</strong></p><ul><li v-for="g in guideFor(row)!.good" :key="g">{{ g }}</li></ul>
            <template v-if="guideFor(row)!.avoid?.length"><p><strong>피할 것</strong></p><ul><li v-for="g in guideFor(row)!.avoid" :key="g">{{ g }}</li></ul></template>
            <p v-if="guideFor(row)!.origin"><strong>국산 구별</strong> {{ guideFor(row)!.origin }}</p>
            <p v-if="guideFor(row)!.keep"><strong>보관</strong> {{ guideFor(row)!.keep }}</p>
            <p v-if="guideFor(row)!.tip"><strong>팁</strong> {{ guideFor(row)!.tip }}</p>
            <p class="fine-print">{{ BASIS_LABEL[guideFor(row)!.basis] }}<template v-if="guideFor(row)!.updated"> · 원문 수정 {{ guideFor(row)!.updated!.replaceAll('-','.') }}</template>
              <a v-if="wikiLink(guideFor(row)!)" :href="wikiLink(guideFor(row)!)!" target="_blank" rel="noopener noreferrer"> 카미위키 원문 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a></p>
          </div>
        </details>
        <a class="grocery-source" :href="row.kind==='meat'?EKAPE_SOURCE:KAMIS_SOURCE" target="_blank" rel="noopener noreferrer">출처 {{ row.kind==='meat'?'축산물품질평가원':'KAMIS' }} <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
      </article>
    </div>
    <div v-else class="empty-state"><h3>조건에 맞는 품목이 없어요</h3><p>다른 부류를 고르거나 검색어를 바꿔 보세요.</p></div>
    <button v-if="filtered.length>visible.length" type="button" class="festival-more" @click="shown+=PAGE">더 보기 ({{ filtered.length-visible.length }}개 남음)</button>
  </section>
</template>
