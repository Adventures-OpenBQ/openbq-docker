// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

/**
 * The /ai (Rita) family on the door (user ruling 2026-10-20, reversing R3a for a
 * Qwen-only Rita). Additive: policy.mjs, the contract BDOBB's web layer vendors, is
 * unchanged. Three routes only -- her document, her one streamed query, and her feedback vote
 * (`/ai/v1/feedback`, rebuilt from its six fields). Her /v1/generate/* routes take a model of
 * their own and stay closed.
 *
 * What the door sends her is REBUILT here, never the caller's bytes:
 *   - the model is the pinned one (settings.json "ritaModel"): agent-rita takes
 *     workspace_options.model over its own DEFAULT_MODEL, so a caller could otherwise
 *     name any provider the container holds a key for;
 *   - `urls` and `documents` are dropped, and every `url` anywhere is blanked, as is any
 *     `content` string that is itself a fetchable URL: Rita fetches those server-side
 *     (url-prefetch, documents, widget and file items, inline media), from
 *     inside the stack's network and the tailnet, so a caller-named URL is a request
 *     forgery against the NAS. "" keeps her request schema valid and is falsy at every
 *     fetch site.
 * The door's Rita (openbq-rita-door) holds no paid key as well: this is one layer of two.
 */

export const RITA_MODEL_RE = /^openai:[A-Za-z0-9._-]{1,100}$/;
const MAX_DEPTH = 64;

export function ritaRoute(url, method) {
  if (url.search) return null;
  if (url.pathname === "/ai/agents.json" && method === "GET") return "agents";
  if (url.pathname === "/ai/v1/query" && method === "POST") return "query";
  if (url.pathname === "/ai/v1/feedback" && method === "POST") return "feedback";
  return null;
}

// A string that parses as a URL Rita, her AI SDK or the model server could fetch.
const FETCHABLE = new Set(["http:", "https:", "ws:", "wss:", "ftp:", "file:"]);
const fetchable = value => { try { return FETCHABLE.has(new URL(value).protocol); } catch { return false; } };
const plain = value => typeof value === "object" && value !== null && !Array.isArray(value);
// defineProperty: a "__proto__" key stays a plain own key, never a prototype.
const put = (target, key, value) => Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });

/** A copy with every `url` blanked; undefined past MAX_DEPTH. */
function blankUrls(value, depth = 0) {
  if (depth > MAX_DEPTH) return undefined;
  if (Array.isArray(value)) {
    const out = [];
    for (const item of value) { const next = blankUrls(item, depth + 1); if (next === undefined) return undefined; out.push(next); }
    return out;
  }
  if (!plain(value)) return value;
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (key === "url") { out.url = ""; continue; }
    // An image or pdf item's string content is handed to the AI SDK as the media itself, and
    // a URL-shaped one is fetched (agent-rita widgets/parse.ts): blanked like a url.
    if (key === "content" && typeof item === "string" && fetchable(item)) { out.content = ""; continue; }
    const next = blankUrls(item, depth + 1);
    if (next === undefined) return undefined;
    put(out, key, next);
  }
  return out;
}

/** Rita's query body as the door forwards it, or null to refuse it (400). */
export function ritaQuery(body, model) {
  let raw;
  try { raw = JSON.parse(body.toString("utf8")); } catch { return null; }
  if (!plain(raw) || !Array.isArray(raw.messages) || raw.messages.length === 0) return null;
  const { model: _model, urls: _urls, documents: _documents, workspace_options: options, ...rest } = raw;
  const out = blankUrls(rest);
  if (out === undefined) return null;
  const kept = {};
  if (plain(options)) {
    for (const [key, value] of Object.entries(options)) {
      if (typeof value === "string" || typeof value === "boolean") put(kept, key, value);
    }
  }
  kept.model = model;
  out.workspace_options = kept;
  return out;
}

/** Her agents.json with the model select narrowed to the pinned model and upload off; null if malformed. */
export function ritaAgents(doc, model) {
  if (!plain(doc)) return null;
  const out = {};
  for (const [id, agent] of Object.entries(doc)) {
    if (!plain(agent) || (agent.features !== undefined && !plain(agent.features))) return null;
    const features = { ...agent.features, "file-upload": false };
    if (plain(features.model)) features.model = { ...features.model, default: model, options: [{ label: model, value: model }] };
    put(out, id, { ...agent, features });
  }
  return out;
}

export const RITA_FEEDBACK_MAX = 64 * 1024;
const VOTES = new Set(["thumbs_up", "thumbs_down"]);

/** A feedback vote as the door forwards it: the six known fields, rebuilt; null to refuse (400). */
export function ritaFeedback(body) {
  let raw;
  try { raw = JSON.parse(body.toString("utf8")); } catch { return null; }
  if (!plain(raw) || !VOTES.has(raw.vote)) return null;
  const tags = raw.tags ?? [];
  if (!Array.isArray(tags) || !tags.every(tag => typeof tag === "string")) return null;
  const out = { vote: raw.vote, tags };
  for (const key of ["user_comment", "ai_response", "user_prompt", "trace_id"]) {
    const value = raw[key] ?? "";
    if (typeof value !== "string") return null;
    out[key] = value;
  }
  return out;
}
