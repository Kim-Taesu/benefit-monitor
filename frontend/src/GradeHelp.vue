<script setup lang="ts">
import { ref } from 'vue';
import { GRADES } from './grade';
const dialog=ref<HTMLDialogElement|null>(null);
let previousOverflow='',opener:HTMLElement|null=null;
function open(){if(dialog.value?.open)return;opener=document.activeElement as HTMLElement|null;previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';dialog.value?.showModal();}
function close(){if(!dialog.value?.open)return;dialog.value.close();document.body.style.overflow=previousOverflow;opener?.focus({preventScroll:true});}
function backdrop(event:MouseEvent){const el=dialog.value;if(!el||event.target!==el)return;const r=el.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)close();}
defineExpose({open});
</script>
<template>
  <dialog ref="dialog" class="benefit-modal grade-modal" aria-labelledby="grade-help-title" @cancel.prevent="close" @click="backdrop">
    <div class="modal-heading"><h2 id="grade-help-title">신뢰도 등급이란?</h2><button type="button" class="modal-close" aria-label="등급 설명 닫기" autofocus @click="close">닫기 ✕</button></div>
    <div class="details-body">
      <p>카드마다 붙은 A·B·C는 <strong>지금도 유효한지 얼마나 확실하게 확인했는지</strong>를 나타내요. 혜택이 좋고 나쁨이나 신청 자격과는 관계없어요.</p>
      <dl class="grade-list">
        <template v-for="g in GRADES" :key="g.grade"><dt><span class="grade-badge" :class="'grade-'+g.grade">{{ g.grade }}</span> {{ g.title }}</dt><dd>{{ g.body }}</dd></template>
      </dl>
      <p class="fine-print">등급은 공개 데이터의 날짜·확인 시각·출처 수집 상태만으로 코드가 매겨요. AI 문장으로 정하지 않아요. 남은 자리, 개인 자격, 조기 마감은 어느 등급이든 확인하지 않았어요.</p>
    </div>
  </dialog>
</template>
