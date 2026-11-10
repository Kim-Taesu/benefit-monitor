<script setup lang="ts">
import { computed } from 'vue';
import { quickMatch, baselineBadge, won, type BasketItem, type PriceRow } from './groceries';
const props=defineProps<{q:string;basket:BasketItem[];rows:PriceRow[];produceDate:string|null;meatDate:string|null}>();
const emit=defineEmits<{pick:[name:string]}>();
const md=(d:string|null)=>d?`${Number(d.slice(5,7))}/${Number(d.slice(8,10))}`:'';
// A basket item without today's row shows no card at all (never a stale or guessed price).
const view=computed(()=>{
 const hit=quickMatch(props.q,props.basket);
 const row=hit?props.rows.find(r=>r.kind+r.id===hit.best.rowKey):undefined;
 if(!hit||!row)return null;
 const badge=baselineBadge(row,hit.best);
 return {item:hit.best,row,others:hit.others,badge,avg:badge?hit.best.baseline:null,date:md(row.kind==='meat'?props.meatDate:props.produceDate)};
});
</script>
<template>
  <div v-if="view" class="grocery-quick" role="region" :aria-label="view.item.name+' 전국 평균 소매가'">
    <h3>{{ view.item.name }} · 전국 평균 소매가</h3>
    <p class="grocery-quick-price"><strong>{{ won(view.row.current) }}</strong> /{{ view.row.unit.replace(/^원\//,'') }}</p>
    <span v-if="view.badge" class="grocery-badge" :class="view.badge.level">{{ view.badge.label }}</span>
    <p class="grocery-quick-note"><template v-if="view.avg">{{ Math.min(view.avg.months,12) }}개월 평균 {{ won(view.avg.avg) }}<template v-if="view.date"> · </template></template><template v-if="view.date">{{ view.date }} 조사</template></p>
    <p v-if="view.others.length" class="grocery-quick-links"><template v-for="(o,i) in view.others" :key="o.id"><template v-if="i"> · </template><button type="button" @click="emit('pick',o.name)">{{ o.name }}</button></template> ›</p>
  </div>
</template>
