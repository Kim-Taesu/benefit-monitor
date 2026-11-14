<script setup lang="ts">
import { computed, ref } from 'vue';
import type { Benefit } from './benefits';
import { parseBenefitPick, benefitDeadline, benefitFeeLabel } from './picks';
const props=defineProps<{raw:unknown;items:Benefit[]}>();
const FIRST=5;
const pick=computed(()=>parseBenefitPick(props.raw,props.items));
const expanded=ref(false);
const visible=computed(()=>expanded.value?pick.value?.picks??[]:(pick.value?.picks??[]).slice(0,FIRST));
const rest=computed(()=>(pick.value?.picks.length??0)-FIRST);
</script>
<template>
  <article v-if="pick" class="grocery-pick benefit-pick" aria-labelledby="benefit-pick-title">
    <div class="card-meta"><h3 id="benefit-pick-title">이번 주 놓치면 아쉬운 혜택</h3><span class="grocery-badge" :class="pick.source==='ai'?'ai':'normal'">{{ pick.source==='ai'?'AI 작성':'자동 선정' }}</span></div>
    <p v-if="pick.summary" class="grocery-pick-summary">{{ pick.summary }}</p>
    <ul>
      <li v-for="p in visible" :key="p.item.source+'\n'+p.item.url">
        <a :href="p.item.url" target="_blank" rel="noopener noreferrer"><strong>{{ p.item.title }}</strong><span class="sr-only"> (새 창)</span></a>
        <span class="grocery-badge normal">{{ benefitFeeLabel(p.item) }}</span>
        <small v-if="benefitDeadline(p.item)">{{ benefitDeadline(p.item) }}</small>
        <span v-if="p.line" class="grocery-pick-menu">→ {{ p.line }}</span>
      </li>
    </ul>
    <button v-if="!expanded&&rest>0" type="button" class="pick-more" @click="expanded=true">더 보기 ({{ rest }}개 남음)</button>
    <p class="fine-print">{{ pick.source==='ai'?'AI가 공개된 혜택 안에서 고른 추천이에요. 마감일과 비용은 공개 데이터에서 그대로 보여드려요.':'마감이 가까운 순으로 자동 선정했어요.' }}</p>
  </article>
</template>
