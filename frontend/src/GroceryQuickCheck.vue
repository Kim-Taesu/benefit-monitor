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
 const live=new Set(props.rows.map(r=>r.kind+r.id));
 return {item:hit.best,row,others:hit.others.filter(o=>live.has(o.rowKey)),badge,avg:badge?hit.best.baseline:null,date:md(row.kind==='meat'?props.meatDate:props.produceDate)};
});
</script>
<template>
  <div>
  <div class="sr-only" role="status" aria-live="polite"><template v-if="view">{{ view.item.name }} 전국 평균 소매가 {{ won(view.row.current) }} /{{ view.row.unit.replace(/^원\//,'') }}<template v-if="view.badge"> {{ view.badge.label }}</template></template></div>
  <div v-if="view" class="grocery-quick">
    <h3>{{ view.item.name }} · 전국 평균 소매가</h3>
    <p class="grocery-quick-price"><strong>{{ won(view.row.current) }}</strong> /{{ view.row.unit.replace(/^원\//,'') }}</p>
    <span v-if="view.badge" class="grocery-badge" :class="view.badge.level">{{ view.badge.label }}</span>
    <p class="grocery-quick-note"><template v-if="view.avg"><template v-if="view.row.kind==='meat'">조사 방식 변경(7월) 후 </template>{{ Math.min(view.avg.months,12) }}개월 평균 {{ won(view.avg.avg) }}<template v-if="view.date"> · </template></template><template v-if="view.date">{{ view.date }} 조사</template></p>
    <p v-if="view.others.length" class="grocery-quick-links"><template v-for="(o,i) in view.others" :key="o.id"><template v-if="i"> · </template><button type="button" @click="emit('pick',o.name)">{{ o.name }}</button></template> ›</p>
  </div>
  </div>
</template>
