"""Ensure documentation no longer references integration blueprint."""

from pathlib import Path

import pytest


DOC_PATHS = (Path("README.md"),)


@pytest.mark.parametrize(
    "doc_path",
    DOC_PATHS,
)
def test_docs_do_not_reference_integration_blueprint(doc_path):
    """Each documentation file should be free of integration blueprint references."""
    content = doc_path.read_text(encoding="utf-8")
    lowered = content.casefold()
    assert "integration blueprint" not in lowered
    assert "integration_blueprint" not in lowered


def test_readme_example_removed():
    """The README example from the template should be removed entirely."""
    readme_example = Path("README_EXAMPLE.md")
    assert not readme_example.exists()
