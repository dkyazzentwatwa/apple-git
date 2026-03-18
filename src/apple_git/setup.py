from __future__ import annotations

import logging
import subprocess
import time


from .config import AppleGitSettings, get_settings

logger = logging.getLogger("apple_git.setup")


def _run_applescript(script: str) -> str:
    """Executes an AppleScript command and returns its stdout."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error("AppleScript failed: %s", e.stderr)
        raise


def create_reminders_list(list_name: str) -> bool:
    """Creates a new Reminders list if it doesn't already exist."""
    safe_name = list_name.replace("\\", "\\\\").replace('"', '\\"')
    script = f"""
    tell application "Reminders"
        if not (exists list "{safe_name}") then
            make new list with properties {{name:"{safe_name}"}}
            return "true"
        else
            return "false"
        end if
    end tell
    """
    try:
        result = _run_applescript(script)
        if result == "true":
            logger.info("Created Reminders list: %s", list_name)
            return True
        else:
            logger.info("Reminders list '%s' already exists.", list_name)
            return False
    except Exception:
        logger.error("Could not create Reminders list '%s'. Please check Reminders app permissions.", list_name)
        return False


def setup_reminders_lists(settings: AppleGitSettings) -> None:
    """Creates all required Reminders lists for apple-git."""
    logger.info("Setting up Apple Reminders lists...")
    lists_to_create = [
        settings.reminders.list_inactive,
        settings.reminders.list_issue_plan,
        settings.reminders.list_issue_ready,
        settings.reminders.list_review,
        settings.reminders.list_done,
    ]

    for list_name in lists_to_create:
        create_reminders_list(list_name)
        time.sleep(0.5)  # Give Reminders app a moment


def setup_cli():
    """Main function for the setup CLI."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    settings = get_settings() # Load settings to get list names

    setup_reminders_lists(settings)
    logger.info("Reminders lists setup complete. You can now start the apple-git daemon.")
    logger.info("Run: python3 -m apple_git")


if __name__ == "__main__":
    setup_cli()
