"""Static checks of the supply-chain controls (spec 003, T019): CI cannot be run locally, so
these keep anyone from quietly unpinning an action, widening the token or softening a scan."""

from __future__ import annotations

import json
import re
from typing import Any

import yaml

from betting_ml.config import PROJECT_ROOT

WORKFLOW = yaml.safe_load((PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
PINNED = re.compile(r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = WORKFLOW["jobs"][job]["steps"]
    return steps


def test_the_token_is_read_only_everywhere() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    for name, job in WORKFLOW["jobs"].items():
        assert "permissions" not in job, f"{name} widens the token"


def test_every_action_is_pinned_to_a_commit_and_checkout_keeps_no_token() -> None:
    for name in WORKFLOW["jobs"]:
        for step in _steps(name):
            if "uses" in step:
                assert PINNED.match(step["uses"]), step["uses"]
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_security_job_runs_every_scan_and_fails_on_findings() -> None:
    steps = _steps("security")
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "ruff check --select S src tests migrations" in commands
    assert "pip-audit --disable-pip --require-hashes" in commands
    assert "npm audit --audit-level=high" in commands
    assert "gitleaks" in commands and "git --redact" in commands
    assert "sha256sum -c -" in commands  # the downloaded binary is verified
    assert not any(step.get("continue-on-error") for step in steps)
    assert "|| true" not in commands
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0  # the whole history is scanned


def test_installs_follow_the_lockfiles() -> None:
    for job in ("test", "security"):
        runs = [s.get("run", "") for s in _steps(job)]
        assert "uv sync --locked --extra dev" in runs


def test_make_security_fails_on_findings_too() -> None:
    makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nsecurity:\n", 1)[1].split("\n\n", 1)[0]
    lines = [line.strip() for line in target.splitlines() if line.strip()]
    assert len(lines) == 5 and not any(line.startswith("-") for line in lines)


def test_dependabot_watches_every_ecosystem() -> None:
    config = yaml.safe_load((PROJECT_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    watched = {(u["package-ecosystem"], u["directory"]) for u in config["updates"]}
    assert watched == {("uv", "/"), ("npm", "/frontend"), ("github-actions", "/")}


def test_pre_commit_blocks_secrets() -> None:
    config = yaml.safe_load((PROJECT_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = {hook["id"] for repo in config["repos"] for hook in repo["hooks"]}
    assert {"gitleaks", "detect-private-key"} <= hooks


def test_the_shadcn_cli_is_not_a_dependency() -> None:
    """Its transitive packages have high advisories without a fix: only its CSS is vendored."""
    package = json.loads((PROJECT_ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    for section in ("dependencies", "devDependencies"):
        assert "shadcn" not in package.get(section, {})
    css = (PROJECT_ROOT / "frontend/src/index.css").read_text(encoding="utf-8")
    assert '@import "./styles/shadcn-tailwind.css";' in css
