#!/usr/bin/env python3
"""Debug script to test the full process."""

import logging
from src.apple_git.config import get_settings
from src.apple_git import store, reminders, github

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test")

# Load settings
settings = get_settings()

# Check GitHub client
print(f"🔐 GitHub Token: {'SET' if settings.github.token else 'NOT SET'}")
print(f"📦 Repo: {settings.github.repo}")
print()

# Test GitHub client
if settings.github.token and settings.github.repo:
    gh = github.GitHubClient(settings.github.token, settings.github.repo)
    print("✅ GitHub client initialized")
    print(f"   Repo accessible: {gh.repo is not None}")
else:
    print("❌ GitHub client not configured (missing token or repo)")
print()

# Check SQLite store
print(f"🗄️  Database: {settings.db_path}")
db_store = store.SQLiteStore(settings.db_path)
db_store.bootstrap()
print("✅ Database initialized")
print()

# Test fetching reminders and check mapping
client = reminders.RemindersClient(settings.reminders.list_issue_ready)
reminders_list = client.fetch_all()

print(f"📋 Reminders in dev-issue-ready: {len(reminders_list)}")
for rem in reminders_list:
    print(f"\n   Reminder: {rem.name}")
    print(f"   ID: {rem.id}")

    # Check if it's mapped
    mapping = db_store.get_mapping_by_reminder_id(rem.id)
    if mapping:
        print(f"   ⚠️  Already mapped: Issue #{mapping.get('github_issue_number')}")
    else:
        print("   ✅ Not mapped - would create issue")
        print(f"   Body preview: {rem.body[:100]}...")
