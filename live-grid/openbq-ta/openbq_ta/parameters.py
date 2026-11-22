# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Typed decorator metadata and authoritative shared parameter validation."""

from datetime import datetime
import math

_TYPES = {"integer", "number", "string", "boolean"}
_KEYS = {"type", "default", "label", "minimum", "maximum", "step", "enum", "nullable"}


def validate_value(name, value, descriptor, *, time_parameter=False):
    if value is None and descriptor.get("nullable"):
        return
    if time_parameter and isinstance(value, datetime):
        return  # Existing in-process anchors resolve to UTC in compute.resolve_times.
    kind = descriptor["type"]
    valid = {
        "integer": lambda v: type(v) is int,
        "number": lambda v: type(v) in (int, float) and math.isfinite(v),
        "string": lambda v: isinstance(v, str),
        "boolean": lambda v: type(v) is bool,
    }[kind](value)
    if not valid:
        raise ValueError(f"{name}: expected {kind}")
    if kind in ("integer", "number"):
        if "minimum" in descriptor and value < descriptor["minimum"]:
            raise ValueError(f"{name}: below minimum")
        if "maximum" in descriptor and value > descriptor["maximum"]:
            raise ValueError(f"{name}: above maximum")
    if "enum" in descriptor and not any(
        (kind == "number" or type(value) is type(v)) and value == v for v in descriptor["enum"]
    ):
        raise ValueError(f"{name}: unsupported choice")


def parameter_schema(params, supplied=None, *, labels=None, steps=None, windows=(), times=()):
    supplied = dict(supplied or {})
    if supplied.keys() - params.keys():
        raise ValueError("parameter schema names unknown parameters")
    result = {}
    for name, default in params.items():
        kind = (
            "boolean"
            if type(default) is bool
            else "integer"
            if type(default) is int
            else "number"
            if type(default) is float
            else "string"
            if isinstance(default, str) or default is None
            else None
        )
        if kind is None:
            raise ValueError(f"{name}: unsupported parameter default")
        descriptor = {
            "type": kind,
            "default": default,
            "label": (labels or {}).get(name, name.replace("_", " ").capitalize()),
        }
        if kind == "integer":
            descriptor["step"] = 1
        if name in windows:
            descriptor["minimum"] = 1
        if name in (steps or {}):
            descriptor["step"] = steps[name]
        if default is None:
            descriptor["nullable"] = True
        explicit = supplied.get(name, {})
        if not isinstance(explicit, dict) or explicit.keys() - _KEYS:
            raise ValueError(f"{name}: invalid parameter descriptor")
        if "default" in explicit and (
            type(explicit["default"]) is not type(default) or explicit["default"] != default
        ):
            raise ValueError(f"{name}: descriptor default disagrees with params")
        descriptor.update(explicit)
        if (
            descriptor["type"] not in _TYPES
            or not isinstance(descriptor["label"], str)
            or not descriptor["label"]
        ):
            raise ValueError(f"{name}: invalid parameter type or label")
        numeric = descriptor["type"] in ("integer", "number")
        for key in ("minimum", "maximum", "step"):
            if key in descriptor and (
                not numeric
                or type(descriptor[key]) not in (int, float)
                or not math.isfinite(descriptor[key])
            ):
                raise ValueError(f"{name}: invalid {key}")
        if (
            descriptor["type"] == "integer"
            and "step" in descriptor
            and (type(descriptor["step"]) is not int)
        ):
            raise ValueError(f"{name}: integer step must be a whole number")
        if "step" in descriptor and descriptor["step"] <= 0:
            raise ValueError(f"{name}: step must be positive")
        if descriptor.get("minimum", float("-inf")) > descriptor.get("maximum", float("inf")):
            raise ValueError(f"{name}: reversed bounds")
        if "nullable" in descriptor and type(descriptor["nullable"]) is not bool:
            raise ValueError(f"{name}: invalid nullable")
        if "enum" in descriptor:
            choices = descriptor["enum"]
            if not isinstance(choices, list) or not choices or len(choices) > 256:
                raise ValueError(f"{name}: invalid choices")
            check = {k: v for k, v in descriptor.items() if k != "enum"}
            for choice in choices:
                validate_value(name, choice, check)
            if len({(type(v).__name__, str(v)) for v in choices}) != len(choices):
                raise ValueError(f"{name}: duplicate choices")
        validate_value(name, default, descriptor, time_parameter=name in times)
        result[name] = descriptor
    return result
