// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {request} from 'node:http';
import {once} from 'node:events';
import {validateConfig} from './config.mjs';
import {createGateway} from './server.mjs';
const origin='https://openbq.'+['example-tailnet','ts','net'].join('.')+':10000';
const token='synthetic_test_credential_not_for_deployment';
const config=(extra={})=>validateConfig({origin,...extra},{token,apiUsername:'testuser',apiPassword:'synthetic-password'});
async function delayed(t,path,delay,{settings={},dependencies={}}={}){
 t.mock.timers.enable({apis:['setTimeout']});
 let entered;const started=new Promise(resolve=>entered=resolve);let signal;
 const server=createGateway(config(settings),{requestJson:(_path,_cfg,s)=>new Promise((resolve,reject)=>{signal=s;s.addEventListener('abort',()=>reject(new Error('bounded deadline')),{once:true});setTimeout(()=>resolve({results:[{value:42}]}),delay);entered();}),...dependencies});
 server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.closeGateway());
 const result=new Promise((resolve,reject)=>{const req=request({host:'127.0.0.1',port:server.address().port,path,headers:{Host:new URL(origin).host,Authorization:'Bearer '+token}},res=>{res.resume();res.once('end',()=>resolve(res.statusCode));});req.once('error',reject);req.end();});
 await started;return {result,signal};
}
test('ordinary API GET survives a cold fifteen-second acquisition',async t=>{const x=await delayed(t,'/api/api/v1/cftc/fx_forward_points?pair=USDJPY',15000);t.mock.timers.tick(15000);assert.equal(await x.result,200);assert.equal(x.signal.aborted,false);});
test('reference GET retains its twelve-second deadline',async t=>{const x=await delayed(t,'/ref/metric_widget',15000);t.mock.timers.tick(15000);assert.equal(await x.result,502);assert.equal(x.signal.aborted,true);});
test('configured API deadline aborts before a slower acquisition completes',async t=>{const x=await delayed(t,'/api/api/v1/cftc/fx_forward_points?pair=USDJPY',2000,{settings:{apiTimeoutMs:1000}});t.mock.timers.tick(2000);assert.equal(await x.result,502);assert.equal(x.signal.aborted,true);});
test('explicit factory deadline override remains effective for API GET',async t=>{const x=await delayed(t,'/api/api/v1/cftc/fx_forward_points?pair=USDJPY',2000,{dependencies:{requestMs:10}});t.mock.timers.tick(2000);assert.equal(await x.result,502);});
test('API deadline is bounded and defaults to the cold-lane allowance',()=>{assert.equal(config().apiTimeoutMs,170000);for(const apiTimeoutMs of [0,999,170001,1.5,'170000',null])assert.throws(()=>config({apiTimeoutMs}));assert.equal(config({apiTimeoutMs:1000}).apiTimeoutMs,1000);});
test('client disconnect cancels an ordinary API acquisition',async t=>{
 let entered,cancelled;const started=new Promise(resolve=>entered=resolve),aborted=new Promise(resolve=>cancelled=resolve);
 const server=createGateway(config(),{requestJson:(_path,_cfg,signal)=>new Promise((_resolve,reject)=>{signal.addEventListener('abort',()=>{cancelled();reject(new Error('disconnected'));},{once:true});entered();})});server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.closeGateway());
 const req=request({host:'127.0.0.1',port:server.address().port,path:'/api/api/v1/cftc/fx_forward_points?pair=USDJPY',headers:{Host:new URL(origin).host,Authorization:'Bearer '+token}},res=>res.resume());req.on('error',()=>{});req.end();await started;req.destroy();await aborted;
});
