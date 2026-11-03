# SPDX-License-Identifier: Apache-2.0
"""Read-only NAS deployment inventory. Never collect environment or log payloads."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

LABELS = (
    "com.docker.compose.project",
    "com.docker.compose.service",
    "com.docker.compose.project.config_files",
    "com.docker.compose.project.working_dir",
)
# Restrict collection at the Docker boundary as well as before writing a receipt.
INSPECT = """{"Id":{{json .Id}},"Name":{{json .Name}},"Image":{{json .Image}},"Config":{"Image":{{json .Config.Image}},"Labels":{"com.docker.compose.project":{{json (index .Config.Labels "com.docker.compose.project")}},"com.docker.compose.service":{{json (index .Config.Labels "com.docker.compose.service")}},"com.docker.compose.project.config_files":{{json (index .Config.Labels "com.docker.compose.project.config_files")}},"com.docker.compose.project.working_dir":{{json (index .Config.Labels "com.docker.compose.project.working_dir")}}}},"State":{"Status":{{json .State.Status}},"Health":{"Status":{{with (index .State "Health")}}{{json (index . "Status")}}{{else}}null{{end}}}},"HostConfig":{"Memory":{{json .HostConfig.Memory}},"NanoCpus":{{json .HostConfig.NanoCpus}}},"Mounts":{{json .Mounts}},"NetworkSettings":{"Networks":{{json .NetworkSettings.Networks}}}}"""
HOST_REPORT = (
    "uname -m; cat /proc/meminfo; df -Pk /share/Container /share/ZFS29_DATA/minio"
)


def validate_target(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value
    ):
        raise ValueError("explicit SSH host alias or Docker context name required")
    return value


def container_record(value):
    config = value.get("Config") or {}
    labels = config.get("Labels") or {}
    host = value.get("HostConfig") or {}
    state = value.get("State") or {}
    return {
        "container_id": value["Id"],
        "name": value["Name"].lstrip("/"),
        "image_id": value["Image"],
        "configured_image": config.get("Image"),
        "state": state.get("Status"),
        "health": (state.get("Health") or {}).get("Status"),
        "memory_limit_bytes": host.get("Memory"),
        "nano_cpus": host.get("NanoCpus"),
        "compose": {
            key.removeprefix("com.docker.compose."): labels[key]
            for key in LABELS
            if labels.get(key)
        },
        "mounts": [
            {
                key.lower(): row[key]
                for key in ("Type", "Name", "Source", "Destination", "RW")
                if key in row
            }
            for row in value.get("Mounts", [])
        ],
        "networks": sorted((value.get("NetworkSettings") or {}).get("Networks") or {}),
    }


def _read(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if result.returncode:
        # SSH/Docker stderr can contain configuration; never include it in errors.
        raise RuntimeError("read-only inventory command failed")
    if len(result.stdout.encode()) > 8 * 1024 * 1024:
        raise ValueError("inventory response exceeds bounded receipt size")
    return result.stdout


def inventory(target, docker_context):
    validate_target(target)
    validate_target(docker_context)
    observed = datetime.now(timezone.utc).isoformat()
    host = _read(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, HOST_REPORT]
    )
    docker = ["docker", "--context", docker_context]
    ids = _read(docker + ["ps", "-aq", "--no-trunc"]).split()
    if len(ids) > 128 or any(not re.fullmatch("[0-9a-f]{64}", item) for item in ids):
        raise ValueError("inventory requires at most 128 identified containers")
    rows = _read(docker + ["inspect", "--format", INSPECT, *ids]) if ids else ""
    containers = [container_record(json.loads(line)) for line in rows.splitlines()]
    return {
        "schema_version": 1,
        "observed_at": observed,
        "ssh_target": target,
        "docker_context": docker_context,
        "host_report": host,
        "containers": sorted(containers, key=lambda item: item["name"]),
        "limitations": [
            "Read-only inventory; no service, schema or store mutation.",
            "Memory is an observation, not a measured admission budget.",
            "Object contents, Delta versions and backup integrity are not verified.",
        ],
    }


def write_receipt(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-target", default="nas")
    parser.add_argument("--docker-context", default="nas")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("use a new observation path")
    value = inventory(args.ssh_target, args.docker_context)
    write_receipt(args.output, value)
    print(
        json.dumps(
            {
                "containers": len(value["containers"]),
                "observed_at": value["observed_at"],
                "receipt": str(args.output),
                "mode": "read-only",
            }
        )
    )


if __name__ == "__main__":
    main()
