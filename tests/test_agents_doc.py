"""Tests for the repository guidance available to agents."""

from pathlib import Path


def _read_agents_doc() -> str:
    """Return the AGENTS.md contents, asserting the file exists."""
    repo_root = Path(__file__).resolve().parents[1]
    agents_path = repo_root / "AGENTS.md"

    assert agents_path.exists(), "Expected AGENTS.md to be present at repository root"

    return agents_path.read_text(encoding="utf-8")


def test_agents_doc_includes_reference_to_typescript_repo() -> None:
    """AGENTS.md should reference the upstream repo and Home Assistant port."""
    contents = _read_agents_doc()
    lower_contents = contents.lower()

    assert (
        "constructorfleet/ultimate-govee" in contents
    ), "Document should reference the TypeScript library"
    assert (
        "port" in lower_contents and "home-assistant" in lower_contents
    ), "Document should note that this project is a port to a Home Assistant custom component"


def test_agents_doc_mentions_op_codes_and_device_states() -> None:
    """AGENTS.md should guide contributors about op codes and device states."""
    contents = _read_agents_doc()
    lower_contents = contents.lower()

    assert any(
        phrase in lower_contents for phrase in ("op code", "opcode", "op-code")
    ), "Document should mention op codes to align with upstream protocol semantics"
    assert all(
        keyword in lower_contents for keyword in ("device", "state")
    ), "Document should describe device types and their states for context"


def test_agents_doc_requires_pre_pr_quality_checks() -> None:
    """AGENTS.md should remind contributors to run linting and tests before PRs."""
    contents = _read_agents_doc()
    lower_contents = contents.lower()

    assert (
        "lint" in lower_contents
    ), "Document should mention linting expectations before pull requests"
    assert any(
        keyword in lower_contents for keyword in ("format", "formatter", "formatting")
    ), "Document should call out formatting steps alongside linting"
    assert (
        "test" in lower_contents
    ), "Document should direct contributors to run tests before pull requests"
    assert (
        "pull request" in lower_contents
    ), "Document should tie quality checks to pull request workflow"
