// SPDX-License-Identifier: Apache-2.0
// Private qualification harness; production UI, gateway and relay, actual retained rows.
import {chromium,expect} from '@playwright/test';
import {readFile,writeFile,mkdir,cp,mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {once} from 'node:events';
import {randomBytes} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {createServer as httpsServer} from 'node:https';
import {build} from 'esbuild';
import {encode} from '@auth/core/jwt';
import {createPreviewServer} from '/app/web/server.mjs';
import {readConfig,SESSION_COOKIE} from '/app/web/config.mjs';
import {createGateway} from '/host/funnel-gateway/server.mjs';
import {validateConfig} from '/host/funnel-gateway/config.mjs';
const secrets=JSON.parse(await readFile('/private/harness.json','utf8'));
if(typeof secrets.webApiToken!=='string'||!/^[A-Za-z0-9_-]{32,256}$/.test(secrets.webApiToken)||
  [secrets.apiToken,secrets.mcpToken,secrets.tableGatewayToken,secrets.tableRelayToken].includes(secrets.webApiToken))
  throw new Error('Qualification requires a distinct scoped webApiToken');
const root=await mkdtemp(join(tmpdir(),'native-ui-'));
const machine=randomBytes(32).toString('base64url');
const hidden=[secrets.apiToken,secrets.webApiToken,secrets.mcpToken,secrets.tableGatewayToken,secrets.tableRelayToken,machine];
const clean=value=>{let raw=JSON.stringify(value,null,2);for(const key of hidden)raw=raw.split(key).join('[REDACTED]');return raw;};
const report={startedAt:new Date().toISOString(),status:'RUNNING',executionId:secrets.executionId,resultHash:secrets.resultHash,synthetic_market_data:false,synthetic_local_auth_session:true,public_tls_qualified:false,oauth_issuer_qualified:false};
let browser,context,tls,gateway;
try{
 await mkdir(join(root,'state'));await cp('/app/browser',join(root,'ui'),{recursive:true});
 const assets=join(root,'ui');await mkdir(join(assets,'assets'),{recursive:true});
 const cfg=validateConfig({origin:'https://qualification.YOUR-TAILNET.ts.net:10000',temporalDB:true,tableService:true,stateDir:join(root,'state')},{token:machine,apiUsername:'qualification',apiPassword:randomBytes(32).toString('base64url'),temporalToken:secrets.apiToken,temporalPrincipalTokens:{'github:42':secrets.webApiToken},tableGatewayToken:secrets.tableGatewayToken,tableRelayToken:secrets.tableRelayToken});
 gateway=createGateway(cfg);gateway.listen(0,'127.0.0.1');await once(gateway,'listening');
 const gatewayURL='http://127.0.0.1:'+gateway.address().port;cfg.origin=gatewayURL;
 const config=readConfig({APP_ORIGIN:'https://localhost',AUTH_SECRET:randomBytes(64).toString('base64url'),AUTH_GITHUB_ID:'qualification',AUTH_GITHUB_SECRET:randomBytes(32).toString('base64url'),SESSION_EPOCH:'native-sip',GITHUB_ALLOWED_USER_IDS:'42',BACKEND_GATEWAY_ORIGIN:'https://gateway.example.test',BACKEND_GATEWAY_TOKEN:machine,TABLE_RELAY_TOKEN:secrets.tableRelayToken,TEMPORALDB_V11:'true'});
 config.backend=gatewayURL;
 const alias=Object.fromEntries(Object.entries({'@tauri-apps/plugin-http':'http','@tauri-apps/plugin-fs':'fs','@tauri-apps/api/path':'path','@tauri-apps/api/core':'core','@tauri-apps/plugin-dialog':'dialog','@tauri-apps/plugin-opener':'opener','@tauri-apps/api/webviewWindow':'webviewWindow'}).map(([name,file])=>[name,'/app/src/browser-shim/'+file+'.ts']));
 await build({stdin:{contents:`import {createTemporalClient} from './src/lib/temporal/client';import {discoverBackend} from './src/lib/discovery';const backend={id:'preview-temporal',name:'TemporalDB',baseUrl:location.origin+'/temporal',authLocation:'header',validateWidgets:false};window.temporalClient=createTemporalClient(backend);window.discover=()=>discoverBackend(backend);`,resolveDir:'/app',loader:'ts'},bundle:true,format:'esm',platform:'browser',alias,outfile:join(assets,'assets/probe.js')});
 await writeFile(join(assets,'index.html'),(await readFile(join(assets,'index.html'),'utf8')).replace('</body>','<script type="module" src="/assets/probe.js"></script></body>'));
 execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',join(root,'key.pem'),'-out',join(root,'cert.pem'),'-days','1','-subj','/CN=localhost'],{stdio:'ignore'});
 const preview=createPreviewServer({config,assets});tls=httpsServer({key:readFileSync(join(root,'key.pem')),cert:readFileSync(join(root,'cert.pem'))},preview.listeners('request')[0]);
 tls.listen(0,'127.0.0.1');await once(tls,'listening');config.origin='https://localhost:'+tls.address().port;
 browser=await chromium.launch({headless:true,args:['--disable-dev-shm-usage']});context=await browser.newContext({ignoreHTTPSErrors:true,viewport:{width:1920,height:1200}});
 report.browserVersion=browser.version();
 expect((await context.request.get(config.origin+'/temporal/widgets.json')).status()).toBe(401);
 expect((await fetch(gatewayURL+'/temporal/widgets.json')).status).toBe(401);
 const session=await encode({token:{githubId:'42',epoch:config.epoch,deadline:Date.now()/1000+3600},secret:config.secret,salt:SESSION_COOKIE,maxAge:3600});
 await context.addCookies([{name:SESSION_COOKIE,value:session,url:config.origin,secure:true,httpOnly:true,sameSite:'Lax'}]);
 const columns=['source_position','source_timestamp_naive','corroborated_timestamp_utc','source_price','source_sequence','matched_count','unmatched_count','partial_partition','canonical_tick_eligible'];
 const table={widths:{source_timestamp_naive:280,corroborated_timestamp_utc:280,source_sequence:200,source_position:110},columnOrder:columns,hidden:secrets.columns.filter(c=>!columns.includes(c))};
 const binding={kind:'execution',executionId:secrets.executionId};
 const cards=[
  {id:'paged',widgetId:'temporaldb_query',title:'Retained SIP inspection — cursor view',backendId:'preview-temporal',params:{},queryBinding:binding,table,layout:{x:0,y:0,w:40,h:14}},
  {id:'full',widgetId:'temporaldb_query',title:'Complete retained result — global descending sort',backendId:'preview-temporal',params:{},queryBinding:{...binding,tableExecution:{kind:'managed',version:1,backendId:'preview-table',sourceBackendId:'qualified-temporal'}},table:{...table,sorting:[{id:'source_position',desc:true}]},layout:{x:0,y:14,w:40,h:16}}
 ];
 const page=await context.newPage();const leaked=[];const executions=[];const errors=[];
 const pending=new Set();let phase='startup',lastActivity=Date.now();const trace=[];
 const tableCommand=r=>/\/table\/sessions\/[^/]+\/(commands|cancel)$/.test(new URL(r.url()).pathname);
 page.on('request',r=>{if(!tableCommand(r))return;pending.add(r);lastActivity=Date.now();let kind='unknown',requestId,targetRequestId,range;try{const body=JSON.parse(r.postData()??'{}');targetRequestId=body.targetRequestId;if(body.wire){const wire=JSON.parse(body.wire);kind=wire.request?.kind??wire.kind??kind;requestId=wire.request?.requestId??wire.requestId;range=wire.request?.kind==='rows'?wire.request.request:undefined;}}catch{}if(trace.length<2000)trace.push({event:'request',at:Date.now(),phase,operation:new URL(r.url()).pathname.endsWith('/cancel')?'cancel':kind,requestId,targetRequestId,range});});
 const finished=r=>{if(!tableCommand(r))return;pending.delete(r);lastActivity=Date.now();if(trace.length<2000)trace.push({event:r.failure()?'requestfailed':'finished',at:Date.now(),phase,failure:r.failure()?.errorText});};page.on('requestfinished',finished);page.on('requestfailed',finished);
 const settle=async(card,expected)=>{await expect(card.getByRole('cell',{name:String(expected),exact:true}).first()).toBeVisible({timeout:60000});await expect.poll(()=>pending.size===0&&Date.now()-lastActivity>=3000,{timeout:45000,intervals:[500]}).toBe(true);await expect(card.getByRole('cell',{name:String(expected),exact:true}).first()).toBeVisible();const loading=await card.locator('tbody tr').evaluateAll(rows=>rows.some(row=>{const r=row.getBoundingClientRect(),a=row.closest('.widget-card')?.getBoundingClientRect();return a&&r.height>0&&r.bottom>a.top&&r.top<a.bottom&&/Loading rows/.test(row.textContent??'');}));expect(loading).toBe(false);};
 report.commandTrace=trace;report.failedTableResponses=[];report.directTableDiagnostics=[];page.on('response',async r=>{const path=new URL(r.url()).pathname;if(!path.startsWith('/table/')||r.status()<400)return;report.failedTableResponses.push({path,status:r.status(),body:(await r.text().catch(()=>'<body unavailable after navigation>')).slice(0,2000)});if(r.status()===413&&path.endsWith('/commands')){try{const body=JSON.parse(r.request().postData()??'{}'),wire=JSON.parse(body.wire??'{}');if(wire.request?.kind!=='rows')return;wire.request.requestId='diagnostic-'+Date.now();body.wire=JSON.stringify(wire);const direct=await fetch('http://table-service:8080'+path.slice('/table'.length),{method:'POST',headers:{'Content-Type':'application/json','X-Table-Gateway-Token':secrets.tableGatewayToken,'X-Table-Principal':'github:42'},body:JSON.stringify(body)});const value=await direct.json();report.directTableDiagnostics.push({status:direct.status,error:direct.ok?undefined:value.error});}catch(error){report.directTableDiagnostics.push({diagnosticError:error.name});}}});
 page.on('request',r=>{const all=r.url()+JSON.stringify(r.headers())+(r.postData()??'');if(hidden.some(key=>all.includes(key)))leaked.push(r.url());if(r.method()==='POST'&&new URL(r.url()).pathname.endsWith('/executions'))executions.push(r.url());});
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({cards})=>{const files={'settings.json':'{}','backends.json':JSON.stringify([{id:'preview-temporal',name:'TemporalDB',baseUrl:location.origin+'/temporal',authLocation:'header',validateWidgets:false},{id:'preview-table',name:'Managed tables',baseUrl:location.origin+'/table',authLocation:'header',validateWidgets:false}]),'dashboards/d1.json':JSON.stringify({id:'d1',name:'Native SIP inspection',tabs:[{id:'t1',name:'Retained inspection',cards}]})};Object.defineProperty(window,'__bdobbSeed',{get:()=>files,set:()=>{},configurable:true});},{cards});
 await page.addInitScript(()=>{window.__qualificationFetchTrace=[];const original=window.fetch;window.fetch=function(input,init){const url=typeof input==='string'?input:input instanceof Request?input.url:String(input);if(/\/table\/sessions\//.test(url)&&init?.signal){let requestId,kind,range;try{const body=JSON.parse(String(init.body??'{}')),wire=JSON.parse(body.wire??'{}');requestId=wire.request?.requestId??wire.requestId;range=wire.request?.kind==='rows'?wire.request.request:undefined;kind=wire.request?.kind??wire.kind;}catch{}init.signal.addEventListener('abort',()=>{if(window.__qualificationFetchTrace.length<2000)window.__qualificationFetchTrace.push({at:Date.now(),kind,requestId,reason:String(init.signal.reason),stack:new Error('fetch cancellation').stack?.slice(0,1600)});},{once:true});}return original.call(this,input,init);};});
 await page.goto(config.origin,{timeout:90000});await page.mouse.move(1800,1100);await page.waitForFunction(()=>Boolean(window.temporalClient),{timeout:60000});
 const discovery=await page.evaluate(()=>window.discover());expect(discovery.status).toBe('online');expect(discovery.issues).toEqual([]);
 const paged=page.locator('.widget-card').filter({hasText:'Retained SIP inspection — cursor view'});
 await expect(paged.getByLabel('Temporal result page')).toContainText('rows 1–25 of 1788',{timeout:90000});
 await expect(paged).toContainText('SIP inspection only');
 for(const field of ['source_timestamp_naive','corroborated_timestamp_utc','source_sequence'])await expect(paged.getByRole('cell',{name:String(secrets.firstRow[field]),exact:true}).first()).toBeVisible();
 await paged.getByRole('button',{name:'Next result page',exact:true}).click();
 await expect(paged.getByLabel('Temporal result page')).toContainText('rows 26–50 of 1788');
 await paged.getByRole('button',{name:'Previous result page',exact:true}).click();
 await expect(paged.getByLabel('Temporal result page')).toContainText('rows 1–25 of 1788');
 phase='paged-complete';
 await page.screenshot({path:'/output/sip-paged-widget.png',fullPage:true});report.paged={status:'PASS',firstPageRows:25,total:1788,nextPrevious:true,inspectionWarning:true};
 const full=page.locator('.widget-card').filter({hasText:'Complete retained result — global descending sort'});
 phase='complete-load';await full.scrollIntoViewIfNeeded();
 await expect.poll(async()=>{const text=await full.innerText();if(text.includes('Retained result state budget exceeded'))throw Error('Retained result state budget exceeded');return /2\.05K|2,047|2047/.test(text);},{timeout:120000}).toBe(true);
 await expect(full).toContainText('SIP inspection only');
 report.geometry=await full.locator('.table-scroll').evaluate(el=>({viewportHeight:el.clientHeight,contentHeight:el.scrollHeight,cardHeight:el.closest('.widget-card').clientHeight,renderedRows:el.querySelectorAll('tbody tr').length}));
 expect(report.geometry.viewportHeight).toBeLessThan(report.geometry.cardHeight);
 expect(report.geometry.renderedRows).toBeLessThan(150);
 phase='complete-export';await full.getByRole('button',{name:'Card menu',exact:true}).click();await page.getByRole('menuitem',{name:'Export ▸',exact:true}).click();
 const downloaded=page.waitForEvent('download');await page.getByRole('menuitem',{name:'JSON',exact:true}).click();
 const download=await downloaded;const exported=JSON.parse(await readFile(await download.path(),'utf8'));
 expect(exported.rows).toHaveLength(1788);expect(exported.provenance.receipt.temporal.executionId).toBe(secrets.executionId);expect(exported.provenance.receipt.temporal.resultHash).toBe(secrets.resultHash);
 expect(exported.completeness.kind).toBe('complete');expect(exported.completeness.warnings.join(' ')).toContain('SIP inspection only');
 expect(exported.rows[0].source_position).toBe(secrets.lastRow.source_position);
 await writeFile('/output/full-result-export.json',JSON.stringify(exported));
 for(const field of ['source_timestamp_naive','corroborated_timestamp_utc','source_sequence'])await expect(full.getByRole('cell',{name:String(secrets.lastRow[field]),exact:true}).first()).toBeVisible();
 phase='complete-settle';await settle(full,secrets.lastRow.source_position);report.completeDisplaySettled=true;
 await page.screenshot({path:'/output/sip-complete-widget.png',fullPage:true});
 report.complete={status:'PASS',rows:1788,globalSortFirstPosition:exported.rows[0].source_position,matchingExecutionAndHash:true,inspectionWarning:true};
 phase='filter';await full.getByRole('button',{name:'Filter rows',exact:true}).click();
 await full.getByLabel('Minimum source_position',{exact:true}).fill('2000');
 await expect(full.getByLabel('Minimum source_position',{exact:true})).toHaveValue('2000');
 phase='filter-ready';await expect(full).toContainText('43 of 1788 rows',{timeout:60000});await settle(full,secrets.lastRow.source_position);phase='filter-export';
 await expect.poll(async()=>{await full.getByRole('button',{name:'Card menu',exact:true}).click();await page.getByRole('menuitem',{name:'Export ▸',exact:true}).click();const next=page.waitForEvent('download');await page.getByRole('menuitem',{name:'JSON',exact:true}).click();const file=await next;const data=JSON.parse(await readFile(await file.path(),'utf8'));if(data.rows.length!==43)return data.rows.length;expect(data.rows.every(row=>row.source_position>=2000)).toBe(true);expect(data.provenance.receipt.temporal.executionId).toBe(secrets.executionId);expect(data.completeness.warnings.join(' ')).toContain('SIP inspection only');await writeFile('/output/filtered-result-export.json',JSON.stringify(data));return data.rows.length;},{timeout:30000,intervals:[1000]}).toBe(43);
 phase='filter-settle';await settle(full,secrets.lastRow.source_position);report.filterDisplaySettled=true;
 await page.screenshot({path:'/output/sip-filtered-widget.png',fullPage:true});report.filter={status:'PASS',minimumSourcePosition:2000,rows:43,allOutsideFirstPage:true,inspectionWarning:true};
 expect(leaked).toEqual([]);expect(executions).toEqual([]);report.browserMachineCredentialLeaks=0;report.newExecutionsStartedByPinnedWidgets=0;
 report.fetchCancellationTrace=await page.evaluate(()=>window.__qualificationFetchTrace);report.pendingTableRequests=pending.size;report.pageErrors=errors;report.status='PASS';
}catch(error){report.status='FAIL';report.error=error instanceof Error?error.stack:String(error);if(context){const pages=context.pages();if(pages.length){report.fetchCancellationTrace=await pages[0].evaluate(()=>window.__qualificationFetchTrace??[]).catch(()=>[]);}if(pages.length)await pages[0].screenshot({path:'/output/sip-browser-failure.png',fullPage:true}).catch(()=>{});}throw error;}
finally{
 await writeFile('/output/report.json',clean(report));await context?.close();await browser?.close();if(tls){tls.closeAllConnections();await new Promise(r=>tls.close(r));}await gateway?.closeGateway();
 console.log(clean({status:report.status,executionId:report.executionId,paged:report.paged,complete:report.complete,error:report.error}));
}
