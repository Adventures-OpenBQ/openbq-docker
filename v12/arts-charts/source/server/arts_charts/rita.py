# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""The headless Rita client: the worker plays BDOBB's part in one Rita turn (spec §3, §4).

agent-rita's protocol, as its source states it (routes/query.ts,
protocol/stream.ts, protocol/events.ts, mcp/factory.ts, mcp/results.ts) and as
BDOBB speaks it (bdobb-v2 src/lib/agent/query.ts, request.ts, execute.ts):

- POST <rita>/v1/query, JSON `{messages, widgets: {primary, secondary, extra},
  context: null, urls: [], timezone, workspace_options: {}, tools,
  skills_catalog: [], selected_skills: []}`. `tools` are MCP tools as
  `{name, server_id, url, description, input_schema: {properties, required}}`.
- The answer is SSE: `event: <name>` / `data: <json>` blocks. Text arrives as
  `copilotMessageChunk {delta}`; a failure as `copilotStatusUpdate` with
  `eventType: "ERROR"`.
- Rita declares MCP tools without an executor, so a tool call ends the stream
  with `copilotFunctionCall {function: "execute_agent_tool", input_arguments:
  {server_id, tool_name, parameters}, extra_state}`. The client runs the tool and
  POSTs again with two more messages: `{role: "ai", content: {function,
  input_arguments}}` and `{role: "tool", function, input_arguments, data:
  [{items: <the MCP result's content[]>}], extra_state}` -- fields at the top
  level, `data` a list (agent-rita iterates it).
- A stream that ends without a function call ends the turn.

Text from Rita is untrusted markdown; the caller decides where it goes.
"""
from __future__ import annotations

import asyncio
import json

import httpx

from arts_charts.auth import StackAuth

#: Tool rounds per turn; one more answer may summarize but cannot call a tool.
ROUNDS = 4
#: Seconds one whole turn may take, every round included.
TURN_TIMEOUT = 120.0
#: Characters of reply kept; the rest is cut and marked with an ellipsis.
REPLY_MAX = 8000
#: Bytes of SSE read per round before the rest is dropped.
STREAM_MAX = 2_000_000
SERVER_ID = "arts-charts"
_MCP_HEADERS = {"Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18"}


class RitaUnavailable(Exception):
    """Rita could not answer: unreachable, an error, too slow, or no reply at all."""


def _text_item(value) -> dict:
    return {"type": "text", "text": json.dumps(value)}


class Mcp:
    """The chart tools as the worker calls them: one JSON-RPC POST per call to the
    stateless endpoint, with the wake token in its header."""

    def __init__(self, http: httpx.AsyncClient, url: str):
        self.http, self.url = http, url

    async def _rpc(self, method: str, params: dict, token: str | None = None) -> dict:
        headers = {**_MCP_HEADERS, **({"X-Arts-Charts-Wake": token} if token else {})}
        # Only this request carries the stack's pair: `http` is Rita's client too.
        response = await self.http.post(self.url, headers=headers, auth=StackAuth(), json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        response.raise_for_status()
        answer = response.json()
        if "result" not in answer:
            raise ValueError(str(answer.get("error", {}).get("message", "no result"))[:200])
        return answer["result"]

    async def agent_tools(self, names: set[str]) -> list[dict]:
        """The named tools, as Rita's request lists them."""
        listed = (await self._rpc("tools/list", {}))["tools"]
        return [{"name": t["name"], "server_id": SERVER_ID, "url": self.url,
                 "description": t.get("description") or t["name"],
                 "input_schema": {"properties": t["inputSchema"].get("properties", {}),
                                  "required": t["inputSchema"].get("required", [])}}
                for t in listed if t["name"] in names]

    async def call(self, name: str, arguments: dict, token: str) -> dict:
        """The tool's MCP result; a failure to reach it is a result too, as BDOBB's is."""
        try:
            return await self._rpc("tools/call", {"name": name, "arguments": arguments}, token)
        except (httpx.HTTPError, ValueError) as exc:
            return {"content": [_text_item({"error_type": "tool_failed", "tool": name,
                                            "message": str(exc)[:200]})], "isError": True}


async def _events(response: httpx.Response):
    """(event, payload) per SSE block; stops quietly after STREAM_MAX bytes."""
    event, data, size = "message", [], 0
    async for line in response.aiter_lines():
        size += len(line) + 1
        if size > STREAM_MAX:
            return
        if line == "":
            if data:
                try:
                    yield event, json.loads("\n".join(data))
                except ValueError:
                    pass
            event, data = "message", []
        elif not line.startswith(":"):
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "event":
                event = value
            elif field == "data":
                data.append(value)
    if data:
        try:
            yield event, json.loads("\n".join(data))
        except ValueError:
            pass


class Rita:
    def __init__(self, url: str, http: httpx.AsyncClient, mcp: Mcp):
        self.url, self.http, self.mcp = url.rstrip("/") + "/v1/query", http, mcp

    def _request(self, history: list[dict], tools: list[dict]) -> dict:
        return {"messages": history, "widgets": {"primary": [], "secondary": [], "extra": []},
                "context": None, "urls": [], "timezone": "America/New_York",
                "workspace_options": {}, "tools": tools, "skills_catalog": [],
                "selected_skills": []}

    async def _execute(self, call: dict, offered: set[str], token: str) -> dict:
        args = call.get("input_arguments") if isinstance(call.get("input_arguments"), dict) else {}
        tool = args.get("tool_name")
        if call.get("function") != "execute_agent_tool":
            data: object = {"error_type": "unsupported"}
        elif args.get("server_id") != SERVER_ID or tool not in offered:
            data = [{"items": [_text_item({"error_type": "unsupported", "tool": tool})]}]
        else:
            params = args.get("parameters") if isinstance(args.get("parameters"), dict) else {}
            data = [{"items": (await self.mcp.call(tool, params, token)).get("content", [])}]
        message = {"role": "tool", "function": call.get("function"),
                   "input_arguments": call.get("input_arguments"), "data": data}
        if call.get("extra_state") is not None:
            message["extra_state"] = call["extra_state"]
        return message

    async def turn(self, prompt: str, tools: list[dict], token: str, *, rounds: int = ROUNDS,
                   timeout: float = TURN_TIMEOUT) -> str:
        """Rita's whole reply to `prompt`, every tool call run under `token`."""
        try:
            async with asyncio.timeout(timeout):
                text = await self._turn(prompt, tools, token, rounds)
        except TimeoutError:
            raise RitaUnavailable(f"Rita timed out after {timeout:g} s") from None
        except httpx.HTTPError as exc:
            raise RitaUnavailable(f"Rita unreachable ({type(exc).__name__})") from None
        text = text.strip()
        if not text:
            raise RitaUnavailable("Rita sent no reply")
        return text if len(text) <= REPLY_MAX else text[:REPLY_MAX - 1] + "…"

    async def _turn(self, prompt: str, tools: list[dict], token: str, rounds: int) -> str:
        history: list[dict] = [{"role": "human", "content": prompt}]
        offered, reply, kept = {t["name"] for t in tools}, [], 0
        for round_ in range(rounds + 1):
            call = None
            async with self.http.stream("POST", self.url, json=self._request(history, tools),
                                        headers={"Accept": "text/event-stream"}) as response:
                if response.status_code != 200:
                    raise RitaUnavailable(f"Rita answered {response.status_code}")
                async for event, payload in _events(response):
                    if not isinstance(payload, dict):
                        continue
                    if event == "copilotMessageChunk" and isinstance(payload.get("delta"), str):
                        if kept <= REPLY_MAX:  # past the cap, read on but keep nothing
                            reply.append(payload["delta"][:REPLY_MAX + 1 - kept])
                            kept += len(reply[-1])
                    elif event == "copilotFunctionCall":
                        call = payload
                    elif event == "copilotStatusUpdate" and payload.get("eventType") == "ERROR":
                        raise RitaUnavailable("Rita reported an error")
            if call is None or round_ == rounds:
                break
            history.append({"role": "ai", "content": {"function": call.get("function"),
                                                      "input_arguments": call.get("input_arguments")}})
            history.append(await self._execute(call, offered, token))
        return "".join(reply)
