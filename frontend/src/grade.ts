import type { Benefit } from './benefits';

/** 카드 신뢰도 등급. 공개 데이터의 값만으로 코드가 정한다(모델 문장 없음). 승인 2026-11-10. */
export type Grade = 'A' | 'B' | 'C';
export const FRESH_DAYS = 7;
export const FAILING_RUNS = 3;
const DAY = 86400000;

export const GRADES: { grade: Grade; title: string; body: string }[] = [
  { grade: 'A', title: '기간까지 확인됨', body: `공식 원문에서 끝나는 날을 연도까지 확인했고 아직 지나지 않았어요. 확인한 지 ${FRESH_DAYS}일 이내이고, 출처 수집도 정상이에요. AI가 찾은 후보는 이 기준을 모두 통과해야만 자동으로 공개돼요.` },
  { grade: 'B', title: '확인됨 · 기간 미정', body: `공식 원문으로 확인했지만 끝나는 날이 원문에 없거나(상시 안내), 확인한 지 ${FRESH_DAYS + 1}일 이상 지났어요. 이용 전에 공식 안내를 한 번 더 보세요.` },
  { grade: 'C', title: '재확인 필요', body: `이 혜택을 가져오는 공식 출처의 수집이 ${FAILING_RUNS}회 이상 연속 실패해, 지금도 그대로인지 확인하지 못했어요. 바뀌었거나 끝났을 수 있어요.` },
];

export function grade(item: Benefit, failures: Record<string, number>, now: number): { grade: Grade; reason: string } {
  const failed = failures[item.source] ?? 0;
  if (failed >= FAILING_RUNS) return { grade: 'C', reason: `출처 수집 ${failed}회 연속 실패` };
  const age = Math.floor((now - Date.parse(item.verified_at)) / DAY);
  if (item.validity_kind === 'ongoing' || !(item.valid_until || item.deadline_at)) return { grade: 'B', reason: '끝나는 날이 원문에 없음' };
  if (age > FRESH_DAYS) return { grade: 'B', reason: `확인한 지 ${age}일` };
  return { grade: 'A', reason: '' };
}
