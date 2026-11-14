<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import PickCard from './PickCard.vue';
import { weeklyPicks, type HealthBundle, type HealthKind } from './health';
const props=defineProps<{bundle:HealthBundle;district:string;today:string}>();
const SHOW=3;
const kind=ref<HealthKind|''>(''),expanded=ref(false);
const picks=computed(()=>weeklyPicks(props.bundle,props.today,kind.value));
watch(()=>[props.district,kind.value],()=>{expanded.value=false;});
const rows=computed(()=>picks.value.districts.filter(d=>(!props.district||d.district===props.district)&&(!kind.value||d.kinds.includes(kind.value))));
const shownSummary=computed(()=>(expanded.value?rows.value:rows.value.slice(0,SHOW)).some(d=>d.programs.some(p=>p.summary)));
const visible=computed(()=>picks.value.districts.length>0&&(kind.value||!props.district||rows.value.length>0));
</script>
<template>
  <PickCard v-if="visible" id="health-weekly" v-model:expanded="expanded" class="health-weekly" title="이번 주 보건소 추천" :source="shownSummary?'ai':'rule'" :count="rows.length" :first="SHOW" unit="곳" v-slot="{limit}"
    :note="(shownSummary?'AI가 공식 페이지를 요약했습니다.':'공식 페이지 링크입니다.')+' 대상·기간·비용은 원문에서 확인하세요.'">
    <div v-if="picks.kinds.length" class="quick-filters health-weekly-kinds" role="group" aria-label="사업 종류">
      <button v-for="k in picks.kinds" :key="k.key" type="button" :aria-pressed="kind===k.key" @click="kind=kind===k.key?'':k.key">{{ k.label }} {{ k.districts }}개 구</button>
    </div>
    <div v-for="d in rows.slice(0,limit)" :key="d.district" class="health-weekly-district">
      <div class="health-weekly-head"><strong>{{ d.district }}</strong><span v-if="d.newNotices" class="health-badge">새 공지 {{ d.newNotices }}건</span></div>
      <ul v-if="d.programs.length" class="pick-list">
        <li>
          <a :href="d.programs[0].url" target="_blank" rel="noopener noreferrer"><strong>{{ d.programs[0].name }}</strong><span class="sr-only"> (새 창, {{ d.programs[0].center }})</span></a>
          <span v-if="d.programs[0].summary" class="pick-line">→ {{ d.programs[0].summary }}</span>
        </li>
        <li v-if="d.programs.length>1" class="health-weekly-others">외: <template v-for="(p,i) in d.programs.slice(1)" :key="p.url"><template v-if="i"> · </template><a :href="p.url" target="_blank" rel="noopener noreferrer">{{ p.name }}<span class="sr-only"> (새 창, {{ p.center }})</span></a></template></li>
      </ul>
      <small v-if="d.more>0" class="health-weekly-more">외 {{ d.more }}곳</small>
    </div>
    <p v-if="!rows.length" class="health-weekly-empty" role="status">조건에 맞는 구가 없어요</p>
  </PickCard>
</template>
