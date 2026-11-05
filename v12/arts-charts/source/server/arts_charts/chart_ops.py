# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""`chart-ops/1`: the edits Rita makes to a chart body, applied as one change.

`apply(body, ops)` returns a new body (and a new title, if an op set one) or
raises OpError naming the first bad op; the input is never touched, so a list
with one bad op changes nothing. The result is still checked by
`chart_body.validate` when it is saved -- this module only knows the ops.

Where an added study goes (S14): an overlay (registry pane "price") goes on
the price series' panel and side, an own-pane study in the last panel of the
`panels` text, unless Rita names `panel`/`side`. The `panels` text is never
rewritten. A study added with no colour is stored with the next palette
colour no series on the chart uses (P2; the card's own picker gives the registry's colour instead -- a ruling). Its
params are the registry's defaults under the ones Rita gave: the card claims
a served line for a study series by its full params, and draws a line it
cannot claim on panel 1, so a study stored as `{"name": "rsi"}` alone would
be drawn over the price whatever its panel.
"""
from __future__ import annotations

import copy
import json
import uuid

from arts_charts.anchors import instant, is_anchor
from openbq_ta.registry import REGISTRY

MAX_OPS = 64
#: The series types that draw the price itself (chart_body.TYPES less volume, performance, study).
PRICE = ("candlestick", "ohlc", "line", "area")
#: The card's study swatches (client/src/lib/chart/createChartTheme.ts STUDY_SWATCHES);
#: test_chart_ops reads that file and asserts the two lists are equal.
STUDY_SWATCHES = ("#2563eb", "#da7101", "#0e9f6e", "#e0393e", "#7c5cbf", "#01696f", "#98c379")
#: The six keys every panel row carries (client/src/lib/chart/panels.ts HEAD_KEYS).
PANEL_KEYS = {"top", "left", "width", "height", "xmargin", "ymargin"}
#: The card's DEFAULT_PANELS_TEXT: a price panel over a volume panel.
DEFAULT_PANELS = 2


class OpError(ValueError):
    """Why an op list cannot apply; nothing is written."""


def panel_count(panels: str | None) -> int | None:
    """How many panels the card's `panels` text lays out, or None when it cannot be read.

    ponytail: counts the dict entries (or `;` rows) that carry all six head
    fields, as parsePanels keeps them; it does not resolve geometry
    expressions. The card clamps a series past its last panel, so an
    over-count is drawn in the last panel. Port parsePanels if that bites.
    """
    if panels is None:
        return DEFAULT_PANELS
    text = panels.strip()
    if text.startswith("{"):
        for candidate in (text, text.replace("'", '"')):
            try:
                parsed = json.loads(candidate)
                break
            except ValueError:
                parsed = None
        if not isinstance(parsed, dict):
            return None
        n = sum(1 for v in parsed.values() if isinstance(v, dict) and PANEL_KEYS <= set(v))
    else:
        n = sum(1 for row in text.split(";") if len(row.split(",")) >= 6)
    return n or None


def _keys(op: dict, required: tuple, optional: tuple = ()) -> None:
    for key in required:
        if key not in op:
            raise OpError(f"{op['op']} needs {key}")
    extra = sorted(set(op) - {"op", *required, *optional})
    if extra:
        raise OpError(f"{op['op']} takes no {extra[0][:32]!r}")


def _series(body: dict) -> list:
    """The body's series, materialising the card's default drawing first when it has
    none -- otherwise adding one study would leave a chart of only that study."""
    if "series" not in body:
        last = panel_count(body.get("panels"))
        if last is None:
            raise OpError("the panels text cannot be read; name a panel and side")
        body["series"] = [{"type": "candlestick", "panel": 1, "side": "right"},
                          {"type": "volume", "panel": last, "side": "right"}]
    return body["series"]


def _study(body: dict, ref) -> dict:
    series = _series(body)
    if isinstance(ref, bool) or not isinstance(ref, (int, str)):
        raise OpError("series is a series id or index")
    if isinstance(ref, int):
        if not 0 <= ref < len(series):
            raise OpError(f"no series {ref}")
        found = series[ref]
    else:
        found = next((s for s in series if s.get("id") == ref), None)
        if found is None:
            raise OpError(f"no series {ref[:64]!r}")
    if found.get("type") != "study":
        raise OpError(f"series {ref!r} is not a study")
    return found


def _next_color(series: list) -> str:
    """The first swatch no series on the chart uses; the first again when all are used."""
    used = {str(s.get("color", "")).lower() for s in series}
    return next((c for c in STUDY_SWATCHES if c not in used), STUDY_SWATCHES[0])


def _object(op: dict, key: str) -> dict:
    value = op.get(key, {})
    if not isinstance(value, dict):
        raise OpError(f"{key} must be an object")
    return value


def _merge(current: dict, patch: dict) -> dict:
    """`patch` over `current`; a null value removes that key."""
    out = {**current, **patch}
    return {k: v for k, v in out.items() if v is not None}


def _instant(values: dict, key: str, obs: bool = False) -> str:
    """Rita writes instants only (S14): she has no date grammar, and the host is the one
    that resolves expressions."""
    value = values[key]
    if not (is_anchor(value) and (obs or not str(value).startswith("OBS-"))):
        raise OpError(f"{key} must be an ISO-8601 instant{' or OBS-n' if obs else ''}, "
                      f"not {str(value)[:64]!r}; expressions are resolved by the host")
    return value


def _times(name: str, params: dict) -> None:
    for key in (REGISTRY[name].times if name in REGISTRY else ()):
        if params.get(key) is not None:
            _instant(params, key, obs=True)


def _add_study(body: dict, op: dict) -> None:
    _keys(op, ("name",), ("params", "panel", "side", "color", "style"))
    name = op["name"]
    if not isinstance(name, str) or name not in REGISTRY:
        raise OpError(f"unknown indicator {str(name)[:64]!r}")
    params, style = _object(op, "params"), _object(op, "style")
    series = _series(body)
    if REGISTRY[name].pane == "price":
        price = next((s for s in series if s.get("type") in PRICE), None)
        panel, side = (price["panel"], price["side"]) if price else (1, "right")
    else:
        panel, side = panel_count(body.get("panels")), "right"
    panel, side = op.get("panel", panel), op.get("side", side)
    if panel is None:
        raise OpError("the panels text cannot be read; name a panel and side")
    _times(name, params)
    defaults = {k: v for k, v in REGISTRY[name].params.items() if v is not None}
    entry = {"id": str(uuid.uuid4()), "type": "study", "name": name,
             "params": {**defaults, **params}, "panel": panel, "side": side}
    entry["color"] = op["color"] if "color" in op else _next_color(series)
    if style:
        entry["style"] = style
    series.append(entry)


def _remove_study(body: dict, op: dict) -> None:
    _keys(op, ("series",))
    found = _study(body, op["series"])
    body["series"] = [s for s in body["series"] if s is not found]


def _retune_study(body: dict, op: dict) -> None:
    _keys(op, ("series",), ("params", "color", "style"))
    found = _study(body, op["series"])
    if "params" in op:
        found["params"] = _merge(found.get("params", {}), _object(op, "params"))
        _times(found["name"], found["params"])
    if "style" in op:
        found["style"] = _merge(found.get("style", {}), _object(op, "style"))
        if not found["style"]:
            del found["style"]
    if "color" in op:
        if op["color"] is None:
            found.pop("color", None)
        else:
            found["color"] = op["color"]


def _set_interval(body: dict, op: dict) -> None:
    _keys(op, ("interval",))
    body["interval"] = op["interval"]


def _set_range(body: dict, op: dict) -> None:
    _keys(op, ("from", "to"))
    body["range"] = {"from": _instant(op, "from"), "to": _instant(op, "to")}


def _clear_range(body: dict, op: dict) -> None:
    _keys(op, ())
    body.pop("range", None)


def _add_anchor(body: dict, op: dict) -> None:
    _keys(op, ("anchor",))
    anchor = _instant(op, "anchor", obs=True)
    anchors = body.setdefault("anchors", [])
    if not any(instant(a) == anchor for a in anchors):
        anchors.append(anchor)


def _remove_anchor(body: dict, op: dict) -> None:
    _keys(op, ("anchor",))
    found = next((a for a in body.get("anchors", []) if a == op["anchor"] or instant(a) == op["anchor"]), None)
    if found is None:
        raise OpError(f"no anchor {str(op['anchor'])[:64]!r}")
    body["anchors"].remove(found)


def _add_level(body: dict, op: dict) -> None:
    _keys(op, ("price",))
    body.setdefault("levels", []).append({"price": op["price"], "origin": "rita"})


def _add_drawing(body: dict, op: dict) -> None:
    _keys(op, ("drawing",))
    body.setdefault("drawings", []).append(op["drawing"])


def _remover(key: str, noun: str):
    def remove(body: dict, op: dict) -> None:
        _keys(op, ("index",))
        items, index = body.get(key, []), op["index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
            raise OpError(f"no {noun} {str(index)[:16]}")
        del items[index]
    return remove


OPS = {
    "set_interval": _set_interval, "set_range": _set_range, "clear_range": _clear_range,
    "add_study": _add_study, "remove_study": _remove_study, "retune_study": _retune_study,
    "add_anchor": _add_anchor, "remove_anchor": _remove_anchor,
    "add_level": _add_level, "remove_level": _remover("levels", "level"),
    "add_drawing": _add_drawing, "remove_drawing": _remover("drawings", "drawing"),
    "set_title": None,  # handled in apply: the title is the document's, not the body's
}


def apply(body: dict, ops) -> tuple[dict, str | None]:
    """`ops` applied in order to a copy of `body`: (new body, new title or None)."""
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        raise OpError(f"ops must be a list of 1-{MAX_OPS} ops")
    out, title = copy.deepcopy(body), None
    for i, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or op.get("op") not in OPS:
                name = op.get("op") if isinstance(op, dict) else op
                raise OpError(f"unknown op {str(name)[:32]!r}")
            if op["op"] == "set_title":
                _keys(op, ("title",))
                if not isinstance(op["title"], str):
                    raise OpError("title must be text")
                title = op["title"]
            else:
                OPS[op["op"]](out, op)
        except OpError as exc:
            raise OpError(f"ops[{i}]: {exc}") from None
    return out, title
