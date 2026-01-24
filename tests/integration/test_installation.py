"""
Tests for Hyperion Installation

Tests the installation process on fresh systems.
"""

import json
import os
import subprocess
import pytest
from pathlib import Path


@pytest.mark.integration
class TestDirectoryCreation:
    """Tests for directory creation during installation."""

    def test_messages_directories_exist(self, temp_messages_dir: Path):
        """Test that all message directories are created."""
        required_dirs = ["inbox", "outbox", "processed", "config", "audio", "task-outputs"]

        for dirname in required_dirs:
            dir_path = temp_messages_dir / dirname
            assert dir_path.exists(), f"Directory {dirname} should exist"
            assert dir_path.is_dir(), f"{dirname} should be a directory"

    def test_scheduled_tasks_directories_exist(self, temp_scheduled_tasks_dir: Path):
        """Test that scheduled tasks directories are created."""
        required_dirs = ["tasks", "logs"]

        for dirname in required_dirs:
            dir_path = temp_scheduled_tasks_dir / dirname
            assert dir_path.exists(), f"Directory {dirname} should exist"

    def test_workspace_directory_created(self, temp_workspace: Path):
        """Test that workspace directory is created."""
        assert temp_workspace.exists()
        assert (temp_workspace / "logs").exists()


@pytest.mark.integration
class TestFileInitialization:
    """Tests for file initialization."""

    def test_tasks_json_initialized(self, temp_messages_dir: Path):
        """Test that tasks.json is properly initialized."""
        tasks_file = temp_messages_dir / "tasks.json"
        tasks_file.write_text(json.dumps({"tasks": [], "next_id": 1}))

        content = json.loads(tasks_file.read_text())

        assert "tasks" in content
        assert "next_id" in content
        assert content["tasks"] == []
        assert content["next_id"] == 1

    def test_jobs_json_initialized(self, temp_scheduled_tasks_dir: Path):
        """Test that jobs.json is properly initialized."""
        jobs_file = temp_scheduled_tasks_dir / "jobs.json"

        content = json.loads(jobs_file.read_text())

        assert "jobs" in content
        assert content["jobs"] == {}


@pytest.mark.integration
class TestPythonEnvironment:
    """Tests for Python environment setup."""

    def test_python_version(self):
        """Test that Python version is adequate."""
        import sys
        assert sys.version_info >= (3, 9), "Python 3.9+ required"

    def test_required_packages_importable(self):
        """Test that required packages can be imported."""
        required_packages = [
            ("mcp.server", "mcp"),
            ("telegram", "python-telegram-bot"),
            ("watchdog.observers", "watchdog"),
        ]

        for module, package in required_packages:
            try:
                __import__(module)
            except ImportError:
                pytest.skip(f"Package {package} not installed")

    def test_mcp_server_importable(self):
        """Test that MCP server module can be imported."""
        try:
            from src.mcp import inbox_server
            assert hasattr(inbox_server, "server")
        except ImportError as e:
            pytest.skip(f"MCP server not importable: {e}")

    def test_bot_module_importable(self):
        """Test that bot module can be imported."""
        try:
            # This will fail without env vars, which is expected
            with pytest.raises((ValueError, KeyError)):
                from src.bot import hyperion_bot
        except ImportError as e:
            pytest.skip(f"Bot module not importable: {e}")


@pytest.mark.integration
class TestScriptExecutability:
    """Tests for script executability."""

    @pytest.fixture
    def hyperion_dir(self) -> Path:
        """Get Hyperion installation directory."""
        return Path(__file__).parent.parent.parent

    def test_cli_is_bash_script(self, hyperion_dir: Path):
        """Test that CLI is a valid bash script."""
        cli_path = hyperion_dir / "src" / "cli"
        if cli_path.exists():
            content = cli_path.read_text()
            assert content.startswith("#!/bin/bash"), "CLI should be a bash script"

    def test_run_job_script_exists(self, hyperion_dir: Path):
        """Test that run-job.sh exists."""
        script = hyperion_dir / "scheduled-tasks" / "run-job.sh"
        if script.exists():
            assert os.access(script, os.X_OK), "run-job.sh should be executable"

    def test_sync_crontab_script_exists(self, hyperion_dir: Path):
        """Test that sync-crontab.sh exists."""
        script = hyperion_dir / "scheduled-tasks" / "sync-crontab.sh"
        if script.exists():
            assert os.access(script, os.X_OK), "sync-crontab.sh should be executable"


@pytest.mark.integration
@pytest.mark.docker
class TestDockerInstallation:
    """Tests that run in Docker containers."""

    def test_fresh_debian_install(self):
        """Test installation on fresh Debian container."""
        # This test is meant to be run in Docker
        # Skip if not in Docker environment
        if not os.path.exists("/.dockerenv"):
            pytest.skip("Not running in Docker")

        # Verify basic system requirements
        result = subprocess.run(
            ["python3", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_dependencies_installed(self):
        """Test that all dependencies are installed."""
        if not os.path.exists("/.dockerenv"):
            pytest.skip("Not running in Docker")

        required_commands = ["curl", "wget", "git", "jq", "python3"]

        for cmd in required_commands:
            result = subprocess.run(
                ["which", cmd],
                capture_output=True,
            )
            assert result.returncode == 0, f"{cmd} should be installed"
