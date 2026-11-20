import test from 'node:test';
import assert from 'node:assert/strict';
import {parseTabChecks} from '../src/checks.ts';

const URL='https://www.gwangjin.go.kr/health/bbs/view.do?nttId=1';
function raw(over:Record<string,unknown>={}){
 return {tab_checks:{schema_version:1,notices:[{url:URL,title:'기간제 근로자 채용 공고',reason:'recruitment'}],
  festivals:[{id:'a',note:'partly_paid',quote:'체험비 5,000원'}],...over}};
}

test('valid rows are read into maps',()=>{
 const c=parseTabChecks(raw());
 assert.equal(c.notices.get(URL),'recruitment');
 assert.deepEqual(c.festivals.get('a'),{note:'partly_paid',quote:'체험비 5,000원'});
});

test('missing or malformed blocks are ignored as a whole',()=>{
 for(const bad of [undefined,{},{tab_checks:null},raw({schema_version:2}),raw({extra:1}),
  raw({notices:[{url:URL,title:'x',reason:'spam'}]}),raw({festivals:[{id:'a',note:'partly_paid',quote:''}]}),
  raw({festivals:[{id:'a',note:'partly_paid',quote:'x',more:1}]})]){
  const c=parseTabChecks(bad);
  assert.equal(c.notices.size+c.festivals.size,0);
 }
});
