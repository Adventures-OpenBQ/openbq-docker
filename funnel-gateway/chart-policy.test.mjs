import test from 'node:test';
import assert from 'node:assert/strict';
import {chartStreamControl,socketTarget} from './policy.mjs';
import {readFileSync} from 'node:fs';
const fixtures=JSON.parse(readFileSync(new URL('../live-grid/app/resources/chart-stream-v1.examples.json',import.meta.url)));
test('chart frozen controls pass canonical gateway validator',()=>{
 for(const transcript of fixtures) for(const frame of transcript.frames) {
   const control=['subscribe','resume','ack','unsubscribe','pong'].includes(frame.type);
   assert.equal(chartStreamControl(Buffer.from(JSON.stringify(frame))) !== null,control,frame.type);
 }
});
test('chart route and malformed controls fail closed',()=>{
 const origin='https://example.test';
 assert.equal(socketTarget('/grid/chart_stream_ws',origin),'/grid/chart_stream_ws');
 for(const path of ['/grid/chart_stream_ws?','/grid/chart_stream_ws?x=1','/grid/chart_stream_ws/','/grid/../grid/chart_stream_ws']) assert.equal(socketTarget(path,origin),null);
 const base=fixtures[0].frames[4];
 for(const frame of [{...base,cursor:{epoch:'a',seq:'9223372036854775808'}},{...base,extra:true},{...base,generation:''}]) assert.equal(chartStreamControl(Buffer.from(JSON.stringify(frame))),null);
});
