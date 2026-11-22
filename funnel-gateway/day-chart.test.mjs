// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import * as policy from './policy.mjs';
import {getJson} from './server.mjs';
const origin='https://openbq.'+['example','ts','net'].join('.');
const png=Buffer.from('89504e470d0a1a0a00000000','hex');
test('Day Chart and symbol logo paths accept exact bounded symbol queries',()=>{
 for(const route of ['/grid/day_charts?symbol=AAPL,MSFT','/grid/day_charts?symbol=AAPL,CL=F','/grid/symbol_logo?symbol=AAPL'])assert.equal(policy.upstreamPath(new URL(route,origin),{liveGrid:true}),route.replace(',','%2C').replace('=F','%3DF'));
 for(const route of ['/grid/day_charts','/grid/day_charts?symbol=','/grid/day_charts?symbol='+Array(21).fill('AAPL').join(','),'/grid/day_charts?symbol=AAPL&url=https://evil.test','/grid/symbol_logo?symbol=AAPL,MSFT','/grid/symbol_logo?symbol=AAPL&symbol=MSFT','/grid/symbol_logo/?symbol=AAPL'])assert.equal(policy.upstreamPath(new URL(route,origin),{liveGrid:true}),null,route);
});
test('raster validation requires a safe matching MIME and signature',()=>{
 assert.equal(typeof policy.rasterType,'function');assert.equal(policy.rasterType(png,'image/png'),'image/png');
 for(const type of ['image/svg+xml','text/html','image/jpeg'])assert.equal(policy.rasterType(png,type),null);
 assert.equal(policy.rasterType(Buffer.from('<svg/>'),'image/png'),null);
});
test('gateway fetches logo bytes using only server auth and rejects unsafe or oversized answers',async t=>{
 let type='image/png',body=png,status=200;const calls=[];
 const server=createServer((req,res)=>{calls.push({path:req.url,auth:req.headers.authorization});res.writeHead(status,{'content-type':type});res.end(body);});
 server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
 const cfg={gridOrigin:`http://127.0.0.1:${server.address().port}`,apiAuthorization:'Basic synthetic'};
 const value=await getJson('/grid/symbol_logo?symbol=AAPL',cfg,AbortSignal.timeout(1000));assert.deepEqual(value.bytes,png);assert.equal(value.mime,'image/png');assert.deepEqual(calls[0],{path:'/symbol_logo?symbol=AAPL',auth:'Basic synthetic'});
 type='image/svg+xml';await assert.rejects(getJson('/grid/symbol_logo?symbol=AAPL',cfg,AbortSignal.timeout(1000)));
 type='image/png';body=Buffer.alloc(262145);await assert.rejects(getJson('/grid/symbol_logo?symbol=AAPL',cfg,AbortSignal.timeout(1000)));
 body=png;status=302;await assert.rejects(getJson('/grid/symbol_logo?symbol=AAPL',cfg,AbortSignal.timeout(1000)));
});
test('trading-day query is bounded and never accepted for logos',()=>{
 assert.equal(policy.upstreamPath(new URL('/grid/day_charts?symbol=AAPL&days=2',origin),{liveGrid:true}),'/grid/day_charts?symbol=AAPL&days=2');
 for(const route of ['/grid/day_charts?symbol=AAPL&days=0','/grid/day_charts?symbol=AAPL&days=6','/grid/day_charts?symbol=AAPL&days=2&days=3','/grid/symbol_logo?symbol=AAPL&days=2'])assert.equal(policy.upstreamPath(new URL(route,origin),{liveGrid:true}),null);
});
test('closed-session history admits only a single symbol and approved interval',()=>{
 assert.equal(policy.upstreamPath(new URL('/grid/closed_session?symbol=MSFT&interval=1m',origin),{liveGrid:true}),'/grid/closed_session?symbol=MSFT&interval=1m');
 for(const route of ['/grid/closed_session?symbol=AAPL,MSFT','/grid/closed_session?symbol=AAPL&interval=evil','/grid/closed_session?symbol=AAPL&url=https://evil.test','/grid/closed_session?symbol=AAPL&symbol=MSFT'])assert.equal(policy.upstreamPath(new URL(route,origin),{liveGrid:true}),null);
});
