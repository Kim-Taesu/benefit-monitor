<script setup lang="ts">
import { computed } from 'vue';
import { festivalFees } from './festivals';
import type { FestivalBundle } from './festivals';
import { parseFestivalPick, festivalLine } from './picks';
const props=defineProps<{raw:unknown;bundle:FestivalBundle}>();
const pick=computed(()=>parseFestivalPick(props.raw,props.bundle));
</script>
<template>
  <article v-if="pick" class="grocery-pick" aria-labelledby="festival-pick-title">
    <div class="card-meta"><h3 id="festival-pick-title">이번 주말 나들이 추천</h3><span class="grocery-badge" :class="pick.source==='ai'?'ai':'normal'">{{ pick.source==='ai'?'AI 작성':'자동 선정' }}</span></div>
    <p v-if="pick.summary" class="grocery-pick-summary">{{ pick.summary }}</p>
    <ul>
      <li v-for="p in pick.picks" :key="p.festival.id">
        <strong>{{ festivalLine(p.festival) }}</strong>
        <span class="grocery-badge normal">{{ festivalFees[p.festival.fee_status] }}</span>
        <span v-if="p.line" class="grocery-pick-menu">→ {{ p.line }}</span>
      </li>
    </ul>
    <p class="fine-print">{{ pick.source==='ai'?'AI가 공개 정보 안에서 쓴 문장이에요. 날짜·요금은 공개 전에 코드가 원본과 대조했어요.':'가까운 날짜 순으로 자동 선정했어요.' }}</p>
  </article>
</template>
