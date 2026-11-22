"""Frozen chart-stream-v1 validation; sequences never pass through floats."""

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

_SCHEMA = json.loads((Path(__file__).parent / "resources/chart-stream-v1.schema.json").read_text())
MAX_SEQ = 2**63 - 1


def validate(value, schema=None):
    """Validate the small, pinned schema without runtime package discovery."""
    schema = _SCHEMA if schema is None else schema
    if "$ref" in schema:
        return validate(value, _SCHEMA["$defs"][schema["$ref"].split("/")[-1]])
    if "oneOf" in schema:
        hits = 0
        for candidate in schema["oneOf"]:
            try:
                validate(value, candidate)
                hits += 1
            except ValueError:
                pass
        if hits != 1:
            raise ValueError("invalid frame structure")
    if "anyOf" in schema:
        for candidate in schema["anyOf"]:
            try:
                validate(value, candidate)
                break
            except ValueError:
                pass
        else:
            raise ValueError("invalid alternative")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError("invalid constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("invalid enum")
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    predicates = {
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str),
        "integer": lambda x: type(x) is int,
        "number": lambda x: type(x) in (int, float),
        "boolean": lambda x: type(x) is bool,
        "null": lambda x: x is None,
    }
    if types and not any(predicates[t](value) for t in types):
        raise ValueError("invalid type")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if any(k not in value for k in schema.get("required", [])):
            raise ValueError("missing field")
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError("unknown field")
        for k, v in value.items():
            if k in props:
                validate(v, props[k])
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", len(value)):
            raise ValueError("too many items")
        for item in value:
            validate(item, schema.get("items", {}))
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value)):
            raise ValueError("invalid length")
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise ValueError("invalid string")
        if pattern == "^(0|[1-9][0-9]{0,18})$" and int(value) > MAX_SEQ:
            raise ValueError("sequence out of range")
    if type(value) in (int, float):
        import math

        if not math.isfinite(value) or not schema.get("minimum", value) <= value <= schema.get(
            "maximum", value
        ):
            raise ValueError("invalid number")
    for condition in schema.get("allOf", []):
        try:
            validate(value, condition["if"])
        except ValueError:
            validate(value, condition.get("else", {}))
        else:
            validate(value, condition.get("then", {}))
    if "not" in schema:
        try:
            validate(value, schema["not"])
        except ValueError:
            pass
        else:
            raise ValueError("forbidden field")


def timestamp(value):
    base, _, fraction = value[:-1].partition(".")
    datetime.strptime(base, "%Y-%m-%dT%H:%M:%S")
    return base + "." + fraction.ljust(9, "0") + "Z"


def normalize_view(view):
    result = dict(view)
    result.setdefault("max_items", 2000 if result.get("mode") == "candles" else 10000)
    validate(result, _SCHEMA["$defs"]["view"])
    for field in ("start", "end"):
        if field in result:
            result[field] = timestamp(result[field])
    if "end" in result and result["end"] <= result["start"]:
        raise ValueError("end must follow start")
    return result


def view_key(view):
    return sha256(
        json.dumps(
            normalize_view(view), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def wire(value):
    """Normalize native q dictionaries without lossy numeric coercion."""
    if hasattr(value, "py"):
        return wire(value.py())
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, dict):
        return {wire(k): wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire(v) for v in value]
    if hasattr(value, "item"):
        return wire(value.item())
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise ValueError("unsupported native value")


def cursor_cmp(left, right):
    validate(left, _SCHEMA["$defs"]["cursor"])
    validate(right, _SCHEMA["$defs"]["cursor"])
    if left["epoch"] != right["epoch"]:
        raise ValueError("epoch mismatch")
    return int(left["seq"]) - int(right["seq"])
