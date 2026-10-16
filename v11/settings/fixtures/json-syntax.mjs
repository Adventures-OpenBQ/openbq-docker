// Compare actual Node22 JSON.parse with the installed private API, preserving bytes.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const token = JSON.parse(readFileSync('/fixture/gateway.json')).secrets.token;
const cases = [
  '['.repeat(100000) + '0' + ']'.repeat(100000),
  '{"x":'.repeat(30000) + 'false' + '}'.repeat(30000),
  '['.repeat(100000) + '0' + ']'.repeat(99999),
  '1'.repeat(5000), '1e999999', '-0.2e+7', 'true', 'false', 'null', '[]', '{}',
  ' {"x":1,"x":2,"n":1e2} ', '"\\ud800"', '"\\ud800\\udfff"',
  '"\\\\\\\"\\/\\b\\f\\n\\r\\t"', Buffer.from([34,255,34]),
  '[1,]', '{"x":}', '{1:2}', '01', '-01', '+1', '1.', '.1', '1e', '1e+',
  'true false', '{"x" 1}', '[[] []]', '{"x":[]]', '[}', '{"x":1,}',
  'NaN', 'Infinity', '-Infinity', '"\\q"', '"\\u12xz"', '"\u0000"', '\ufeff{}', '',
];
let accepted = 0, rejected = 0;
for (const value of cases) {
  const raw = Buffer.isBuffer(value) ? value : Buffer.from(value);
  assert.ok(raw.length <= 262144);
  let valid = true;
  try { JSON.parse(raw.toString('utf8')); } catch { valid = false; }
  const response = await fetch(`http://${process.argv[2]}:6900/_openbq/settings/v1/state/96/settings.json`, {
    method:'PUT', headers:{Authorization:`Bearer ${token}`, 'Content-Type':'application/json'},
    body:raw, signal:AbortSignal.timeout(10000),
  });
  assert.equal(response.status, valid ? 204 : 400, `syntax case ${accepted + rejected}`);
  if (valid) accepted++; else rejected++;
}
console.log(`PASS actual Node22/private API JSON syntax parity: ${accepted} accepted, ${rejected} refused`);
