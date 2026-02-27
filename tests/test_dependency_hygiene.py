"""Tests for dependency hygiene across the project.

Validates:
- bundle.md pins foundation to a specific commit (not @main)
- tool-lnd pyproject.toml has pinned httpx and [test] optional deps
- tool-aggeus-markets pyproject.toml has no cryptography dep and has [test] optional deps
"""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestBundlePinning:
    """bundle.md must pin foundation to a specific commit SHA, not @main."""

    def setup_method(self):
        self.bundle_path = ROOT / "bundle.md"
        self.content = self.bundle_path.read_text()

    def test_bundle_md_exists(self):
        assert self.bundle_path.exists()

    def test_foundation_not_pinned_to_main(self):
        """Foundation bundle must NOT use @main (floating ref)."""
        assert "amplifier-foundation@main" not in self.content, (
            "Foundation bundle must be pinned to a specific commit, not @main"
        )

    def test_foundation_pinned_to_commit_sha(self):
        """Foundation bundle must be pinned to a hex commit SHA."""
        # Match the foundation include line and extract the ref after @
        match = re.search(
            r"git\+https://github\.com/microsoft/amplifier-foundation@([a-f0-9]+)",
            self.content,
        )
        assert match is not None, (
            "Foundation bundle must be pinned to a commit SHA (hex string after @)"
        )
        sha = match.group(1)
        assert len(sha) >= 7, f"Commit SHA too short: {sha}"


class TestToolLndPyproject:
    """tool-lnd pyproject.toml must have pinned deps and test optional-dependencies."""

    def setup_method(self):
        self.toml_path = ROOT / "modules" / "tool-lnd" / "pyproject.toml"

    def _load(self):
        with open(self.toml_path, "rb") as f:
            return tomllib.load(f)

    def test_pyproject_exists(self):
        assert self.toml_path.exists()

    def test_project_name(self):
        data = self._load()
        assert data["project"]["name"] == "amplifier-module-tool-lnd"

    def test_project_version(self):
        data = self._load()
        assert data["project"]["version"] == "0.1.0"

    def test_httpx_pinned_with_minimum(self):
        """httpx must have a minimum version pin (>=0.27)."""
        data = self._load()
        deps = data["project"]["dependencies"]
        httpx_deps = [d for d in deps if d.startswith("httpx")]
        assert len(httpx_deps) == 1, "Must have exactly one httpx dependency"
        assert httpx_deps[0] == "httpx>=0.27", f"httpx must be pinned: got {httpx_deps[0]}"

    def test_has_test_optional_dependencies(self):
        """Must have [project.optional-dependencies] test section."""
        data = self._load()
        assert "optional-dependencies" in data["project"], (
            "Must have [project.optional-dependencies]"
        )
        assert "test" in data["project"]["optional-dependencies"], (
            "Must have test optional dependencies"
        )

    def test_test_deps_include_pytest(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        pytest_deps = [d for d in test_deps if d.startswith("pytest>=")]
        assert len(pytest_deps) >= 1, "Must include pytest>=8.0"

    def test_test_deps_include_pytest_asyncio(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        asyncio_deps = [d for d in test_deps if d.startswith("pytest-asyncio>=")]
        assert len(asyncio_deps) >= 1, "Must include pytest-asyncio>=0.24"

    def test_test_deps_include_respx(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        respx_deps = [d for d in test_deps if d.startswith("respx>=")]
        assert len(respx_deps) >= 1, "Must include respx>=0.22"

    def test_entry_point(self):
        data = self._load()
        ep = data["project"]["entry-points"]["amplifier.modules"]
        assert ep["tool-lnd"] == "amplifier_module_tool_lnd:mount"

    def test_build_system_is_hatchling(self):
        data = self._load()
        assert data["build-system"]["build-backend"] == "hatchling.build"


class TestToolAggeusMarketsPyproject:
    """tool-aggeus-markets pyproject.toml must have no cryptography and must have test deps."""

    def setup_method(self):
        self.toml_path = ROOT / "modules" / "tool-aggeus-markets" / "pyproject.toml"

    def _load(self):
        with open(self.toml_path, "rb") as f:
            return tomllib.load(f)

    def test_pyproject_exists(self):
        assert self.toml_path.exists()

    def test_project_name(self):
        data = self._load()
        assert data["project"]["name"] == "amplifier-module-tool-aggeus-markets"

    def test_project_version(self):
        data = self._load()
        assert data["project"]["version"] == "0.1.0"

    def test_no_cryptography_dependency(self):
        """cryptography must NOT be in dependencies (unused)."""
        data = self._load()
        deps = data["project"]["dependencies"]
        crypto_deps = [d for d in deps if "cryptography" in d.lower()]
        assert len(crypto_deps) == 0, f"cryptography must be removed (unused): {crypto_deps}"

    def test_has_websockets_dependency(self):
        data = self._load()
        deps = data["project"]["dependencies"]
        ws_deps = [d for d in deps if d.startswith("websockets>=")]
        assert len(ws_deps) == 1, "Must have websockets>=12.0"

    def test_has_coincurve_dependency(self):
        data = self._load()
        deps = data["project"]["dependencies"]
        cc_deps = [d for d in deps if d.startswith("coincurve>=")]
        assert len(cc_deps) == 1, "Must have coincurve>=13.0"

    def test_has_test_optional_dependencies(self):
        """Must have [project.optional-dependencies] test section."""
        data = self._load()
        assert "optional-dependencies" in data["project"], (
            "Must have [project.optional-dependencies]"
        )
        assert "test" in data["project"]["optional-dependencies"], (
            "Must have test optional dependencies"
        )

    def test_test_deps_include_pytest(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        pytest_deps = [d for d in test_deps if d.startswith("pytest>=")]
        assert len(pytest_deps) >= 1, "Must include pytest>=8.0"

    def test_test_deps_include_pytest_asyncio(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        asyncio_deps = [d for d in test_deps if d.startswith("pytest-asyncio>=")]
        assert len(asyncio_deps) >= 1, "Must include pytest-asyncio>=0.24"

    def test_test_deps_include_respx(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        respx_deps = [d for d in test_deps if d.startswith("respx>=")]
        assert len(respx_deps) >= 1, "Must include respx>=0.22"

    def test_test_deps_include_pytest_mock(self):
        data = self._load()
        test_deps = data["project"]["optional-dependencies"]["test"]
        mock_deps = [d for d in test_deps if "pytest-mock" in d]
        assert len(mock_deps) >= 1, "Must include pytest-mock"

    def test_entry_point(self):
        data = self._load()
        ep = data["project"]["entry-points"]["amplifier.modules"]
        assert ep["tool-aggeus-markets"] == "amplifier_module_tool_aggeus_markets:mount"

    def test_build_system_is_hatchling(self):
        data = self._load()
        assert data["build-system"]["build-backend"] == "hatchling.build"
