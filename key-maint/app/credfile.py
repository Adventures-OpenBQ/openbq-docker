# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

"""Read literal settings from the credential file used by Docker Compose.

Quoted values preserve internal spaces and hashes. For unquoted values, as
in Compose, an initial hash is literal and a later space-hash starts a comment.
Compose can also interpolate from its host environment, which is unavailable
to this service. Use single quotes for literal dollar signs, or escape them in
double quotes.
"""
from __future__ import annotations

import errno
import os
import re
import stat
import tempfile

_UTF8_BOM = "\ufeff"

# Use the same statement boundaries when reading and replacing entries.
# An assignment-looking line inside a quoted value is part of that value.
_ENTRY = re.compile(
    r"""
    ^[^\S\n]*(?:export[^\S\n]+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)[^\S\n]*[=:][^\S\n]*
    (?:
        "(?P<double>(?:[^"\\]|\\[\s\S])*)"[^\S\n]*(?:\#[^\n]*)?$
      | '(?P<single>(?:[^'\\]|\\[\s\S])*)'[^\S\n]*(?:\#[^\n]*)?$
      | (?P<plain>[^\n]*)
    )
    | ^(?P<other>[^\n]+)
    """,
    re.MULTILINE | re.VERBOSE,
)
_DOUBLE_ESCAPES = {
    r"\a": "\a", r"\b": "\b", r"\f": "\f", r"\n": "\n", r"\r": "\r",
    r"\t": "\t", r"\v": "\v", r'\"': '"', r"\\": "\\", r"\$": "$$",
}
_DOUBLE_ESCAPE = re.compile(r'\\[abfnrtv"\\$]')
_AUTH_FLAG = "OPENBB_API_AUTH"
_AUTH_FIELDS = {_AUTH_FLAG, "OPENBB_API_USERNAME", "OPENBB_API_PASSWORD"}
_HOST_REFERENCE = re.compile(r"(?<!\$)(?:\$\$)*\$(?=[A-Za-z_{])")
_EXPORT = re.compile(r"^export\s+")


def _parse(text: str) -> tuple[dict[str, str], list[str]]:
    """Return literal values and line numbers for malformed entries."""
    out: dict[str, str] = {}
    warnings: list[str] = []
    text = "\n".join(text.removeprefix(_UTF8_BOM).splitlines())
    lineno, previous_start = 1, 0
    for entry in _ENTRY.finditer(text):
        lineno += text.count("\n", previous_start, entry.start())
        previous_start = entry.start()
        if entry["other"] is not None:
            line = entry["other"].strip()
            if line and not line.startswith("#"):
                warnings.append(f"line {lineno}")
                inherited = _EXPORT.sub("", line)
                if inherited in _AUTH_FIELDS:
                    # There is no way to verify a value inherited from the Compose host.
                    out[inherited] = inherited if inherited == _AUTH_FLAG else ""
            continue

        key = entry["key"]
        if entry["single"] is not None:
            out[key] = entry["single"].replace(r"\'", "'")
            continue

        malformed = False
        if entry["double"] is not None:
            value = _DOUBLE_ESCAPE.sub(lambda m: _DOUBLE_ESCAPES[m[0]], entry["double"])
        else:
            value = entry["plain"].strip()
            malformed = value.startswith(("'", '"'))
            if not malformed and not value.startswith("#"):
                value = value.split(" #", 1)[0].rstrip()
        if key in _AUTH_FIELDS and (malformed or _HOST_REFERENCE.search(value)):
            # Keep the flag unknown and make the username/password unusable.
            value = key if key == _AUTH_FLAG else ""
            malformed = True
        if entry["double"] is not None or key in _AUTH_FIELDS:
            value = value.replace("$$", "$")
        if malformed:
            warnings.append(f"line {lineno}")
        out[key] = value
    return out, warnings


def parse_text(text: str) -> dict[str, str]:
    return _parse(text)[0]


def load(path: str) -> dict[str, str] | None:
    return load_with_warnings(path)[0]


def load_with_warnings(path: str) -> tuple[dict[str, str] | None, list[str]]:
    """Like `load`, but also reports malformed lines instead of silently
    skipping them (see _parse)."""
    try:
        with open(path, encoding="utf-8") as f:
            return _parse(f.read())
    except OSError:
        return None, []


def set_value(path: str, env_var: str, value: str) -> None:
    """Update one variable in credentials.env, preserving comments, blank
    lines, ordering and every other entry.

    Rewritten atomically (temp file in the same directory + os.replace) so a
    crash mid-write cannot truncate the file the API loads its credentials
    from. A partial credentials.env is worse than a stale one.

    Dollar-containing values are quoted and escaped so Compose loads them
    literally. Other values are written unquoted.
    """
    # Reject every separator recognized by splitlines() so a value cannot
    # inject a second assignment.
    if value and value.splitlines() != [value]:
        raise ValueError(f"value for {env_var!r} must not contain a line break")

    try:
        with open(path, encoding="utf-8") as f:
            text = "".join(f"{line}\n" for line in f.read().splitlines())
            original_mode: int | None = stat.S_IMODE(os.fstat(f.fileno()).st_mode)
    except OSError:
        text = ""
        original_mode = None

    encoded = value
    if "$" in value:
        escaped = value.replace("\\", "\\\\").replace('"', r'\"').replace("$", "$$")
        encoded = f'"{escaped}"'
    assignment = f"{env_var}={encoded}"
    replaced = False

    def update(entry: re.Match[str]) -> str:
        nonlocal replaced
        if entry["key"] == env_var:
            replaced = True
            return assignment
        return entry[0]

    bom = _UTF8_BOM if text.startswith(_UTF8_BOM) else ""
    out = bom + _ENTRY.sub(update, text.removeprefix(_UTF8_BOM))
    if not replaced:
        out += assignment + "\n"

    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".credentials.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(out)
        # mkstemp creates the temp file at 0600, and os.replace is a rename,
        # so without this the credentials file would silently narrow to
        # 0600 on every write regardless of what mode it was created with.
        # If the API process reads the file as a different user or group
        # than this writer, that breaks credential loading with no error
        # anywhere -- the same failure the atomic write exists to prevent,
        # by a different route. No original file (first write) leaves
        # mkstemp's restrictive default in place, which is the right call
        # for a brand-new credentials file.
        if original_mode is not None:
            os.chmod(tmp, original_mode)
        try:
            os.replace(tmp, path)
        except OSError as e:
            # docker-compose mounts credentials.env as a single file, and a
            # rename onto a mount point fails (EBUSY; EXDEV across devices).
            # Write that inode in place instead: a new inode would never
            # reach the host's file anyway.
            if e.errno not in (errno.EBUSY, errno.EXDEV):
                raise
            with open(path, "r+", encoding="utf-8") as f:
                f.write(out)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            os.unlink(tmp)
    except BaseException:
        # Never leave a temp file holding a credential behind.
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
