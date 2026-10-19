// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { requestState, STATE_LIST_RESPONSE_MAX } from './state-store.mjs';

async function upstream(t, handler) {
  const server=createServer(handler); server.listen(0,'127.0.0.1'); await once(server,'listening');
  t.after(()=>{server.closeAllConnections();return new Promise(resolve=>server.close(resolve));});
  return {apiOrigin:`http://127.0.0.1:${server.address().port}`,token:'synthetic_state_fixture_token_123456'};
}
test('private state transports raw PUT bytes and machine Bearer to the fixed path', async t=>{
  const raw=Buffer.from(' {"x":1,"x":2,"n":1e2} ');
  const config=await upstream(t, async(req,res)=>{
    assert.equal(req.url,'/_openbq/settings/v1/state/00042/settings.json');
    assert.equal(req.headers.authorization,'Bearer synthetic_state_fixture_token_123456');
    assert.equal(req.method,'PUT');
    const chunks=[]; for await(const chunk of req) chunks.push(chunk);
    assert.deepEqual(Buffer.concat(chunks),raw); res.writeHead(204);res.end();
  });
  assert.equal((await requestState('PUT','00042','settings.json',raw,config,AbortSignal.timeout(1000))).status,204);
});
test('private state admits the complete valid quota fixture and preserves every text', async t=>{
  const raw='{"x":1}'+'\t'.repeat(262137);
  const files=Object.fromEntries(Array.from({length:8},(_,i)=>[`dashboards/quota${i}.json`,raw]));
  const body=JSON.stringify({files}); assert.equal(Buffer.byteLength(body),4194499);
  const config=await upstream(t,(_,res)=>res.end(body));
  assert.deepEqual((await requestState('GET','42',undefined,undefined,config,AbortSignal.timeout(2000))).json,{files});
  assert.equal(STATE_LIST_RESPONSE_MAX,12603323);
});
test('private state rejects declared, streamed, compressed, malformed and non-success responses', async t=>{
  for(const variant of ['declared','streamed','compressed','malformed','shape','redirect','outage']) {
    const config=await upstream(t,(_,res)=>{
      if(variant==='declared'){res.writeHead(200,{'Content-Length':'12603324'});res.flushHeaders();return;}
      if(variant==='compressed'){res.writeHead(200,{'Content-Encoding':'gzip'});res.end('{}');return;}
      if(variant==='redirect'){res.writeHead(302,{Location:'http://untrusted.invalid'});res.end();return;}
      if(variant==='outage'){res.writeHead(503);res.end('synthetic secret');return;}
      if(variant==='streamed'){res.end(' '.repeat(12603324));return;}
      res.end(variant==='shape'?'{"files":{"../evil":"x"}}':'{"files":');
    });
    await assert.rejects(requestState('GET','42',undefined,undefined,config,AbortSignal.timeout(1000)),/State unavailable/);
  }
});
test('private state stops a disconnected request and refuses invalid transport inputs', async t=>{
  let closed; const closure=new Promise(resolve=>closed=resolve);
  const config=await upstream(t,(req,res)=>{req.once('close',closed);res.writeHead(200);res.flushHeaders();});
  await assert.rejects(requestState('GET','42',undefined,undefined,config,AbortSignal.timeout(30)));
  await closure;
  for(const [method,id,name] of [['GET','42/evil'],['PUT','42','../bad'],['POST','42'],['GET','42','settings.json']]) {
    await assert.rejects(requestState(method,id,name,undefined,config,AbortSignal.timeout(1000)));
  }
});
