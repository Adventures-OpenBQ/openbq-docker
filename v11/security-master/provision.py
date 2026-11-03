# SPDX-License-Identifier: Apache-2.0
"""Prepare private standalone Security Master staging; never seed demonstration data."""

import argparse
import json
from pathlib import Path
import re
import secrets
from datetime import datetime


def _admission_root(admission, release):
    if (
        not isinstance(admission, dict)
        or admission.get("status") != "admitted_unserved"
        or admission.get("image_id") != release["image_id"]
        or admission.get("source_commit") != release["source_commit"]
        or not isinstance(admission.get("destination"), str)
        or not re.fullmatch(r"/data/admissions/[0-9a-f]{64}", admission["destination"])
    ):
        raise ValueError("completed admission must match the image and owned root")
    evidence = admission.get("receipt")
    if (
        not isinstance(evidence, dict)
        or evidence.get("status") != "complete"
        or evidence.get("schema_version") != 1
    ):
        raise ValueError("complete native admission receipt required")
    for key in ("package_fingerprint", "source_manifest_sha256"):
        if not isinstance(evidence.get(key), str) or not re.fullmatch(
            "[0-9a-f]{64}", evidence[key]
        ):
            raise ValueError("admission identity required")
    clocks = []
    for key in ("prepared_at", "completed_at"):
        value = evidence.get(key)
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("UTC admission clocks required")
        clocks.append(datetime.fromisoformat(value))
    if (
        clocks[0] > clocks[1]
        or evidence.get("visibility_floor") != evidence["completed_at"]
    ):
        raise ValueError("admission visibility clock differs")
    relations = evidence.get("relations")
    if not isinstance(relations, dict) or not relations:
        raise ValueError("reference verification required")
    for value in relations.values():
        if (
            not isinstance(value, dict)
            or any(
                type(value.get(key)) is not int or value[key] < 0
                for key in ("version", "row_count")
            )
            or not isinstance(value.get("content_hash"), str)
            or not re.fullmatch("[0-9a-f]{64}", value["content_hash"])
        ):
            raise ValueError("verified relation identity required")
    return admission["destination"]


def prepare_bundle(output, receipt, *, port=18089, admission=None):
    image, source = receipt.get("image_id"), receipt.get("source_commit")
    if (
        receipt.get("platform") != "linux/amd64"
        or not isinstance(image, str)
        or not re.fullmatch("sha256:[0-9a-f]{64}", image)
        or not isinstance(source, str)
        or not re.fullmatch("[0-9a-f]{40}", source)
    ):
        raise ValueError("immutable amd64 image and full source commit required")
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("unprivileged loopback port required")
    store_root = (
        _admission_root(admission, receipt)
        if admission is not None
        else "/data/security_master"
    )
    out = Path(output)
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    environment = {
        "SECURITY_MASTER_ROOT": store_root,
        "SECURITY_MASTER_ACQUISITION": "disabled",
        "SECURITY_MASTER_SQL": "review",
        "SECURITY_MASTER_PREFLIGHT_SECRET": secrets.token_hex(32),
        "SECURITY_MASTER_MEMORY_LIMIT": "512MB",
        "SECURITY_MASTER_THREADS": "1",
        "OPENBB_API_AUTH": "true",
        "OPENBB_API_USERNAME": "v11-staging",
        "OPENBB_API_PASSWORD": secrets.token_hex(32),
    }
    compose = {
        "name": "openbq-v11-security-master",
        "services": {
            "security-master": {
                "image": image,
                "platform": "linux/amd64",
                "pull_policy": "never",
                "env_file": ["service.env"],
                "user": "65532:65532",
                "read_only": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "mem_limit": 2 * 1024**3,
                "cpus": 1,
                "pids_limit": 256,
                "volumes": ["data:/data"],
                "ports": [f"127.0.0.1:{port}:6905"],
                "tmpfs": [
                    "/tmp:rw,size=268435456,mode=1777",
                    "/run/security-master:rw,size=134217728,uid=65532,gid=65532,mode=0700",
                ],
                "restart": "unless-stopped",
            }
        },
        "volumes": {"data": {}},
        "networks": {"default": {"internal": True}},
    }
    files = {
        "compose.staging.yaml": json.dumps(compose, indent=2) + "\n",
        "service.env": "".join(k + "=" + v + "\n" for k, v in environment.items()),
        "release.json": json.dumps(
            dict(
                receipt,
                status="prepared_admitted_store_not_started"
                if admission is not None
                else "prepared_empty_store_not_started",
                **({"admission": admission} if admission is not None else {}),
                provider_acquisition_enabled=False,
            ),
            indent=2,
        )
        + "\n",
    }
    for name, content in files.items():
        with (out / name).open("x") as stream:
            (out / name).chmod(0o600)
            stream.write(content)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--admission-receipt", type=Path)
    args = parser.parse_args()
    prepare_bundle(
        args.output,
        json.loads(args.release_receipt.read_text()),
        admission=json.loads(args.admission_receipt.read_text())
        if args.admission_receipt
        else None,
    )
    print(json.dumps({"status": "prepared_not_started"}))


if __name__ == "__main__":
    main()
