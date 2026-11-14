<script setup lang="ts">
import { computed } from 'vue';
import PickCard from './PickCard.vue';
import type { Benefit } from './benefits';
import { parseBenefitPick, benefitDeadline, benefitFeeLabel } from './picks';
const props=defineProps<{raw:unknown;items:Benefit[];personalized?:boolean}>();
const pick=computed(()=>{
 const value=parseBenefitPick(props.raw,props.items);if(!value||!props.personalized)return value;
 const ranks=new Map(props.items.map((item,n)=>[item.source+'\n'+item.url,n]));
 return {...value,summary:null,picks:[...value.picks].sort((a,b)=>ranks.get(a.item.source+'\n'+a.item.url)!-ranks.get(b.item.source+'\n'+b.item.url)!)};
});
const note=computed(()=>(props.personalized?'공통 후보를 이 브라우저의 선호 순서로 정렬했습니다.':'개인 프로필 없이 선정한 공통 추천입니다.')+' 신청 자격·재고는 별도 확인하세요. '+(pick.value?.source==='ai'?'AI가 공개된 혜택 안에서 고른 추천이에요. 마감일과 비용은 공개 데이터에서 그대로 보여드려요.':'마감이 가까운 순으로 자동 선정했어요.'));
</script>
<template>
  <PickCard v-if="pick" id="benefit-pick" class="benefit-pick" title="이번 주 놓치면 아쉬운 혜택" :source="pick.source" :summary="pick.summary" :note="note" :count="pick.picks.length" v-slot="{limit}">
    <ul class="pick-list">
      <li v-for="p in pick.picks.slice(0,limit)" :key="p.item.source+'\n'+p.item.url">
        <a :href="p.item.url" target="_blank" rel="noopener noreferrer"><strong>{{ p.item.title }}</strong><span class="sr-only"> (새 창)</span></a>
        <span class="grocery-badge normal">{{ benefitFeeLabel(p.item) }}</span>
        <small v-if="benefitDeadline(p.item)">{{ benefitDeadline(p.item) }}</small>
        <span v-if="p.line" class="pick-line">→ {{ p.line }}</span>
      </li>
    </ul>
  </PickCard>
</template>
