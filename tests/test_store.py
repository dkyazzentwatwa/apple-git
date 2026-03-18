from __future__ import annotations

import sqlite3

import pytest

from src.apple_git.store import SQLiteStore


@pytest.fixture
def temp_db_store(tmp_path):
    """Fixture for a SQLiteStore using a temporary file."""
    db_file = tmp_path / "test_apple_git.sqlite"
    store = SQLiteStore(db_path=db_file)
    store.bootstrap()
    yield store
    store.close()


def test_bootstrap_creates_table(temp_db_store):
    """Test that bootstrap creates the issue_mappings table."""
    conn = sqlite3.connect(temp_db_store.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='issue_mappings';")
    assert cursor.fetchone() is not None
    conn.close()


def test_upsert_and_get_mapping(temp_db_store):
    """Test upserting a new mapping and retrieving it."""
    reminder_id = "rem123"
    github_issue_number = 1
    section = "dev-issue-ready"
    reminder_title = "Test Reminder"

    temp_db_store.upsert_issue_mapping(
        reminder_id, github_issue_number, section, reminder_title
    )
    mapping = temp_db_store.get_mapping_by_reminder_id(reminder_id)

    assert mapping is not None
    assert mapping["reminder_id"] == reminder_id
    assert mapping["github_issue_number"] == github_issue_number
    assert mapping["section"] == section
    assert mapping["reminder_title"] == reminder_title
    assert mapping["github_pr_number"] is None


def test_update_pr_number(temp_db_store):
    """Test updating the PR number for an existing mapping."""
    reminder_id = "rem123"
    github_issue_number = 1
    section = "dev-issue-ready"
    reminder_title = "Test Reminder"
    pr_number = 101

    temp_db_store.upsert_issue_mapping(
        reminder_id, github_issue_number, section, reminder_title
    )
    temp_db_store.update_pr_number(reminder_id, pr_number)
    mapping = temp_db_store.get_mapping_by_reminder_id(reminder_id)

    assert mapping is not None
    assert mapping["github_pr_number"] == pr_number


def test_delete_mapping(temp_db_store):
    """Test deleting an existing mapping."""
    reminder_id = "rem123"
    github_issue_number = 1
    section = "dev-issue-ready"
    reminder_title = "Test Reminder"

    temp_db_store.upsert_issue_mapping(
        reminder_id, github_issue_number, section, reminder_title
    )
    temp_db_store.delete_mapping(reminder_id)
    mapping = temp_db_store.get_mapping_by_reminder_id(reminder_id)

    assert mapping is None


def test_get_non_existent_mapping(temp_db_store):
    """Test retrieving a mapping that does not exist."""
    mapping = temp_db_store.get_mapping_by_reminder_id("non_existent_id")
    assert mapping is None


def test_upsert_updates_existing_mapping(temp_db_store):
    """Test that upserting with an existing reminder_id updates the mapping."""
    reminder_id = "rem123"
    github_issue_number_old = 1
    section_old = "dev-issue-ready"
    reminder_title_old = "Old Title"

    temp_db_store.upsert_issue_mapping(
        reminder_id, github_issue_number_old, section_old, reminder_title_old
    )

    github_issue_number_new = 2
    section_new = "dev-review"
    reminder_title_new = "New Title"

    temp_db_store.upsert_issue_mapping(
        reminder_id, github_issue_number_new, section_new, reminder_title_new
    )
    mapping = temp_db_store.get_mapping_by_reminder_id(reminder_id)

    assert mapping is not None
    assert mapping["reminder_id"] == reminder_id
    assert mapping["github_issue_number"] == github_issue_number_new
    assert mapping["section"] == section_new
    assert mapping["reminder_title"] == reminder_title_new
