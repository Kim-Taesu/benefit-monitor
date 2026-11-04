import {test} from 'node:test';
import assert from 'node:assert/strict';
import {adapt,benefitValueLabel} from '../src/benefits.ts';
import {item,snapshot,NOW} from './fixtures.ts';
const claim=(overrides:Record<string,unknown>={})=>{
 const result={kind:'discount_rate',value:10,qualifier:'up_to',conditions:'[테스트] 지정 결제수단·한도 확인 필요',evidence_url:'https://mediahub.seoul.go.kr/archives/1',...overrides};
 const units:Record<string,string>={discount_rate:'% 할인',discount_amount:'원 할인',grant_amount:'원 지원',refund_amount:'원 환급',reward_points:'포인트 적립'};
 return {...result,evidence_quote:'[테스트] '+(result.qualifier==='up_to'?'최대 ':'')+String(result.value)+units[String(result.kind)],...overrides};
};
test('legacy records omit the highlight; reviewed rate and amount keep type, qualifier and conditions',()=>{
 assert.equal(adapt(snapshot([item()]),NOW).items[0].benefitValue,null);
 for(const [value,label]of [[claim(),'최대 10% 할인'],[claim({value:0.5}),'최대 0.5% 할인'],[claim({kind:'discount_amount',value:5000,qualifier:'exact'}),'5,000원 할인'],[claim({kind:'grant_amount',value:100000}),'최대 100,000원 지원'],[claim({kind:'refund_amount',value:1000}),'최대 1,000원 환급'],[claim({kind:'reward_points',value:100}),'최대 100포인트 적립']] as const){
  const rows=adapt(snapshot([item({benefit_value:value})]),NOW).items;assert.equal(rows.length,1);assert.equal(benefitValueLabel(rows[0].benefitValue!),label);assert.equal(rows[0].benefitValue!.conditions,value.conditions);
 }
});
test('invalid structured claims withhold the whole record instead of showing an unsupported number',()=>{
 const invalid=[null,[],claim({value:true}),claim({value:0}),claim({value:-1}),claim({value:NaN}),claim({value:Infinity}),claim({value:101}),claim({value:1.001}),claim({kind:'discount_amount',value:1.5}),claim({kind:'grant_amount',value:1e12}),claim({kind:'price'}),claim({qualifier:'guaranteed'}),claim({conditions:''}),claim({extra:'unknown'}),claim({evidence_quote:''}),claim({evidence_url:'https://evil.example/'}),claim({evidence_url:'https://mediahub.seoul.go.kr/archives/2'})];
 for(const value of invalid){const result=adapt(snapshot([item({benefit_value:value})]),NOW);assert.equal(result.items.length,0);assert.equal(result.withheldCount,1);}
});
test('structured values never bypass file, item or verification freshness gates',()=>{
 for(const body of [snapshot([item({benefit_value:claim(),needs_recheck:true})]),snapshot([item({benefit_value:claim(),display_until:new Date(NOW).toISOString()})]),snapshot([item({benefit_value:claim()})],{valid_through:new Date(NOW).toISOString()})])assert.deepEqual(adapt(body,NOW).items,[]);
});
test('a payment evidence URL, when supplied, remains the observed source for numerical facts',()=>{
 const target='https://mediahub.seoul.go.kr/archives/2';
 assert.equal(adapt(snapshot([item({benefit_value:claim(),payment_terms:{evidence_url:target}})]),NOW).items.length,0);
 assert.equal(adapt(snapshot([item({benefit_value:claim({evidence_url:target}),payment_terms:{evidence_url:target}})]),NOW).items.length,1);
});

test('an explicit numerical claim cannot contradict its quoted number, unit or maximum qualifier',()=>{
 for(const value of [claim({kind:'grant_amount',value:5000,evidence_quote:'최대 5000원 할인'}),claim({value:20,evidence_quote:'최대 10% 할인'}),claim({kind:'grant_amount',value:5000,evidence_quote:'최대 10% 할인'}),claim({qualifier:'exact',evidence_quote:'최대 10% 할인'}),claim({evidence_quote:'10% 할인'}),claim({value:1,evidence_quote:'최대 0.1% 할인'})])assert.equal(adapt(snapshot([item({benefit_value:value})]),NOW).items.length,0);
});

test('equivalent decimal zero padding is allowed without rounding a different value',()=>{
 assert.equal(adapt(snapshot([item({benefit_value:claim({value:0.5,evidence_quote:'최대 0.50% 할인'})})]),NOW).items.length,1);
 assert.equal(adapt(snapshot([item({benefit_value:claim({value:0.15,evidence_quote:'최대 0.2% 할인'})})]),NOW).items.length,0);
});
