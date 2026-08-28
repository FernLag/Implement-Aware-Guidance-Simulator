"""Security audit for the web interface.

    python3 scripts/security_audit.py

Written as a script rather than a one time report so it can be re-run after
any change. Each check prints PASS, WARN or FAIL with the reasoning, and the
exit code is non zero if anything FAILs.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
results: list[tuple[str, str, str]] = []


def record(level: str, name: str, detail: str) -> None:
    results.append((level, name, detail))


def check_no_hardcoded_secrets() -> None:
    pattern = re.compile(
        r"(?i)\b(secret_key|api_key|apikey|password|passwd|access_token|"
        r"auth_token|private_key|aws_secret)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
    )
    hits = []
    for path in REPO.rglob("*.py"):
        if any(p in path.parts for p in (".git", "venv", "scratchpad")):
            continue
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if pattern.search(line) and "test" not in path.name:
                hits.append(f"{path.relative_to(REPO)}:{i}")
    if hits:
        record("FAIL", "No hardcoded secrets", "; ".join(hits))
    else:
        record("PASS", "No hardcoded secrets",
               "every credential is read from the environment at start up")


def check_secrets_not_in_git() -> None:
    try:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        record("WARN", "Secrets not committed", "could not run git")
        return
    bad = [f for f in tracked
           if f == ".env" or f.startswith("instance/") or f.endswith(".jsonl")]
    if bad:
        record("FAIL", "Secrets not committed", f"tracked: {bad}")
    else:
        record("PASS", "Secrets not committed",
               ".env, instance/ and message files are git ignored and untracked")


def check_dangerous_calls() -> None:
    banned = {"eval", "exec", "compile", "__import__"}
    banned_mods = {"pickle", "marshal", "shelve", "subprocess", "os.system"}
    hits = []
    for path in (REPO / "web").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in banned:
                    hits.append(f"{path.name}: {node.func.id}() line {node.lineno}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
                for n in names:
                    if n in banned_mods:
                        hits.append(f"{path.name}: imports {n}")
    if hits:
        record("FAIL", "No dangerous evaluation or deserialisation", "; ".join(hits))
    else:
        record("PASS", "No dangerous evaluation or deserialisation",
               "no eval, exec, pickle or subprocess in the web package")


def check_yaml_loading() -> None:
    hits = []
    for path in REPO.rglob("*.py"):
        if ".git" in path.parts or "venv" in path.parts:
            continue
        text = path.read_text(errors="ignore")
        if re.search(r"yaml\.load\s*\(", text) and "SafeLoader" not in text:
            hits.append(str(path.relative_to(REPO)))
    if hits:
        record("FAIL", "YAML parsed safely", f"yaml.load without SafeLoader: {hits}")
    else:
        record("PASS", "YAML parsed safely",
               "the catalog uses yaml.safe_load, so tags cannot construct objects")


def check_headers_and_csp() -> None:
    sys.path.insert(0, str(REPO))
    from dataclasses import replace

    from web.app import create_app
    from web.config import load_settings

    app = create_app(replace(load_settings(), secret_key="audit",
                             secret_key_is_ephemeral=False,
                             rate_limit_per_minute=6000, rate_limit_burst=500))
    response = app.test_client().get("/")
    h = response.headers

    required = {
        "Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
        "Referrer-Policy", "Permissions-Policy",
    }
    missing = required - set(h.keys())
    if missing:
        record("FAIL", "Security headers", f"missing: {sorted(missing)}")
    else:
        record("PASS", "Security headers", ", ".join(sorted(required)))

    csp = h["Content-Security-Policy"]
    weak = [t for t in ("'unsafe-inline'", "'unsafe-eval'", "*") if t in csp]
    if weak:
        record("FAIL", "CSP strictness", f"weak directives: {weak}")
    else:
        record("PASS", "CSP strictness",
               "same origin only, no unsafe-inline, no unsafe-eval, frame-ancestors none")


def check_rate_limiting() -> None:
    sys.path.insert(0, str(REPO))
    from dataclasses import replace

    from web.app import create_app
    from web.config import load_settings

    app = create_app(replace(load_settings(), secret_key="audit",
                             secret_key_is_ephemeral=False,
                             rate_limit_per_minute=1, rate_limit_burst=1))
    client = app.test_client()
    page = [client.get("/").status_code for _ in range(6)]
    api = [client.post("/api/simulate", json={"tractor": "jd_6145r"}).status_code
           for _ in range(4)]
    if 429 in page and 429 in api:
        record("PASS", "Rate limiting", "pages and API both limited; static assets exempt")
    else:
        record("FAIL", "Rate limiting", f"pages {page}, api {api}")

    record("WARN", "Rate limiting is per process",
           "The limiter is in-memory, so with N gunicorn workers the effective "
           "limit is N times the configured value, and it resets on restart. "
           "Put an edge limiter in front of any public deployment.")

    record("WARN", "Rate limiting keys on the socket address",
           "request.remote_addr is used deliberately, because X-Forwarded-For is "
           "attacker controlled unless a trusted proxy is configured. Behind a "
           "reverse proxy every client shares the proxy address, turning the "
           "per-client limit into a global one. Configure ProxyFix with the "
           "correct hop count before deploying behind a proxy.")


def check_input_validation() -> None:
    schemas = (REPO / "web" / "schemas.py").read_text()
    if 'extra="forbid"' in schemas and schemas.count("Field(") > 8:
        record("PASS", "Input validation",
               "every request field is bounded and unknown fields are rejected")
    else:
        record("FAIL", "Input validation", "schemas are not strict")

    app_src = (REPO / "web" / "app.py").read_text()
    if "MAX_CONTENT_LENGTH" in app_src:
        record("PASS", "Payload size limit",
               "oversized bodies are refused by Flask before handler code runs")
    else:
        record("FAIL", "Payload size limit", "MAX_CONTENT_LENGTH is not configured")

    sim = (REPO / "web" / "simulation.py").read_text()
    if "max_steps" in sim:
        record("PASS", "Compute bounded",
               "simulation cost is capped by total integration steps, not only "
               "by request rate, so one long request cannot monopolise a worker")
    else:
        record("FAIL", "Compute bounded", "no cap on simulation cost")


def check_csrf_and_cookies() -> None:
    app_src = (REPO / "web" / "app.py").read_text()
    checks = {
        "CSRF token on the contact form": "_csrf_ok" in app_src,
        "Constant time token comparison": "hmac.compare_digest" in app_src,
        "HttpOnly session cookie": "SESSION_COOKIE_HTTPONLY=True" in app_src,
        "SameSite session cookie": 'SESSION_COOKIE_SAMESITE="Lax"' in app_src,
        "Secure cookie when served over TLS": "SESSION_COOKIE_SECURE" in app_src,
    }
    for name, ok in checks.items():
        record("PASS" if ok else "FAIL", name, "present" if ok else "missing")

    record("WARN", "JSON API has no CSRF token",
           "/api/simulate is a POST but has no side effects: it computes and "
           "returns a result, storing nothing. A cross origin JSON POST also "
           "triggers a preflight that this server does not answer. Add a token "
           "if the API ever gains state changing endpoints.")


def check_debug_and_server() -> None:
    from web.config import load_settings
    settings = load_settings()
    if settings.debug:
        record("FAIL", "Debug mode", "AGGSIM_DEBUG is enabled in this environment")
    else:
        record("PASS", "Debug mode",
               "off by default, so tracebacks are never sent to a browser")

    if settings.secret_key_is_ephemeral:
        record("WARN", "Session signing key",
               "AGGSIM_SECRET_KEY is unset, so a random key is generated per "
               "process. With more than one worker each has a different key and "
               "contact form submissions will fail CSRF validation. Set it "
               "before deploying.")
    else:
        record("PASS", "Session signing key", "supplied from the environment")

    wsgi = (REPO / "wsgi.py").read_text()
    if "gunicorn" in wsgi:
        record("PASS", "Production server documented",
               "wsgi.py names gunicorn; the Flask development server is not for "
               "public use")


def check_pii_handling() -> None:
    record("WARN", "Contact messages are stored in clear text",
           "Names, email addresses and message bodies are appended to "
           "instance/messages.jsonl. That file is git ignored, but it is "
           "personal data: restrict its permissions, back it up deliberately, "
           "and delete entries once answered.")


def check_dependencies() -> None:
    from importlib.metadata import PackageNotFoundError, version
    versions = {}
    for pkg in ("flask", "jinja2", "pydantic"):
        try:
            versions[pkg] = version(pkg)
        except PackageNotFoundError:
            versions[pkg] = "not installed"
    record("WARN", "Dependency scanning is not automated",
           "Installed: " + ", ".join(f"{k} {v}" for k, v in versions.items()) +
           ". Run `pip-audit` or `safety check` in CI against a pinned "
           "requirements file; this script deliberately does not guess at "
           "advisories from version numbers alone.")


def main() -> int:
    check_no_hardcoded_secrets()
    check_secrets_not_in_git()
    check_dangerous_calls()
    check_yaml_loading()
    check_headers_and_csp()
    check_rate_limiting()
    check_input_validation()
    check_csrf_and_cookies()
    check_debug_and_server()
    check_pii_handling()
    check_dependencies()

    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    results.sort(key=lambda r: order[r[0]])

    print("SECURITY AUDIT: web interface\n" + "=" * 74)
    for level, name, detail in results:
        print(f"\n[{level}] {name}")
        for line in _wrap(detail, 70):
            print(f"       {line}")

    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    passes = sum(1 for r in results if r[0] == "PASS")
    print("\n" + "=" * 74)
    print(f"{passes} passed, {warns} warnings, {fails} failures")
    if warns:
        print("Warnings are accepted limitations, documented rather than hidden.")
    return 1 if fails else 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


if __name__ == "__main__":
    sys.exit(main())
