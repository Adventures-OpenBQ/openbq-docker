# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0

"""Assemble widget rows from parsed credentials, applying tier redaction.

`value` is ABSENT (not masked) below tier 3, so no client rendering bug can
ever leak it. `values=None` means the file was unreadable: emit a banner row
plus one 'unknown' row per registered provider — HTTP 200 always."""
from __future__ import annotations

from app.registry import (
    IGNORE,
    LOCAL_PROVIDERS,
    OPTIONAL_PROVIDERS,
    PROVIDERS,
    is_demo,
    provider_index,
)

_CRED_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET")
WORST_RANK = {"no_response": 4, "error": 3, "auth_failed": 2, "skipped": 1, "ok": 0}

_NOT_INSTALLED = {
    "result": "skipped",
    "detail": "not installed on this backend",
    "kind": "connectivity",
    "code": "not_installed",
}


def _status(values: dict[str, str], env_var: str) -> str:
    if env_var not in values:
        return "missing"
    return "set" if values[env_var] else "empty"


def worst_check(checks: list[dict]) -> dict | None:
    """The worst check by result rank: no_response > error > auth_failed >
    skipped > ok. None when there are no checks."""
    if not checks:
        return None
    return max(checks, key=lambda c: WORST_RANK.get(c.get("result", "ok"), 0))


def _registry_auth(provider_id: str) -> str:
    """auth from the registry, used only when the descriptor is unavailable.
    Registry entries are all credentialed; the optional set is the exception."""
    return "optional" if provider_id in OPTIONAL_PROVIDERS else "required"


def _attach_checks(row: dict, tests, provider_id: str) -> None:
    checks = (tests or {}).get(provider_id)
    if checks:
        row["checks"] = list(checks)
        row["test"] = worst_check(checks)


def build_rows(
    values: dict[str, str] | None,
    tier: int,
    tests: dict[str, list[dict]] | None,
    *,
    malformed: list[str] | None = None,
    descriptor: list[dict] | None = None,
) -> list[dict]:
    if values is None:
        banner = {
            "provider": "⚠ credentials.env",
            "env_var": "",
            "status": "unknown",
            "demo": False,
        }
        unknowns = [
            {"provider": p.name, "env_var": var, "status": "unknown", "demo": False}
            for var, p in PROVIDERS.items()
        ]
        return [banner, *unknowns]

    if descriptor is None:
        rows = _registry_only_rows(values, tier, tests)
    else:
        rows = _joined_rows(values, tier, tests, descriptor)

    # Credential-shaped vars present in the file but unknown to the registry.
    for var, value in values.items():
        if var in PROVIDERS or var in IGNORE or not var.endswith(_CRED_SUFFIXES):
            continue
        row = {
            "provider": var,
            "env_var": var,
            "status": "set" if value else "empty",
            "demo": False,
        }
        if tier == 3:
            row["value"] = value
        rows.append(row)

    if malformed:
        rows.extend(
            {
                "provider": "⚠ malformed line",
                "env_var": entry,
                "status": "unknown",
                "demo": False,
            }
            for entry in malformed
        )
    return rows


def _registry_only_rows(values, tier, tests):
    """Descriptor unavailable: today's rows plus provider_id and registry
    auth. No `supported` key at all -- the descriptor never spoke, so
    "supported" cannot be answered, not even as `supported: None`."""
    rows = []
    for var, p in PROVIDERS.items():
        row = {
            "provider": p.name,
            "env_var": var,
            "status": _status(values, var),
            "demo": is_demo(var, values.get(var, "")),
            "provider_id": p.provider_id,
            "auth": _registry_auth(p.provider_id),
        }
        if tier == 3 and var in values:
            row["value"] = values[var]
        _attach_checks(row, tests, p.provider_id)
        rows.append(row)
    return rows


def _joined_rows(values, tier, tests, descriptor):
    """Join the live descriptor against the local registry. Descriptor-named
    non-local providers come first, in descriptor order (Cases A/B below),
    then registry entries the descriptor did not name (Case C/D)."""
    idx = provider_index()  # provider_id -> Provider
    rows = []
    named: set[str] = set()
    for d in descriptor:
        pid = d.get("id")
        if not pid or d.get("local") or pid in LOCAL_PROVIDERS:
            continue
        named.add(pid)
        auth = d.get("auth", "unknown")
        p = idx.get(pid)
        if p is not None:
            # Case A: descriptor provider WITH a registry entry.
            row = {
                "provider": p.name,
                "env_var": p.env_var,
                "status": _status(values, p.env_var),
                "demo": is_demo(p.env_var, values.get(p.env_var, "")),
                "provider_id": pid,
                "auth": auth,
                "supported": True,
            }
            if tier == 3 and p.env_var in values:
                row["value"] = values[p.env_var]
        else:
            # Case B: descriptor provider WITHOUT a registry entry
            #         (keyless, or a keyed provider the registry has not learned).
            env_vars = d.get("env_vars") or []
            env_var = env_vars[0] if env_vars else ""
            keyless = auth == "not_required"
            has_value = bool(env_var and values.get(env_var))
            status = _status(values, env_var) if env_var else "missing"
            row = {
                "provider": d.get("name") or pid.replace("_", " ").title(),
                "env_var": env_var,
                "status": status if has_value or env_var else "missing",
                "demo": is_demo(env_var, values.get(env_var, "")) if env_var else False,
                "provider_id": pid,
                "auth": auth,
                "supported": True,
            }
            if tier == 3 and env_var and env_var in values and not keyless:
                row["value"] = values[env_var]
        _attach_checks(row, tests, pid)
        rows.append(row)

    # Case D: registry entries the descriptor did not name -> not installed.
    for var, p in PROVIDERS.items():
        if p.provider_id in named:
            continue
        row = {
            "provider": p.name,
            "env_var": var,
            "status": _status(values, var),
            "demo": is_demo(var, values.get(var, "")),
            "provider_id": p.provider_id,
            "auth": "required",
            "supported": False,
            "test": dict(_NOT_INSTALLED),
            "checks": [dict(_NOT_INSTALLED)],
        }
        if tier == 3 and var in values:
            row["value"] = values[var]
        rows.append(row)  # no probe attempted; fixed skipped test overrides any supplied check
    return rows


def build_summary(rows: list[dict], *, descriptor_available: bool = True) -> str:
    """Key state as markdown, for the summary widget.

    Counts and provider names only, deliberately. Tier-3 rows carry the
    credential itself in row["value"]; this must never render it, which is
    also why its widget declares no raw view.
    """
    lines = []
    if not descriptor_available:
        lines.append("Provider inventory unavailable; showing configured credentials only.")
        lines.append("")

    by_status: dict[str, list[str]] = {}
    for row in rows:
        by_status.setdefault(str(row.get("status", "unknown")), []).append(
            str(row.get("provider", "?"))
        )
    total = len(rows)
    n_set = len(by_status.get("set", []))
    existing_lines = [f"**{n_set} of {total} provider keys configured**", ""]
    for status, label in (
        ("missing", "Missing"),
        ("empty", "Present but empty"),
        ("unknown", "Unreadable"),
    ):
        names = sorted(by_status.get(status, []))
        if names:
            existing_lines.append(f"- **{label} ({len(names)}):** {', '.join(names)}")
    demo = sorted(str(r.get("provider", "?")) for r in rows if r.get("demo"))
    if demo:
        existing_lines.append(
            f"- **Public demo key ({len(demo)}):** {', '.join(demo)}"
            " -- rate-limited and shared; replace before relying on it."
        )
    if n_set == total and not demo:
        existing_lines.append("- Every provider is configured with a private key.")
    return "\n".join(lines + existing_lines)
