<script setup lang="ts">
import { computed, ref, useId, onMounted, onBeforeUnmount } from 'vue';
import type { Benefit } from './benefits';
import { fees, timing, timingBadge, verifiedAge, formatDate, benefitValueLabel, categoryLabel } from './benefits';
import { grade, GRADES } from './grade';
// pick: 이번 주 추천에 든 항목. line은 AI가 쓴 한 줄(검증 통과분)이고 없으면 규칙으로 고른 항목이다.
const props=defineProps<{item:Benefit;now:number;saved?:boolean;failures?:Record<string,number>;pick?:{source:'ai'|'rule';line:string|null}|null;fresh?:boolean}>();
const emit=defineEmits<{toggleFavorite:[]}>();
const dialog=ref<HTMLDialogElement|null>(null),titleId=useId();
const opener=ref<HTMLButtonElement|null>(null);
let previousOverflow='',returnFocus=false;
function openDetails(){if(dialog.value?.open)return;previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';returnFocus=true;history.pushState({...history.state,benefitDialog:titleId},'');dialog.value?.showModal();}
function closeDetails(){if(!dialog.value?.open)return;dialog.value.close();document.body.style.overflow=previousOverflow;if(history.state?.benefitDialog===titleId)history.back();}
function popDetails(){if(dialog.value?.open){dialog.value.close();document.body.style.overflow=previousOverflow;}if(returnFocus){returnFocus=false;setTimeout(()=>opener.value?.focus({preventScroll:true}),0);}}
function backdrop(event:MouseEvent){const element=dialog.value;if(!element||event.target!==element)return;const r=element.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)closeDetails();}
onMounted(()=>window.addEventListener('popstate',popDetails));
onBeforeUnmount(()=>{window.removeEventListener('popstate',popDetails);if(dialog.value?.open){document.body.style.overflow=previousOverflow;dialog.value.close();if(history.state?.benefitDialog===titleId){const state={...history.state};delete state.benefitDialog;history.replaceState(state,'');}}});
const badge=computed(()=>timingBadge(props.item,props.now));
const status=computed(()=>timing(props.item,props.now));
const age=computed(()=>verifiedAge(props.item,props.now));
const trust=computed(()=>{const g=grade(props.item,props.failures??{},props.now);return {...g,title:GRADES.find(x=>x.grade===g.grade)!.title};});
const aiReview=computed(()=>props.item.review.kind==='ai_auto'?props.item.review:null);
// 구 이름이 다른 지역 표기 안에 이미 들어 있으면 한 번만 보인다.
const region=computed(()=>props.item.regions.filter((r,_,all)=>!all.some(other=>other!==r&&other.includes(r))).join(' · '));
// AI 문장이 없으면 공식 조건의 첫 문장을 그대로 보인다(만들어 쓰지 않는다).
const lead=computed(()=>props.pick?.line||props.item.conditions.split(/(?<=[.;])\s/)[0].replace(/[.;]$/,''));
const paymentNames:Record<string,string>={method:'결제 방식',funding_source:'결제 재원',excluded_methods:'제외 수단',minimum_spend:'최소 지출',limit:'혜택 한도'};
// Approved payment terms always carry all five fields; otherwise none are known.
const paymentRows=computed(()=>Object.entries(paymentNames).filter(([key])=>props.item.payment_terms[key]).map(([key,label])=>({key,label,value:props.item.payment_terms[key]})));
const period=computed(()=>props.item.validity_kind==='ongoing'?'끝나는 날이 정해지지 않음':`${formatDate(props.item.valid_from)} ~ ${formatDate(props.item.valid_until)}`);
const missing=computed(()=>[['대상',props.item.labels.audience],['신청 마감',props.item.deadline_at],['이용 방법',props.item.labels.action],['결제 조건',paymentRows.value.length?'y':'']].filter(row=>!row[1]).map(row=>row[0]));
</script>
<template>
  <article class="benefit-card bcard">
    <p class="bcard-top"><span class="category">{{ categoryLabel(item.category) }}</span><span class="badge timing" :class="{urgent:badge.urgent}">{{ badge.label }}</span><span v-if="fresh" class="badge new">새로 올라옴</span><span v-if="pick" class="badge pick-badge" :class="pick.source==='ai'&&pick.line?'ai':''">{{ pick.source==='ai'&&pick.line?'AI 작성':'자동 선정' }}</span><span v-if="aiReview" class="badge ai-badge">AI 정리</span><span v-if="trust.grade==='C'" class="badge urgent recheck" :title="trust.reason">⚠️ 재확인 필요</span></p>
    <h3 class="bcard-title"><button ref="opener" class="card-open" type="button" aria-haspopup="dialog" @click="openDetails">{{ item.summary }}</button></h3>
    <p v-if="lead" class="bcard-lead" :class="{'pick-line':pick?.line}">{{ lead }}</p>
    <p class="bcard-facts">{{ [region||'지역 조건 확인 필요',fees[item.fee_status],item.labels.action].filter(Boolean).join(' · ') }}</p>
    <p class="bcard-foot"><span>{{ item.sourceName }} · {{ age }}</span><b aria-hidden="true">자세히 ›</b></p>
    <button class="favorite-toggle bcard-fav" type="button" :aria-pressed="Boolean(saved)" :aria-label="item.summary+' 즐겨찾기'" @click="emit('toggleFavorite')"><span aria-hidden="true">{{ saved?'★':'☆' }}</span></button>
    <dialog ref="dialog" class="benefit-modal sheet" :aria-labelledby="titleId" @cancel.prevent="closeDetails" @click="backdrop">
      <div class="sheet-head"><h2 :id="titleId">{{ item.summary }}</h2><button type="button" class="modal-close sheet-close" aria-label="상세 조건 닫기" autofocus @click="closeDetails"><span aria-hidden="true">✕</span></button></div>
      <div class="sheet-body details-body">
        <p class="sheet-tags"><span class="badge">{{ categoryLabel(item.category) }}</span><span class="badge" :class="{urgent:badge.urgent}">{{ status.label }}</span><span v-if="pick" class="badge" :class="pick.source==='ai'&&pick.line?'ai':''">{{ pick.source==='ai'&&pick.line?'AI 작성':'자동 선정' }}</span></p>
        <p v-if="pick?.line" class="sheet-pick">{{ pick.line }}</p>
        <section v-if="item.benefitValue" class="value-evidence" aria-label="혜택 수치 근거"><p><strong>{{ benefitValueLabel(item.benefitValue) }}</strong></p><p>수치 적용 조건: {{ item.benefitValue.conditions }}</p><p>근거 문구: {{ item.benefitValue.evidence_quote }}</p><a :href="item.benefitValue.evidence_url" target="_blank" rel="noopener noreferrer">금액 근거 원문<span class="sr-only"> (새 창)</span></a><p class="fine-print">공식 확인 시점의 조건부 수치이며 개인별 수령·절약액을 보장하지 않습니다. 참여 비용·최소 지출·결제 한도와 구분하세요.</p></section>
        <dl class="detail-list">
          <dt>적용기간</dt><dd>{{ period }}</dd>
          <template v-if="item.deadline_at"><dt>신청 마감</dt><dd>{{ formatDate(item.deadline_at) }}</dd></template>
          <dt>참여 비용</dt><dd>{{ fees[item.fee_status] }}</dd>
          <template v-if="item.labels.audience"><dt>대상</dt><dd>{{ item.labels.audience }}</dd></template>
          <dt>지역</dt><dd>{{ region || '공식 안내 확인 필요' }}</dd>
          <template v-if="item.labels.action"><dt>이용 방법</dt><dd>{{ item.labels.action }}</dd></template>
        </dl>
        <section v-if="paymentRows.length" class="payment-terms" :aria-labelledby="titleId+'-payment'">
          <h3 :id="titleId+'-payment'">결제 조건</h3>
          <dl><template v-for="row in paymentRows" :key="row.key"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></template></dl>
          <a v-if="item.payment_terms.evidence_url" :href="item.payment_terms.evidence_url" target="_blank" rel="noopener noreferrer">결제 조건 원문 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
        </section>
        <section><h3>조건</h3><p class="full-conditions">{{ item.conditions || '공식 안내 확인 필요' }}</p>
          <p v-if="missing.length" class="fine-print">따로 정리되지 않은 항목: {{ missing.join('·') }}. 구체적 금액과 추가 비용을 포함해 공식 안내에서 확인하세요.</p></section>
        <section v-if="aiReview" class="ai-review" :aria-labelledby="titleId+'-ai'">
          <h3 :id="titleId+'-ai'">AI 정리 · 공식 원문 {{ aiReview.documentCount }}곳 대조</h3>
          <p>사람이 검수하지 않고 AI가 공식 원문을 서로 대조해 정리한 항목입니다. 대조한 원문은 아래에서 직접 확인하세요. (확인 {{ formatDate(aiReview.checkedAt) }})</p>
          <ul><li v-for="(doc,n) in aiReview.documents" :key="doc.url+n"><a :href="doc.url" target="_blank" rel="noopener noreferrer">{{ doc.title || doc.url }}<span aria-hidden="true"> ↗</span><span class="sr-only"> (새 창)</span></a></li></ul>
        </section>
        <section class="sheet-trust">
          <p>{{ item.sourceName }} 공식 안내 · 공식 확인 {{ formatDate(item.verified_at) }} · <span class="grade-badge" :class="'grade-'+trust.grade">신뢰도 {{ trust.grade }}</span> {{ trust.title }}<template v-if="trust.reason"> · {{ trust.reason }}</template></p>
          <p v-if="item.title!==item.summary" class="original-title">원문 제목: {{ item.title }}</p>
          <details class="grade-details"><summary>신뢰도 등급이란?</summary>
            <p>A·B·C는 <strong>지금도 유효한지 얼마나 확실하게 확인했는지</strong>를 나타내요. 혜택이 좋고 나쁨이나 신청 자격과는 관계없어요.</p>
            <dl class="grade-list"><template v-for="g in GRADES" :key="g.grade"><dt><span class="grade-badge" :class="'grade-'+g.grade">{{ g.grade }}</span> {{ g.title }}</dt><dd>{{ g.body }}</dd></template></dl>
            <p class="fine-print">등급은 공개 데이터의 날짜·확인 시각·출처 수집 상태만으로 코드가 매겨요. AI 문장으로 정하지 않아요.</p>
          </details>
          <p class="fine-print">표시 유효기한 {{ formatDate(item.display_until) }} · 검증 유효기한이며 행사 종료와 다를 수 있습니다. 개인 자격·잔여석·재고·조기 마감은 확인하지 않았습니다. 신청 마감과 실제 이용 기간은 다를 수 있습니다.</p>
        </section>
      </div>
      <div class="sheet-foot"><button type="button" class="sheet-fav" :aria-pressed="Boolean(saved)" @click="emit('toggleFavorite')"><span aria-hidden="true">{{ saved?'★':'☆' }}</span> {{ saved?'저장됨':'저장' }}</button><a class="official-link" :href="item.url" target="_blank" rel="noopener noreferrer" :aria-label="item.summary+' 공식 안내 보기 (새 창)'">공식 안내 보기 <span aria-hidden="true">↗</span></a></div>
    </dialog>
  </article>
</template>
