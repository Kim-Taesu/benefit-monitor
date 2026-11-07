import test from 'node:test';
import assert from 'node:assert/strict';
import {loadToken,saveToken,clearToken,TOKEN_KEY} from '../src/admin/token-store.ts';

function memory(){const m=new Map<string,string>();return {getItem:(k:string)=>m.get(k)??null,setItem:(k:string,v:string)=>{m.set(k,v);},removeItem:(k:string)=>{m.delete(k);},m};}
const broken=()=>{throw new Error('SecurityError');};

test('saving defaults to the session only',()=>{
 const session=memory(),local=memory();
 saveToken('tok',false,()=>session,()=>local);
 assert.equal(session.m.get(TOKEN_KEY),'tok');assert.equal(local.m.has(TOKEN_KEY),false);
 assert.equal(loadToken(()=>session,()=>local),'tok');
});
test('remembering opts into localStorage and drops the session copy',()=>{
 const session=memory(),local=memory();
 saveToken('tok',true,()=>session,()=>local);
 assert.equal(local.m.get(TOKEN_KEY),'tok');assert.equal(session.m.has(TOKEN_KEY),false);
 assert.equal(loadToken(()=>memory(),()=>local),'tok');
});
test('session wins over local on load; switching back to session forgets the local copy',()=>{
 const session=memory(),local=memory();
 local.setItem(TOKEN_KEY,'old');session.setItem(TOKEN_KEY,'new');
 assert.equal(loadToken(()=>session,()=>local),'new');
 saveToken('tok',false,()=>session,()=>local);
 assert.equal(local.m.has(TOKEN_KEY),false);
});
test('delete clears both stores',()=>{
 const session=memory(),local=memory();
 session.setItem(TOKEN_KEY,'a');local.setItem(TOKEN_KEY,'b');
 clearToken(()=>session,()=>local);
 assert.equal(session.m.size+local.m.size,0);
 assert.equal(loadToken(()=>session,()=>local),'');
});
test('unavailable storage never throws',()=>{
 assert.equal(loadToken(broken,broken),'');
 assert.doesNotThrow(()=>saveToken('tok',true,broken,broken));
 assert.doesNotThrow(()=>clearToken(broken,broken));
 const local=memory();
 assert.equal((saveToken('tok',false,broken,()=>local),local.m.has(TOKEN_KEY)),false);
});
