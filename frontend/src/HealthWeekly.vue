<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { weeklyPicks, type HealthBundle, type HealthKind } from './health';
const props=defineProps<{bundle:HealthBundle;district:string;today:string}>();
const SHOW=4;
const picks=computed(()=>weeklyPicks(props.bundle,props.today));
const kind=ref<HealthKind|''>(''),expanded=ref(false);
watch(()=>[props.district,kind.value],()=>{expanded.value=false;});
const rows=computed(()=>picks.value.districts.filter(d=>(!props.district||d.district===props.district)&&(!kind.value||d.kinds.includes(kind.value))));
const shown=computed(()=>expanded.value?rows.value:rows.value.slice(0,SHOW));
</script>
<template>
  <section v-if="picks.districts.length" class="health-weekly" aria-labelledby="health-weekly-title">
    <h3 id="health-weekly-title">이번 주 보건소 추천</h3>
    <p v-if="picks.hasSummary" class="fine-print"><span class="health-ai">AI 작성</span>AI가 공식 페이지를 요약했습니다. 대상·기간·비용은 원문에서 확인하세요.</p>
    <p v-else class="fine-print">공식 페이지 링크입니다. 대상·기간·비용은 원문에서 확인하세요.</p>
    <div v-if="picks.kinds.length" class="quick-filters health-weekly-kinds" aria-label="사업 종류">
      <button v-for="k in picks.kinds" :key="k.key" type="button" :aria-pressed="kind===k.key" @click="kind=kind===k.key?'':k.key">{{ k.label }} {{ k.districts }}개 구</button>
    </div>
    <div v-for="d in shown" :key="d.district" class="health-weekly-district">
      <div class="health-weekly-head"><strong>{{ d.district }}</strong><span v-if="d.newNotices" class="health-badge">새 공지 {{ d.newNotices }}건</span></div>
      <ul>
        <li v-for="p in d.programs" :key="p.url">
          <a :href="p.url" target="_blank" rel="noopener noreferrer">{{ p.name }}<span class="sr-only"> (새 창, {{ p.center }})</span></a>
          <p v-if="p.summary" class="health-note"><span class="health-ai">AI 작성</span>{{ p.summary }}</p>
        </li>
      </ul>
      <small v-if="d.more>0" class="health-weekly-more">외 {{ d.more }}곳</small>
    </div>
    <p v-if="!rows.length" class="health-weekly-empty">조건에 맞는 구가 없어요</p>
    <button v-if="rows.length>SHOW&&!expanded" type="button" class="festival-more" @click="expanded=true">구 더 보기 ({{ rows.length-SHOW }}곳 남음)</button>
  </section>
</template>
