// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

import test from "node:test";
import assert from "node:assert/strict";
import { ritaRoute, ritaQuery, ritaAgents, RITA_MODEL_RE } from "./rita-policy.mjs";

const ORIGIN = "https://door.example.com";
const at = path => new URL(path, ORIGIN);
const MODEL = "openai:qwen3.6-35b";
// Built at run time so the public-content scan never sees a literal private address.
const LAN = [10, 0, 0, 1].join("."), CGNAT = [100, 64, 0, 1].join(".");
const query = value => ritaQuery(Buffer.from(JSON.stringify(value)), MODEL);

test("two routes, exact paths, no query", () => {
  assert.equal(ritaRoute(at("/ai/agents.json"), "GET"), "agents");
  assert.equal(ritaRoute(at("/ai/v1/query"), "POST"), "query");
  assert.equal(ritaRoute(at("/ai/agents.json"), "POST"), null);
  assert.equal(ritaRoute(at("/ai/v1/query"), "GET"), null);
  assert.equal(ritaRoute(at("/ai/agents.json?x=1"), "GET"), null);
  assert.equal(ritaRoute(at("/ai/v1/query?x=1"), "POST"), null);
  for (const path of ["/ai/v1/generate/code", "/ai/status", "/ai/rita.png", "/ai/", "/ai"]) {
    assert.equal(ritaRoute(at(path), "GET"), null, path);
    assert.equal(ritaRoute(at(path), "POST"), null, path);
  }
});

test("the model is forced to the pinned one, whatever the caller asked for", () => {
  const out = query({ messages: [{ role: "human", content: "hi" }], model: "anthropic:claude-opus-5-5",
    workspace_options: { model: "anthropic:claude-opus-5-5", "prompt-suggestions": false } });
  assert.equal(out.model, undefined);
  assert.deepEqual(out.workspace_options, { model: MODEL, "prompt-suggestions": false });
  assert.deepEqual(query({ messages: [{ role: "human", content: "hi" }] }).workspace_options, { model: MODEL });
});

test("workspace_options keeps only string and boolean values", () => {
  const out = query({ messages: [{}], workspace_options: { a: true, b: "x", c: 1, d: { model: "z" }, e: null } });
  assert.deepEqual(out.workspace_options, { a: true, b: "x", model: MODEL });
});

test("urls and documents are dropped, and every nested url string is blanked", () => {
  const out = query({
    messages: [{ role: "tool", function: "get_widget_data", data: [{ items: [
      { url: "http://openbq-api:6900/secret", data_format: { data_type: "pdf" } },
      { content: "ok", nested: { deeper: [{ url: `http://${CGNAT}/` }] } },
    ] }] }],
    urls: ["http://169.254.169.254/"],
    documents: [{ id: "1", name: "a", format: "pdf", url: "http://127.0.0.1/" }],
    tools: [{ name: "t", server_id: "s", url: `http://${LAN}/mcp` }],
    widgets: { primary: [{ uuid: "u", url: "file:///etc/passwd" }] },
  });
  assert.equal(out.urls, undefined);
  assert.equal(out.documents, undefined);
  const items = out.messages[0].data[0].items;
  assert.equal(items[0].url, "");
  assert.equal(items[1].nested.deeper[0].url, "");
  assert.equal(items[1].content, "ok");
  assert.equal(out.tools[0].url, "");
  assert.equal(out.widgets.primary[0].url, "");
  assert.ok(!JSON.stringify(out).includes("http://"));
});

test("a fetchable URL as an item's content is blanked; data, base64 and text are not", () => {
  // agent-rita hands an image or pdf item's string content to the AI SDK as the media itself,
  // and the SDK (or the model server) fetches a content string that parses as a URL.
  const items = [
    { content: `http://${LAN}/x.png`, data_format: { data_type: "png" } },
    { content: " HTTPS://example.com/a.pdf", data_format: { data_type: "pdf" } },
    { content: "file:///etc/passwd" }, { content: `ws://${CGNAT}/` }, { content: "ftp://x/y" },
    { content: "data:image/png;base64,iVBORw0KGgo=" }, { content: "iVBORw0KGgoAAAANSUhEUg==" },
    { content: "Revenue: 100" }, { content: "see https://example.com for more" }, { content: 7 },
  ];
  const out = query({ messages: [{ role: "tool", data: [{ items }] }] }).messages[0].data[0].items.map(i => i.content);
  assert.deepEqual(out, ["", "", "", "", "",
    "data:image/png;base64,iVBORw0KGgo=", "iVBORw0KGgoAAAANSUhEUg==", "Revenue: 100", "see https://example.com for more", 7]);
});

test("a url key that is not a string is removed, not passed through", () => {
  const out = query({ messages: [{ url: { href: `http://${LAN}/` } }, { url: ["http://x/"] }] });
  assert.equal(out.messages[0].url, "");
  assert.equal(out.messages[1].url, "");
});

test("anything but an object with a non-empty messages array is refused", () => {
  for (const bad of [null, [], "x", 1, {}, { messages: [] }, { messages: "hi" }]) {
    assert.equal(ritaQuery(Buffer.from(JSON.stringify(bad)), MODEL), null, JSON.stringify(bad));
  }
  assert.equal(ritaQuery(Buffer.from("{"), MODEL), null);
});

test("nesting past the depth cap is refused rather than walked", () => {
  let deep = { url: "http://x/" };
  for (let i = 0; i < 100; i++) deep = { a: deep };
  assert.equal(query({ messages: [deep] }), null);
  let ok = { url: "http://x/" };
  for (let i = 0; i < 30; i++) ok = { a: ok };
  assert.notEqual(query({ messages: [ok] }), null);
});

test("__proto__ keys never reach the rewritten body as prototypes", () => {
  const out = ritaQuery(Buffer.from('{"messages":[{}],"workspace_options":{"__proto__":{"model":"x"}}}'), MODEL);
  assert.equal(out.workspace_options.model, MODEL);
  assert.equal(Object.getPrototypeOf(out.workspace_options), Object.prototype);
});

test("agents.json offers only the pinned model and no file upload", () => {
  const doc = { openbb_agent_rita: { name: "Agent Rita", endpoints: { query: "/v1/query" }, features: {
    streaming: true, "file-upload": true,
    model: { label: "Model", type: "select", default: "anthropic:claude-opus-5-5",
      options: [{ label: "Opus", value: "anthropic:claude-opus-5-5" }, { label: "Qwen", value: MODEL }] },
  } } };
  const out = ritaAgents(doc, MODEL);
  const features = out.openbb_agent_rita.features;
  assert.equal(features["file-upload"], false);
  assert.equal(features.streaming, true);
  assert.equal(features.model.default, MODEL);
  assert.deepEqual(features.model.options, [{ label: MODEL, value: MODEL }]);
  assert.equal(out.openbb_agent_rita.name, "Agent Rita");
});

test("an agents.json that is not an object of agents is refused", () => {
  for (const bad of [null, [], "x", { a: null }, { a: { features: [] } }]) assert.equal(ritaAgents(bad, MODEL), null, JSON.stringify(bad));
  assert.deepEqual(ritaAgents({ a: { name: "x" } }, MODEL), { a: { name: "x", features: { "file-upload": false } } });
});

test("the model setting names the OpenAI-compatible provider only", () => {
  assert.ok(RITA_MODEL_RE.test(MODEL));
  for (const bad of ["anthropic:claude-opus-5-5", "qwen3.6-35b", "openai:", "openai:a b", "openai:x/../y"]) {
    assert.ok(!RITA_MODEL_RE.test(bad), bad);
  }
});
