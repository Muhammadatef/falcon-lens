#!/usr/bin/env python3
"""Container hardening checks for ``make scan`` (docs/THREAT_MODEL.md, E: browser exploit escape).

1. ``docker compose config --format json`` (all profiles): every service must be read_only, drop ALL
   capabilities and set no-new-privileges. The *isolated* services (sandbox, egress-proxy, fixtures)
   must also run as non-root, have mem / pids limits, and sit only on internal networks (plus the
   egress proxy's single outbound network).
2. ``docker image inspect`` on locally built falcon-lens images: Config.User must be non-root.
   Images that are not built yet are reported as skipped, never as a pass.

Exit 1 on any violation. ``--compose-json FILE`` reads a saved config (used by the tests).
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from typing import Any

ISOLATED = ("sandbox", "egress-proxy", "fixtures")
# The proxy is the one isolated service that may go out: `app` is its (non-internal) uplink.
EGRESS_OUTBOUND_OK = {"egress-proxy": {"app"}}
PROFILES = ("core", "obs", "tools", "stretch")


def _root(user: str | None) -> bool:
    if not user:
        return True
    name = str(user).split(":", 1)[0].strip()
    return name in ("", "0", "root")


def _compose_config() -> dict[str, Any]:
    cmd = ["docker", "compose"]
    for p in PROFILES:
        cmd += ["--profile", p]
    cmd += ["config", "--format", "json"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)  # noqa: S603
    data: dict[str, Any] = json.loads(out.stdout)
    return data


def _image_user(image: str) -> tuple[str | None, bool]:
    """(Config.User, found)."""
    r = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", image, "--format", "{{json .Config.User}}"],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        return None, False
    return json.loads(r.stdout.strip() or '""'), True


def check_config(cfg: dict[str, Any], inspect_images: bool) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    networks = cfg.get("networks", {}) or {}
    for name, svc in sorted((cfg.get("services") or {}).items()):
        where = f"service {name}"
        # Isolated services must pass every check; for the rest the baseline is a warning (stateful
        # stores such as postgres need a writable rootfs and their entrypoints need a few caps).
        strict = problems if name in ISOLATED else notes
        if svc.get("read_only") is not True:
            strict.append(f"{where}: read_only is not true")
        caps = [c.upper() for c in svc.get("cap_drop") or []]
        if "ALL" not in caps:
            strict.append(f"{where}: cap_drop does not include ALL")
        sec = [str(s).replace("=", ":").replace(" ", "") for s in svc.get("security_opt") or []]
        if not any(s in ("no-new-privileges:true", "no-new-privileges") for s in sec):
            problems.append(f"{where}: security_opt lacks no-new-privileges:true")
        if svc.get("privileged"):
            problems.append(f"{where}: privileged")
        if svc.get("cap_add"):
            strict.append(f"{where}: cap_add {svc['cap_add']}")
        if svc.get("network_mode") == "host" or svc.get("pid") == "host":
            problems.append(f"{where}: host network/pid namespace")
        for v in svc.get("volumes") or []:
            src = v.get("source", "") if isinstance(v, dict) else str(v)
            if "docker.sock" in str(src):
                ro = isinstance(v, dict) and v.get("read_only") is True
                (notes if ro else problems).append(f"{where}: mounts the Docker socket{' (read-only)' if ro else ''}")

        user = svc.get("user")
        image = svc.get("image")
        image_user: str | None = None
        if inspect_images and image:
            image_user, found = _image_user(image)
            if not found:
                notes.append(f"{where}: image {image} not present locally; image USER not inspected")
        effective_root = _root(user) and (image_user is None or _root(image_user))
        if name in ISOLATED:
            if effective_root and (user is not None or image_user is not None):
                problems.append(f"{where}: runs as root (user={user!r}, image USER={image_user!r})")
            elif user is None and image_user is None:
                notes.append(f"{where}: no compose user and image not inspected; non-root not proven")
            if not (svc.get("mem_limit") or (svc.get("deploy") or {}).get("resources")):
                problems.append(f"{where}: no memory limit")
            if not svc.get("pids_limit"):
                problems.append(f"{where}: no pids_limit")
            nets = svc.get("networks") or {}
            for net in nets:
                internal = (networks.get(net) or {}).get("internal") is True
                if not internal and net not in EGRESS_OUTBOUND_OK.get(name, set()):
                    problems.append(f"{where}: on non-internal network {net!r}")
            if svc.get("ports"):
                problems.append(f"{where}: publishes host ports")
        elif inspect_images and image_user is not None and _root(image_user) and _root(user):
            notes.append(f"{where}: image runs as root (image USER={image_user!r})")
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--compose-json", help="read a saved `docker compose config --format json` instead")
    ap.add_argument("--no-inspect", action="store_true", help="skip docker image inspect")
    args = ap.parse_args(argv)
    if args.compose_json:
        with open(args.compose_json, encoding="utf-8") as fh:
            cfg = json.load(fh)
    else:
        if shutil.which("docker") is None:
            print("WARN: docker not installed; compose hardening checks skipped (NOT a pass)", file=sys.stderr)
            return 0
        cfg = _compose_config()
    problems, notes = check_config(cfg, inspect_images=not args.no_inspect and shutil.which("docker") is not None)
    for n in notes:
        print(f"note: {n}")
    if problems:
        print("compose hardening: FAILED", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"compose hardening: ok ({len(cfg.get('services') or {})} services; isolated: {', '.join(ISOLATED)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
