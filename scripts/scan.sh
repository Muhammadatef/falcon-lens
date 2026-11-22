#!/usr/bin/env bash
# make scan: supply-chain and container checks (docs/THREAT_MODEL.md, E: supply chain / escape).
#   gitleaks · pip-audit · pnpm audit · trivy fs · semgrep (p/python p/secrets p/typescript,
#   ERROR severity) · compose + image hardening (scripts/compose_hardening.py) · syft SBOM.
# A missing tool only warns locally (CI installs them); a tool that runs and finds a problem fails.
# Semgrep registry packs are fetched from semgrep.dev at run time: they are NOT available offline.
# If the fetch fails the step warns and is reported as skipped, never as a pass.
set -uo pipefail
cd "$(dirname "$0")/.."

SEMGREP_VERSION="${SEMGREP_VERSION:-1.186.0}"
rc=0
skipped=()
warn() { echo "WARN: $*" >&2; }
step() { echo "── $*"; }

step gitleaks
if command -v gitleaks >/dev/null; then gitleaks git --config .gitleaks.toml --no-banner . || rc=1
else warn "gitleaks not installed (brew install gitleaks); skipped"; skipped+=(gitleaks); fi

step pip-audit
req="$(mktemp -t falcon-req.XXXXXX)"
if uv export --frozen --no-dev --all-packages --no-emit-workspace --no-hashes -o "$req" >/dev/null; then
  uvx pip-audit -r "$req" --no-deps --disable-pip || rc=1
else rc=1; fi
rm -f "$req"

step "pnpm audit"
if command -v pnpm >/dev/null && [ -f web/package.json ]; then (cd web && pnpm audit --prod) || rc=1
else warn "pnpm not installed; skipped pnpm audit"; skipped+=(pnpm-audit); fi

step "trivy fs"
if command -v trivy >/dev/null; then
  trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 \
    --skip-dirs web/node_modules --skip-dirs .venv . || rc=1
else warn "trivy not installed (brew install trivy); skipped"; skipped+=(trivy); fi

step "semgrep ${SEMGREP_VERSION} (p/python p/secrets p/typescript, ERROR)"
if command -v uvx >/dev/null; then
  out="$(mktemp -t falcon-semgrep.XXXXXX)"
  uvx --from "semgrep==${SEMGREP_VERSION}" semgrep scan --metrics=off --disable-version-check -q \
    --config p/python --config p/secrets --config p/typescript --severity ERROR \
    --exclude .venv --exclude node_modules --exclude .next --exclude data/private --exclude evals/results \
    --json --json-output="$out" . >/dev/null 2>"$out.err"
  src=$?
  if [ ! -s "$out" ]; then
    warn "semgrep could not run or fetch registry rules (offline?): $(tail -1 "$out.err" 2>/dev/null); skipped"
    skipped+=(semgrep)
  else
    n="$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(len(d["results"]))' "$out")"
    echo "semgrep: ${n} ERROR finding(s) (exit ${src})"
    if [ "${n}" != "0" ]; then
      python3 -c 'import json,sys
for r in json.load(open(sys.argv[1]))["results"]:
    print(f"  {r["path"]}:{r["start"]["line"]} {r["check_id"]}")' "$out"
      rc=1
    fi
  fi
  rm -f "$out" "$out.err"
else warn "uv not installed; semgrep skipped"; skipped+=(semgrep); fi

step "compose + image hardening"
if command -v docker >/dev/null; then
  if [ -f .env ]; then python3 scripts/compose_hardening.py || rc=1
  else
    # compose config needs an env file; use the example values (no secrets) for the static check
    tmp_env="$(mktemp -t falcon-env.XXXXXX)"; cp .env.example "$tmp_env"
    COMPOSE_ENV_FILES="$tmp_env" python3 scripts/compose_hardening.py || rc=1
    rm -f "$tmp_env"
  fi
else warn "docker not installed; hardening checks skipped"; skipped+=(hardening); fi

step "syft SBOM"
if command -v syft >/dev/null; then mkdir -p evals/results && syft dir:. -q -o cyclonedx-json=evals/results/sbom.cdx.json || rc=1
else warn "syft not installed (brew install syft); SBOM skipped"; skipped+=(syft); fi

if [ ${#skipped[@]} -gt 0 ]; then echo "scan: skipped (NOT passed): ${skipped[*]}"; fi
if [ $rc -ne 0 ]; then echo "scan: FAILED" >&2; else echo "scan: ok for every step that ran"; fi
exit $rc
