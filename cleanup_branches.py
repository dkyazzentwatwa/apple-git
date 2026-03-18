#!/usr/bin/env python3
"""One-time cleanup: delete all issue-* branches from GitHub."""
from src.apple_git.config import get_settings
from src.apple_git.github import GitHubClient

settings = get_settings()
client = GitHubClient(settings.github.token, settings.github.repo)

count = client.delete_branches_matching("issue-*")
print(f"✅ Deleted {count} branches matching issue-*")
