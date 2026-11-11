import test from 'node:test';
import assert from 'node:assert/strict';
import {takeDown,restore,readTakedowns,DeployError,REPO,NOTE_MAX,type Takedown} from '../src/admin/github.ts';

const TOKEN='github_pat_TESTONLY_0123456789abcdef';
const CID='0123456789abcdef01234567';
const FILE=`https://api.github.com/repos/${REPO}/contents/ai-takedowns.json`;
const DISPATCH=`https://api.github.com/repos/${REPO}/actions/workflows/briefing-pages.yml/dispatches`;
type Call={url:string;method:string;headers:Record<string,string>;body:unknown};

function encode(value:unknown){return Buffer.from(JSON.stringify(value)).toString('base64').replace(/(.{60})/g,'$1\n');}
function decode(content:string){return JSON.parse(Buffer.from(content,'base64').toString('utf8'));}
function json(status:number,body?:unknown){return new Response(body===undefined?null:JSON.stringify(body),{status,headers:{'content-type':'application/json'}});}
// Scripted fetch: each response is consumed in order; every request is recorded.
function fake(responses:Response[]){
 const calls:Call[]=[];
 const fn=async(url:string,init:RequestInit={})=>{
  calls.push({url,method:init.method||'GET',headers:Object.fromEntries(new Headers(init.headers).entries()),body:init.body?JSON.parse(String(init.body)):undefined});
  const next=responses.shift();if(!next)throw new Error('unexpected request '+url);return next;
 };
 return {fn,calls};
}
const existing:Takedown={candidate_id:'aaaaaaaaaaaaaaaaaaaaaaaa',title_key:'다른 항목',taken_down_at:'2026-11-07T09:00:00.000Z',note:''};
const NOW=new Date('2026-11-08T03:00:00.000Z');

test('takeDown reads, writes with the sha precondition, then dispatches the takedown-only deploy',async()=>{
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing])}),json(200,{content:{sha:'sha2'}}),new Response(null,{status:204})]);
 await takeDown(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},'  잘못된 기간  ',{fetch:fn,now:()=>NOW});
 assert.deepEqual(calls.map(c=>[c.method,c.url]),[['GET',FILE+'?ref=briefing-data'],['PUT',FILE],['POST',DISPATCH]]);
 const put=calls[1].body as {sha:string;branch:string;content:string;message:string};
 assert.equal(put.sha,'sha1');assert.equal(put.branch,'briefing-data');
 assert.deepEqual(decode(put.content),[existing,{candidate_id:CID,title_key:'테스트 항목',taken_down_at:NOW.toISOString(),note:'잘못된 기간'}]);
 assert.deepEqual(calls[2].body,{ref:'main',inputs:{apply_takedowns:true}});
 for(const c of calls){
  assert.equal(new URL(c.url).origin,'https://api.github.com');
  assert.equal(c.headers.authorization,'Bearer '+TOKEN);
  assert.ok(!c.url.includes(TOKEN));
 }
});

test('a missing takedown file is created without a sha',async()=>{
 const {fn,calls}=fake([json(404,{message:'Not Found'}),json(201,{}),new Response(null,{status:204})]);
 await takeDown(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},'',{fetch:fn,now:()=>NOW});
 const put=calls[1].body as Record<string,unknown>;
 assert.equal('sha' in put,false);
 assert.equal((decode(String(put.content)) as Takedown[]).length,1);
});

for(const status of [409,422])test(`sha conflict ${status} re-reads once and merges the newer list`,async()=>{
 const newer:Takedown={...existing,candidate_id:'bbbbbbbbbbbbbbbbbbbbbbbb',title_key:'동시에 내린 항목'};
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing])}),json(status,{message:'sha does not match'}),
  json(200,{encoding:'base64',sha:'sha3',content:encode([existing,newer])}),json(200,{}),new Response(null,{status:204})]);
 await takeDown(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},'',{fetch:fn,now:()=>NOW});
 assert.deepEqual(calls.map(c=>c.method),['GET','PUT','GET','PUT','POST']);
 const retry=calls[3].body as {sha:string;content:string};
 assert.equal(retry.sha,'sha3');
 assert.deepEqual((decode(retry.content) as Takedown[]).map(t=>t.candidate_id),[existing.candidate_id,newer.candidate_id,CID]);
});

test('a second conflict fails without dispatching',async()=>{
 const list=json(200,{encoding:'base64',sha:'sha1',content:encode([])});
 const {fn,calls}=fake([list,json(409,{}),json(200,{encoding:'base64',sha:'sha2',content:encode([])}),json(409,{})]);
 await assert.rejects(takeDown(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},'',{fetch:fn,now:()=>NOW}));
 assert.equal(calls.some(c=>c.method==='POST'),false);
});

test('already taken down items are not duplicated but still redeployed',async()=>{
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([{...existing,candidate_id:CID}])}),new Response(null,{status:204})]);
 await takeDown(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},'',{fetch:fn,now:()=>NOW});
 assert.deepEqual(calls.map(c=>c.method),['GET','POST']);
});

test('restore removes only the matching candidate and redeploys',async()=>{
 const mine:Takedown={...existing,candidate_id:CID,title_key:'테스트 항목'};
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing,mine])}),json(200,{}),new Response(null,{status:204})]);
 await restore(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},{fetch:fn,now:()=>NOW});
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing]);
 assert.deepEqual(calls[2].body,{ref:'main',inputs:{apply_takedowns:true}});
});

test('invalid input is refused before any request',async()=>{
 const {fn,calls}=fake([]);
 await assert.rejects(takeDown('bad token\r\nX: y',{candidate_id:CID,title_key:'t'},'',{fetch:fn}));
 await assert.rejects(takeDown(TOKEN,{candidate_id:'../../x',title_key:'t'},'',{fetch:fn}));
 await assert.rejects(takeDown(TOKEN,{candidate_id:CID,title_key:''},'',{fetch:fn}));
 await assert.rejects(takeDown(TOKEN,{candidate_id:CID,title_key:'t'},'x'.repeat(NOTE_MAX+1),{fetch:fn}));
 await assert.rejects(restore(TOKEN,{candidate_id:'nothex',title_key:'t'},{fetch:fn}));
 assert.equal(calls.length,0);
});

test('readTakedowns keeps only well-formed entries and errors never echo the token',async()=>{
 const {fn}=fake([json(200,{encoding:'base64',sha:'s',content:encode([existing,'junk',{candidate_id:5}])})]);
 assert.deepEqual((await readTakedowns(TOKEN,{fetch:fn})).list,[existing]);
 const bad=fake([json(401,{message:'Bad credentials '+TOKEN})]);
 await assert.rejects(readTakedowns(TOKEN,{fetch:bad.fn}),(e:Error)=>!e.message.includes(TOKEN)&&/401/.test(e.message));
 const notList=fake([json(200,{encoding:'base64',sha:'s',content:encode({})})]);
 await assert.rejects(readTakedowns(TOKEN,{fetch:notList.fn}));
});

test('a failed dispatch after a saved list is reported as a deploy error',async()=>{
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([])}),json(200,{}),json(403,{message:'Resource not accessible'})]);
 await assert.rejects(takeDown(TOKEN,{candidate_id:CID,title_key:'t'},'',{fetch:fn,now:()=>NOW}),(e:Error)=>e instanceof DeployError&&/403/.test(e.message));
 assert.deepEqual(calls.map(c=>c.method),['GET','PUT','POST']);
});

test('restore also removes entries with the same title_key (the backend matches either)',async()=>{
 const byKey:Takedown={...existing,candidate_id:'cccccccccccccccccccccccc',title_key:'테스트 항목'};
 const mine:Takedown={...existing,candidate_id:CID,title_key:'테스트 항목'};
 const {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing,byKey,mine,'unknown'])}),json(200,{}),new Response(null,{status:204})]);
 await restore(TOKEN,{candidate_id:CID,title_key:'테스트 항목'},{fetch:fn,now:()=>NOW});
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing,'unknown']);
});

test('grocery text mute adds a dated entry, keeps other entries and redeploys; unmute removes it',async()=>{
 const {muteGroceryText,unmuteGroceryText,readGroceryMutes}=await import('../src/admin/github.ts');
 const mute={kind:'grocery_pick_text',survey_date:'2026-11-06',taken_down_at:NOW.toISOString(),note:'어색한 문장'};
 let {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing])}),json(200,{}),new Response(null,{status:204})]);
 await muteGroceryText(TOKEN,'2026-11-06',' 어색한 문장 ',{fetch:fn,now:()=>NOW});
 assert.deepEqual(calls.map(c=>c.method),['GET','PUT','POST']);
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing,mute]);
 ({fn,calls}=fake([json(200,{encoding:'base64',sha:'sha2',content:encode([existing,mute])})]));
 assert.deepEqual(await readGroceryMutes(TOKEN,{fetch:fn}),['2026-11-06']);
 const {readAdminState}=await import('../src/admin/github.ts');
 ({fn,calls}=fake([json(200,{encoding:'base64',sha:'sha2',content:encode([existing,mute])})]));
 assert.deepEqual(await readAdminState(TOKEN,{fetch:fn}),{list:[existing],mutes:['2026-11-06'],healthMutes:[]});
 assert.equal(calls.length,1);
 ({fn,calls}=fake([json(200,{encoding:'base64',sha:'sha2',content:encode([existing,mute])}),json(200,{}),new Response(null,{status:204})]));
 await unmuteGroceryText(TOKEN,'2026-11-06',{fetch:fn});
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing]);
 await assert.rejects(()=>muteGroceryText(TOKEN,'11/06','',{fetch:fn}),/조사일/);
 await assert.rejects(()=>muteGroceryText(TOKEN,'2026-11-06','x'.repeat(NOTE_MAX+1),{fetch:fn}),/메모/);
});

test('health note mute adds a url entry and redeploys; unmute removes it; bad urls refused',async()=>{
 const {muteHealthNote,unmuteHealthNote,readAdminState}=await import('../src/admin/github.ts');
 const url='https://www.gangseo.seoul.kr/health/ht020103';
 const mute={kind:'health_note_text',url,taken_down_at:NOW.toISOString(),note:'어색함'};
 let {fn,calls}=fake([json(200,{encoding:'base64',sha:'sha1',content:encode([existing])}),json(200,{}),new Response(null,{status:204})]);
 await muteHealthNote(TOKEN,url,' 어색함 ',{fetch:fn,now:()=>NOW});
 assert.deepEqual(calls.map(c=>c.method),['GET','PUT','POST']);
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing,mute]);
 ({fn,calls}=fake([json(200,{encoding:'base64',sha:'sha2',content:encode([existing,mute])})]));
 assert.deepEqual((await readAdminState(TOKEN,{fetch:fn})).healthMutes,[url]);
 ({fn,calls}=fake([json(200,{encoding:'base64',sha:'sha2',content:encode([existing,mute])}),json(200,{}),new Response(null,{status:204})]));
 await unmuteHealthNote(TOKEN,url,{fetch:fn});
 assert.deepEqual(decode((calls[1].body as {content:string}).content),[existing]);
 await assert.rejects(()=>muteHealthNote(TOKEN,'http://x.kr','',{fetch:fn}),/주소/);
});
