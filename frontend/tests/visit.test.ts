import test from 'node:test';
import assert from 'node:assert/strict';
import {VISIT_KEY,VISIT_GAP,loadVisit,saveVisit,clearVisit,nextVisit,visitKey,fingerprint} from '../src/visit.ts';
function storage(){const data=new Map<string,string>();return {data,getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>{data.set(k,v);},removeItem:(k:string)=>{data.delete(k);}};}
const NOW=Date.parse('2026-11-15T09:00:00+09:00');
const k=(n:number)=>visitKey({source:'seoul',url:'https://mediahub.seoul.go.kr/archives/'+n});

test('first visit shows the intro and marks nothing as new',()=>{
 const v=nextVisit(null,[k(1),k(2)],NOW);
 assert.equal(v.first,true);assert.equal(v.previousAt,null);assert.equal(v.fresh.size,0);
 assert.deepEqual(v.record,{version:1,at:NOW,keys:[k(1),k(2)],previousAt:null,previousKeys:[],introClosed:false});
});
test('a reload inside the same visit keeps the earlier comparison point',()=>{
 const first=nextVisit(null,[k(1)],NOW).record;
 const again=nextVisit(first,[k(1),k(2)],NOW+VISIT_GAP-1);
 assert.equal(again.first,true);assert.equal(again.fresh.size,0);assert.equal(again.record.at,NOW);
 assert.deepEqual(again.record.keys,[k(1),k(2)]);
});
test('a later visit marks only items that were not shown last time, even if re-verified since',()=>{
 const first=nextVisit(null,[k(1),k(2)],NOW).record;
 const later=nextVisit(first,[k(1),k(2),k(3)],NOW+VISIT_GAP+1);
 assert.equal(later.first,false);assert.equal(later.previousAt,NOW);assert.deepEqual([...later.fresh],[k(3)]);
 const reload=nextVisit(later.record,[k(1),k(2),k(3)],NOW+VISIT_GAP+60000);
 assert.deepEqual([...reload.fresh],[k(3)]);assert.equal(reload.previousAt,NOW);
 const third=nextVisit(reload.record,[k(1),k(3)],NOW+3*VISIT_GAP);
 assert.equal(third.fresh.size,0);assert.equal(third.previousAt,NOW+VISIT_GAP+1);
});
test('only fingerprints are stored: no source name, URL or title',()=>{
 const s=storage(),v=nextVisit(null,[k(1)],NOW);
 assert.equal(saveVisit(s,v.record),true);
 const text=s.data.get(VISIT_KEY)!;
 assert.ok(!text.includes('seoul')&&!text.includes('http'));assert.match(k(1),/^[0-9a-f]{16}$/);
 assert.notEqual(fingerprint('a'),fingerprint('b'));
 assert.deepEqual(loadVisit(s,NOW),v.record);
 assert.equal(clearVisit(s),true);assert.equal(loadVisit(s,NOW),null);
});
test('damaged, future or oversized records and blocked storage are ignored safely',()=>{
 const s=storage();
 for(const bad of ['{','null','{"version":2}',JSON.stringify({version:1,at:NOW,keys:['https://x'],previousAt:null,previousKeys:[],introClosed:false}),JSON.stringify({version:1,at:NOW,keys:[],previousAt:null,previousKeys:[],introClosed:false,extra:1}),JSON.stringify({version:1,at:NOW+1,keys:[],previousAt:null,previousKeys:[],introClosed:false})]){
  s.setItem(VISIT_KEY,bad);assert.equal(loadVisit(s,NOW),null,bad);
 }
 assert.equal(loadVisit(null,NOW),null);assert.equal(saveVisit(null,nextVisit(null,[],NOW).record),false);assert.equal(clearVisit(null),false);
 const blocked={getItem(){throw new Error('x');},setItem(){throw new Error('x');},removeItem(){throw new Error('x');}};
 assert.equal(loadVisit(blocked,NOW),null);assert.equal(saveVisit(blocked,nextVisit(null,[],NOW).record),false);assert.equal(clearVisit(blocked),false);
 const many=Array.from({length:700},(_,n)=>k(n));
 assert.equal(nextVisit(null,many,NOW).record.keys.length,500);
});
