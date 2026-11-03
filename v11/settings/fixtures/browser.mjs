// Actual browser service + authenticated synthetic session + real gateway HTTP.
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { request } from 'node:http';
import { Readable } from 'node:stream';
import { createPreviewServer, STATE_LIST_RESPONSE_MAX as clientBound } from '/client/web/server.mjs';
import { STATE_LIST_RESPONSE_MAX as gatewayBound } from '/gateway/state-store.mjs';
import { readConfig, SESSION_COOKIE } from '/client/web/config.mjs';
import { encode } from '/client/node_modules/@auth/core/jwt.js';
import { readFileSync } from 'node:fs';
const input=JSON.parse(readFileSync('/fixture/gateway.json'));
assert.equal(clientBound, gatewayBound); assert.equal(clientBound, 12603323);
const env={APP_ORIGIN:'https://preview.example.com',AUTH_SECRET:'synthetic_browser_secret_task51_1234567890',
  AUTH_GITHUB_ID:'fixture-client',AUTH_GITHUB_SECRET:'fixture-secret',SESSION_EPOCH:'fixture',GITHUB_ALLOWED_USER_IDS:'99',
  BACKEND_GATEWAY_ORIGIN:'https://gateway.example.com',BACKEND_GATEWAY_TOKEN:input.secrets.token};
const config=readConfig(env);
const cookie=`${SESSION_COOKIE}=${await encode({token:{githubId:'99',epoch:'fixture',deadline:Date.now()/1000+3600},
  secret:env.AUTH_SECRET,salt:SESSION_COOKIE,maxAge:3600})}`;
const gateway=process.argv[2];
const fixtureHost=['openbq','fixture','ts','net'].join('.')+':10000';
function httpFetch(url,options={}) {
  return new Promise((resolve,reject)=>{
    const req=request(url,{method:options.method,headers:options.headers,signal:options.signal},res=>{
      resolve(new Response(res.statusCode===204?null:Readable.toWeb(res),{status:res.statusCode,headers:res.headers}));
    });
    req.on('error',reject);req.end(options.body);
  });
}
const server=createPreviewServer({config,assets:'/tmp',fetchUpstream:(url,options)=>httpFetch(
  `http://${gateway}:8080${new URL(url).pathname}`,{...options,headers:{...options.headers,Host:fixtureHost}})});
server.listen(0,'127.0.0.1');await once(server,'listening');
const origin=`http://127.0.0.1:${server.address().port}`;
try{
  for(const variant of ['tabs','replacement']){
    const raw=variant==='tabs'?Buffer.from('{"x":1}'+'\t'.repeat(262137)):
      Buffer.concat([Buffer.from('"'),Buffer.alloc(262142,255),Buffer.from('"')]);
    for(let i=0;i<8;i++){
      const result=await httpFetch(`${origin}/state/dashboards/quota${i}.json`,{method:'PUT',body:raw,
        headers:{Host:'preview.example.com',Cookie:cookie,Origin:env.APP_ORIGIN,'Sec-Fetch-Site':'same-origin','Content-Type':'application/json','Content-Length':String(raw.length)}});
      assert.equal(result.status,204);
    }
    const response=await httpFetch(`${origin}/preview-bootstrap.js`,{headers:{Host:'preview.example.com',Cookie:cookie}});
    const js=await response.text();assert.equal(response.status,200);
    assert.match(js,/window\.__bdobbPersist=true;/);assert.doesNotMatch(js,/dashboards\/preview\.json/);
    for(let i=0;i<8;i++)assert.ok(js.includes(JSON.stringify(`dashboards/quota${i}.json`)+':'+JSON.stringify(raw.toString('utf8'))));
    console.log('PASS real browser complete state '+variant);
  }
}finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
