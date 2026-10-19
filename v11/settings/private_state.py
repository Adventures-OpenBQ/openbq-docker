"""Fixed machine-only browser-state endpoint, independent of key-mode identity."""
import hashlib
import hmac
import json
import re
from starlette.responses import JSONResponse, Response

PREFIX = "/_openbq/settings/v1/state"
NAME = re.compile(r"(?:settings|backends|folders|chat|chart-presets)\.json|dashboards/[A-Za-z0-9_-]{1,80}\.json")
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
SPACE = re.compile(r"[ \t\r\n]*")


def valid_json(raw):
    """Validate Node-compatible syntax without numeric conversion or recursive trees.

    Input is already byte-bounded. The explicit container stack accepts deep JSON
    that JSON.parse accepts without changing the process recursion limit. The
    stdlib string scanner retains JSON escape/control/Unicode validation.
    """
    text = raw.decode("utf-8", errors="replace")
    stack = ["value"]
    index = 0
    while stack:
        index = SPACE.match(text, index).end()
        if index == len(text):
            raise ValueError()
        state = stack.pop()
        char = text[index]
        if state == "colon":
            if char != ":":
                raise ValueError()
            index += 1
        elif state in ("object_first", "object_key"):
            if state == "object_first" and char == "}":
                index += 1
            else:
                if char != '"':
                    raise ValueError()
                _, index = json.decoder.scanstring(text, index + 1, True)
                stack.extend(("object_next", "value", "colon"))
        elif state == "object_next":
            if char == ",":
                stack.append("object_key")
            elif char != "}":
                raise ValueError()
            index += 1
        elif state == "array_first":
            if char == "]":
                index += 1
            else:
                stack.extend(("array_next", "value"))
        elif state == "array_next":
            if char == ",":
                stack.extend(("array_next", "value"))
            elif char != "]":
                raise ValueError()
            index += 1
        elif char in "{[":
            stack.append("object_first" if char == "{" else "array_first")
            index += 1
        elif char == '"':
            _, index = json.decoder.scanstring(text, index + 1, True)
        elif char in "-0123456789":
            number = NUMBER.match(text, index)
            if number is None:
                raise ValueError()
            index = number.end()
        else:
            literal = next((word for word in ("true", "false", "null") if text.startswith(word, index)), None)
            if literal is None:
                raise ValueError()
            index += len(literal)
    if SPACE.match(text, index).end() != len(text):
        raise ValueError()


async def handle(request, runtime):
    config = runtime.store.config
    if not config.gateway:
        return Response(status_code=404)
    auth = request.headers.getlist("authorization")
    expected = hashlib.sha256(("Bearer " + config.token).encode()).digest()
    if len(auth) != 1 or not hmac.compare_digest(hashlib.sha256(auth[0].encode()).digest(), expected):
        return Response(status_code=401)
    match = re.fullmatch(re.escape(PREFIX) + r"/([0-9]{1,20})(?:/(.+))?", request.url.path)
    if not match or request.url.query or request.scope.get("raw_path", b"").find(b"%") >= 0:
        return Response(status_code=404)
    principal, name = match.groups()
    if name is None:
        if request.method != "GET":
            return Response(status_code=405)
        return JSONResponse({"files": await runtime.run(runtime.store.files, principal)})
    if not NAME.fullmatch(name):
        return Response(status_code=404)
    if request.method not in ("PUT", "DELETE"):
        return Response(status_code=405)
    body = None
    if request.method == "PUT":
        if not request.headers.get("content-type", "").startswith("application/json"):
            return Response(status_code=415)
        lengths = request.headers.getlist("content-length")
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]) or request.headers.get("transfer-encoding"):
            return Response(status_code=411)
        if int(lengths[0]) > 262144:
            return Response(status_code=413)
        parts = []
        size = 0
        async for part in request.stream():
            size += len(part)
            if size > 262144:
                return Response(status_code=413)
            parts.append(part)
        body = b"".join(parts)
        if len(body) != int(lengths[0]):
            return Response(status_code=400)
        try:
            valid_json(body)
        except (ValueError, RecursionError):
            return Response(status_code=400)
    return Response(status_code=await runtime.run(runtime.store.state, principal, name, body))
