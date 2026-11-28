// Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
// Run: VIEWER_PLAYWRIGHT_PACKAGE=/path/to/package.json node --test this-file
import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';

const { chromium } = createRequire(process.env.VIEWER_PLAYWRIGHT_PACKAGE ?? import.meta.url)('@playwright/test');
const assets = new URL('../', import.meta.url);
let browser, server, origin;
const pages = new Map();
before(async () => {
  server = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html');
    res.end(pages.get(new URL(req.url, origin).pathname) ?? '<p>Document</p>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  await new Promise(resolve => server?.close(resolve));
});
function asset(path, placeholder, data) {
  return readFileSync(fileURLToPath(new URL(path, assets)), 'utf8')
    .replace(placeholder, JSON.stringify(data).replaceAll('<', '\\u003c'));
}
async function withPage(fn) {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.addInitScript(() => { window.attacked = false; });
  try { await fn(page); } finally { await context.close(); }
}
const member = data => asset('openbb_government_us/congress/assets/member_bio.html', '__WIDGET_DATA__', {
  name: 'Test Member', party: 'Independent', committees: [], terms: [], ...data,
});
const rss = items => asset('openbb_us_eia/assets/rss_feed.html', '__EIA_RSS_DATA__', { label: 'Feed', items });
const eia = data => asset('openbb_us_eia/assets/data_browser.html', '__EIA_BROWSER_DATA__', {
  browser: 'test', label: 'Test', src: '/document', home: '/document', proxy: '/eia_proxy', ...data,
});

test('EIA site rejects executable initial/home URLs and retains safe navigation/theme', async () => withPage(async page => {
  pages.set('/site', eia({ mode: 'site', src: 'javascript:parent.attacked=true', home: 'data:text/html,bad' }));
  await page.goto(origin + '/site');
  assert.equal(await page.evaluate(() => window.attacked), false);
  assert.doesNotMatch(await page.locator('iframe').getAttribute('src') ?? '', /^(javascript|data):/i);
  await page.locator('.home-btn').click();
  assert.doesNotMatch(await page.locator('iframe').getAttribute('src') ?? '', /^(javascript|data):/i);
  pages.set('/safe-site', eia({ mode: 'site' }));
  await page.goto(origin + '/safe-site');
  assert.equal(new URL(await page.locator('iframe').getAttribute('src'), origin).pathname, '/document');
  await page.locator('.home-btn').click();
  assert.equal(new URL(await page.locator('iframe').getAttribute('src'), origin).pathname, '/document');
}));

test('EIA maps preserve filtering/text and refuse active image schemes', async () => withPage(async page => {
  pages.set('/maps', eia({ mode: 'maps', proxy: 'javascript:parent.attacked=true;//', maps: [
    { title: '<img src=x onerror="window.attacked=true">Map', image: '/map.png', date: '2026-01-01' },
    { title: 'Other', image: '/other.png' },
  ] }));
  await page.goto(origin + '/maps');
  await page.locator('#q').fill('Map');
  assert.equal(await page.locator('.map-item').count(), 1);
  await page.locator('.map-item').click();
  assert.equal(await page.evaluate(() => window.attacked), false);
  assert.doesNotMatch(await page.locator('#doc img').getAttribute('src') ?? '', /^javascript:/i);
  assert.match(await page.locator('#h-title').textContent(), /<img/);
}));

test('RSS rich text keeps tables/headings/bold while removing active markup and attributes', async () => withPage(async page => {
  pages.set('/rss-rich', rss([{ title: 'Report', viewer: 'table', url: '/document',
    excerpt: '<b>Summary</b><img src=x onerror="window.attacked=true">',
    body_html: '<h2>Prices</h2><table><tr><td><b>42</b></td></tr></table><img src=x onerror="window.attacked=true"><svg onload="window.attacked=true"></svg><a href="javascript:window.attacked=true">Bad</a>',
  }]));
  await page.goto(origin + '/rss-rich');
  await page.locator('.card').click();
  assert.equal(await page.evaluate(() => window.attacked), false);
  assert.equal(await page.locator('#m-body h2').textContent(), 'Prices');
  assert.equal(await page.locator('#m-body td b').textContent(), '42');
  assert.equal(await page.locator('#m-body img, #m-body svg, #m-body [onerror]').count(), 0);
  assert.equal(await page.locator('#m-body a[href^="javascript:"]').count(), 0);
}));

test('RSS quoted URL attributes cannot inject handlers; document schemes are restricted', async () => withPage(async page => {
  pages.set('/rss-url', rss([{ title: 'Document', viewer: 'site', src: 'javascript:parent.attacked=true',
    url: 'javascript:window.attacked=true', ppt_url: 'https://example.test/" onclick="window.attacked=true', meta: [{ label: 'A', value: 'B' }],
  }]));
  await page.goto(origin + '/rss-url');
  await page.locator('.card').click();
  assert.equal(await page.evaluate(() => window.attacked), false);
  assert.equal(await page.locator('#m-body [onclick]').count(), 0);
  assert.doesNotMatch(await page.locator('#m-newtab').getAttribute('href') ?? '', /^javascript:/i);
  assert.doesNotMatch(await page.locator('#m-body iframe').getAttribute('src') ?? '', /^javascript:/i);
}));

test('member links/photos are inert text or HTTP(S), including control-character schemes', async () => withPage(async page => {
  pages.set('/member', member({ name: '<img src=x onerror="window.attacked=true">', photo_url: 'javascript:window.attacked=true',
    links: [{ label: 'Bad', url: 'java\nscript:window.attacked=true' }, { label: 'Good', url: 'https://example.test/member' }],
  }));
  await page.goto(origin + '/member');
  assert.equal(await page.evaluate(() => window.attacked), false);
  assert.equal(await page.locator('a').count(), 1);
  assert.equal(await page.locator('a').getAttribute('href'), 'https://example.test/member');
}));

test('member protocol addresses the immediate parent and ignores sibling requests', async () => withPage(async page => {
  pages.set('/member-frame', member({ committees: [{ name: 'Committee' }] }));
  pages.set('/parent', '<script>window.messages=[];addEventListener("message",e=>messages.push(e.data));</script><iframe src="/member-frame"></iframe><iframe src="/sibling"></iframe>');
  pages.set('/outer', '<script>window.messages=[];addEventListener("message",e=>messages.push(e.data));</script><iframe src="/parent"></iframe>');
  await page.goto(origin + '/outer');
  const parent = page.frames().find(frame => frame.url() === origin + '/parent');
  const sibling = page.frames().find(frame => frame.url() === origin + '/sibling');
  await parent.evaluate(() => document.querySelector('iframe').contentWindow.postMessage({ type: 'openbb-request' }, location.origin));
  await parent.waitForFunction(() => messages.some(message => message.type === 'openbb-data'));
  assert.equal(await page.evaluate(() => messages.filter(message => message.type === 'openbb-data').length), 0);
  await parent.evaluate(() => { messages.length = 0; });
  await sibling.evaluate(() => parent.frames[0].postMessage({ type: 'openbb-request' }, location.origin));
  await parent.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await parent.evaluate(() => messages.filter(message => message.type === 'openbb-data').length), 0);
}));

test('member connects to a cross-origin immediate parent with referrer disabled', async () => withPage(async page => {
  const childOrigin = origin.replace('127.0.0.1', 'localhost');
  pages.set('/member-no-referrer', member({ committees: [{ name: 'Committee' }] }));
  pages.set('/parent-no-referrer', `<script>window.messages=[];addEventListener('message',e=>messages.push({origin:e.origin,data:e.data}));</script><iframe referrerpolicy="no-referrer" src="${childOrigin}/member-no-referrer"></iframe>`);
  await page.goto(origin + '/parent-no-referrer');
  await page.waitForFunction(() => messages.some(message => message.data.type === 'openbb-connect'));
  const child = page.frames().find(frame => frame.url() === childOrigin + '/member-no-referrer');
  assert.equal(await child.evaluate(() => document.referrer), '');
  await page.evaluate(target => document.querySelector('iframe').contentWindow.postMessage({type:'openbb-request'},target), childOrigin);
  await page.waitForFunction(() => messages.some(message => message.data.type === 'openbb-data'));
  assert.equal(await page.evaluate(target => messages.filter(message => message.data.type === 'openbb-data').every(message => message.origin === target), childOrigin), true);
}));

test('embedded viewers retain same-origin HTTP proxies and HTTPS external URLs, refusing external HTTP', async () => withPage(async page => {
  for (const source of ['http://external.example.test/document', 'https://external.example.test/document?name=a%2Fb&rate=10%25', '/document?name=a%2Fb&rate=10%25', origin + '//external.example.test/document']) {
    await page.route('https://external.example.test/**', route => route.fulfill({body: '<p>Document</p>',contentType: 'text/html'}));
    pages.set('/frame-policy', eia({ mode: 'site', src: source }));
    await page.goto(origin + '/frame-policy');
    const expected = source.startsWith(origin) ? '/external.example.test/document' : source.startsWith('http:') ? '' : source;
    assert.equal(await page.locator('iframe').getAttribute('src'), expected);
    pages.set('/rss-frame-policy', rss([{title: 'Document', viewer: 'site', src: source, url: source}]));
    await page.goto(origin + '/rss-frame-policy');
    await page.locator('.card').click();
    assert.equal(await page.locator('#m-body iframe').getAttribute('src'), expected);
  }
}));
