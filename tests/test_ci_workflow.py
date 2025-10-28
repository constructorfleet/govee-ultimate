"""Regression coverage for the CI workflow definition."""

from __future__ import annotations

from pathlib import Path


def _has_push_main_branch(lines: list[str]) -> bool:
    push_indent = None
    branch_indent = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("push:"):
            push_indent = indent
            branch_indent = None
            continue
        if push_indent is not None and indent <= push_indent and stripped.endswith(":"):
            # exited the push block
            push_indent = None
        if push_indent is None:
            continue
        if stripped.startswith("branches:"):
            branch_indent = indent
            continue
        if (
            branch_indent is not None
            and indent <= branch_indent
            and stripped.endswith(":")
        ):
            branch_indent = None
        if branch_indent is not None and stripped.startswith("-"):
            value = stripped.lstrip("-").strip().strip("'").strip('"')
            if value == "main":
                return True
    return False


def _collect_job_names(lines: list[str]) -> set[str]:
    jobs_indent = None
    job_names: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if stripped.startswith("jobs:"):
            jobs_indent = indent
            continue
        if jobs_indent is None:
            continue
        if indent <= jobs_indent and stripped.endswith(":"):
            # exited jobs block
            jobs_indent = None
            continue
        if indent == jobs_indent + 2 and stripped.endswith(":"):
            job_names.add(stripped.rstrip(":"))
    return job_names


def test_ci_workflow_defines_required_jobs() -> None:
    """The CI workflow should expose lint/test on PR and tagging on main merges."""

    workflow_path = Path(".github/workflows/ci.yml")
    assert workflow_path.exists(), "missing ci workflow file"

    lines = workflow_path.read_text().splitlines()

    assert any(
        "pull_request:" in line for line in lines
    ), "pull request trigger required"
    assert any(
        line.strip().startswith("push:") for line in lines
    ), "push trigger required"
    assert _has_push_main_branch(lines), "push trigger must include main branch"

    jobs = _collect_job_names(lines)
    assert "lint" in jobs, "lint job missing"
    assert "tests" in jobs, "tests job missing"
    assert "tag" in jobs, "tag job missing"
