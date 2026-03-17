from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("apple_git.config")

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class GitHubSettings(BaseSettings):
    token: str = ""
    repo: str = ""


class RemindersSettings(BaseSettings):
    list_inactive: str = "dev-backlog"
    list_started: str = "dev-started"
    list_issue_ready: str = "dev-issue-ready"
    list_review: str = "dev-review"
    list_done: str = "dev-done"


class NotesSettings(BaseSettings):
    folder_name: str = "apple-git-logs"
    log_enabled: bool = True


class AppleGitSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="apple_git_",
        extra="ignore",
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        enable_decoding=False,
    )

    github: GitHubSettings = Field(default_factory=GitHubSettings)
    reminders: RemindersSettings = Field(default_factory=RemindersSettings)
    notes: NotesSettings = Field(default_factory=NotesSettings)

    poll_interval_seconds: float = 5.0

    db_path: Path = Path.home() / ".apple-git" / "apple_git.sqlite"
    log_file: Path = Path.home() / ".apple-git" / "apple-git.log"

    @field_validator("db_path", "log_file", mode="after")
    @classmethod
    def _resolve_path(cls, v: Path) -> Path:
        if v.is_absolute():
            return v
        return Path.home() / ".apple-git" / v

    @classmethod
    def load_from_yaml(cls, config_path: Path) -> "AppleGitSettings":
        if not config_path.exists():
            logger.warning("Config file not found: %s", config_path)
            return cls()

        with open(config_path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        github_data = data.get("github", {})
        reminders_data = data.get("reminders", {})
        notes_data = data.get("notes", {})

        env_token = os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            github_data["token"] = env_token

        return cls(
            github=GitHubSettings(**github_data),
            reminders=RemindersSettings(**reminders_data),
            notes=NotesSettings(**notes_data),
            poll_interval_seconds=data.get("poll_interval_seconds", 5.0),
            db_path=Path(data.get("db_path", "~/.apple-git/apple_git.sqlite")).expanduser(),
            log_file=Path(data.get("log_file", "~/.apple-git/apple-git.log")).expanduser(),
        )


_default_settings: AppleGitSettings | None = None


def get_settings(config_path: Path | None = None) -> AppleGitSettings:
    global _default_settings
    if _default_settings is None:
        if config_path is None:
            config_path = Path(__file__).resolve().parents[2] / "config" / "config.yaml"
        _default_settings = AppleGitSettings.load_from_yaml(config_path)
    return _default_settings
