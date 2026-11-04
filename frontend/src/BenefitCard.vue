<script setup lang="ts">
import { computed } from 'vue';
import type { Benefit } from './benefits';
import { fees, timing, formatDate } from './benefits';
const props=defineProps<{item:Benefit;now:number;saved?:boolean}>();
const emit=defineEmits<{toggleFavorite:[]}>();
const status=computed(()=>timing(props.item,props.now));
const paymentNames:Record<string,string>={method:'결제 방식',funding_source:'결제 재원',excluded_methods:'제외 수단',minimum_spend:'최소 지출',limit:'혜택 한도'};
</script>
<template>
  <article class="benefit-card">
    <div class="card-meta"><span class="category">{{ item.category }}</span><span class="timing" :class="{urgent:status.urgent}">{{ status.label }}</span></div>
    <h3>{{ item.summary }}</h3>
    <p class="card-source">{{ item.sourceName }}<span aria-hidden="true"> · </span>{{ item.regions.join(' · ') || '지역 조건 확인 필요' }}</p>
    <div class="card-tags"><span v-if="item.labels.audience">{{ item.labels.audience }}</span><span v-if="item.labels.action">{{ item.labels.action }}</span><span>{{ fees[item.fee_status] }}</span></div>
    <p class="card-conditions">{{ item.conditions || '대상과 이용 조건은 공식 안내에서 확인하세요.' }}</p>
    <p class="verified">공식 확인 <time :datetime="item.verified_at">{{ formatDate(item.verified_at) }}</time></p>
    <button class="favorite-toggle" type="button" :aria-pressed="Boolean(saved)" :aria-label="item.summary+' 즐겨찾기'" @click="emit('toggleFavorite')"><span aria-hidden="true">{{ saved?'★':'☆' }}</span> {{ saved?'저장됨':'즐겨찾기 저장' }}</button>
    <details class="card-details">
      <summary>상세 조건<span aria-hidden="true">＋</span></summary>
      <div class="details-body">
        <p v-if="item.title!==item.summary" class="original-title">원문 제목: {{ item.title }}</p>
        <dl>
          <dt>적용기간</dt><dd>{{ formatDate(item.valid_from) }} ~ {{ item.validity_kind==='ongoing'?'상시 안내':formatDate(item.valid_until) }}</dd>
          <dt>신청 마감</dt><dd>{{ formatDate(item.deadline_at) }}</dd>
          <dt>참여 비용</dt><dd>{{ fees[item.fee_status] }} · 구체적 금액과 추가 비용은 아래 조건 및 공식 안내 확인</dd>
          <dt>대상</dt><dd>{{ item.labels.audience || '공식 안내 확인 필요' }}</dd>
          <dt>지역</dt><dd>{{ item.regions.join(' · ') || '공식 안내 확인 필요' }}</dd>
          <dt>이용 방법</dt><dd>{{ item.labels.action || '공식 안내 확인 필요' }}</dd>
          <template v-for="(label,key) in paymentNames" :key="key"><dt>{{ label }}</dt><dd>{{ item.payment_terms[key] || '구조화된 조건 미확인 · 공식 안내 확인 필요' }}</dd></template>
          <dt>조건 전문</dt><dd class="full-conditions">{{ item.conditions || '공식 안내 확인 필요' }}</dd>
          <dt>표시 유효기한</dt><dd>{{ formatDate(item.display_until) }} · 검증 유효기한이며 행사 종료와 다를 수 있습니다.</dd>
        </dl>
        <a v-if="item.payment_terms.evidence_url" :href="item.payment_terms.evidence_url" target="_blank" rel="noopener noreferrer">결제조건 원문 <span aria-hidden="true">↗</span><span class="sr-only"> (새 창)</span></a>
        <p class="fine-print">개인 자격·잔여석·재고·조기 마감은 확인하지 않았습니다. 신청 마감과 실제 이용 기간은 다를 수 있습니다.</p>
      </div>
    </details>
    <a class="official-link" :href="item.url" target="_blank" rel="noopener noreferrer" :aria-label="item.summary+' 공식 안내 보기 (새 창)'">공식 안내 보기 <span aria-hidden="true">↗</span></a>
  </article>
</template>
