// SPDX-License-Identifier: Apache-2.0
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import assert from 'node:assert/strict';
const html = readFileSync(new URL('../app/static/demo.html', import.meta.url), 'utf8');
const source = html.slice(html.indexOf('function parseRangeDateUtc(s)'), html.indexOf('// Cumulative telemetry'));
const context = {};
runInNewContext(source, context);
const fixture = JSON.parse(readFileSync(new URL('fixtures/market-time.json', import.meta.url)));
for (const {input, wire} of fixture.valid) {
  test(`demo range preserves ${input}`, () => {
    assert.equal(context.parseRangeDateUtc(input).getTime(), Date.parse(wire));
  });
}
for (const input of fixture.invalid) {
  test(`demo range refuses ${input}`, () => {
    assert.ok(Number.isNaN(context.parseRangeDateUtc(input).getTime()));
  });
}
test('UTC marker does not erase seconds or milliseconds', () => {
  assert.equal(context.parseRangeDateUtc('2026-01-15T14:30:45.123Z').getTime(), Date.parse('2026-01-15T14:30:45.123Z'));
});
