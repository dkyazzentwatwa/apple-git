from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from apple_git.config import (
    AppleGitSettings,
)


@pytest.fixture
def clean_env():
    """Fixture to clean environment variables before each test."""
    with patch.dict(os.environ, clear=True):
        yield


def test_default_settings(clean_env):
    """Test that default settings are loaded correctly when env is clean."""
    # We explicitly pass empty values to constructor to avoid any leaking BaseSettings logic
    settings = AppleGitSettings(
        github={"token": "", "repo": ""},
        anthropic_api_key="",
        connector_backend="claude"
    )
    assert settings.github.token == ""
    assert settings.reminders.list_inactive == "dev-backlog"
    assert settings.reminders.list_issue_plan == "issue-plan"
    assert settings.poll_interval_seconds == 15.0
    assert settings.connector_backend == "claude"


def test_settings_from_env_vars(clean_env):
    """Test that settings are loaded correctly from environment variables."""
    os.environ["APPLE_GIT_POLL_INTERVAL_SECONDS"] = "10.0"
    os.environ["APPLE_GIT_CONNECTOR_BACKEND"] = "codex"

    settings = AppleGitSettings()
    assert settings.poll_interval_seconds == 10.0
    assert settings.connector_backend == "codex"


def test_settings_from_yaml_file(tmp_path, clean_env):
    """Test that settings are loaded correctly from a YAML file."""
    config_data = {
        "github": {
            "token": "yaml_token",
            "repo": "yaml_owner/yaml_repo",
            "base_branch": "develop",
        },
        "poll_interval_seconds": 5.0,
        "db_path": "test_db.sqlite",
        "repo_path": "~/test_repo",
        "connector_logs_dir": "connector-runs",
        "reminders": {"list_issue_plan": "triage-plan"},
        "anthropic_api_key": "yaml_anthropic_key",
        "enable_pr_review": False,
        "connector_backend": "kilo",
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    settings = AppleGitSettings.load_from_yaml(config_file)

    assert settings.github.token == "yaml_token"
    assert settings.github.base_branch == "develop"
    assert settings.reminders.list_issue_plan == "triage-plan"
    assert settings.poll_interval_seconds == 5.0
    assert settings.db_path == Path.home() / ".apple-git" / "test_db.sqlite"
    assert settings.connector_logs_dir == Path.home() / ".apple-git" / "connector-runs"
    assert settings.repo_path == Path.home() / "test_repo"
    assert settings.anthropic_api_key == "yaml_anthropic_key"
    assert settings.enable_pr_review is False
    assert settings.connector_backend == "kilo"


def test_env_vars_override_yaml(tmp_path, clean_env):
    """Test that environment variables override settings from a YAML file."""
    config_data = {
        "poll_interval_seconds": 5.0,
    }
    config_file = tmp_path / "config.yaml"
    with open(config_file, "w") as f:
        yaml.dump(config_data, f)

    # load_from_yaml uses os.environ.get("GITHUB_TOKEN") explicitly
    os.environ["GITHUB_TOKEN"] = "env_token"
    
    # load_from_yaml calls cls(...) which picks up prefixed env vars
    os.environ["APPLE_GIT_POLL_INTERVAL_SECONDS"] = "10.0"

    settings = AppleGitSettings.load_from_yaml(config_file)

    assert settings.github.token == "env_token"
    # APPLE_GIT_POLL_INTERVAL_SECONDS env var should override the YAML value
    assert settings.poll_interval_seconds == 10.0


def test_path_resolution():
    """Test that path settings are resolved correctly via validator."""
    settings = AppleGitSettings(
        db_path=Path("my_db.sqlite"),
        log_file=Path("/tmp/absolute.log")
    )

    assert settings.db_path == Path.home() / ".apple-git" / "my_db.sqlite"
    assert settings.log_file == Path("/tmp/absolute.log")


def test_connector_logs_dir_resolution():
    """Test that connector log directory is resolved like other app paths."""
    settings = AppleGitSettings(
        connector_logs_dir=Path("connector-runs"),
    )

    assert settings.connector_logs_dir == Path.home() / ".apple-git" / "connector-runs"
