"""Ensure documentation no longer references integration blueprint."""

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "doc_path",
    [
        Path("README.md"),
        Path("README_EXAMPLE.md"),
    ],
)
def test_docs_do_not_reference_integration_blueprint(doc_path):
    """Each documentation file should be free of integration blueprint references."""
    content = doc_path.read_text(encoding="utf-8")
    lowered = content.casefold()
    assert "integration blueprint" not in lowered
    assert "integration_blueprint" not in lowered
