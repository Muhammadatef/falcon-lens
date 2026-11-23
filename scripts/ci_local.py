#!/usr/bin/env python3
"""Local CI: run every job of .github/workflows/ci.yml on this machine (stdlib only).

Usage
    make ci-local                       # current checkout, all jobs
    make ci-local JOBS="lint contracts" # a subset
    make ci-local-pr PR=123             # merge result of origin/main + PR head, comment on the PR
    python3 scripts/ci_local.py --pr 123 [--no-comment] [--jobs a,b]

How it works
    1. A serial-per-checkout prepare step installs dependencies once (uv sync --frozen, pnpm install
       --frozen-lockfile for web/ and extension/) so parallel jobs never race on .venv or node_modules.
    2. Independent jobs then run in parallel (thread pool, one subprocess each). Every job writes its
       own log to work/ci-local/<sha>/<job>.log; a summary table is printed and saved as summary.md.
    3. Exit code is non-zero if any job fails. A missing tool is a FAILURE with an explicit message,
       never a silent skip.

Differences from GitHub (all visible in the logs, none weaken a check)
    - docker-build builds the native arch (arm64 on Apple silicon); CI builds linux/amd64. Set
      FL_CI_PLATFORM=linux/amd64 to match CI exactly (slow under emulation). Images are tagged in the
      throwaway namespace falcon-lens-ci/<service>:<sha> under compose project falcon-ci-local, so
      shared falcon-lens/* tags never move. Only `docker compose build` runs: no container, network
      or volume is created, and nothing is pruned (the running `falcon` stack is untouched).
    - Playwright installs chromium without --with-deps (a Linux-only flag).
    - trivy additionally skips local-only directories (extension/node_modules, work, web/.next).
    - Tool versions are the ones installed locally; CI pins gitleaks/trivy/uv versions.

Parity: scripts/tests/test_ci_local.py parses ci.yml and fails if any job lacks an entry in JOBS.
"""

# ruff: noqa: S603, S607  (a CI runner launches fixed git/docker/bash commands by design)
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CI_IMAGE_NS = "falcon-lens-ci"

# Job name -> (required tools, shell script). Names must equal the job names in ci.yml.
JOBS: dict[str, tuple[tuple[str, ...], str]] = {
    "lint": (
        ("uv", "pnpm"),
        "uv run ruff check . && uv run ruff format --check . && cd web && pnpm lint",
    ),
    "typecheck": (("uv", "pnpm"), "uv run mypy && cd web && pnpm typecheck"),
    "test": (
        ("uv", "pnpm"),
        "uv run pytest -q --cov=falcon_core --cov-report=term --cov-report=xml"
        " && uv run coverage report --skip-covered | tail -n 25"
        " && cd web && pnpm test",
    ),
    "web": (
        ("pnpm",),
        "cd web && pnpm test:unit && pnpm exec playwright install chromium && pnpm build && pnpm test:e2e",
    ),
    "extension": (
        ("pnpm",),
        "cd extension && pnpm lint && pnpm test && pnpm zip && pnpm audit"
        " && pnpm exec playwright install chromium && pnpm test:e2e",
    ),
    "contracts": (
        ("uv",),
        "uv run pytest -q packages/falcon_core/tests/contracts"
        " && uv run python scripts/check_openapi_drift.py"
        " && uv run python scripts/gen_openapi.py --check",
    ),
    "security": (
        ("uv", "uvx", "pnpm", "gitleaks", "trivy", "python3"),
        "gitleaks git --config .gitleaks.toml --no-banner ."
        " && uv export --frozen --no-dev --all-packages --no-emit-workspace --no-hashes"
        ' -o "$FL_CI_LOGDIR/requirements.audit.txt"'
        ' && uvx pip-audit -r "$FL_CI_LOGDIR/requirements.audit.txt" --no-deps --disable-pip'
        " && (cd web && pnpm audit --prod)"
        " && trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1"
        " --skip-dirs web/node_modules --skip-dirs extension/node_modules --skip-dirs .venv"
        " --skip-dirs work --skip-dirs web/.next ."
        " && python3 scripts/check_no_live_urls.py",
    ),
    "docker-build": (("docker", "python3"), f"python3 {Path(__file__).resolve()} --docker-build"),
    "eval-gate": (("uv", "make"), "make eval-gate"),
}

PREPARE: list[tuple[str, str]] = [
    ("uv sync", "uv sync --frozen"),
    ("web install", "cd web && pnpm install --frozen-lockfile"),
    ("extension install", "cd extension && pnpm install --frozen-lockfile"),
]


@dataclass
class Result:
    name: str
    ok: bool
    seconds: float
    note: str = ""


def sh(script: str, cwd: Path, log: Path, env: dict[str, str]) -> int:
    with log.open("ab") as fh:
        fh.write(f"$ {script}\n".encode())
        fh.flush()
        return subprocess.call(
            ["bash", "-o", "pipefail", "-c", script],
            cwd=cwd,
            env=env,
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )


def run_job(name: str, root: Path, logdir: Path, env: dict[str, str]) -> Result:
    tools, script = JOBS[name]
    log = logdir / f"{name}.log"
    log.write_bytes(b"")
    t0 = time.monotonic()
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        msg = f"MISSING TOOL(S): {', '.join(missing)} (install them; this job is not skipped)"
        log.write_text(msg + "\n")
        return Result(name, False, 0.0, msg)
    rc = sh(script, root, log, env)
    note = "" if rc == 0 else f"exit {rc}, see {log.name}"
    return Result(name, rc == 0, time.monotonic() - t0, note)


def docker_build(root: Path) -> int:
    """Build every compose image as falcon-lens-ci/<service>:<sha>; build only, nothing is run."""
    sha = os.environ.get("FL_CI_SHA", "local")
    env_file = root / ".env"
    if not env_file.exists():
        shutil.copy(root / ".env.example", env_file)
    profiles = ["--profile", "core", "--profile", "obs", "--profile", "tools"]
    cfg = subprocess.run(
        ["docker", "compose", "-p", "falcon-ci-local", *profiles, "config", "--format", "json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(cfg.stdout)["services"]
    override = {"services": {n: {"image": f"{CI_IMAGE_NS}/{n}:{sha}"} for n, s in services.items() if "build" in s}}
    ov = Path(os.environ["FL_CI_LOGDIR"]) / "compose.ci-override.json"
    ov.write_text(json.dumps(override))
    cmd = [
        "docker", "compose", "-p", "falcon-ci-local",
        "-f", "docker-compose.yml", "-f", str(ov), *profiles, "build",
    ]  # fmt: skip
    plat = os.environ.get("FL_CI_PLATFORM")
    print("platform:", plat or "native", "| images:", ", ".join(override["services"]), flush=True)
    env = {**os.environ, **({"DOCKER_DEFAULT_PLATFORM": plat} if plat else {})}
    return subprocess.call(cmd, cwd=root, env=env)


def git(*args: str, cwd: Path = REPO) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def run_all(root: Path, log_root: Path, names: list[str]) -> tuple[list[Result], Path, str]:
    sha = git("rev-parse", "--short=12", "HEAD", cwd=root)
    if git("status", "--porcelain", cwd=root):
        sha += "-dirty"
    logdir = log_root / sha
    shutil.rmtree(logdir, ignore_errors=True)
    logdir.mkdir(parents=True)
    env = {
        **os.environ,
        "CI": "1",
        "FL_CI_LOGDIR": str(logdir),
        "FL_CI_SHA": sha.replace("-dirty", "d"),
    }
    t0 = time.monotonic()
    results: list[Result] = []
    prep_failed = False
    with ThreadPoolExecutor(len(PREPARE)) as ex:
        futs = [(n, ex.submit(sh, s, root, logdir / f"prepare-{n.split()[0]}.log", env)) for n, s in PREPARE]
        for n, f in futs:
            rc = f.result()
            print(f"prepare {n}: {'ok' if rc == 0 else 'FAILED'}", flush=True)
            prep_failed |= rc != 0
    note = "" if not prep_failed else "see prepare-*.log"
    results.append(Result("prepare", not prep_failed, time.monotonic() - t0, note))
    if not prep_failed:
        # jobs must not re-sync the shared .venv concurrently
        job_env = {**env, "UV_NO_SYNC": "1"}
        with ThreadPoolExecutor(len(names)) as ex:
            for r in ex.map(lambda n: run_job(n, root, logdir, job_env), names):
                print(f"job {r.name}: {'PASS' if r.ok else 'FAIL'} {r.seconds:.0f}s {r.note}", flush=True)
                results.append(r)
    results.append(Result("TOTAL (wall)", all(r.ok for r in results), time.monotonic() - t0))
    return results, logdir, sha


def table(results: list[Result], sha: str, extra: str = "") -> str:
    head = [f"### ci-local `{sha}`", "", extra, "| job | result | seconds | note |", "|---|---|---|---|"]
    rows = [f"| {r.name} | {'PASS' if r.ok else 'FAIL'} | {r.seconds:.0f} | {r.note} |" for r in results]
    return "\n".join(head + rows) + "\n"


def run_pr(pr: int, log_root: Path, names: list[str], comment: bool) -> int:
    git("fetch", "-q", "origin", "main")
    git("fetch", "-q", "origin", f"pull/{pr}/head")
    head = git("rev-parse", "FETCH_HEAD")
    main_sha = git("rev-parse", "origin/main")
    tmp = Path(tempfile.mkdtemp(prefix=f"falcon-ci-pr{pr}-"))
    wt = tmp / "wt"
    git("worktree", "add", "--detach", str(wt), main_sha)
    try:
        m = subprocess.run(
            [
                "git",
                "-c",
                "user.name=ci-local",
                "-c",
                "user.email=ci-local@localhost",
                "merge",
                "--no-ff",
                "-m",
                f"ci-local merge of PR #{pr}",
                head,
            ],  # fmt: skip
            cwd=wt,
            capture_output=True,
            text=True,
        )
        if m.returncode:
            msg = f"PR #{pr} does not merge cleanly into origin/main {main_sha[:12]}:\n{m.stdout}{m.stderr}"
            print(msg, file=sys.stderr)
            if comment:
                body = "ci-local: MERGE CONFLICT\n\n```\n" + msg + "```"
                subprocess.call(["gh", "pr", "comment", str(pr), "--body", body], cwd=REPO)
            return 1
        tree = git("rev-parse", "HEAD^{tree}", cwd=wt)
        merge_sha = git("rev-parse", "HEAD", cwd=wt)
        results, logdir, sha = run_all(wt, tmp / "logs", names)
        dest = log_root / f"pr{pr}-{merge_sha[:12]}"
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(logdir, dest)
        extra = (
            f"PR #{pr}: merge commit `{merge_sha}`, merge tree `{tree}`, "
            f"base origin/main `{main_sha[:12]}`, PR head `{head[:12]}`\n"
        )
        md = table(results, sha, extra)
        (dest / "summary.md").write_text(md)
        print("\n" + md + f"\nlogs: {dest}")
        if comment:
            subprocess.call(["gh", "pr", "comment", str(pr), "--body-file", str(dest / "summary.md")], cwd=REPO)
        return 0 if results[-1].ok else 1
    finally:
        subprocess.call(["git", "worktree", "remove", "--force", str(wt)], cwd=REPO)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, help="test the merge result of origin/main + this PR")
    ap.add_argument("--no-comment", action="store_true", help="with --pr: do not post a PR comment")
    ap.add_argument("--jobs", default=os.environ.get("JOBS", ""), help="comma/space separated subset")
    ap.add_argument("--docker-build", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.docker_build:
        return docker_build(Path.cwd())
    names = a.jobs.replace(",", " ").split() or list(JOBS)
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        raise SystemExit(f"unknown job(s): {unknown}; known: {list(JOBS)}")
    log_root = REPO / "work" / "ci-local"
    if a.pr:
        return run_pr(a.pr, log_root, names, not a.no_comment)
    results, logdir, sha = run_all(REPO, log_root, names)
    md = table(results, sha)
    (logdir / "summary.md").write_text(md)
    print("\n" + md + f"\nlogs: {logdir}")
    return 0 if results[-1].ok else 1


if __name__ == "__main__":
    sys.exit(main())
