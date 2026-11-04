import {test} from 'node:test';
import assert from 'node:assert/strict';
import {INTERESTS_KEY,loadInterests,saveInterests,clearInterests,initialInterests} from '../src/preferences.ts';
const memory=()=>{const values=new Map<string,string>();return {getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>{values.set(k,v);},removeItem:(k:string)=>{values.delete(k);}};};
test('only explicit region/category are saved and restored',()=>{
 const storage=memory();const value={region:'은평구',category:'생활지원'};
 assert.equal(saveInterests(storage,value),true);assert.deepEqual(loadInterests(storage),value);
 assert.deepEqual(JSON.parse(storage.getItem(INTERESTS_KEY)!),{version:1,...value});
 assert.equal(clearInterests(storage),true);assert.equal(loadInterests(storage),null);
});
test('damaged, invalid, unexpected or outdated stored values are ignored',()=>{
 const storage=memory();
 for(const value of ['{', 'null','[]',JSON.stringify({version:2,region:'서울',category:''}),JSON.stringify({version:1,region:42,category:''}),JSON.stringify({version:1,region:'서울',category:'unknown'}),JSON.stringify({version:1,region:'서울',category:'',secret:'unexpected'})]){
  storage.setItem(INTERESTS_KEY,value);assert.equal(loadInterests(storage),null);
 }
});
test('missing or blocked browser storage never breaks discovery or claims success',()=>{
 const denied={getItem(){throw Error('denied');},setItem(){throw Error('quota');},removeItem(){throw Error('denied');}};
 for(const storage of [null,denied]){assert.equal(loadInterests(storage),null);assert.equal(saveInterests(storage,{region:'서울',category:''}),false);assert.equal(clearInterests(storage),false);}
});
test('link filters take precedence; unrelated query values do not disable remembered defaults',()=>{
 const stored={region:'은평구',category:'생활지원'};
 assert.deepEqual(initialInterests('',stored),stored);
 assert.deepEqual(initialInterests('?utm_source=direct',stored),stored);
 for(const query of ['?q=강좌','?region=','?category=','?sort=title','?status=urgent']) assert.equal(initialInterests(query,stored),null);
});
test('empty preferences and explicit unknown regions are never broadened',()=>{
 const storage=memory();assert.equal(saveInterests(storage,{region:'서울·경기',category:''}),true);
 assert.deepEqual(loadInterests(storage),{region:'서울·경기',category:''});
 assert.equal(saveInterests(storage,{region:'',category:''}),true);assert.deepEqual(loadInterests(storage),{region:'',category:''});
});
