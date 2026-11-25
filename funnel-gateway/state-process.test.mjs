// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtemp,rm,writeFile,mkdir,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {commitState,readState} from './state-store.mjs';
const moduleUrl=new URL('./state-store.mjs',import.meta.url).href;
const writer='11111111-1111-4111-8111-111111111111';
function version(sequence){return {writer,sequence,raw:String(sequence)};}
function child(code,args=[]){
  const proc=spawn(process.execPath,['--input-type=module','-e',code,...args],{stdio:['ignore','pipe','pipe']});
  let stdout='',stderr='';proc.stdout.on('data',c=>stdout+=c);proc.stderr.on('data',c=>stderr+=c);
  const done=new Promise((resolve,reject)=>{proc.on('error',reject);proc.on('close',status=>status===0?resolve(stdout):reject(Error(stderr||`exit ${status}`)));});
  return {proc,done};
}
async function temp(t){const root=await mkdtemp(join(tmpdir(),'state-sql-process-'));t.after(()=>rm(root,{recursive:true,force:true}));return join(root,'42');}

test('independent processes racing sequences converge on greatest committed sequence',async t=>{
  const dir=await temp(t);
  const jobs=Array.from({length:12},(_,i)=>child(`import {commitState} from ${JSON.stringify(moduleUrl)};const n=Number(process.argv[2]);console.log(commitState(process.argv[1],'settings.json',JSON.stringify({n}),{writer:${JSON.stringify(writer)},sequence:n,raw:String(n)}));`,[dir,String(i+1)]));
  const statuses=await Promise.all(jobs.map(j=>j.done));assert(statuses.every(s=>['204','409'].includes(s.trim())));
  assert.deepEqual(JSON.parse(readState(dir)['settings.json']),{n:12});
  assert.equal(commitState(dir,'settings.json','{"n":11}',version(11)),409);
});

test('killed midtransaction process leaves both prior body and fence recoverable',async t=>{
  const dir=await temp(t);assert.equal(commitState(dir,'settings.json','{"n":1}',version(1)),204);
  const job=child(`import {DatabaseSync} from 'node:sqlite';const db=new DatabaseSync(process.argv[1]+'/.state.sqlite');db.exec('BEGIN IMMEDIATE');db.prepare('UPDATE records SET body=?,fences=? WHERE name=?').run('{"n":999}','{}','settings.json');console.log('uncommitted');setInterval(()=>{},1000);`,[dir]);job.done.catch(()=>{});
  await once(job.proc.stdout,'data');job.proc.kill('SIGKILL');await once(job.proc,'close');
  assert.equal(readState(dir)['settings.json'],'{"n":1}');assert.equal(commitState(dir,'settings.json','{}',version(1)),409);
  assert.equal(commitState(dir,'settings.json','{"n":2}',version(2)),204);
});

test('account byte/file quota, one-time legacy import and symlink database refusal',async t=>{
  const dir=await temp(t);await mkdir(dir);await writeFile(join(dir,'settings.json'),'{"legacy":true}');
  assert.equal(commitState(dir,'dashboards/seed.json','{}',null),204);
  await writeFile(join(dir,'settings.json'),'{"stale":true}');assert.equal(readState(dir)['settings.json'],'{"legacy":true}');
  const big=JSON.stringify('x'.repeat(262138));
  for(let n=0;n<7;n++)assert.equal(commitState(dir,`dashboards/d${n}.json`,big,null),204);
  assert.equal(commitState(dir,'dashboards/last.json',big,null),204);
  assert.equal(commitState(dir,'dashboards/overflow.json','"overflow-past-byte-budget"',null),413);
  for(let n=0;n<8;n++)assert.equal(commitState(dir,`dashboards/${n===7?'last':'d'+n}.json`,null,null),204);
  for(let n=0;n<198;n++)assert.equal(commitState(dir,`dashboards/f${n}.json`,'{}',null),204);
  assert.equal(commitState(dir,'dashboards/overflow.json','{}',null),413);
  assert.throws(()=>commitState(dir,'../settings.json','{}',version(1)),/Unsafe/);
  const other=join(dir,'..','43');await mkdir(other);await symlink(join(dir,'.state.sqlite'),join(other,'.state.sqlite'));
  assert.throws(()=>commitState(other,'settings.json','{}',version(1)),/Unsafe/);
});

test('independent writers cannot race past the shared account byte quota',async t=>{
  const dir=await temp(t),big=JSON.stringify('x'.repeat(262138));
  for(let n=0;n<7;n++)assert.equal(commitState(dir,`dashboards/q${n}.json`,big,null),204);
  const code=`import {commitState} from ${JSON.stringify(moduleUrl)};console.log(commitState(process.argv[1],process.argv[2],JSON.stringify('q'.repeat(200000)),null));`;
  const jobs=['a','b'].map(n=>child(code,[dir,`dashboards/${n}.json`]));
  const statuses=(await Promise.all(jobs.map(j=>j.done))).map(s=>Number(s.trim())).sort();
  assert.deepEqual(statuses,[204,413]);assert(Object.values(readState(dir)).reduce((n,body)=>n+Buffer.byteLength(body),0)<=2*1024*1024);
});
