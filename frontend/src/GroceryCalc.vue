<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { compareShelf, parseUnit, won, type PriceRow } from './groceries';
const props=defineProps<{row:PriceRow}>();
const unit=computed(()=>parseUnit(props.row.unit));
const options=computed(()=>unit.value?.base==='g'?['g','kg']:unit.value?[unit.value.base]:[]);
const shelf=ref<number|null>(null),qty=ref<number|null>(null),qtyUnit=ref('');
const chosenUnit=computed(()=>qtyUnit.value||(unit.value?.base==='g'?(unit.value.amount>=1000?'kg':'g'):unit.value?.base||''));
const result=computed(()=>shelf.value&&qty.value?compareShelf({unit:props.row.unit,current:props.row.current,normal:props.row.normal,yearAgo:props.row.yearAgo},shelf.value,qty.value,chosenUnit.value):null);
const uid='grocery-'+useId();
</script>
<template>
  <div v-if="unit" class="grocery-calc">
    <p class="fine-print">매장 가격과 양을 넣으면 {{ unit.label }} 기준으로 바꿔 비교해요. 입력값은 이 화면에서만 계산하고 저장·전송하지 않아요.</p>
    <div class="grocery-calc-fields">
      <label :for="uid+'-price'">가격(원)<input :id="uid+'-price'" v-model.number="shelf" type="number" inputmode="numeric" min="1" placeholder="예: 3500"></label>
      <label :for="uid+'-qty'">양<input :id="uid+'-qty'" v-model.number="qty" type="number" inputmode="decimal" min="0" step="any" :placeholder="chosenUnit==='kg'?'예: 1.5':'예: 600'"></label>
      <label v-if="options.length>1" :for="uid+'-unit'">단위<select :id="uid+'-unit'" :value="chosenUnit" @change="qtyUnit=($event.target as HTMLSelectElement).value"><option v-for="o in options" :key="o">{{ o }}</option></select></label>
      <span v-else class="grocery-calc-unit">{{ chosenUnit }}</span>
    </div>
    <p v-if="result" class="grocery-calc-result" role="status" aria-live="polite">
      {{ unit.label }}당 <strong>{{ won(result.perUnit) }}</strong>
      · {{ row.kind==='meat'?'전국 평균':'조사 평균' }} {{ won(row.current) }}보다 {{ result.vsCurrent===0?'같음':Math.abs(result.vsCurrent)+'% '+(result.vsCurrent<0?'쌈':'비쌈') }}
      <template v-if="result.verdict"> · <span class="grocery-badge" :class="result.verdict.level">{{ result.verdict.label }}</span></template>
    </p>
  </div>
</template>
