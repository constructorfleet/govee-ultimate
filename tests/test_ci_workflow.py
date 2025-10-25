"""Regression coverage for the CI workflow definition."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_defines_required_jobs() -> None:
    """The CI workflow should expose lint/test on PR and tagging on main merges."""

    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists(), "missing ci workflow file"

    workflow = yaml.safe_load(workflow_path.read_text()) or {}

    triggers = workflow.get("on", {})
    assert "pull_request" in triggers, "pull request trigger required"
    push = triggers.get("push")
    assert push, "push trigger required"
    branches = push.get("branches", [])
    assert "main" in branches, "push trigger must include main branch"

    jobs = workflow.get("jobs") or {}
    assert "lint" in jobs, "lint job missing"
    assert "tests" in jobs, "tests job missing"
    assert "tag" in jobs, "tag job missing"
