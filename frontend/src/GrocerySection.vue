<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue';
import GroceryQuickCheck from './GroceryQuickCheck.vue';
import PickCard from './PickCard.vue';
import { featuredRows, verdict, guideFor, wikiLink, won, foodEmoji, CATEGORY_EMOJI, GROCERY_EMOJI_FALLBACK, CATEGORIES, BASIS_LABEL, KAMIS_SOURCE, EKAPE_SOURCE, type PriceRow, type BasketItem, quickMatch, type FeaturedRow, type GroceryBundle, type WeeklyPick, type DiscountLink } from './groceries';
import GroceryCalc from './GroceryCalc.vue';
import { formatDate } from './benefits';
const props=defineProps<{bundle:GroceryBundle;weekly:WeeklyPick|null;basket?:BasketItem[];discounts?:DiscountLink[]}>();
const emit=defineEmits<{more:[]}>();
const basketItems=computed(()=>props.basket??[]);
const PAGE=12,FEATURED='자주 사는 품목';
const bundle=computed(()=>props.bundle);
const q=ref(''),category=ref(FEATURED),cheapOnly=ref(false),shown=ref(PAGE),sort=ref<'cheap'|'official'>('cheap');
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
 // 기본은 평년(없으면 1년전)보다 많이 싼 순(2026-11-15 승인). 비교값이 없는 품목은 공식 순서대로 뒤에 둔다.
 return sort.value==='cheap'?[...rows].sort((a,b)=>(level(a)?.pct??1e9)-(level(b)?.pct??1e9)):rows;
});
// 한 줄 목록: 누른 품목만 비교·계산·고르는 법을 펼친다.
const opened=ref(new Set<string>());
const rowKey=(r:PriceRow)=>r.kind+r.id;
function toggle(r:PriceRow){const next=new Set(opened.value),k=rowKey(r);if(next.has(k))next.delete(k);else next.add(k);opened.value=next;}
const tabLabel=(c:string)=>c===FEATURED?c:(CATEGORY_EMOJI[c]??GROCERY_EMOJI_FALLBACK)+' '+c;
const unitOf=(r:PriceRow)=>r.unit.replace(/^원\//,'');
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
const inBasket=computed(()=>!!quickMatch(q.value,basketItems.value));
// Without a basket (baselines missing/stale) we cannot claim an item is outside it.
const showNotInBasket=computed(()=>!!q.value.trim()&&basketItems.value.length>0&&!inBasket.value);
// The card shows only when the best basket match has a row today (same rule as GroceryQuickCheck).
const quickKey=computed(()=>{
 const hit=quickMatch(q.value,basketItems.value);
 return hit&&bundle.value?.rows.some(r=>r.kind+r.id===hit.best.rowKey)?hit.best.rowKey:'';
});
// Bring the search field to the top once when the card first appears (or its best item changes), not on every keystroke.
watch(quickKey,k=>{if(k)nextTick(()=>document.querySelector('.grocery-filters')?.scrollIntoView({block:'start'}));});
function pickName(name:string){q.value=name;shown.value=PAGE;nextTick(()=>document.getElementById('grocery-q')?.focus());}
function pick(c:string){category.value=c;q.value='';shown.value=PAGE;}
</script>
<template>
  <section v-if="bundle" id="groceries" class="groceries panel" aria-labelledby="groceries-title">
    <div class="sec-title"><h2 id="groceries-title">장보기 시세 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}개</span></h2></div>
    <p class="festival-notice">{{ bundle.notice }}
      <template v-if="bundle.produceDate"> 농·수산물 {{ md(bundle.produceDate) }} 조사</template><template v-if="bundle.meatDate"> · 육류·계란 {{ md(bundle.meatDate) }} 조사</template>
      · 수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></p>
    <p v-if="bundle.missing.length" class="fine-print">⚠️ 일부 품목 미수집: {{ bundle.missing.join(', ') }}</p>
    <div class="tools grocery-filters">
      <div class="field grow grocery-search"><label for="grocery-q">품목 찾기</label><input id="grocery-q" v-model="q" type="search" placeholder="예: 양파, 삼겹살, 고등어" autocomplete="off" @input="shown=PAGE"></div>
      <div class="field"><label for="grocery-sort">정렬</label><select id="grocery-sort" v-model="sort"><option value="cheap">많이 싼 순</option><option value="official">분류 순</option></select></div>
    </div>
    <GroceryQuickCheck :q="q" :basket="basketItems" :rows="bundle.rows" :produce-date="bundle.produceDate" :meat-date="bundle.meatDate" :discounts="discounts" @pick="pickName" @more="emit('more')" />
    <PickCard v-if="weekly" id="grocery-pick" class="grocery-pick" title="이번 주 장보기 추천" :source="weekly.source" :summary="weekly.summary" :count="weekly.picks.length" v-slot="{limit}"
      :note="weekly.source==='ai'?'AI가 공식 조사값 안에서 쓴 문장이에요. 문장 속 숫자와 품목은 공개 전에 코드가 원본과 대조했어요.':'평년보다 많이 싼 순서로 자동 선정했어요.'">
      <ul class="pick-list pick-tiles">
        <li v-for="p in weekly.picks.slice(0,limit)" :key="p.row.kind+p.row.id">
          <strong><span aria-hidden="true">{{ foodEmoji(p.row.name,p.row.category) }}</span> {{ p.row.name }}</strong> <span class="pick-price">{{ won(p.row.current) }}<small> / {{ unitOf(p.row) }}</small></span>
          <span v-if="level(p.row)" class="grocery-badge" :class="level(p.row)!.level">{{ level(p.row)!.label }}</span>
          <span v-if="p.menu" class="pick-line">→ {{ p.menu }}</span>
        </li>
      </ul>
    </PickCard>
    <div class="chips grocery-tabs" role="group" aria-label="부류">
      <button type="button" class="chip" :aria-pressed="cheapOnly" @click="cheapOnly=!cheapOnly;shown=PAGE">평년보다 싼 것만</button>
      <button v-for="c in tabs" :key="c" type="button" class="chip" :aria-pressed="!q.trim()&&category===c" @click="pick(c)">{{ tabLabel(c) }}</button>
    </div>
    <div v-if="visible.length" class="grocery-list">
      <div class="grocery-list-head" aria-hidden="true"><span>품목</span><span>비교</span><span>가격</span><span>평년 대비</span></div>
      <article v-for="row in visible" :key="rowKey(row)" class="grocery-card grocery-row" :class="{open:opened.has(rowKey(row))}">
        <h3><button type="button" class="grocery-toggle" :aria-expanded="opened.has(rowKey(row))" @click="toggle(row)"><span aria-hidden="true">{{ foodEmoji(row.name,row.category) }}</span> {{ row.name }}<small v-if="row.detail"> {{ row.detail }}</small></button></h3>
        <p v-if="row.kind==='produce'" class="grocery-compare">
          <span v-if="row.normal">평년 {{ won(row.normal) }}</span><span v-if="row.yearAgo">1년전 {{ won(row.yearAgo) }}</span><span v-if="row.weekAgo">1주전 {{ won(row.weekAgo) }}</span>
        </p>
        <p v-else-if="row.range" class="grocery-compare">
          <span>지역별 {{ won(row.range.min) }}({{ row.range.minRegion }}) ~ {{ won(row.range.max) }}({{ row.range.maxRegion }})</span><span v-if="row.seoul">서울 {{ won(row.seoul) }}</span>
        </p>
        <p v-else class="grocery-compare"></p>
        <p class="grocery-price"><strong>{{ won(row.current) }}</strong><span> / {{ unitOf(row) }}</span><time class="grocery-asof" :datetime="row.priceDate">{{ md(row.priceDate) }} 기준</time></p>
        <p class="grocery-verdict"><span v-if="level(row)" class="grocery-badge" :class="level(row)!.level">{{ level(row)!.label }}</span></p>
        <span class="grocery-chevron" aria-hidden="true">+</span>
        <div v-if="opened.has(rowKey(row))" class="grocery-more">
          <p class="fine-print">{{ row.category }} · {{ row.currentLabel }} 가격</p>
          <p v-if="othersLine(row)" class="grocery-compare grocery-others">{{ othersLine(row) }}</p>
          <section><h4>매장 가격과 비교</h4><GroceryCalc :row="row" /></section>
          <section v-if="guideFor(row)" class="grocery-guide"><h4>좋은 품질 · 고르는 법</h4>
            <p v-if="guideFor(row)!.grade"><strong>등급 뜻</strong> {{ guideFor(row)!.grade }}</p>
            <p><strong>좋은 것</strong></p><ul><li v-for="g in guideFor(row)!.good" :key="g">{{ g }}</li></ul>
            <template v-if="guideFor(row)!.avoid?.length"><p><strong>피할 것</strong></p><ul><li v-for="g in guideFor(row)!.avoid" :key="g">{{ g }}</li></ul></template>
            <p v-if="guideFor(row)!.origin"><strong>국산 구별</strong> {{ guideFor(row)!.origin }}</p>
            <p v-if="guideFor(row)!.keep"><strong>보관</strong> {{ guideFor(row)!.keep }}</p>
            <p v-if="guideFor(row)!.tip"><strong>팁</strong> {{ guideFor(row)!.tip }}</p>
            <p class="fine-print">{{ BASIS_LABEL[guideFor(row)!.basis] }}<template v-if="guideFor(row)!.updated"> · 원문 수정 {{ guideFor(row)!.updated!.replaceAll('-','.') }}</template>
              <a v-if="wikiLink(guideFor(row)!)" :href="wikiLink(guideFor(row)!)!" target="_blank" rel="noopener noreferrer"> 카미위키 원문 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a></p>
          </section>
          <a class="grocery-source" :href="row.kind==='meat'?EKAPE_SOURCE:KAMIS_SOURCE" target="_blank" rel="noopener noreferrer">출처 {{ row.kind==='meat'?'축산물품질평가원':'KAMIS' }} <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
        </div>
      </article>
    </div>
    <div v-else-if="!quickKey" class="empty-state"><h3>조건에 맞는 품목이 없어요</h3><p>다른 부류를 고르거나 검색어를 바꿔 보세요.</p><p v-if="showNotInBasket">아직 자주 사는 품목에 없어요</p></div>
    <button v-if="filtered.length>visible.length" type="button" class="festival-more" @click="shown+=PAGE">더 보기 ({{ filtered.length-visible.length }}개 남음)</button>
    <p class="fine-print grocery-legend">평년(최근 5년 중 최고·최저 해를 뺀 3년 평균)보다 10% 이상 싸면 <span class="grocery-badge cheap">쌈</span>, 10% 이상 비싸면 <span class="grocery-badge pricey">비쌈</span>. 평년이 없으면 1년전과 비교해요. 육류는 2026-07 조사 방식 변경으로 평년이 없어 지역 범위로 보여줘요.</p>
  </section>
</template>
