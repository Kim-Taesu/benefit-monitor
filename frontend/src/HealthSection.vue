<script setup lang="ts">
import { computed, ref } from 'vue';
import { parseHealth, filterHealth, boardStatus } from './health';
import { formatDate } from './benefits';
const props=defineProps<{raw:unknown;now:number}>();
const PAGE=20;
const bundle=computed(()=>parseHealth(props.raw,props.now));
const district=ref(''),hintOnly=ref(false),query=ref(''),shown=ref(PAGE);
const filtered=computed(()=>filterHealth(bundle.value?.items??[],district.value,hintOnly.value,query.value));
const visible=computed(()=>filtered.value.slice(0,shown.value));
const hints=computed(()=>(bundle.value?.items??[]).filter(i=>i.hint&&(!district.value||i.district===district.value)).length);
const selectedBoard=computed(()=>bundle.value?.boards.find(b=>b.district===district.value)??null);
const others=computed(()=>(bundle.value?.boards??[]).filter(b=>b.status!=='checked'));
const md=(d:string)=>`${Number(d.slice(5,7))}/${Number(d.slice(8,10))}`;
</script>
<template>
  <section v-if="bundle" id="health" class="festivals health" aria-labelledby="health-title">
    <div class="results-heading"><h2 id="health-title">보건소 공지 <span aria-live="polite" aria-atomic="true">{{ filtered.length }}건</span></h2></div>
    <p class="festival-notice">{{ bundle.notice }} 수집 <time :datetime="bundle.fetchedAt">{{ formatDate(bundle.fetchedAt) }}</time></p>
    <div class="filter-row festival-filters">
      <div class="filter-field"><label for="health-district">지역</label><select id="health-district" v-model="district" @change="shown=PAGE"><option value="">전체</option><option v-for="b in bundle.boards" :key="b.district" :value="b.district">{{ b.district }}{{ b.status==='checked'?'':' (자동 수집 안 됨)' }}</option></select></div>
      <div class="quick-filters" aria-label="공지 종류"><button type="button" :aria-pressed="hintOnly" @click="hintOnly=!hintOnly;shown=PAGE">검진·접종·프로그램만 <span>{{ hints }}</span></button></div>
      <div class="filter-field health-search"><label for="health-q">검색</label><input id="health-q" v-model="query" type="search" maxlength="100" placeholder="예: 검진, 독감, 치매" autocomplete="off" @input="shown=PAGE"></div>
    </div>
    <p class="fine-print">"검진·접종·프로그램" 표시는 제목 단어만 본 것입니다. 무료 여부·대상·기간은 원문에서 확인하세요. 확인된 건은 혜택 탭에 카드로 올라갑니다.</p>
    <div v-if="selectedBoard&&selectedBoard.status!=='checked'" class="notice warning health-board-note" role="status"><span aria-hidden="true">!</span><div><strong>{{ selectedBoard.name }}: {{ boardStatus[selectedBoard.status] }}</strong><p>{{ selectedBoard.reason }}<template v-if="selectedBoard.count"> · 마지막으로 받은 공지 {{ selectedBoard.count }}건을 보여줍니다.</template></p><a class="official-link" :href="selectedBoard.homeUrl" target="_blank" rel="noopener noreferrer">{{ selectedBoard.name }} 바로가기 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a></div></div>
    <ul v-if="visible.length" class="health-list">
      <li v-for="item in visible" :key="item.district+item.id" class="health-row" :class="{hint:item.hint}">
        <div class="health-meta"><span class="category">{{ item.district }}</span><time :datetime="item.date">{{ md(item.date) }}</time><span v-if="item.hint" class="health-badge">검진·접종·프로그램</span></div>
        <a :href="item.url" target="_blank" rel="noopener noreferrer" class="health-title">{{ item.title }}<span class="sr-only"> (새 창, {{ item.center }} 원문)</span></a>
        <small>{{ item.center }}<template v-if="item.dept"> · {{ item.dept }}</template></small>
      </li>
    </ul>
    <div v-else-if="!(selectedBoard&&selectedBoard.status!=='checked')" class="empty-state"><h3>조건에 맞는 공지가 없어요</h3><p>지역이나 검색어를 바꿔 보세요. 최근 60일 공지만 보여줍니다.</p></div>
    <button v-if="filtered.length>visible.length" type="button" class="festival-more" @click="shown+=PAGE">공지 더 보기 ({{ filtered.length-visible.length }}건 남음)</button>
    <details class="card-details health-coverage">
      <summary>자동 수집이 안 되는 보건소 {{ others.length }}곳 <span aria-hidden="true">+</span></summary>
      <div class="details-body">
        <p class="fine-print">사이트가 자동 수집을 막았거나(robots) 보안 연결·접속 확인 화면 때문에 가져오지 않습니다. 우회하지 않고 바로가기만 둡니다.</p>
        <ul><li v-for="b in others" :key="b.district"><a :href="b.homeUrl" target="_blank" rel="noopener noreferrer">{{ b.name }} <span aria-hidden="true">↗</span></a> — {{ boardStatus[b.status] }}<template v-if="b.reason"> ({{ b.reason }})</template></li></ul>
      </div>
    </details>
  </section>
  <p v-else class="empty-state">이번 실행에서 보건소 공지를 가져오지 못했어요.</p>
</template>
