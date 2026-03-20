from __future__ import annotations

import logging
import subprocess
from typing import Any

logger = logging.getLogger("apple_git.apple_tools")


def reminders_resolve_list_selector(selector: str) -> dict[str, Any] | None:
    if not selector:
        return None

    escaped_selector = selector.replace('"', '\\"')
    script = f'''
    tell application "Reminders"
        try
            set targetList to first list whose name is "{escaped_selector}"
            return id of targetList & "|" & name of targetList & "|" & "" & "|accessibility"
        on error
            try
                set allLists to every list
                repeat with lst in allLists
                    if name of lst contains "{escaped_selector}" then
                        return id of lst & "|" & name of lst & "|" & name of lst & "|accessibility"
                    end if
                end repeat
            end try
        end try
        return ""
    end tell
    '''

    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        output = result.stdout.strip()
        if not output:
            return None

        parts = output.split("|")
        if len(parts) >= 3:
            return {
                "id": parts[0],
                "name": parts[1],
                "path": parts[2],
                "source": parts[3] if len(parts) > 3 else "accessibility",
            }
    except Exception as exc:
        logger.warning("Error resolving reminders list: %s", exc)
        return None

    return None


def reminders_list(
    list_name: str,
    filter: str = "all",
    limit: int = 50,
    as_text: bool = True,
) -> Any:
    return []
