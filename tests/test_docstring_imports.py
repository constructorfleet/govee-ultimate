"""Guard style expectations for docstring tests."""

import inspect

import tests.test_docstrings as doc_tests

_EXPECTED_IMPORT = "from collections.abc import Callable"


def test_docstring_tests_use_collections_callable() -> None:
    """Docstring tests should import Callable from collections.abc."""

    source = inspect.getsource(doc_tests)
    assert _EXPECTED_IMPORT in source
