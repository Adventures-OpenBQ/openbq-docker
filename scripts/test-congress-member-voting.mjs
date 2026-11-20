// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {test} from 'node:test';
import assert from 'node:assert/strict';
const html=readFileSync(new URL('../provider-fixes/openbb_government_us/congress/assets/member_bio.html',import.meta.url),'utf8');
function render(voting){const body=html.split('function renderVoting() {')[1].split('function renderCommittees()')[0];const section=(title,body)=>({title,body});const node=(text)=>({text,style:{},appendChild(){}});return vm.runInNewContext('(function(){'+body+')',{DATA:{voting},section,el:(_tag,_cls,text)=>node(text),document:{createElement:()=>node(),createTextNode:node}})();}
test('unavailable history is distinct from a completed zero-vote record',()=>{const result=render({status:'unavailable',message:'Full career vote history is not available yet.',total:null});assert.match(result.body.text,/not available|unavailable/i);assert.doesNotMatch(result.body.text,/No On-Passage/);});
test('a complete zero-vote history keeps its empty state',()=>{assert.match(render({yea:0,nay:0,total:0,yea_pct:null}).body.text,/No On-Passage/);});
test('available career totals keep the career chart',()=>{assert.match(render({yea:123,nay:8,total:131,yea_pct:93.9}).title,/career/);});
test('published profile markdown reports unavailable history honestly',()=>{const body=html.split('function profileMarkdown() {')[1].split('function publish(')[0];const text=vm.runInNewContext('(function(){'+body+')',{DATA:{name:'Example',voting:{status:'unavailable',total:null}},safeUrl:()=>false})();assert.match(text,/unavailable|not available/i);assert.doesNotMatch(text,/0 Yea/);});
