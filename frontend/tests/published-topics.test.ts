import test from 'node:test';
import assert from 'node:assert/strict';
import {adapt} from '../src/benefits.ts';
import {emptyBeta} from '../src/beta.ts';
import {publishedTopics} from '../src/published-topics.ts';
import {item,snapshot,NOW} from './fixtures.ts';

function data(){const row=item();return snapshot([row],{topic_cards:{schema_version:1,generated_at:'2026-11-04T08:00:00+09:00',valid_until:'2026-11-04T18:00:00+09:00',used_fallback:false,topics:[{id:'culture',title:'문화·체험',items:[{source:row.source,url:row.url,facts:row}]}]}});}
test('approved static topic cards use only currently adapted benefits',()=>{
 const raw=data(),items=adapt(raw,NOW).items;
 const result=publishedTopics(raw,items,emptyBeta().profile,NOW);
 assert.equal(result?.[0].title,'문화·체험');assert.equal(result?.[0].items.length,1);
 assert.equal(publishedTopics(raw,[],emptyBeta().profile,NOW),null);
});
test('expired or malformed bundle falls back to existing rules',()=>{
 const raw=data();assert.equal(publishedTopics(raw,adapt(raw,NOW).items,emptyBeta().profile,NOW+86400000),null);
 raw.topic_cards.topics[0].title='누구나 무료 보장';assert.equal(publishedTopics(raw,adapt(raw,NOW).items,emptyBeta().profile,NOW),null);
 assert.equal(publishedTopics(snapshot(),adapt(snapshot(),NOW).items,emptyBeta().profile,NOW),null);
});
test('changed facts and foreign references cannot be resurrected by a card',()=>{
 const raw=data();raw.items[0]={...raw.items[0],conditions:'가격과 대상이 변경됨'};
 assert.equal(publishedTopics(raw,adapt(raw,NOW).items,emptyBeta().profile,NOW),null);
 const fresh=data();fresh.topic_cards.topics[0].items[0].url='https://evil.example/item';
 assert.equal(publishedTopics(fresh,adapt(fresh,NOW).items,emptyBeta().profile,NOW),null);
});
test('directly chosen interests remain pinned without sending profile anywhere',()=>{
 const raw=data(),profile=emptyBeta().profile;profile.interests=['culture'];
 assert.equal(publishedTopics(raw,adapt(raw,NOW).items,profile,NOW)?.[0].pinned,true);
 assert.deepEqual(profile.interests,['culture']);
});

test('empty approved card set falls back to current local rules',()=>{
 const raw=data();raw.topic_cards.topics=[];
 assert.equal(publishedTopics(raw,adapt(raw,NOW).items,emptyBeta().profile,NOW),null);
});
