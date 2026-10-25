// Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
// SPDX-License-Identifier: Apache-2.0

/**
 * The /mcp family on the door (user ruling 2026-10-21): the stack's openbq-mcp, for the web
 * preview's MCP client and so for Rita's MCP tools. Additive, like rita-policy.mjs: policy.mjs,
 * the contract BDOBB's web layer vendors, is unchanged.
 *
 * One route, POST /mcp, one JSON-RPC message per request (MCP 2025-06-18 has no batches). The
 * door re-serialises each message from its parse and admits only:
 *   - the protocol's own methods below (no sampling, logging, completion or anything new);
 *   - tools/call on the read-only discovery tools, and call_tool, which runs one OpenBB
 *     endpoint with the stack's provider keys -- the catalogue /api already serves.
 * Refused: install_skill (it writes skills every user then reads), run_pipeline (one call,
 * many endpoints: past any per-request cap), and through call_tool those two, call_tool itself,
 * and the TMX file viewers, which fetched any URL named to them (verified 2026-10-21 against
 * openbq-mcp:6999 on NAS production; openbq-docker claude/v2.0-tmx-viewer-hosts fixes them).
 * And any call_tool whose arguments name a fetchable URL off the vetted hosts (URL_HOSTS).
 */

export const MCP_SESSION_RE = /^[A-Za-z0-9._~-]{1,200}$/;
export const MCP_VERSION_RE = /^\d{4}-\d{2}-\d{2}$/;
const METHODS = new Set(["initialize", "notifications/initialized", "notifications/cancelled", "ping", "tools/list",
  "tools/call", "prompts/list", "prompts/get", "resources/list", "resources/read", "resources/templates/list"]);
const TOOLS = new Set(["available_categories", "available_tools", "search_tools", "call_tool", "list_prompts",
  "get_prompt", "list_resources", "read_resource"]);
const CALL_TOOL_REFUSED = new Set(["install_skill", "run_pipeline", "call_tool", "tmx_equity_filings_view", "tmx_index_document_view"]);
// The names call_tool dispatches on: lowercase identifiers, so a case or space variant of a
// refused name is refused as a shape rather than slipping past the set.
const TOOL_NAME_RE = /^[a-z0-9_]{1,200}$/;

const plain = value => typeof value === "object" && value !== null && !Array.isArray(value);
// Hosts whose documents call_tool may name, https only (and their subdomains). Their endpoints
// check the host themselves -- SEC and USDA by parsed hostname -- but the Congress text fetchers
// only look for "govinfo.gov"/"congress.gov" anywhere in the string, so the door parses every URL
// itself. Anything else that parses as a fetchable URL is refused, whatever tool or key names it.
const URL_HOSTS = ["sec.gov", "congress.gov", "govinfo.gov", "esmis.nal.usda.gov"];
const FETCHABLE = new Set(["http:", "https:", "ws:", "wss:", "ftp:", "file:"]);
const MAX_DEPTH = 32;
function allowedUrl(text) {
  let url; try { url = new URL(text); } catch { return true; }     // not a URL at all
  if (!FETCHABLE.has(url.protocol)) return true;
  const host = url.hostname.toLowerCase();
  return url.protocol === "https:" && !url.username && !url.password && !url.port &&
    URL_HOSTS.some(allowed => host === allowed || host.endsWith("." + allowed));
}
/** Every string in a call_tool's arguments -- and each comma-separated piece, as OpenBB splits them. */
function urlsAllowed(value, depth = 0) {
  if (depth > MAX_DEPTH) return false;
  if (typeof value === "string") return [value, ...value.split(",")].every(piece => allowedUrl(piece.trim()));
  if (Array.isArray(value)) return value.every(item => urlsAllowed(item, depth + 1));
  if (plain(value)) return Object.values(value).every(item => urlsAllowed(item, depth + 1));
  return true;
}

export function mcpRoute(url, method) {
  return url.pathname === "/mcp" && !url.search && method === "POST";
}

/** { body } to forward, or { error } -- never the caller's bytes. */
export function mcpMessage(raw) {
  let message;
  try { message = JSON.parse(raw.toString("utf8")); } catch { return { error: "parse" }; }
  if (!plain(message) || message.jsonrpc !== "2.0" || !METHODS.has(message.method)) return { error: "method" };
  if (message.id !== undefined && typeof message.id !== "string" && typeof message.id !== "number") return { error: "id" };
  if (message.method === "tools/call") {
    const params = message.params;
    if (!plain(params) || !TOOLS.has(params.name)) return { error: "tool" };
    if (params.name === "call_tool") {
      const target = params.arguments;
      if (!plain(target) || typeof target.name !== "string" || !TOOL_NAME_RE.test(target.name) ||
          CALL_TOOL_REFUSED.has(target.name) || !urlsAllowed(target.arguments)) return { error: "tool" };
    }
  }
  return { body: Buffer.from(JSON.stringify(message)), method: message.method };
}
