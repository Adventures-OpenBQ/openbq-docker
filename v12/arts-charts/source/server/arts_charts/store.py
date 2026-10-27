# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Business Source License 1.1.
# SPDX-License-Identifier: BUSL-1.1
"""Chart documents and every revision of them, in SQLite or Postgres.

One schema in portable SQL. The URL picks the database: `sqlite:///<path>`
(stdlib sqlite3; four slashes for an absolute path) or `postgresql://...`
(psycopg 3, the `postgres` extra). Statements are written with `?` and
rewritten to `%s` for psycopg -- none of them contains a literal `?` or `%`.

A save is one compare-and-set: `UPDATE ... WHERE revision = <base>`. Two
saves on the same base race on that row; exactly one matches, the other
sees the winner's revision and raises Conflict carrying it.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

DEFAULT_URL = "sqlite:///arts-charts.db"


def is_chart_id(value: str) -> bool:
    """True for what `create` mints (a canonical lowercase uuid4 string) -- the only
    text a chart id may be where it becomes part of a URL path."""
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False

#: Applied in order at service start; position + 1 is the schema version.
#: Append only -- a shipped migration is never edited.
MIGRATIONS: list[list[str]] = [
    [
        """CREATE TABLE charts (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            revision INTEGER NOT NULL,
            body TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            deleted BOOLEAN NOT NULL DEFAULT FALSE
        )""",
        """CREATE TABLE chart_revisions (
            chart_id TEXT NOT NULL REFERENCES charts (id),
            revision INTEGER NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (chart_id, revision)
        )""",
    ],
    [  # step 3a: watches, their firings, the inbox and the push queue
        """CREATE TABLE watches (
            id TEXT PRIMARY KEY,
            chart_id TEXT NOT NULL,
            condition TEXT NOT NULL,
            note TEXT NOT NULL,
            cooldown INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL,
            muted_until TEXT,
            state TEXT NOT NULL,
            error TEXT,
            failures INTEGER NOT NULL,
            last_bar TEXT,
            snapshot_requested_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE watch_events (
            watch_id TEXT NOT NULL,
            bar_time TEXT NOT NULL,
            observed TEXT NOT NULL,
            status TEXT NOT NULL,
            inbox_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (watch_id, bar_time)
        )""",
        """CREATE TABLE inbox (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            chart_ids TEXT NOT NULL,
            read_at TEXT
        )""",
        """CREATE TABLE inbox_snapshots (
            inbox_id TEXT NOT NULL,
            n INTEGER NOT NULL,
            chart_id TEXT NOT NULL,
            png BYTEA NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (inbox_id, n)
        )""",
        """CREATE TABLE pushes (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            next_at TEXT NOT NULL
        )""",
    ],
    [  # step 4: schedules and their runs (one row per occurrence, so each runs once)
        """CREATE TABLE schedules (
            id TEXT PRIMARY KEY,
            chart_ids TEXT NOT NULL,
            rule TEXT NOT NULL,
            note TEXT NOT NULL,
            enabled BOOLEAN NOT NULL,
            armed_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE schedule_runs (
            schedule_id TEXT NOT NULL,
            occurrence TEXT NOT NULL,
            status TEXT NOT NULL,
            inbox_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (schedule_id, occurrence)
        )""",
    ],
]

#: A watch's columns, in the order _watch reads them.
_WATCH = ("id, chart_id, condition, note, cooldown, enabled, muted_until, state, error, failures,"
          " last_bar, snapshot_requested_at, created_at, updated_at")
#: What set_watch may change (column names never come from a request).
_WATCH_SET = {"condition", "note", "cooldown", "enabled", "muted_until", "state", "error",
              "failures", "last_bar", "snapshot_requested_at"}
_PUSH_SET = {"status", "attempts", "next_at"}
#: A schedule's columns, in the order _schedule reads them. `when` is stored as `rule`:
#: WHEN is an SQL keyword.
_SCHEDULE = "id, chart_ids, rule, note, enabled, armed_at, created_at, updated_at"
_SCHEDULE_SET = {"chart_ids", "when", "note", "enabled", "armed_at"}

_COLUMNS = "id, title, revision, body, updated_by, updated_at, deleted"


class NotFound(LookupError):
    """No document with this id, it is deleted, or it has no such revision."""


class Conflict(Exception):
    """A save from a revision that is no longer current; `current` is the document now."""

    def __init__(self, current: dict):
        super().__init__(f"revision {current['revision']} is current")
        self.current = current


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _watch(row) -> dict:
    keys = [k.strip() for k in _WATCH.split(",")]
    watch = dict(zip(keys, row))
    watch["enabled"] = bool(watch["enabled"])
    return watch


def _schedule(row) -> dict:
    schedule = dict(zip([k.strip() for k in _SCHEDULE.split(",")], row))
    schedule["when"] = schedule.pop("rule")
    schedule["chart_ids"], schedule["enabled"] = json.loads(schedule["chart_ids"]), bool(
        schedule["enabled"])
    return schedule


def _where(changes: dict, where: dict | None) -> tuple[str, str, list]:
    """SET and WHERE clauses for a compare-and-set; a None in `where` means IS NULL."""
    sets = ", ".join(f"{k} = ?" for k in changes)
    tests, params = [], list(changes.values())
    for k, v in (where or {}).items():
        tests.append(f"{k} IS NULL" if v is None else f"{k} = ?")
        if v is not None:
            params.append(v)
    return sets, "".join(f" AND {t}" for t in tests), params


def _doc(row) -> dict:
    return {"id": row[0], "title": row[1], "revision": row[2], "body": json.loads(row[3]),
            "updated_by": row[4], "updated_at": row[5], "deleted": bool(row[6])}


class Store:
    def __init__(self, url: str = DEFAULT_URL):
        if url.startswith("sqlite:///"):
            self._target, self._pg = url[len("sqlite:///"):], False
        elif url.startswith(("postgresql://", "postgres://")):
            self._target, self._pg = url, True
        else:
            # The URL itself is not echoed: a Postgres URL carries a password.
            raise ValueError("ARTS_CHARTS_DB must be sqlite:///<path> or postgresql://...")

    @contextmanager
    def _tx(self) -> Iterator:
        """One transaction: yields `run(sql, params)`; commits on exit, rolls back on error.

        ponytail: a connection per transaction, no pool -- one user, a few
        saves a minute. Pool when a profile shows connect time.
        """
        if self._pg:
            import psycopg  # the postgres extra; SQLite needs nothing installed
            conn = psycopg.connect(self._target)
        else:
            conn = sqlite3.connect(self._target, timeout=30)
            conn.autocommit = False  # PEP 249: DDL runs inside the transaction too
        try:
            cur = conn.cursor()

            def run(sql: str, params=()):
                cur.execute(sql.replace("?", "%s") if self._pg else sql, params)
                return cur
            yield run
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def migrate(self) -> None:
        """Bring the schema up to date. Safe to run at every start.

        ponytail: two processes migrating one Postgres at once can race on
        the first CREATE; only `arts-charts` migrates today. Add a
        pg_advisory_xact_lock when the worker starts migrating too.
        """
        with self._tx() as run:
            run("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            done = run("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
            for version, statements in enumerate(MIGRATIONS[done:], start=done + 1):
                for sql in statements:
                    run(sql)
                run("INSERT INTO schema_version (version) VALUES (?)", (version,))

    def _current(self, run, chart_id: str) -> dict:
        row = run(f"SELECT {_COLUMNS} FROM charts WHERE id = ?", (chart_id,)).fetchone()
        if row is None or row[6]:
            raise NotFound(chart_id)
        return _doc(row)

    @staticmethod
    def _record(run, doc: dict) -> None:
        run("INSERT INTO chart_revisions (chart_id, revision, title, body, updated_by, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (doc["id"], doc["revision"], doc["title"], json.dumps(doc["body"]),
             doc["updated_by"], doc["updated_at"]))

    def create(self, title: str, body: dict, by: str) -> dict:
        doc = {"id": str(uuid.uuid4()), "title": title, "revision": 1, "body": body,
               "updated_by": by, "updated_at": _now(), "deleted": False}
        with self._tx() as run:
            run(f"INSERT INTO charts ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc["id"], title, 1, json.dumps(body), by, doc["updated_at"], False))
            self._record(run, doc)
        return doc

    def get(self, chart_id: str) -> dict:
        with self._tx() as run:
            return self._current(run, chart_id)

    def list(self) -> list[dict]:
        """Every live document, newest change first, without its body.

        ponytail: symbol and interval are read out of each body; promote them
        to columns if the library grows past a few hundred charts.
        """
        with self._tx() as run:
            rows = run(f"SELECT {_COLUMNS} FROM charts WHERE deleted = ? ORDER BY updated_at DESC",
                       (False,)).fetchall()
        out = []
        for row in rows:
            doc = _doc(row)
            body = doc.pop("body")
            out.append({**doc, "symbol": body["symbol"], "interval": body["interval"]})
        return out

    def save(self, chart_id: str, title: str, body: dict, by: str,
             base_revision: int | None, deleted: bool = False) -> dict:
        """Write the next revision. `base_revision` None writes unconditionally
        (a restore); otherwise a stale base raises Conflict with the current
        document. A missing or deleted document raises NotFound."""
        at = _now()
        sql = ("UPDATE charts SET title = ?, body = ?, updated_by = ?, updated_at = ?,"
               " deleted = ?, revision = revision + 1 WHERE id = ? AND deleted = ?")
        params: list = [title, json.dumps(body), by, at, deleted, chart_id, False]
        if base_revision is not None:
            sql += " AND revision = ?"
            params.append(base_revision)
        with self._tx() as run:
            if run(sql, params).rowcount != 1:
                raise Conflict(self._current(run, chart_id))  # NotFound when missing
            revision = run("SELECT revision FROM charts WHERE id = ?", (chart_id,)).fetchone()[0]
            doc = {"id": chart_id, "title": title, "revision": revision, "body": body,
                   "updated_by": by, "updated_at": at, "deleted": deleted}
            self._record(run, doc)
        return doc

    def history(self, chart_id: str) -> list[dict]:
        """Every revision of a live document, newest first, without bodies."""
        with self._tx() as run:
            self._current(run, chart_id)
            rows = run("SELECT revision, title, updated_by, updated_at FROM chart_revisions"
                       " WHERE chart_id = ? ORDER BY revision DESC", (chart_id,)).fetchall()
        return [{"revision": r[0], "title": r[1], "updated_by": r[2], "updated_at": r[3]}
                for r in rows]

    def revision(self, chart_id: str, revision: int) -> dict:
        """One past revision of a live document: {revision, title, body, updated_by, updated_at}."""
        with self._tx() as run:
            self._current(run, chart_id)
            row = run("SELECT revision, title, body, updated_by, updated_at FROM chart_revisions"
                      " WHERE chart_id = ? AND revision = ?", (chart_id, revision)).fetchone()
        if row is None:
            raise NotFound(f"{chart_id} revision {revision}")
        return {"revision": row[0], "title": row[1], "body": json.loads(row[2]),
                "updated_by": row[3], "updated_at": row[4]}

    # -- step 3a: watches, firings, inbox, pushes ------------------------------------------

    def schema_version(self) -> int:
        """How far this database is migrated; 0 before the first migrate. The worker
        waits for the API's migration instead of racing it."""
        try:
            with self._tx() as run:
                return run("SELECT MAX(version) FROM schema_version").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no schema_version table yet (either driver's error)
            return 0

    def create_watch(self, chart_id: str, condition: str, note: str, cooldown: int,
                     enabled: bool = True) -> dict:
        at = _now()
        watch = {"id": str(uuid.uuid4()), "chart_id": chart_id, "condition": condition,
                 "note": note, "cooldown": cooldown, "enabled": enabled, "muted_until": None,
                 "state": "ok", "error": None, "failures": 0, "last_bar": None,
                 "snapshot_requested_at": None, "created_at": at, "updated_at": at}
        with self._tx() as run:
            run(f"INSERT INTO watches ({_WATCH}) VALUES ({', '.join('?' * len(watch))})",
                tuple(watch.values()))
        return watch

    def get_watch(self, watch_id: str) -> dict:
        with self._tx() as run:
            row = run(f"SELECT {_WATCH} FROM watches WHERE id = ?", (watch_id,)).fetchone()
        if row is None:
            raise NotFound(watch_id)
        return _watch(row)

    def list_watches(self, chart_id: str | None = None) -> list[dict]:
        """Every watch (of one chart), oldest first."""
        sql, params = f"SELECT {_WATCH} FROM watches", ()
        if chart_id is not None:
            sql, params = sql + " WHERE chart_id = ?", (chart_id,)
        with self._tx() as run:
            return [_watch(r) for r in run(sql + " ORDER BY created_at, id", params).fetchall()]

    def set_watch(self, watch_id: str, changes: dict, where: dict | None = None) -> bool:
        """Change a watch, only if every `where` column still holds its value. True when
        this call changed it -- the claim two workers race on."""
        assert set(changes) <= _WATCH_SET and set(where or {}) <= _WATCH_SET | {"enabled"}
        sets, tests, params = _where({**changes, "updated_at": _now()}, where)
        with self._tx() as run:
            return run(f"UPDATE watches SET {sets} WHERE id = ?{tests}",
                       (*params[:len(changes) + 1], watch_id, *params[len(changes) + 1:])
                       ).rowcount == 1

    def delete_watch(self, watch_id: str) -> None:
        with self._tx() as run:
            if run("DELETE FROM watches WHERE id = ?", (watch_id,)).rowcount != 1:
                raise NotFound(watch_id)
            run("DELETE FROM watch_events WHERE watch_id = ?", (watch_id,))

    def insert_event(self, watch_id: str, bar_time: str, observed: dict, now: str) -> bool:
        """Record that `bar_time` fired the watch. False when it already had: one bar
        fires a watch once, however many workers saw it (spec §3 firing 1)."""
        with self._tx() as run:
            return run("INSERT INTO watch_events (watch_id, bar_time, observed, status, created_at)"
                       " VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                       (watch_id, bar_time, json.dumps(observed), "new", now)).rowcount == 1

    def set_event(self, watch_id: str, bar_time: str, status: str,
                  inbox_id: str | None = None) -> None:
        with self._tx() as run:
            run("UPDATE watch_events SET status = ?, inbox_id = ? WHERE watch_id = ? AND bar_time = ?",
                (status, inbox_id, watch_id, bar_time))

    def stale_events(self, before: str) -> list[dict]:
        """Firings still `new` since before `before`: claimed, but never filed (a crash, the
        API down). Oldest first."""
        with self._tx() as run:
            rows = run("SELECT watch_id, bar_time, observed, created_at FROM watch_events"
                       " WHERE status = ? AND created_at < ? ORDER BY created_at",
                       ("new", before)).fetchall()
        return [{"watch_id": r[0], "bar_time": r[1], "observed": json.loads(r[2]),
                 "created_at": r[3]} for r in rows]

    def renew_event(self, watch_id: str, bar_time: str, seen: str, now: str) -> bool:
        """Take a stale firing to re-file: restamps it from the `created_at` the caller read,
        so one worker wins and the firing is looked at again only after another wait."""
        with self._tx() as run:
            return run("UPDATE watch_events SET created_at = ? WHERE watch_id = ? AND bar_time = ?"
                       " AND status = ? AND created_at = ?",
                       (now, watch_id, bar_time, "new", seen)).rowcount == 1

    def last_delivered(self, watch_id: str) -> str | None:
        """The bar of the watch's latest delivered firing: where its cooldown runs from."""
        with self._tx() as run:
            return run("SELECT MAX(bar_time) FROM watch_events WHERE watch_id = ? AND status = ?",
                       (watch_id, "delivered")).fetchone()[0]

    def _inbox(self, run, row) -> dict:
        shots = run("SELECT n, chart_id FROM inbox_snapshots WHERE inbox_id = ? ORDER BY n",
                    (row[0],)).fetchall()
        return {"id": row[0], "kind": row[1], "created_at": row[2], "title": row[3],
                "body": row[4], "chart_ids": json.loads(row[5]), "read_at": row[6],
                "snapshots": [{"chart_id": c, "url": f"/inbox/{row[0]}/snapshots/{n}.png"}
                              for n, c in shots]}

    def add_inbox(self, kind: str, title: str, body: str, chart_ids: list[str],
                  pngs: list[tuple[str, bytes]]) -> dict:
        item_id, at = str(uuid.uuid4()), _now()
        with self._tx() as run:
            run("INSERT INTO inbox (id, kind, created_at, title, body, chart_ids, read_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item_id, kind, at, title, body, json.dumps(chart_ids), None))
            for n, (chart_id, png) in enumerate(pngs):
                run("INSERT INTO inbox_snapshots (inbox_id, n, chart_id, png, created_at)"
                    " VALUES (?, ?, ?, ?, ?)", (item_id, n, chart_id, png, at))
        return self.get_inbox(item_id)

    def get_inbox(self, item_id: str) -> dict:
        with self._tx() as run:
            row = run("SELECT id, kind, created_at, title, body, chart_ids, read_at FROM inbox"
                      " WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise NotFound(item_id)
            return self._inbox(run, row)

    def list_inbox(self, limit: int = 200, after: tuple[str, str] | None = None) -> list[dict]:
        """Up to `limit` items, newest first (created_at desc, then id), starting past the
        `(created_at, id)` of the last item of the previous page.

        ponytail: one snapshot query per item -- up to 200 small queries per listing.
        Join if the inbox page shows load.
        """
        where, args = ("", ()) if after is None else (
            " WHERE created_at < ? OR (created_at = ? AND id > ?)", (after[0], after[0], after[1]))
        with self._tx() as run:
            rows = run("SELECT id, kind, created_at, title, body, chart_ids, read_at FROM inbox"
                       f"{where} ORDER BY created_at DESC, id LIMIT ?", (*args, limit)).fetchall()
            return [self._inbox(run, r) for r in rows]

    def unread_inbox(self) -> int:
        """How many items in the whole table have not been read."""
        with self._tx() as run:
            return run("SELECT COUNT(*) FROM inbox WHERE read_at IS NULL").fetchone()[0]

    def read_inbox(self, item_id: str, at: str) -> dict:
        with self._tx() as run:
            if run("UPDATE inbox SET read_at = ? WHERE id = ? AND read_at IS NULL",
                   (at, item_id)).rowcount != 1 and run(
                    "SELECT 1 FROM inbox WHERE id = ?", (item_id,)).fetchone() is None:
                raise NotFound(item_id)
        return self.get_inbox(item_id)

    def delete_inbox(self, item_id: str) -> None:
        with self._tx() as run:
            if run("DELETE FROM inbox WHERE id = ?", (item_id,)).rowcount != 1:
                raise NotFound(item_id)
            run("DELETE FROM inbox_snapshots WHERE inbox_id = ?", (item_id,))

    def inbox_png(self, item_id: str, n: int) -> bytes:
        with self._tx() as run:
            row = run("SELECT png FROM inbox_snapshots WHERE inbox_id = ? AND n = ?",
                      (item_id, n)).fetchone()
        if row is None:
            raise NotFound(f"{item_id} snapshot {n}")
        return bytes(row[0])

    def purge_snapshots(self, before: str) -> int:
        """Drop snapshot PNGs made before `before` (spec §4: kept 30 days); items keep their text."""
        with self._tx() as run:
            return run("DELETE FROM inbox_snapshots WHERE created_at < ?", (before,)).rowcount

    def add_push(self, payload: dict, now: str, since: str, cap: int) -> str | None:
        """Queue a push unless `cap` pushes were queued since `since`; its id, or None.

        ponytail: count-then-insert, so two workers racing at the cap can pass it
        by one. A lock row if the cap must be exact.
        """
        with self._tx() as run:
            if run("SELECT COUNT(*) FROM pushes WHERE created_at > ?", (since,)).fetchone()[0] >= cap:
                return None
            push_id = str(uuid.uuid4())
            run("INSERT INTO pushes (id, created_at, payload, status, attempts, next_at)"
                " VALUES (?, ?, ?, ?, ?, ?)", (push_id, now, json.dumps(payload), "pending", 0, now))
        return push_id

    def due_pushes(self, now: str) -> list[dict]:
        with self._tx() as run:
            rows = run("SELECT id, created_at, payload, attempts FROM pushes"
                       " WHERE status = ? AND next_at <= ? ORDER BY created_at, id",
                       ("pending", now)).fetchall()
        return [{"id": r[0], "created_at": r[1], "payload": json.loads(r[2]), "attempts": r[3]}
                for r in rows]

    def set_push(self, push_id: str, changes: dict, where: dict | None = None) -> bool:
        assert set(changes) <= _PUSH_SET and set(where or {}) <= _PUSH_SET
        sets, tests, params = _where(changes, where)
        with self._tx() as run:
            return run(f"UPDATE pushes SET {sets} WHERE id = ?{tests}",
                       (*params[:len(changes)], push_id, *params[len(changes):])).rowcount == 1

    # -- step 4: schedules and their runs ------------------------------------------------------

    def create_schedule(self, chart_ids: list[str], when: str, note: str, enabled: bool,
                        armed_at: str) -> dict:
        """`armed_at`: occurrences before it never run (a new schedule does not report on
        the time it was made after)."""
        at, schedule_id = _now(), str(uuid.uuid4())
        with self._tx() as run:
            run(f"INSERT INTO schedules ({_SCHEDULE}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (schedule_id, json.dumps(chart_ids), when, note, enabled, armed_at, at, at))
        return self.get_schedule(schedule_id)

    def get_schedule(self, schedule_id: str) -> dict:
        with self._tx() as run:
            row = run(f"SELECT {_SCHEDULE} FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        if row is None:
            raise NotFound(schedule_id)
        return _schedule(row)

    def list_schedules(self) -> list[dict]:
        """Every schedule, oldest first."""
        with self._tx() as run:
            return [_schedule(r) for r in run(f"SELECT {_SCHEDULE} FROM schedules"
                                              " ORDER BY created_at, id").fetchall()]

    def set_schedule(self, schedule_id: str, changes: dict) -> bool:
        """Change a schedule; False when there is none."""
        assert set(changes) <= _SCHEDULE_SET
        columns = {("rule" if k == "when" else k): (json.dumps(v) if k == "chart_ids" else v)
                   for k, v in changes.items()}
        sets, _, params = _where({**columns, "updated_at": _now()}, None)
        with self._tx() as run:
            return run(f"UPDATE schedules SET {sets} WHERE id = ?",
                       (*params, schedule_id)).rowcount == 1

    def delete_schedule(self, schedule_id: str) -> None:
        with self._tx() as run:
            if run("DELETE FROM schedules WHERE id = ?", (schedule_id,)).rowcount != 1:
                raise NotFound(schedule_id)
            run("DELETE FROM schedule_runs WHERE schedule_id = ?", (schedule_id,))

    def claim_run(self, schedule_id: str, occurrence: str, now: str, stale_before: str) -> bool:
        """Take an occurrence to run: True for exactly one caller. A new occurrence is taken
        by its unique row; one still `new` since before `stale_before` (claimed, never
        filed: a crash, the API down) is taken again by restamping it. Anything else --
        running elsewhere, or finished -- is not taken. Two single-statement writes, no
        read first: a read-then-write transaction can deadlock two SQLite processes.

        ponytail: the worker calls this every pass, so a finished occurrence costs two
        no-op writes per schedule per pass. Remember finished keys in memory if that shows.
        """
        with self._tx() as run:
            if run("INSERT INTO schedule_runs (schedule_id, occurrence, status, inbox_id,"
                   " created_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                   (schedule_id, occurrence, "new", None, now)).rowcount == 1:
                return True
            return run("UPDATE schedule_runs SET created_at = ? WHERE schedule_id = ?"
                       " AND occurrence = ? AND status = ? AND created_at < ?",
                       (now, schedule_id, occurrence, "new", stale_before)).rowcount == 1

    def set_run(self, schedule_id: str, occurrence: str, status: str,
                inbox_id: str | None = None) -> None:
        with self._tx() as run:
            run("UPDATE schedule_runs SET status = ?, inbox_id = ?"
                " WHERE schedule_id = ? AND occurrence = ?",
                (status, inbox_id, schedule_id, occurrence))
