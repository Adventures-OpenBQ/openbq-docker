# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

"""Entry point: one process, two uvicorn servers. admin = unix socket
(bind-mounted from a 0700 host dir owned by the host admin; reachable only via
an SSH session as that user), 8447 = network (localhost on the host, and the
tailnet-only Tailscale Service svc:openbq-keys)."""
from __future__ import annotations

import asyncio
import os

import uvicorn

from app.server import create_app

NETWORK_PORT = 8447


def build_servers(
    cred_file: str, auth_file: str, admin_socket: str
) -> list[uvicorn.Server]:
    admin_cfg = uvicorn.Config(
        create_app(role="admin", cred_file=cred_file, auth_file=auth_file),
        uds=admin_socket,
        log_level="info",
    )
    network_cfg = uvicorn.Config(
        create_app(role="network", cred_file=cred_file, auth_file=auth_file),
        # key-maint is the only service whose bind lives in Python rather than
        # in compose, so it needs this knob to join the openbb-internal bridge:
        # compose sets it to 0.0.0.0. The DEFAULT stays loopback deliberately --
        # a compose file or image that forgets it fails closed (unreachable)
        # rather than binding whatever interfaces happen to exist.
        #
        # Only this server is affected. The admin server above binds a unix
        # socket, so it never reaches the bridge at all: its 0700 host directory
        # is what raises a caller to tier 3, on top of the same Basic auth that
        # every tier requires (create_app applies the guard for both roles).
        host=os.environ.get("KEYMAINT_NETWORK_HOST", "127.0.0.1"),
        port=NETWORK_PORT,
        log_level="info",
    )
    return [uvicorn.Server(admin_cfg), uvicorn.Server(network_cfg)]


def prepare_admin_dir(admin_socket: str) -> None:
    """The admin directory's 0700 is the whole tier-3 boundary (the socket
    itself is 0666), so key-maint sets it rather than trusting the operator's
    chmod: a directory Docker auto-created for the bind mount is 0755. Through
    the bind mount this sets the host directory's mode too; its owner stays
    whoever created it, so a root-created one fails closed for other users."""
    d = os.path.dirname(admin_socket)
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)


async def _chmod_admin_socket(path: str) -> None:
    """uvicorn creates the uds file during server startup, not before, so poll
    for it rather than chmod-ing a path that doesn't exist yet. Directory
    permissions (0700, admin-owned on the host) are the real access control;
    this just lets the admin user's own connections through the mode bits."""
    for _ in range(50):  # ~5s at 0.1s intervals
        if os.path.exists(path):
            os.chmod(path, 0o666)
            return
        await asyncio.sleep(0.1)


async def _serve_all() -> None:
    cred = os.environ.get("KEYMAINT_CRED_FILE", "/config/credentials.env")
    auth = os.environ.get("KEYMAINT_AUTH_FILE", "/config/credentials.env")
    admin_socket = os.environ.get(
        "KEYMAINT_ADMIN_SOCKET", "/config/admin/key-maint-admin.sock"
    )

    prepare_admin_dir(admin_socket)
    if os.path.exists(admin_socket):
        os.unlink(admin_socket)

    servers = build_servers(cred, auth, admin_socket)
    await asyncio.gather(
        _chmod_admin_socket(admin_socket),
        *(s.serve() for s in servers),
    )


if __name__ == "__main__":
    asyncio.run(_serve_all())
