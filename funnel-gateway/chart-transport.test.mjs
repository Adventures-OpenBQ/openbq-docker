// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0
import test from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {WebSocketServer} from 'ws';
import {connectGrid} from './server.mjs';

test('real chart upstream transport accepts snapshot chunks and bounded logical frames', async t => {
  const source = new WebSocketServer({host:'127.0.0.1',port:0});
  await once(source,'listening');
  t.after(() => new Promise(resolve => {
    for (const client of source.clients) client.terminate();
    source.close(resolve);
  }));
  const client = connectGrid({gridOrigin:`http://127.0.0.1:${source.address().port}`,
    apiAuthorization:'Basic qualification'},'/chart_stream_ws');
  client.on('error',()=>{});
  t.after(()=>client.terminate());
  await once(client,'open');
  const upstream = source.clients.values().next().value;
  // Exercise the real ws parser before the relay handler, where the old 64KiB
  // limit silently rejected larger 1-second BTC snapshots.
  for (const bytes of [128*1024,512*1024,8*1024*1024]) {
    const payload = 'x'.repeat(bytes);
    const received = once(client,'message');
    upstream.send(payload);
    const [actual] = await received;
    assert.equal(actual.length,bytes);
  }
  const failed = once(client,'error');
  upstream.send('x'.repeat(8*1024*1024+1));
  const [error] = await failed;
  assert.match(error.message,/[Mm]ax payload/);
});
test('Technical Chart upstream accepts ordinary full figures and refuses over-budget frames', async t => {
  const source = new WebSocketServer({host:'127.0.0.1',port:0});
  await once(source,'listening');
  t.after(() => new Promise(resolve => {
    for (const client of source.clients) client.terminate();
    source.close(resolve);
  }));
  const client = connectGrid({gridOrigin:`http://127.0.0.1:${source.address().port}`,
    apiAuthorization:'Basic qualification'},'/ta_chart_ws?symbol=AAPL&interval=1d');
  client.on('error',()=>{});
  t.after(()=>client.terminate());
  await once(client,'open');
  const upstream = source.clients.values().next().value;
  // Exercise the real ws parser before the relay handler, where the old 64KiB
  // limit silently rejected larger 1-second BTC snapshots.
  for (const bytes of [128*1024,512*1024,8*1024*1024]) {
    const payload = 'x'.repeat(bytes);
    const received = once(client,'message');
    upstream.send(payload);
    const [actual] = await received;
    assert.equal(actual.length,bytes);
  }
  const failed = once(client,'error');
  upstream.send('x'.repeat(8*1024*1024+1));
  const [error] = await failed;
  assert.match(error.message,/[Mm]ax payload/);
});
