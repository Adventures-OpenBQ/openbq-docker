// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';
const source=readFileSync(new URL('../provider-fixes/openbb_us_eia/assets/rss_feed.html',import.meta.url),'utf8');
const protocol=source.slice(source.indexOf('function openbbProtocol() {'),source.indexOf('    var list = document.getElementById("list");'));
function fixture(){
 let handler;const navigations=[];const messages=[];
 const location={origin:'https://reader.example',set href(url){navigations.push(url);}};
 const target={postMessage:message=>messages.push(message)};
 const context={DATA:{endpoint:'/api/v1/eia/rss_feed',feed:'today_in_energy',theme:'dark',items:[]},document:{documentElement:{setAttribute(){}},getElementById:()=>({classList:{add(){}},textContent:''})},window:{top:target,parent:target,location,addEventListener:(_,cb)=>{handler=cb;}},requestAnimationFrame:cb=>cb(),URL,URLSearchParams};
 vm.runInNewContext(protocol+';openbbProtocol();',context);
 return {navigations,messages,send:params=>handler({data:{type:'openbb-params-update',params}})};
}
test('identical parameters sent on connect do not reload the feed',()=>{const x=fixture();x.send({feed:'today_in_energy',theme:'dark'});x.send({feed:'today_in_energy',theme:'dark'});assert.equal(x.navigations.length,0);});
test('identical theme-only update does not reload',()=>{const x=fixture();x.send({theme:'dark'});assert.equal(x.navigations.length,0);});
test('changed feed navigates to the same HTTPS endpoint with current theme',()=>{const x=fixture();x.send({feed:'press_releases'});assert.equal(x.navigations.length,1);const u=new URL(x.navigations[0]);assert.equal(u.origin,'https://reader.example');assert.equal(u.searchParams.get('feed'),'press_releases');assert.equal(u.searchParams.get('theme'),'dark');});
test('changed theme navigates once and preserves the selected feed',()=>{const x=fixture();x.send({theme:'light'});assert.equal(x.navigations.length,1);const u=new URL(x.navigations[0]);assert.equal(u.searchParams.get('feed'),'today_in_energy');assert.equal(u.searchParams.get('theme'),'light');});
