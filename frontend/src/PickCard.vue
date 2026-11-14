<script setup lang="ts">
// One frame for every tab's weekly pick card: title + source badge, optional summary, the tab's own
// lines (default slot, cut to `limit`), one "더 보기" button and one closing note.
import { computed } from 'vue';
const props=withDefaults(defineProps<{id:string;title:string;source:'ai'|'rule';summary?:string|null;note:string;count:number;first?:number;unit?:string}>(),{summary:null,first:5,unit:'개'});
const expanded=defineModel<boolean>('expanded',{default:false});
const limit=computed(()=>expanded.value?props.count:props.first);
const rest=computed(()=>props.count-props.first);
</script>
<template>
  <article class="pick-card" :aria-labelledby="id+'-title'">
    <div class="card-meta"><h3 :id="id+'-title'">{{ title }}</h3><span class="grocery-badge" :class="source==='ai'?'ai':'normal'">{{ source==='ai'?'AI 작성':'자동 선정' }}</span></div>
    <p v-if="summary" class="pick-summary">{{ summary }}</p>
    <slot :limit="limit" />
    <button v-if="!expanded&&rest>0" type="button" class="pick-more" @click="expanded=true">더 보기 ({{ rest }}{{ unit }} 남음)</button>
    <p class="fine-print">{{ note }}</p>
  </article>
</template>
