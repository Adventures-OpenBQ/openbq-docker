// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createServer,request} from 'node:http';
import {createGateway} from './server.mjs';
import {validateConfig} from './config.mjs';
import * as policy from './policy.mjs';
const token='synthetic_study_test_credential_not_for_deployment';
const origin='https://openbq.'+['example','ts','net'].join('.');
function call(port,path,{method='GET',body,auth=true}={}) {
 return new Promise((resolve,reject)=>{
  const headers={host:new URL(origin).host,origin};
  if(auth)headers.authorization=`Bearer ${token}`;
  if(body!==undefined){headers['content-type']='application/json';headers['content-length']=Buffer.byteLength(body);}
  const req=request({host:'127.0.0.1',port,path,method,headers},res=>{const parts=[];res.on('data',c=>parts.push(c));res.on('end',()=>resolve({status:res.statusCode,body:Buffer.concat(parts).toString()}));});
  req.on('error',reject);req.end(body);
 });
}
test('study route contract is exact, bounded GET and POST',()=>{
 assert.equal(typeof policy.studyRoute,'function');
 assert.deepEqual(policy.studyRoute(new URL('/grid/study_catalog',origin),'GET'),{path:'/grid/study_catalog',method:'GET'});
 assert.deepEqual(policy.studyRoute(new URL('/grid/study_results',origin),'POST'),{path:'/grid/study_results',method:'POST'});
 for(const [path,method] of [['/grid/study_results','GET'],['/grid/study_catalog','POST'],['/grid/study_results?upstream=http://evil.test','POST'],['/grid/study_results/','POST']])assert.equal(policy.studyRoute(new URL(path,origin),method),null);
});
test('real gateway study proxy keeps auth, fixed upstream and body limits',async t=>{
 const calls=[];
 const up=createServer((req,res)=>{const parts=[];req.on('data',c=>parts.push(c));req.on('end',()=>{calls.push({url:req.url,auth:req.headers.authorization,body:Buffer.concat(parts).toString()});res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({schema_version:1,results:[]}));});});
 up.listen(0,'127.0.0.1');await once(up,'listening');t.after(()=>new Promise(resolve=>up.close(resolve)));
 const config=validateConfig({origin,liveGrid:true},{token,apiUsername:'test',apiPassword:'synthetic'});
 config.gridOrigin=`http://127.0.0.1:${up.address().port}`;
 const gateway=createGateway(config);gateway.listen(0,'127.0.0.1');await once(gateway,'listening');t.after(()=>gateway.closeGateway());
 const port=gateway.address().port;
 assert.equal((await call(port,'/grid/study_catalog',{auth:false})).status,401);
 assert.equal((await call(port,'/grid/study_catalog')).status,200);
 const body=JSON.stringify({schema_version:1,symbols:['AAPL'],columns:[]});
 assert.equal((await call(port,'/grid/study_results',{method:'POST',body})).status,200);
 assert.equal(calls[1].url,'/study_results');assert.equal(calls[1].body,body);assert.equal(calls[1].auth,config.apiAuthorization);
 assert.equal((await call(port,'/grid/study_results',{method:'POST',body:'x'.repeat(65537)})).status,413);
 assert.equal((await call(port,'/grid/study_results?upstream=http://evil.test',{method:'POST',body})).status,404);
 assert.equal(calls.length,2);
});
test('study response limit and upstream errors remain bounded and private',async t=>{
 const {requestStudy}=await import('./server.mjs');
 let mode='oversize';
 const up=createServer((_req,res)=>{
  if(mode==='oversize'){res.writeHead(200,{'content-length':2*1024*1024+1});res.end('');}
  else if(mode==='secret'){res.writeHead(401);res.end('private upstream credential detail');}
  else {res.writeHead(200);res.end('{"schema_version":1,"value":1e400}');}
 });
 up.listen(0,'127.0.0.1');await once(up,'listening');t.after(()=>new Promise(resolve=>{up.closeAllConnections();up.close(resolve);}));
 const cfg={gridOrigin:`http://127.0.0.1:${up.address().port}`,apiAuthorization:'Basic synthetic'};
 await assert.rejects(requestStudy('GET','/grid/study_catalog',undefined,cfg),/response limit/);
 mode='secret';const denied=await requestStudy('GET','/grid/study_catalog',undefined,cfg);
 assert.equal(denied.status,502);assert.ok(!JSON.stringify(denied).includes('private'));
 mode='nonfinite';await assert.rejects(requestStudy('GET','/grid/study_catalog',undefined,cfg),/invalid study response/);
});
test('study error response closes an endless upstream body before returning its slot',async t=>{
 const {requestStudy}=await import('./server.mjs');
 let closed;
 const socketClosed=new Promise(resolve=>{closed=resolve;});
 const up=createServer((req,res)=>{
  req.socket.once('close',()=>closed());
  res.writeHead(503,{'content-type':'application/json'});
  res.write('{"private":"'); // Never end: the safe error classification needs no body.
 });
 up.listen(0,'127.0.0.1');await once(up,'listening');
 t.after(()=>new Promise(resolve=>{up.closeAllConnections();up.close(resolve);}));
 const result=await requestStudy('GET','/grid/study_catalog',undefined,{gridOrigin:`http://127.0.0.1:${up.address().port}`,apiAuthorization:'Basic synthetic'});
 assert.equal(result.status,503);
 let timer;
 try { await Promise.race([socketClosed,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('error body remained connected')),250);})]); }
 finally {clearTimeout(timer);}
});
