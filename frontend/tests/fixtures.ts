// Synthetic QA data only. Never copied into production or treated as a real offer.
export const NOW=Date.parse('2026-11-04T12:00:00+09:00');
export function item(overrides: Record<string,unknown>={}) {
  return {source:'seoul',url:'https://mediahub.seoul.go.kr/archives/1',title:'[테스트] 문화 체험 안내',summary:'[테스트] 문화 체험 안내',conditions:'테스트 자료. 회원 대상, 참여비 5,000원. 실제 혜택이 아닙니다.',districts:['강서구'],labels:{category:'문화·체험',region:'강서구',audience:'회원',action:'신청·예약 필요'},verified_at:'2026-11-04T06:00:00+09:00',valid_from:'2026-11-01',valid_until:'2026-11-06',deadline_at:'2026-11-06T18:00:00+09:00',validity_kind:'fixed',fee_status:'paid',needs_recheck:false,display_until:'2026-11-06T18:00:00+09:00',...overrides};
}
export function snapshot(items: unknown[]=[item()],overrides: Record<string,unknown>={}) {
 return {schema_version:1,status:'partial',generated_at:'2026-11-04T07:00:00+09:00',source_report_at:'2026-11-04T06:55:00+09:00',valid_through:'2026-11-05T00:00:00+09:00',items,coverage_incomplete:true,message:'일부 공식 출처를 확인한 결과입니다.',coverage:{sources:[{source:'seoul',name:'서울시',status:'checked',scope:'테스트 수집 범위',verified_count:items.length},{source:'kt',name:'KT',status:'failed',scope:'테스트 실패',verified_count:0}],districts:[],scope:'일부 목록만 확인'},run_context:{status:'manual_refresh',trigger:'workflow_dispatch',scheduled_run_confirmed:false},review_queue:[],withheld:{pending:1},...overrides};
}
