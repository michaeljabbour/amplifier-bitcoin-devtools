"""Tests for _load_credentials resource leak fix.

Verifies that:
1. The function uses a context manager (with statement) for file I/O.
2. FileNotFoundError is caught and raised as ValueError with actionable message.
3. PermissionError is caught and raised as ValueError with actionable message.
4. The source file parses cleanly with ast.parse.
"""

import ast
import pathlib
import tempfile

import pytest

from amplifier_module_tool_bitcoin_rpc import _load_credentials

SRC_PATH = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/__init__.py"
)


# ---------------------------------------------------------------------------
# Structural / AST tests
# ---------------------------------------------------------------------------


def test_source_parses_cleanly():
    """The source file must parse without errors."""
    source = SRC_PATH.read_text()
    tree = ast.parse(source)  # Raises SyntaxError if broken
    assert tree is not None


def test_load_credentials_uses_context_manager():
    """_load_credentials must use a `with` statement for file I/O, not bare open()."""
    source = SRC_PATH.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_load_credentials":
            # Check there is at least one `with` statement
            has_with = any(
                isinstance(stmt, ast.With) for stmt in ast.walk(node)
            )
            assert has_with, (
                "_load_credentials must use a `with` statement (context manager) for file I/O"
            )

            # Check there is no bare open().read() pattern (Expr -> Call -> Attribute.read)
            for child in ast.walk(node):
                if isinstance(child, ast.Assign):
                    value = child.value
                    # Detect: content = open(cookie_file).read()
                    if (
                        isinstance(value, ast.Call)
                        and isinstance(value.func, ast.Attribute)
                        and value.func.attr == "read"
                        and isinstance(value.func.value, ast.Call)
                        and isinstance(value.func.value.func, ast.Name)
                        and value.func.value.func.id == "open"
                    ):
                        pytest.fail(
                            "_load_credentials must not use bare open().read() — "
                            "use a context manager instead"
                        )
            return

    pytest.fail("_load_credentials function not found in source")


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


def test_file_not_found_raises_value_error():
    """Missing cookie file must raise ValueError mentioning BITCOIN_COOKIE_FILE."""
    config = {"cookie_file": "/nonexistent/path/to/.cookie"}
    with pytest.raises(ValueError, match="Cookie file not found"):
        _load_credentials(config)
    with pytest.raises(ValueError, match="BITCOIN_COOKIE_FILE"):
        _load_credentials(config)


def test_permission_denied_raises_value_error():
    """Unreadable cookie file must raise ValueError mentioning file permissions."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cookie", delete=False) as tmp:
        tmp.write("user:pass")
        tmp_path = tmp.name

    p = pathlib.Path(tmp_path)
    try:
        p.chmod(0o000)
        config = {"cookie_file": tmp_path}
        with pytest.raises(ValueError, match="Permission denied"):
            _load_credentials(config)
        with pytest.raises(ValueError, match="file permissions"):
            _load_credentials(config)
    finally:
        p.chmod(0o644)
        p.unlink()


# ---------------------------------------------------------------------------
# Happy-path test (context manager should still work for valid files)
# ---------------------------------------------------------------------------


def test_valid_cookie_file_returns_credentials():
    """A valid cookie file should return (user, password) tuple."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".cookie", delete=False
    ) as tmp:
        tmp.write("__cookie__:abc123secret")
        tmp_path = tmp.name

    p = pathlib.Path(tmp_path)
    try:
        config = {"cookie_file": tmp_path}
        user, password = _load_credentials(config)
        assert user == "__cookie__"
        assert password == "abc123secret"
    finally:
        p.unlink()
