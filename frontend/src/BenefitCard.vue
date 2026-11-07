<script setup lang="ts">
import { computed, ref, useId, onMounted, onBeforeUnmount } from 'vue';
import type { Benefit } from './benefits';
import { fees, timing, formatDate, benefitValueLabel } from './benefits';
const props=defineProps<{item:Benefit;now:number;saved?:boolean;hideFavorite?:boolean}>();
const emit=defineEmits<{toggleFavorite:[];officialClick:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),titleId=useId();
const opener=ref<HTMLButtonElement|null>(null);
let previousOverflow='',returnFocus=false;
function openDetails(){if(dialog.value?.open)return;previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';returnFocus=true;history.pushState({...history.state,benefitDialog:titleId},'');dialog.value?.showModal();}
function closeDetails(){if(!dialog.value?.open)return;dialog.value.close();document.body.style.overflow=previousOverflow;if(history.state?.benefitDialog===titleId)history.back();}
function popDetails(){if(dialog.value?.open){dialog.value.close();document.body.style.overflow=previousOverflow;}if(returnFocus){returnFocus=false;setTimeout(()=>opener.value?.focus({preventScroll:true}),0);}}
function backdrop(event:MouseEvent){const element=dialog.value;if(!element||event.target!==element)return;const r=element.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDetails();}
onMounted(()=>window.addEventListener('popstate',popDetails));
onBeforeUnmount(()=>{window.removeEventListener('popstate',popDetails);if(dialog.value?.open){document.body.style.overflow=previousOverflow;dialog.value.close();if(history.state?.benefitDialog===titleId){const state={...history.state};delete state.benefitDialog;history.replaceState(state,'');}}});
const status=computed(()=>timing(props.item,props.now));
const aiReview=computed(()=>props.item.review.kind==='ai_auto'?props.item.review:null);
const paymentNames:Record<string,string>={method:'결제 방식',funding_source:'결제 재원',excluded_methods:'제외 수단',minimum_spend:'최소 지출',limit:'혜택 한도'};
// Approved payment terms always carry all five fields; otherwise none are known.
const paymentRows=computed(()=>Object.entries(paymentNames).filter(([key])=>props.item.payment_terms[key]).map(([key,label])=>({key,label,value:props.item.payment_terms[key]})));
</script>
<template>
  <article class="benefit-card">
    <div class="card-meta"><span class="category">{{ item.category }}</span><span class="timing" :class="{urgent:status.urgent}">{{ status.label }}</span></div>
    <h3><button ref="opener" class="card-open" type="button" aria-haspopup="dialog" @click="openDetails">{{ item.summary }}</button></h3>
    <p class="card-source">{{ item.sourceName }}<span aria-hidden="true"> · </span>{{ item.regions.join(' · ') || '지역 조건 확인 필요' }}</p>
    <div class="card-tags"><span v-if="aiReview" class="ai-badge">AI 정리 · 공식 원문 {{ aiReview.documentCount }}곳 대조</span><span v-if="item.labels.audience">{{ item.labels.audience }}</span><span v-if="item.labels.action">{{ item.labels.action }}</span><span>{{ fees[item.fee_status] }}</span></div>
    <p class="verified">공식 확인 <time :datetime="item.verified_at">{{ formatDate(item.verified_at) }}</time></p>
    <button v-if="!hideFavorite" class="favorite-toggle" type="button" :aria-pressed="Boolean(saved)" :aria-label="item.summary+' 즐겨찾기'" @click="emit('toggleFavorite')"><span aria-hidden="true">{{ saved?'★':'☆' }}</span> {{ saved?'저장됨':'즐겨찾기 저장' }}</button>
    <dialog ref="dialog" class="benefit-modal" :aria-labelledby="titleId" @cancel.prevent="closeDetails" @click="backdrop">
      <div class="modal-heading"><h2 :id="titleId">{{ item.summary }}</h2><button type="button" class="modal-close" aria-label="상세 조건 닫기" autofocus @click="closeDetails">닫기 ✕</button></div>
      <p class="modal-source">{{ item.sourceName }} · 공식 확인 {{ formatDate(item.verified_at) }}</p>
      <div class="details-body">
        <p v-if="item.title!==item.summary" class="original-title">원문 제목: {{ item.title }}</p>
        <section v-if="item.benefitValue" class="value-evidence" aria-label="혜택 수치 근거"><p><strong>{{ benefitValueLabel(item.benefitValue) }}</strong></p><p>수치 적용 조건: {{ item.benefitValue.conditions }}</p><p>근거 문구: {{ item.benefitValue.evidence_quote }}</p><a :href="item.benefitValue.evidence_url" target="_blank" rel="noopener noreferrer">금액 근거 원문<span class="sr-only"> (새 창)</span></a><p class="fine-print">공식 확인 시점의 조건부 수치이며 개인별 수령·절약액을 보장하지 않습니다. 참여 비용·최소 지출·결제 한도와 구분하세요.</p></section>
        <section v-if="paymentRows.length" class="payment-terms" :aria-labelledby="titleId+'-payment'">
          <h3 :id="titleId+'-payment'">결제 조건</h3>
          <dl><template v-for="row in paymentRows" :key="row.key"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
          <a v-if="item.payment_terms.evidence_url" :href="item.payment_terms.evidence_url" target="_blank" rel="noopener noreferrer">결제 조건 원문 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
        </section>
        <section v-if="aiReview" class="ai-review" :aria-labelledby="titleId+'-ai'">
          <h3 :id="titleId+'-ai'">AI 정리 · 공식 원문 {{ aiReview.documentCount }}곳 대조</h3>
          <p>사람이 검수하지 않고 AI가 공식 원문을 서로 대조해 정리한 항목입니다. 대조한 원문은 아래에서 직접 확인하세요. (확인 {{ formatDate(aiReview.checkedAt) }})</p>
          <ul><li v-for="(doc,n) in aiReview.documents" :key="doc.url+n"><a :href="doc.url" target="_blank" rel="noopener noreferrer">{{ doc.title || doc.url }}<span aria-hidden="true"> ↗</span><span class="sr-only"> (새 창)</span></a></li></ul>
        </section>
        <dl class="detail-list">
          <dt>적용기간</dt><dd>{{ formatDate(item.valid_from) }} ~ {{ item.validity_kind==='ongoing'?'상시 안내':formatDate(item.valid_until) }}</dd>
          <dt>신청 마감</dt><dd>{{ formatDate(item.deadline_at) }}</dd>
          <dt>참여 비용</dt><dd>{{ fees[item.fee_status] }} · 구체적 금액과 추가 비용은 아래 조건 및 공식 안내 확인</dd>
          <dt>대상</dt><dd>{{ item.labels.audience || '공식 안내 확인 필요' }}</dd>
          <dt>지역</dt><dd>{{ item.regions.join(' · ') || '공식 안내 확인 필요' }}</dd>
          <dt>이용 방법</dt><dd>{{ item.labels.action || '공식 안내 확인 필요' }}</dd>
          <template v-if="!paymentRows.length"><dt>결제 조건</dt><dd class="muted-value">결제 조건 따로 정리 안 됨 · 아래 조건 전문과 공식 안내 확인</dd></template>
          <dt>조건 전문</dt><dd class="full-conditions">{{ item.conditions || '공식 안내 확인 필요' }}</dd>
          <dt>표시 유효기한</dt><dd>{{ formatDate(item.display_until) }} · 검증 유효기한이며 행사 종료와 다를 수 있습니다.</dd>
        </dl>
        <p class="fine-print">개인 자격·잔여석·재고·조기 마감은 확인하지 않았습니다. 신청 마감과 실제 이용 기간은 다를 수 있습니다.</p>
      </div>

    <a @click="emit('officialClick')" class="official-link" :href="item.url" target="_blank" rel="noopener noreferrer" :aria-label="item.summary+' 공식 안내 보기 (새 창)'">공식 안내 보기 <span aria-hidden="true">↗</span></a>
    </dialog>
  </article>
</template>
