"""Tests guarding GitHub workflow configuration."""

from pathlib import Path


def test_workflows_reference_current_domain():
    """Ensure CI workflows use the updated govee domain."""
    repo_root = Path(__file__).resolve().parents[1]
    workflows = (repo_root / ".github" / "workflows").glob("*.yml")

    offending = [
        f"{workflow}:{idx}: '{line.strip()}'"
        for workflow in workflows
        for idx, line in enumerate(workflow.read_text().splitlines(), start=1)
        if "custom_components/govee_ultimate" in line
    ]

    assert not offending, (
        "CI workflows should reference custom_components/govee rather than "
        "custom_components/govee_ultimate. Offending lines: " + ", ".join(offending)
    )
