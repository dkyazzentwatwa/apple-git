#!/usr/bin/env python3
"""Debug script to test reminder fetching."""

from src.apple_git.reminders import RemindersClient
from src.apple_git.config import get_settings

# Load settings
settings = get_settings()
print("📋 Loaded settings:")
print(f"  list_issue_ready: {settings.reminders.list_issue_ready}")
print()

# Test each list
lists_to_test = [
    ("issue-ready", settings.reminders.list_issue_ready),
    ("review", settings.reminders.list_review),
    ("done", settings.reminders.list_done),
]

for label, list_name in lists_to_test:
    print(f"🔍 Testing '{list_name}' ({label})...")
    client = RemindersClient(list_name)
    reminders = client.fetch_all()

    if reminders:
        print(f"  ✅ Found {len(reminders)} reminders:")
        for rem in reminders:
            print(f"     • {rem.name}")
            if rem.body:
                print(f"       Body: {rem.body[:50]}...")
    else:
        print("  ❌ No reminders found (or list not accessible)")
    print()
