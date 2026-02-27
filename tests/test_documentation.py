"""Tests for project documentation files (README, CHANGELOG, CONTRIBUTING)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


class TestReadme:
    """Verify README.md has correct content after fixes."""

    def setup_method(self):
        self.readme = (PROJECT_ROOT / "README.md").read_text()

    def test_no_placeholder_org_in_clone_url(self):
        """README must not contain <your-org> placeholder."""
        assert "<your-org>" not in self.readme

    def test_correct_clone_url(self):
        """README must have the correct clone URL."""
        assert (
            "git clone https://github.com/michaeljabbour/amplifier-bitcoin-devtools.git"
            in self.readme
        )

    def test_aggeus_markets_deps_no_cryptography(self):
        """tool-aggeus-markets row must NOT list cryptography."""
        assert "cryptography" not in self.readme

    def test_aggeus_markets_deps_correct(self):
        """tool-aggeus-markets row must list websockets and coincurve only."""
        # Find the aggeus-markets row in the Module Dependencies table
        lines = self.readme.splitlines()
        aggeus_row = None
        for line in lines:
            if "tool-aggeus-markets" in line and "|" in line:
                aggeus_row = line
                break
        assert aggeus_row is not None, "tool-aggeus-markets row not found"
        assert "websockets>=12.0" in aggeus_row
        assert "coincurve>=13.0" in aggeus_row


class TestChangelog:
    """Verify CHANGELOG.md exists with required content."""

    def setup_method(self):
        self.path = PROJECT_ROOT / "CHANGELOG.md"

    def test_changelog_exists(self):
        """CHANGELOG.md must exist."""
        assert self.path.exists(), "CHANGELOG.md does not exist"

    def test_changelog_has_keepachangelog_header(self):
        """CHANGELOG must follow Keep a Changelog format."""
        content = self.path.read_text()
        assert "Keep a Changelog" in content

    def test_changelog_has_v010_entry(self):
        """CHANGELOG must have a [0.1.0] entry."""
        content = self.path.read_text()
        assert "[0.1.0]" in content

    def test_changelog_has_date(self):
        """CHANGELOG v0.1.0 entry must have the date 2026-02-26."""
        content = self.path.read_text()
        assert "2026-02-26" in content

    def test_changelog_lists_added_tools(self):
        """CHANGELOG must mention the 3 tool modules."""
        content = self.path.read_text()
        assert "Added" in content
        # Should reference tool modules, agents, behaviors, context
        assert "tool module" in content.lower() or "tool modules" in content.lower()

    def test_changelog_mentions_agents(self):
        """CHANGELOG must mention 3 agent definitions."""
        content = self.path.read_text()
        assert "agent" in content.lower()

    def test_changelog_mentions_behaviors(self):
        """CHANGELOG must mention 3 composable behavior bundles."""
        content = self.path.read_text()
        assert "behavior" in content.lower() or "bundle" in content.lower()


class TestContributing:
    """Verify CONTRIBUTING.md exists with required sections."""

    def setup_method(self):
        self.path = PROJECT_ROOT / "CONTRIBUTING.md"

    def test_contributing_exists(self):
        """CONTRIBUTING.md must exist."""
        assert self.path.exists(), "CONTRIBUTING.md does not exist"

    def test_has_development_setup(self):
        """CONTRIBUTING must have Development Setup section."""
        content = self.path.read_text()
        assert "Development Setup" in content

    def test_has_pip_install_editable(self):
        """Development Setup must mention pip install -e with [test]."""
        content = self.path.read_text()
        assert "pip install -e" in content
        assert "[test]" in content

    def test_has_code_structure(self):
        """CONTRIBUTING must have Code Structure section."""
        content = self.path.read_text()
        assert "Code Structure" in content

    def test_has_pattern_b_files(self):
        """Code Structure must explain Pattern B (client.py/tools.py/__init__.py)."""
        content = self.path.read_text()
        assert "client.py" in content
        assert "tools.py" in content
        assert "__init__.py" in content

    def test_has_adding_new_tool(self):
        """CONTRIBUTING must have Adding a New Tool section."""
        content = self.path.read_text()
        assert "Adding a New Tool" in content or "Adding a new tool" in content

    def test_has_commit_conventions(self):
        """CONTRIBUTING must have Commit Conventions section."""
        content = self.path.read_text()
        assert "Commit Conventions" in content or "Commit conventions" in content

    def test_has_conventional_commits_types(self):
        """Commit Conventions must list the required types."""
        content = self.path.read_text()
        for commit_type in ["feat", "fix", "refactor", "test", "docs", "chore"]:
            assert commit_type in content, f"Missing commit type: {commit_type}"
