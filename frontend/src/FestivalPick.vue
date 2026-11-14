<script setup lang="ts">
import { computed } from 'vue';
import PickCard from './PickCard.vue';
import { festivalFees } from './festivals';
import type { FestivalBundle } from './festivals';
import { parseFestivalPick, festivalLine } from './picks';
const props=defineProps<{raw:unknown;bundle:FestivalBundle}>();
const pick=computed(()=>parseFestivalPick(props.raw,props.bundle));
</script>
<template>
  <PickCard v-if="pick" id="festival-pick" title="이번 주말 나들이 추천" :source="pick.source" :summary="pick.summary" :count="pick.picks.length" v-slot="{limit}"
    :note="pick.source==='ai'?'AI가 공개 정보 안에서 쓴 문장이에요. 날짜·요금은 공개 전에 코드가 원본과 대조했어요.':'수도권 먼저, 가까운 날짜 순으로 자동 선정했어요.'">
    <ul class="pick-list">
      <li v-for="p in pick.picks.slice(0,limit)" :key="p.festival.id">
        <a :href="p.festival.url" target="_blank" rel="noopener noreferrer"><strong>{{ festivalLine(p.festival) }}</strong><span class="sr-only"> (새 창)</span></a>
        <span class="grocery-badge normal">{{ festivalFees[p.festival.fee_status] }}</span>
        <span v-if="p.line" class="pick-line">→ {{ p.line }}</span>
      </li>
    </ul>
  </PickCard>
</template>
