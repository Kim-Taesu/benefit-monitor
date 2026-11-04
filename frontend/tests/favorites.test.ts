import {test} from 'node:test';
import assert from 'node:assert/strict';
import {FAVORITES_KEY,benefitKey,loadFavorites,saveFavorites,clearFavorites,visibleFavorites,searchShareUrl} from '../src/favorites.ts';
import {adapt,readFilters} from '../src/benefits.ts';
import {item,snapshot,NOW} from './fixtures.ts';
const memory=()=>{const values=new Map<string,string>();return {getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>{values.set(k,v);},removeItem:(k:string)=>{values.delete(k);}};};
test('stores only stable identifiers, deduplicates and clears',()=>{
 const s=memory(),id=benefitKey(item());assert.equal(saveFavorites(s,[id,id]),true);assert.deepEqual(loadFavorites(s),[id]);
 assert.deepEqual(JSON.parse(s.getItem(FAVORITES_KEY)!),{version:1,ids:[id]});assert.equal(clearFavorites(s),true);assert.deepEqual(loadFavorites(s),[]);
});
test('invalid records, versions and blocked storage remain safe and clearable',()=>{
 const s=memory();for(const value of ['{','null','[]','{"version":2,"ids":[]}','{"version":1,"ids":[3]}','{"version":1,"ids":[],"private":"x"}']){s.setItem(FAVORITES_KEY,value);assert.deepEqual(loadFavorites(s),[]);assert.equal(clearFavorites(s),true);}
 const blocked={getItem(){throw Error();},setItem(){throw Error();},removeItem(){throw Error();}};
 for(const storage of [null,blocked]){assert.deepEqual(loadFavorites(storage),[]);assert.equal(saveFavorites(storage,['id']),false);assert.equal(clearFavorites(storage),false);}
});
test('limits stored identifiers without overwriting a valid set on rejection',()=>{
 const s=memory();assert.equal(saveFavorites(s,['kept']),true);assert.equal(saveFavorites(s,Array.from({length:201},(_,i)=>String(i))),false);assert.deepEqual(loadFavorites(s),['kept']);assert.equal(saveFavorites(s,['x'.repeat(4097)]),false);
});
test('favorites cannot revive expired, stale, unverified or missing records',()=>{
 const id=benefitKey(item());assert.equal(visibleFavorites(adapt(snapshot([item()]),NOW).items,[id]).length,1);
 for(const body of [snapshot([item({needs_recheck:true})]),snapshot([item({display_until:new Date(NOW).toISOString()})]),snapshot([item()],{valid_through:new Date(NOW).toISOString()}),snapshot([item()],{status:'collection_failed'})])assert.deepEqual(visibleFavorites(adapt(body,NOW).items,[id]),[]);
});
test('share URL carries only current search filters, never unrelated data or local favorite IDs',()=>{
 const url=searchShareUrl(new URL('https://example.org/benefit-monitor/?private=value&saved=1#secret'),{...readFilters(''),q:'강좌',region:'은평구'});
 assert.equal(url.origin,'https://example.org');assert.equal(url.pathname,'/benefit-monitor/');assert.equal(url.searchParams.get('q'),'강좌');assert.equal(url.searchParams.get('region'),'은평구');assert.equal(url.searchParams.has('private'),false);assert.equal(url.searchParams.has('saved'),false);assert.equal(url.hash,'');
});
test('sharing all filters explicitly overrides a recipient remembered default',()=>{
 const url=searchShareUrl(new URL('https://example.org/benefit-monitor/'),readFilters(''));
 assert.equal(url.searchParams.get('sort'),'deadline');
});
