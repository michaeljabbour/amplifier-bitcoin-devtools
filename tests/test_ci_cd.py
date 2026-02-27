"""Tests for CI/CD configuration files.

Validates that .github/workflows/ci.yaml and root pyproject.toml
exist with the correct structure and content.
"""

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class TestCIWorkflow:
    """Tests for .github/workflows/ci.yaml."""

    def setup_method(self):
        self.ci_path = ROOT / ".github" / "workflows" / "ci.yaml"

    def test_ci_yaml_exists(self):
        assert self.ci_path.exists(), ".github/workflows/ci.yaml must exist"

    def test_ci_yaml_is_valid_yaml(self):
        with open(self.ci_path) as f:
            self.workflow = yaml.safe_load(f)
        assert isinstance(self.workflow, dict)

    def _load(self):
        with open(self.ci_path) as f:
            return yaml.safe_load(f)

    def test_triggers_on_push(self):
        workflow = self._load()
        assert "push" in workflow[True], "CI must trigger on push"

    def test_triggers_on_pull_request(self):
        workflow = self._load()
        assert "pull_request" in workflow[True], "CI must trigger on pull_request"

    def test_has_lint_job(self):
        workflow = self._load()
        assert "lint" in workflow["jobs"], "Must have a lint job"

    def test_has_typecheck_job(self):
        workflow = self._load()
        assert "typecheck" in workflow["jobs"], "Must have a typecheck job"

    def test_has_test_job(self):
        workflow = self._load()
        assert "test" in workflow["jobs"], "Must have a test job"

    def test_lint_job_runs_on_ubuntu(self):
        workflow = self._load()
        assert workflow["jobs"]["lint"]["runs-on"] == "ubuntu-latest"

    def test_lint_job_uses_python_311(self):
        workflow = self._load()
        lint_steps = workflow["jobs"]["lint"]["steps"]
        python_step = next(
            (s for s in lint_steps if s.get("uses", "").startswith("actions/setup-python")),
            None,
        )
        assert python_step is not None, "lint job must set up Python"
        assert python_step["with"]["python-version"] == "3.11"

    def test_lint_job_installs_ruff(self):
        workflow = self._load()
        lint_steps = workflow["jobs"]["lint"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in lint_steps)
        assert "pip install ruff" in step_texts

    def test_lint_job_runs_ruff_check(self):
        workflow = self._load()
        lint_steps = workflow["jobs"]["lint"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in lint_steps)
        assert "ruff check modules/" in step_texts

    def test_lint_job_runs_ruff_format_check(self):
        workflow = self._load()
        lint_steps = workflow["jobs"]["lint"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in lint_steps)
        assert "ruff format --check modules/" in step_texts

    def test_typecheck_job_runs_on_ubuntu(self):
        workflow = self._load()
        assert workflow["jobs"]["typecheck"]["runs-on"] == "ubuntu-latest"

    def test_typecheck_job_uses_python_311(self):
        workflow = self._load()
        tc_steps = workflow["jobs"]["typecheck"]["steps"]
        python_step = next(
            (s for s in tc_steps if s.get("uses", "").startswith("actions/setup-python")),
            None,
        )
        assert python_step is not None
        assert python_step["with"]["python-version"] == "3.11"

    def test_typecheck_job_installs_pyright_and_modules(self):
        workflow = self._load()
        tc_steps = workflow["jobs"]["typecheck"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in tc_steps)
        assert "pyright" in step_texts
        assert "modules/tool-bitcoin-rpc" in step_texts
        assert "modules/tool-lnd" in step_texts
        assert "modules/tool-aggeus-markets" in step_texts

    def test_typecheck_job_runs_pyright(self):
        workflow = self._load()
        tc_steps = workflow["jobs"]["typecheck"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in tc_steps)
        assert "pyright modules/" in step_texts

    def test_test_job_runs_on_ubuntu(self):
        workflow = self._load()
        assert workflow["jobs"]["test"]["runs-on"] == "ubuntu-latest"

    def test_test_job_has_matrix_strategy(self):
        workflow = self._load()
        matrix = workflow["jobs"]["test"]["strategy"]["matrix"]["module"]
        assert "tool-bitcoin-rpc" in matrix
        assert "tool-lnd" in matrix
        assert "tool-aggeus-markets" in matrix

    def test_test_job_uses_pytest(self):
        workflow = self._load()
        test_steps = workflow["jobs"]["test"]["steps"]
        step_texts = " ".join(str(s.get("run", "")) for s in test_steps)
        assert "pytest" in step_texts


class TestRootPyprojectToml:
    """Tests for root pyproject.toml (tooling config only)."""

    def setup_method(self):
        self.toml_path = ROOT / "pyproject.toml"

    def test_pyproject_toml_exists(self):
        assert self.toml_path.exists(), "Root pyproject.toml must exist"

    def _load(self):
        with open(self.toml_path, "rb") as f:
            return tomllib.load(f)

    def test_is_not_a_package(self):
        """Root pyproject.toml should NOT define a [project] section."""
        data = self._load()
        assert "project" not in data, "Root pyproject.toml must NOT be a package"

    def test_ruff_target_version(self):
        data = self._load()
        assert data["tool"]["ruff"]["target-version"] == "py311"

    def test_ruff_line_length(self):
        data = self._load()
        assert data["tool"]["ruff"]["line-length"] == 100

    def test_ruff_lint_select(self):
        data = self._load()
        expected = ["E", "F", "I", "W", "UP", "B", "SIM"]
        assert data["tool"]["ruff"]["lint"]["select"] == expected

    def test_pyright_python_version(self):
        data = self._load()
        assert data["tool"]["pyright"]["pythonVersion"] == "3.11"

    def test_pyright_type_checking_mode(self):
        data = self._load()
        assert data["tool"]["pyright"]["typeCheckingMode"] == "basic"

    def test_pytest_asyncio_mode(self):
        data = self._load()
        assert data["tool"]["pytest"]["ini_options"]["asyncio_mode"] == "auto"

    def test_pytest_testpaths(self):
        data = self._load()
        testpaths = data["tool"]["pytest"]["ini_options"]["testpaths"]
        # Root testpaths covers only root-level tests (docs, CI, deps).
        # Module tests run per-module via CI matrix (each needs pip install -e).
        assert "tests" in testpaths
