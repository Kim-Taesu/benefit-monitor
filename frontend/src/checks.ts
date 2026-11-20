// Stage 2 checks (2026-11-20). The server already re-checked every row against the bundles in the same file;
// the page only reads them. Health notices: AI sorted titles and code folds administrative ones only when the
// title carries a word for it. Festivals: a sentence AI copied from the festival's own description about cost
// or cancellation. A malformed block is ignored as a whole and the page looks as it did before.
export type NoticeReason='recruitment'|'bid'|'personnel'|'result'|'legal';
export type FestivalNote='partly_paid'|'fee_found'|'free_found'|'cancelled';
export interface TabChecks{notices:Map<string,NoticeReason>;festivals:Map<string,{note:FestivalNote;quote:string}>}

export const noticeReasons:Record<NoticeReason,string>={recruitment:'채용',bid:'입찰·계약',personnel:'인사·위촉',result:'결과 발표',legal:'공시송달·고시'};
export const festivalNotes:Record<FestivalNote,string>={partly_paid:'소개 글에 유료 프로그램이 있어요',fee_found:'소개 글의 요금',free_found:'소개 글의 무료 안내',cancelled:'취소·연기 안내'};

const EMPTY:TabChecks={notices:new Map(),festivals:new Map()};
function record(v:unknown):v is Record<string,unknown>{return !!v&&typeof v==='object'&&!Array.isArray(v);}
function exact(v:Record<string,unknown>,keys:string[]):boolean{return Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));}

export function parseTabChecks(raw:unknown):TabChecks{
 if(!record(raw)||!record(raw.tab_checks))return EMPTY;
 const c=raw.tab_checks;
 if(!exact(c,['schema_version','notices','festivals'])||c.schema_version!==1||!Array.isArray(c.notices)||!Array.isArray(c.festivals)
   ||c.notices.length>300||c.festivals.length>200)return EMPTY;
 const notices=new Map<string,NoticeReason>(),festivals=new Map<string,{note:FestivalNote;quote:string}>();
 for(const n of c.notices){
  if(!record(n)||!exact(n,['url','title','reason'])||typeof n.url!=='string'||typeof n.title!=='string'
    ||typeof n.reason!=='string'||!Object.hasOwn(noticeReasons,n.reason))return EMPTY;
  notices.set(n.url,n.reason as NoticeReason);
 }
 for(const f of c.festivals){
  if(!record(f)||!exact(f,['id','note','quote'])||typeof f.id!=='string'||typeof f.quote!=='string'||!f.quote||f.quote.length>120
    ||typeof f.note!=='string'||!Object.hasOwn(festivalNotes,f.note))return EMPTY;
  festivals.set(f.id,{note:f.note as FestivalNote,quote:f.quote});
 }
 return {notices,festivals};
}
