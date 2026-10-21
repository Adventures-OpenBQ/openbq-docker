// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { mcpRoute, mcpMessage, MCP_SESSION_RE, MCP_VERSION_RE } from "./mcp-policy.mjs";

const at = path => new URL(path, "https://door.example.com");
const msg = value => mcpMessage(Buffer.from(JSON.stringify(value)));
const call = (name, args) => msg({ jsonrpc: "2.0", id: 7, method: "tools/call", params: { name, arguments: args } });

test("one route: POST /mcp, no query", () => {
  assert.equal(mcpRoute(at("/mcp"), "POST"), true);
  for (const [path, method] of [["/mcp", "GET"], ["/mcp", "DELETE"], ["/mcp?x=1", "POST"], ["/mcp/", "POST"],
    ["/mcp/mcp", "POST"], ["/mcpx", "POST"]]) assert.equal(mcpRoute(at(path), method), false, `${method} ${path}`);
});

test("the protocol's own methods pass, re-serialised", () => {
  for (const method of ["initialize", "notifications/initialized", "notifications/cancelled", "ping", "tools/list",
    "prompts/list", "prompts/get", "resources/list", "resources/read", "resources/templates/list"]) {
    const out = msg({ jsonrpc: "2.0", id: 1, method, params: {} });
    assert.equal(out.error, undefined, method);
    assert.deepEqual(JSON.parse(out.body), { jsonrpc: "2.0", id: 1, method, params: {} });
  }
});

test("anything else is refused before it reaches the server", () => {
  for (const bad of [[], [{ jsonrpc: "2.0", id: 1, method: "ping" }], null, "x", {}, { jsonrpc: "1.0", id: 1, method: "ping" },
    { jsonrpc: "2.0", id: 1, method: "sampling/createMessage" }, { jsonrpc: "2.0", id: 1, method: "logging/setLevel" },
    { jsonrpc: "2.0", id: 1, method: "completion/complete" }, { jsonrpc: "2.0", id: 1, method: 7 },
    { jsonrpc: "2.0", id: { x: 1 }, method: "ping" }]) {
    assert.ok(msg(bad).error, JSON.stringify(bad));
  }
  assert.ok(mcpMessage(Buffer.from("{")).error);
});

test("the read-only discovery tools pass; install_skill and run_pipeline never do", () => {
  for (const name of ["available_categories", "available_tools", "search_tools", "list_prompts", "get_prompt",
    "list_resources", "read_resource"]) assert.equal(call(name, {}).error, undefined, name);
  for (const name of ["install_skill", "run_pipeline", "anything_else", "", 7]) assert.ok(call(name, {}).error, String(name));
  assert.equal(call("call_tool", { name: "equity_price_quote", arguments: { symbol: "AAPL" } }).error, undefined);
});

test("call_tool cannot reach the URL-fetching viewers, the refused tools, or itself", () => {
  for (const name of ["tmx_equity_filings_view", "tmx_index_document_view", "install_skill", "run_pipeline", "call_tool",
    "TMX_INDEX_DOCUMENT_VIEW", " tmx_index_document_view"]) {
    assert.ok(call("call_tool", { name, arguments: {} }).error, name);
  }
  for (const args of [undefined, {}, { name: 7 }, { arguments: {} }, []]) assert.ok(call("call_tool", args).error, JSON.stringify(args));
});

test("tools/call needs a params object with a string name", () => {
  for (const params of [undefined, null, [], { name: 7 }, {}]) {
    assert.ok(msg({ jsonrpc: "2.0", id: 1, method: "tools/call", params }).error, JSON.stringify(params));
  }
});

test("session ids and protocol versions have a narrow shape", () => {
  assert.ok(MCP_SESSION_RE.test("3f0c2b8e5d1a4c7f9e6b2a1d0c8e7f6a"));
  for (const bad of ["", "a b", "x".repeat(201), "a\r\nX: y"]) assert.ok(!MCP_SESSION_RE.test(bad), JSON.stringify(bad));
  assert.ok(MCP_VERSION_RE.test("2025-06-18"));
  for (const bad of ["2025-6-18", "latest", "2025-06-18\r\n"]) assert.ok(!MCP_VERSION_RE.test(bad), bad);
});

test("call_tool arguments may name a URL only on a vetted https host, piece by comma-separated piece", () => {
  const LAN = [10, 0, 0, 1].join(".");
  const tool = (name, args) => call("call_tool", { name, arguments: args });
  // The Congress text fetchers only look for the substring (verified 2026-10-21): the door checks the parsed host.
  for (const urls of [`http://${LAN}/x?govinfo.gov`, [`http://openbq-api:6900/?congress.gov`], "http://www.govinfo.gov/x",
    `https://www.govinfo.gov/a,http://${LAN}/b?govinfo.gov`, "file:///etc/passwd", "https://govinfo.gov.evil.example/x",
    { nested: [`ws://${LAN}/`] }, " HTTPS://EVIL.example/x "]) {
    assert.ok(tool("uscongress_bill_text", { urls }).error, JSON.stringify(urls));
  }
  for (const urls of ["https://www.govinfo.gov/content/pkg/BILLS-118hr1ih/html/BILLS-118hr1ih.htm",
    "https://www.congress.gov/118/bills/hr1/BILLS-118hr1ih.htm,https://www.govinfo.gov/x"]) {
    assert.equal(tool("uscongress_bill_text", { urls }).error, undefined, urls);
  }
  assert.equal(tool("sec_htm_file", { url: "https://www.sec.gov/Archives/edgar/data/320193/x.htm" }).error, undefined);
  assert.equal(tool("usda_weather_bulletins_download", { urls: ["https://esmis.nal.usda.gov/x.pdf"] }).error, undefined);
  // Text that merely mentions a URL, symbols and dates are not URLs.
  assert.equal(tool("equity_price_quote", { symbol: "AAPL,MSFT", note: "see https://example.com", start: "2026-01-01", ratio: "1:2" }).error, undefined);
});

test("a refused name stays refused however JSON spells the message", () => {
  for (const raw of ['{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"call_tool","arguments":{"name":"equity_price_quote","name":"install_skill"}}}',
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_tools","name":"install_skill"}}',
    '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"__proto__":{"name":"search_tools"},"name":"install_skill"}}']) {
    assert.ok(mcpMessage(Buffer.from(raw)).error, raw);
  }
});
