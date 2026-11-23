# ruff: noqa: E501  (copy and tables read better unwrapped)
"""Generate the "tools used" list from what the shipped code actually uses.

Truthfulness rule (CLAUDE.md): "Tools used" lists only what the shipped code uses. Nothing
here is typed by hand. The sources are:

    uv.lock              direct runtime dependencies of the workspace packages (services and
                         falcon_core), kept only when shipped source imports the module or a
                         Dockerfile or compose command names it. Versions are the locked ones.
    web/pnpm-lock.yaml   direct production dependencies of the web app, locked versions.
    docker-compose.yml   images of the services in the `core`, `obs` and `tools` profiles. For
                         an image this repo builds from `infra/`, the upstream image in its
                         Dockerfile is listed instead.
    a few file probes    (Python version, package managers, local model runtime, CI scanners,
                         development agents), each tied to a file that proves the use.

A package with no entry in the name tables is listed under its package name, so a new
dependency can never be dropped silently.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {"core", "obs", "tools"}

# distribution name -> (human name, import module or None when it is not imported)
PYTHON_NAMES: dict[str, tuple[str, str | None]] = {
    "fastapi": ("FastAPI", "fastapi"),
    "uvicorn": ("Uvicorn", "uvicorn"),
    "pydantic": ("Pydantic", "pydantic"),
    "pydantic-settings": ("pydantic-settings", "pydantic_settings"),
    "prometheus-client": ("Prometheus Python client", "prometheus_client"),
    "httpx": ("HTTPX", "httpx"),
    "httpcore": ("HTTPCore", "httpcore"),
    "tldextract": ("tldextract (Public Suffix List)", "tldextract"),
    "pyyaml": ("PyYAML", "yaml"),
    "redis": ("redis-py", "redis"),
    "python-ulid": ("python-ulid", "ulid"),
    "jsonschema": ("jsonschema", "jsonschema"),
    "langgraph": ("LangGraph", "langgraph"),
    "langgraph-checkpoint-postgres": ("LangGraph Postgres checkpointer", "langgraph.checkpoint.postgres"),
    "langchain-core": ("LangChain Core", "langchain_core"),
    "anthropic": ("Anthropic API (Claude models)", "anthropic"),
    "mcp": ("Model Context Protocol Python SDK", "mcp"),
    "fastmcp": ("FastMCP", "fastmcp"),
    "playwright": ("Playwright", "playwright"),
    "psycopg": ("Psycopg", "psycopg"),
    "asyncpg": ("asyncpg", "asyncpg"),
    "sqlalchemy": ("SQLAlchemy", "sqlalchemy"),
    "pgvector": ("pgvector Python client", "pgvector"),
    "sse-starlette": ("sse-starlette", "sse_starlette"),
    "argon2-cffi": ("argon2-cffi", "argon2"),
    "lightgbm": ("LightGBM", "lightgbm"),
    "xgboost": ("XGBoost", "xgboost"),
    "scikit-learn": ("scikit-learn", "sklearn"),
    "numpy": ("NumPy", "numpy"),
    "opentelemetry-sdk": ("OpenTelemetry SDK", "opentelemetry"),
    "opentelemetry-api": ("OpenTelemetry API", "opentelemetry"),
    "structlog": ("structlog", "structlog"),
    "zxing-cpp": ("zxing-cpp (QR decoding)", "zxingcpp"),
    "pyzbar": ("pyzbar (QR decoding)", "pyzbar"),
    "pillow": ("Pillow", "PIL"),
    "dspy": ("DSPy", "dspy"),
    "stix2": ("stix2", "stix2"),
    "whoisit": ("whoisit (RDAP)", "whoisit"),
    "python-multipart": ("python-multipart", "multipart"),
    "confusable-homoglyphs": ("confusable-homoglyphs", "confusable_homoglyphs"),
}
JS_NAMES = {"next": "Next.js", "react": "React", "react-dom": "React DOM"}
IMAGE_NAMES = {
    "caddy": "Caddy",
    "pgvector/pgvector": "pgvector (PostgreSQL)",
    "redis": "Redis",
    "prom/prometheus": "Prometheus",
    "prom/alertmanager": "Alertmanager",
    "grafana/loki": "Grafana Loki",
    "grafana/alloy": "Grafana Alloy",
    "grafana/grafana": "Grafana",
    "arizephoenix/phoenix": "Arize Phoenix",
    "otel/opentelemetry-collector-contrib": "OpenTelemetry Collector",
    "otel/opentelemetry-collector": "OpenTelemetry Collector",
    "nginxinc/nginx-unprivileged": "nginx (test fixtures)",
    "ollama/ollama": "Ollama",
}
BASE_IMAGES = re.compile(r"^(alpine|scratch|debian|ubuntu|busybox|python|node|ghcr\.io/astral-sh/uv)(:|$)")
DEV_NAMES = {"pytest": "pytest", "ruff": "Ruff", "mypy": "mypy"}
SOURCE_GLOBS = ("packages/*/src/**/*.py", "services/*/src/**/*.py", "services/sentinel/sentinel_core/**/*.py")
COMMAND_GLOBS = ("services/*/Dockerfile", "docker-compose.yml")


def _version(text: str) -> str:
    """Leading version of a lock entry: `16.4.6(@types/node@24)` -> `16.4.6`, `v3.16.0` -> `3.16.0`."""
    match = re.match(r"v?(\d+(?:\.\d+)*)", text.removeprefix("version-"))
    return match.group(1) if match else text


def _read_all(root: Path, globs: tuple[str, ...]) -> str:
    chunks = []
    for pattern in globs:
        for path in sorted(root.glob(pattern)):
            if path.is_file() and "/tests/" not in path.as_posix():
                chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def python_tools(root: Path = ROOT) -> list[str]:
    lock_path = root / "uv.lock"
    if not lock_path.is_file():
        return []
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages: list[dict[str, Any]] = lock.get("package", [])
    versions = {p["name"]: p.get("version", "") for p in packages}
    members = [
        p for p in packages if isinstance(p.get("source"), dict) and ({"editable", "virtual"} & p["source"].keys())
    ]
    member_names = {p["name"] for p in members}
    direct: set[str] = set()
    for member in members:
        if member["source"].get("virtual") == ".":  # the workspace root only carries dev tooling
            continue
        direct.update(dep["name"] for dep in member.get("dependencies", []) if dep["name"] not in member_names)

    source = _read_all(root, SOURCE_GLOBS)
    commands = _read_all(root, COMMAND_GLOBS)
    out = []
    for name in sorted(direct):
        human, module = PYTHON_NAMES.get(name, (name, name.replace("-", "_")))
        imported = bool(module) and re.search(rf"(?m)^\s*(?:from|import)\s+{re.escape(module or '')}\b", source)
        commanded = re.search(rf"\b{re.escape(name)}\b", commands)
        if imported or commanded:
            out.append(f"{human} {_version(versions.get(name, ''))}".strip())
    return out


def js_tools(root: Path = ROOT) -> list[str]:
    lock_path = root / "web" / "pnpm-lock.yaml"
    if not lock_path.is_file():
        return []
    import yaml  # noqa: PLC0415  (PyYAML is a locked dependency of falcon_core)

    out = []
    for document in yaml.safe_load_all(lock_path.read_text(encoding="utf-8")):
        importer = ((document or {}).get("importers") or {}).get(".") or {}
        for name, entry in sorted((importer.get("dependencies") or {}).items()):
            if name == "react-dom":
                continue  # ships with React; one entry is enough
            out.append(f"{JS_NAMES.get(name, name)} {_version(str(entry.get('version', '')))}".strip())
    return out


def _split_image(image: str) -> tuple[str, str]:
    name, _, tag = image.partition(":")
    return name, _version(tag.removeprefix("version-").split("-")[0]) if tag else ""


def infra_tools(root: Path = ROOT) -> list[str]:
    compose_path = root / "docker-compose.yml"
    if not compose_path.is_file():
        return []
    import yaml  # noqa: PLC0415

    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8")) or {}
    images: list[str] = []
    for service in (compose.get("services") or {}).values():
        if not PROFILES & set(service.get("profiles") or []):
            continue
        build = service.get("build")
        if build:
            context = build if isinstance(build, str) else build.get("context", ".")
            if not str(context).lstrip("./").startswith("infra/"):
                continue  # this repo's own service code, not a third-party tool
            dockerfile = (
                root / context / (build.get("dockerfile", "Dockerfile") if isinstance(build, dict) else "Dockerfile")
            )
            if dockerfile.is_file():
                images.extend(re.findall(r"(?mi)^FROM\s+(\S+)", dockerfile.read_text(encoding="utf-8")))
        elif service.get("image"):
            images.append(str(service["image"]))
    out: list[str] = []
    for image in images:
        if BASE_IMAGES.match(image) or "$" in image:
            continue
        name, version = _split_image(image)
        entry = f"{IMAGE_NAMES.get(name, name)} {version}".strip()
        if entry not in out:
            out.append(entry)
    return sorted(out, key=str.lower)


def platform_tools(root: Path = ROOT) -> list[str]:
    out = []
    version_file = root / ".python-version"
    if version_file.is_file():
        out.append(f"Python {version_file.read_text(encoding='utf-8').strip()}")
    if (root / "web" / "package.json").is_file():
        out.append("TypeScript")
    if (root / "docker-compose.yml").is_file():
        out.append("Docker Compose")
    if (root / "uv.lock").is_file():
        out.append("uv")
    if (root / "web" / "pnpm-lock.yaml").is_file():
        out.append("pnpm")
    return out


def model_tools(root: Path = ROOT) -> list[str]:
    """Model runtimes, listed only when shipped code has a call site for them.

    Ollama: a service or the core library reads the `ollama_base_url` setting to build a client
    (the setting's definition in config.py, a comment or a docstring does not count).
    Anthropic: the SDK is imported or the API host is addressed.
    """
    source = _read_all(root, SOURCE_GLOBS)
    out = []
    if re.search(r"\b(?:settings|ctx|cfg|config)\.ollama_base_url\b", source):
        out.append("Ollama (local models)")
    if re.search(r"(?m)^\s*(?:from|import)\s+anthropic\b|api\.anthropic\.com", source):
        out.append("Anthropic API (Claude models)")
    return out


def dev_tools(root: Path = ROOT) -> list[str]:
    out = []
    lock_path = root / "uv.lock"
    if lock_path.is_file():
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        for package in lock.get("package", []):
            if isinstance(package.get("source"), dict) and package["source"].get("virtual") == ".":
                dev = {d["name"] for group in (package.get("dev-dependencies") or {}).values() for d in group}
                out.extend(human for name, human in DEV_NAMES.items() if name in dev)
    ci = _read_all(root, (".github/workflows/*.yml",))
    if ci:
        out.append("GitHub Actions")
        out.extend(
            human
            for needle, human in (("gitleaks", "gitleaks"), ("pip-audit", "pip-audit"), ("trivy", "Trivy"))
            if needle in ci
        )
    if any((root / ".claude" / "agents").glob("*.md")):
        out.append("Claude Code (development agents)")
    return out


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = re.sub(r"\s+\d[\d.]*$", "", item).lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def categories(root: Path = ROOT) -> list[tuple[str, list[str]]]:
    backend = python_tools(root)
    models = [m for m in model_tools(root) if not any(m.split(" (")[0] in b for b in backend)]
    rows = [
        ("Languages and runtime", platform_tools(root)),
        ("Backend", backend),
        ("AI models", models),
        ("Web", js_tools(root)),
        ("Data and infrastructure", infra_tools(root)),
        ("Build, test and security scanning", dev_tools(root)),
    ]
    return [(title, _dedupe(items)) for title, items in rows if items]


def render(root: Path = ROOT, versions: bool = True) -> str:
    lines = []
    for title, items in categories(root):
        if not versions:
            items = [re.sub(r"\s+\d[\d.]*$", "", item) for item in items]
        lines.append(f"{title}: {', '.join(items)}")
    return "\n".join(lines) + "\n"


def names(root: Path = ROOT) -> list[tuple[str, list[str]]]:
    """Categories without version numbers (for the deck and the document)."""
    return [(title, [re.sub(r"\s+\d[\d.]*$", "", item) for item in items]) for title, items in categories(root)]


if __name__ == "__main__":
    print(render(), end="")
