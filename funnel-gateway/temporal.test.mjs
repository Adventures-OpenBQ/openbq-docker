// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { createServer, request } from 'node:http';
import { validateConfig } from './config.mjs';
import { createGateway } from './server.mjs';
import { upstreamPath } from './policy.mjs';
import * as overlay from './temporal-policy.mjs';
const root = '/temporal/temporal/v1';
const id = '11111111-1111-4111-8111-111111111111';
const token = 'synthetic_gateway_token_only_for_tests';
const upstreamToken = 'synthetic_temporal_token_only_for_tests';
const settings = { origin: 'https://' + ['fixture','example','ts','net'].join('.') + ':10000' };
const secrets = { token, apiUsername: 'fixture', apiPassword: 'fixture', temporalToken: upstreamToken };

test('v11 is explicit, exact route/method/query admission; v10 remains closed', () => {
  for (const [method,path] of [['GET','/temporal/'],['GET','/temporal/widgets.json'],['GET',root+'/capabilities'],['GET',root+'/queries'],['POST',root+'/queries'],['PUT',root+'/queries/'+id],['GET',root+'/queries/'+id+'?revision=2'],['POST',root+'/executions'],['GET',root+'/executions/'+id+'/pages?cursor=abc_123.def-456'],['DELETE',root+'/executions/'+id],['POST',root+'/audits'],['GET',root+'/audits/'+id],['POST',root+'/audits/'+id+'/replay']]) {
    const url = new URL(path, settings.origin);
    assert.equal(overlay.temporalRoute(url, method, {temporalDB:true})?.path, path, method+' '+path);
    assert.equal(overlay.temporalRoute(url, method, {}), null);
    assert.equal(upstreamPath(url, {temporalDB:true}), null);
  }
  for (const [method,path] of [['POST','/temporal/widgets.json'],['GET',root+'/captures'],['POST',root+'/executions/'+id],['PUT',root+'/audits/'+id],['GET',root+'/queries/'+id+'?revision=0'],['GET',root+'/queries/'+id+'?revision=2&revision=3'],['GET',root+'/executions/'+id+'/pages?url=https://evil.test'],['GET',root+'/executions/'+id+'/pages?cursor=x%0A'],['GET',root+'/executions/not-uuid/pages'],['GET','/temporal/docs'],['GET','/temporal/temporal/v2/queries']]) assert.equal(overlay.temporalRoute(new URL(path, settings.origin),method,{temporalDB:true}),null,method+' '+path);
});

test('TemporalDB config requires explicit opt-in and a separate secret; target is fixed', () => {
  assert.equal(validateConfig(settings,secrets).temporalOrigin,null);
  const cfg = validateConfig({...settings, temporalDB:true},secrets);
  assert.equal(cfg.temporalOrigin,'http://temporaldb-api:8080');
  assert.equal(cfg.temporalAuthorization,'Bearer '+upstreamToken);
  for (const patch of [{temporalDB:'true'},{temporalDB:null},{temporalOrigin:'https://evil.test'}]) assert.throws(()=>validateConfig({...settings,...patch},secrets));
  for (const bad of [undefined,'',token,'bad\ncredential']) assert.throws(()=>validateConfig({...settings,temporalDB:true},{...secrets,temporalToken:bad}));
});

async function listen(server) { server.listen(0,'127.0.0.1'); await once(server,'listening'); return 'http://127.0.0.1:'+server.address().port; }
test('TemporalDB web credentials are bounded, distinct and require the trusted relay', () => {
  const relay='synthetic_distinct_relay_token_for_tests';
  const user='synthetic_first_user_temporal_token_for_tests';
  const good={...secrets,tableRelayToken:relay,temporalPrincipalTokens:{'github:42':user}};
  assert.equal(validateConfig({...settings,temporalDB:true},good).temporalPrincipalTokens['github:42'],user);
  for(const value of [null,[],{'github:0':user},{'desktop:owner':user},{'github:42':'short'},{'github:42':upstreamToken},{'github:42':token},{'github:42':relay},{'github:42':user,'github:43':user}])
    assert.throws(()=>validateConfig({...settings,temporalDB:true},{...good,temporalPrincipalTokens:value}));
  assert.throws(()=>validateConfig({...settings,temporalDB:true},{...good,tableRelayToken:undefined}));
  assert.throws(()=>validateConfig(settings,good));
});
test('TemporalDB selects a scoped token only for a verified mapped web principal', async t => {
  const relay='synthetic_distinct_relay_token_for_tests';
  const tokens={'github:42':'synthetic_first_user_temporal_token_for_tests','github:43':'synthetic_second_user_temporal_token_for_tests'};
  const seen=[];
  const upstream=createServer((req,res)=>{seen.push(req.headers);res.writeHead(200,{'Content-Type':'application/json'});res.end('{}');});
  const temporalOrigin=await listen(upstream);t.after(()=>new Promise(resolve=>upstream.close(resolve)));
  const gateway=createGateway({...validateConfig({...settings,temporalDB:true},{...secrets,tableRelayToken:relay,temporalPrincipalTokens:tokens}),temporalOrigin});
  await listen(gateway);t.after(()=>gateway.closeGateway());const port=gateway.address().port;
  for(const principal of Object.keys(tokens)) {
    assert.equal((await call(port,root+'/queries',{headers:{'x-table-relay-token':relay,'x-table-principal':principal}})).status,200);
    assert.equal(seen.at(-1).authorization,'Bearer '+tokens[principal]);
    assert.equal(seen.at(-1)['x-table-relay-token'],undefined);
    assert.equal(seen.at(-1)['x-table-principal'],undefined);
  }
  const before=seen.length;
  for(const headers of [
    {'x-table-relay-token':'wrong','x-table-principal':'github:42'},
    {'x-table-relay-token':relay,'x-table-principal':'github:44'},
    {'x-table-relay-token':relay}, {'x-table-principal':'github:42'},
    {'x-table-relay-token':relay,'x-table-principal':['github:42','github:43']},
    {'x-table-relay-token':[relay,relay],'x-table-principal':'github:42'},
  ]) assert.equal((await call(port,root+'/queries',{headers})).status,403);
  assert.equal(seen.length,before);
  assert.equal((await call(port,root+'/queries')).status,200);
  assert.equal(seen.at(-1).authorization,'Bearer '+upstreamToken);
});
function call(port,path,{method='GET',body,headers={}}={}) { return new Promise((resolve,reject)=>{
  const req=request({hostname:'127.0.0.1',port,path,method,headers:{host:new URL(settings.origin).host,authorization:'Bearer '+token,...headers}},res=>{const chunks=[];res.on('data',c=>chunks.push(c));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(chunks).toString()}));}); req.on('error',reject);req.end(body);
}); }
test('gateway strips one prefix, replaces all credentials, bounds requests and suppresses upstream errors', async t => {
  const seen=[];
  const upstream=createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{seen.push({path:req.url,method:req.method,headers:req.headers,body});res.writeHead(req.url.endsWith('/queries')?201:409,{'Content-Type':'application/json','Set-Cookie':'secret=leak','WWW-Authenticate':'secret'});res.end(req.url.endsWith('/queries')?'{"query_id":"fixture"}':JSON.stringify({password:'must-not-leak'}));});});
  const temporalOrigin=await listen(upstream); t.after(()=>new Promise(resolve=>upstream.close(resolve)));
  const gateway=createGateway({...validateConfig({...settings,temporalDB:true},secrets),temporalOrigin});await listen(gateway);t.after(()=>gateway.closeGateway());const port=gateway.address().port;
  const response=await call(port,root+'/queries',{method:'POST',body:'{"name":"fixture"}',headers:{'content-type':'application/json','cookie':'browser=secret','x-temporaldb-token':'browser-secret'}});
  assert.equal(response.status,201);assert.equal(response.headers['set-cookie'],undefined);assert.equal(seen[0].path,'/temporal/v1/queries');assert.equal(seen[0].headers.authorization,'Bearer '+upstreamToken);assert.equal(seen[0].headers.cookie,undefined);assert.equal(seen[0].headers['x-temporaldb-token'],undefined);
  const failure=await call(port,root+'/executions/'+id+'/pages');assert.equal(failure.status,409);assert.doesNotMatch(failure.body,/password|must-not-leak/);
  const count=seen.length;
  for(const [options,status] of [[{method:'POST',body:'{}',headers:{'content-type':'application/jsonp'}},415],[{method:'POST',body:'{}',headers:{'content-type':'text/plain'}},415],[{method:'POST',body:'{',headers:{'content-type':'application/json'}},400],[{method:'POST',body:'{}',headers:{authorization:'Bearer wrong','content-type':'application/json'}},401],[{method:'POST',body:'{}',headers:{origin:'https://evil.test','content-type':'application/json'}},403]]) assert.equal((await call(port,root+'/queries',options)).status,status);
  assert.equal(seen.length,count);
});

test('a slow POST body cannot race past the TemporalDB concurrency cap', async t => {
  let release; const arrived=new Promise(resolve=>release=resolve);
  let upstreamResponse;
  const upstream=createServer((req,res)=>{upstreamResponse=res;release();});
  const temporalOrigin=await listen(upstream);t.after(()=>{upstream.closeAllConnections();return new Promise(resolve=>upstream.close(resolve));});
  const gateway=createGateway({...validateConfig({...settings,temporalDB:true,maxConcurrent:1},secrets),temporalOrigin});await listen(gateway);t.after(()=>gateway.closeGateway());const port=gateway.address().port;
  let slow;
  const pending=new Promise((resolve,reject)=>{
    slow=request({hostname:'127.0.0.1',port,path:root+'/queries',method:'POST',headers:{host:new URL(settings.origin).host,authorization:'Bearer '+token,'content-type':'application/json','content-length':'2'}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});slow.on('error',reject);slow.write('{');
  });
  // Let the first request wait for its body before a second takes the upstream slot.
  await new Promise(resolve=>setTimeout(resolve,30));
  const active=call(port,root+'/queries');await arrived;slow.end('}');
  assert.equal(await pending,429);
  upstreamResponse.writeHead(200,{'Content-Type':'application/json'});upstreamResponse.end('{}');await active;
});

test('protected publication routes admit only canonical exact POST and GET shapes', () => {
  const collection = root+'/audits/'+id+'/publications';
  const item = collection+'/'+id;
  for (const [method,path] of [['POST',collection],['GET',item]]) {
    assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true})?.path,path);
    assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{}),null);
  }
  for (const [method,path] of [
    ['GET',collection],['POST',item],['PUT',item],['DELETE',item],
    ['POST',collection+'?format=arrow-ipc-stream-v1'],['GET',item+'?cursor=x'],
    ['GET',item+'/extra'],['POST',collection+'/'],
    ['GET',collection+'/AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'],
    ['GET',collection+'/not-uuid'],['GET',collection+'/%2e%2e%2f'+id],
  ]) assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true}),null,method+' '+path);
});

test('v11 explorer: cache discovery and validation admit exact shapes only', () => {
  for (const [method,path] of [['GET',root+'/cache/datasets'],['GET',root+'/cache/datasets?cursor=eyJh_-0.1f2e&limit=50'],['GET',root+'/cache/datasets?limit=100'],['POST',root+'/cache/describe'],['POST',root+'/cache/coverage'],['POST',root+'/queries/validate']]) {
    assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true})?.path,path,method+' '+path);
    assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{}),null);
  }
  for (const [method,path] of [['POST',root+'/cache/datasets'],['GET',root+'/cache/describe'],['GET',root+'/cache/coverage'],['GET',root+'/queries/validate'],
    ['GET',root+'/cache/datasets?limit=0'],['GET',root+'/cache/datasets?limit=101'],['GET',root+'/cache/datasets?limit=5&limit=6'],['GET',root+'/cache/datasets?tier=gold'],
    ['POST',root+'/cache/coverage?cursor=x'],['GET',root+'/cache/other'],['GET',root+'/queries/page'],['POST',root+'/cache/describe/'+id]])
    assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true}),null,method+' '+path);
});

test('v11 acquisition permits only exact read, preflight and caller run routes',()=>{
 for(const [method,path] of [['GET',root+'/acquisition/policies'],['GET',root+'/acquisition/policies/'+id+'?revision=3'],['POST',root+'/acquisition/preflight'],['POST',root+'/runs'],['GET',root+'/runs/'+id],['DELETE',root+'/runs/'+id]]){
  assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true})?.path,path);
  assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{}),null);
 }
 for(const [method,path] of [['POST',root+'/acquisition/policies'],['PUT',root+'/acquisition/policies/'+id],['GET',root+'/acquisition/preflight'],['GET',root+'/runs'],['PUT',root+'/runs/'+id],['POST',root+'/runs/'+id],['GET',root+'/runs/'+id+'?policy=forged'],['GET',root+'/acquisition/policies/'+id+'?revision=1&revision=2'],['POST',root+'/acquisition/preflight?account=forged'],['GET',root+'/runs/not-uuid']])assert.equal(overlay.temporalRoute(new URL(path,settings.origin),method,{temporalDB:true}),null);
});
