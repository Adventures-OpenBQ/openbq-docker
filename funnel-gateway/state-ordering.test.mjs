// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {request} from 'node:http';
import {once} from 'node:events';
import {mkdtemp,rm,mkdir,writeFile,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createGateway} from './server.mjs';
import {validateConfig} from './config.mjs';
const writer='11111111-1111-4111-8111-111111111111', other='22222222-2222-4222-8222-222222222222';
const origin=`https://openbq.${['example-tailnet','ts','net'].join('.')}:10000`, token='synthetic_state_test_credential_not_deployable';
async function fixture(t,dir){
  const stateDir=dir??await mkdtemp(join(tmpdir(),'state-fence-test-'));
  if(!dir)t.after(()=>rm(stateDir,{recursive:true,force:true}));
  const config=validateConfig({origin,stateDir},{token,apiUsername:'test',apiPassword:'test'});
  const server=createGateway(config);server.listen(0,'127.0.0.1');await once(server,'listening');
  t.after(()=>server.closeGateway());
  function start(method,body,seq,id=writer,name='settings.json',headers={}){
    let req;
    const done=new Promise((resolve,reject)=>{
      req=request({host:'127.0.0.1',port:server.address().port,path:'/state/42'+(name?'/'+name:''),method,
        headers:{Host:new URL(origin).host,Authorization:`Bearer ${token}`,
          ...(body===undefined?{}:{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}),
          ...(seq===undefined?{}:{'X-BDOBB-State-Writer':id,'X-BDOBB-State-Sequence':String(seq)}),...headers}},res=>{
        const parts=[];res.on('data',c=>parts.push(c));res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body:Buffer.concat(parts).toString()}));
      });req.on('error',reject);
    });return {req,done};
  }
  async function send(...args){const call=start(...args);call.req.end(args[1]);return call.done;}
  return {server,stateDir,start,send};
}

test('state commit fences held older bodies, exact duplicates, delete, other writers and restart',async t=>{
  const f=await fixture(t);
  const late=f.start('PUT','{"old":true}',1);late.done.catch(()=>{});t.after(()=>late.req.destroy());late.req.flushHeaders();
  const newer=await f.send('PUT','{"new":true}',2);
  assert.equal(newer.status,204);
  late.req.end('{"old":true}');const lateResult=await late.done;
  assert.equal(JSON.parse((await f.send('GET',undefined,undefined,writer,'')).body).files['settings.json'],'{"new":true}');
  assert.equal(lateResult.status,409);
  assert.equal(newer.headers['x-bdobb-state-writer'],writer);assert.equal(newer.headers['x-bdobb-state-sequence'],'2');
  assert.equal((await f.send('PUT','{"different":true}',2)).status,409);
  assert.equal((await f.send('PUT','{"new":true}',2)).status,204);
  assert.equal((await f.send('PUT','{"other":true}',1,other)).status,204);
  const restarted=await fixture(t,f.stateDir);
  assert.equal((await restarted.send('PUT','{"old":true}',1)).status,409);
  assert.equal((await restarted.send('DELETE',undefined,3)).status,204);
  const again=await fixture(t,f.stateDir);
  assert.equal((await again.send('PUT','{"new":true}',2)).status,409);
  assert.deepEqual(JSON.parse((await again.send('GET',undefined,undefined,writer,'')).body),{files:{}});
  assert.equal((await again.send('DELETE',undefined,3)).status,204);
  assert.equal((await again.send('PUT','{}')).status,409); // legacy cannot undo a versioned tombstone
});

test('state imports legacy JSON once, preserves raw map, and validates version headers',async t=>{
  const f=await fixture(t);await mkdir(join(f.stateDir,'42'));await writeFile(join(f.stateDir,'42','settings.json'),'{"legacy":1}');
  assert.equal((await f.send('PUT','{"v":2}',1)).status,204);
  const listed=JSON.parse((await f.send('GET',undefined,undefined,writer,'')).body);assert.equal(listed.files['settings.json'],'{"v":2}');
  for(const value of ['0','01','-1','1.0','9007199254740992'])assert.equal((await f.send('PUT','{}',value)).status,400);
  assert.equal((await f.send('PUT','{}',2,'INVALID')).status,400);
  assert.equal((await f.send('PUT','{}',undefined,writer,'settings.json',{'X-BDOBB-State-Writer':writer})).status,400);
  assert.equal((await f.send('PUT','{}',2,writer,'../settings.json')).status,421);
  await f.send('DELETE',undefined,2);
  assert.deepEqual(JSON.parse((await f.send('GET',undefined,undefined,writer,'')).body),{files:{}});
});

test('legacy symlink files cannot be imported into fenced state',async t=>{
  const f=await fixture(t);await mkdir(join(f.stateDir,'42'));
  await writeFile(join(f.stateDir,'outside'),'{}');await symlink(join(f.stateDir,'outside'),join(f.stateDir,'42','settings.json'));
  assert.equal((await f.send('PUT','{}',1)).status,502);
});
