from __future__ import annotations

import logging
import subprocess
from datetime import datetime

logger = logging.getLogger("apple_git.notes")


class NotesClient:
    def __init__(self, folder_name: str = "apple-git-logs"):
        self.folder_name = folder_name

    def create_note(self, title: str, body: str) -> bool:
        def _esc(text: str) -> str:
            return (
                text.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "")
            )

        ef = _esc(self.folder_name)
        et = _esc(title)
        eb = _esc(body)

        script = f'''
        tell application "Notes"
            try
                if not (exists folder "{ef}") then
                    set targetFolder to make new folder with properties {{name:"{ef}"}}
                else
                    set targetFolder to folder "{ef}"
                end if
                make new note at targetFolder with properties {{name:"{et}", body:"{eb}"}}
                return "ok"
            on error errMsg
                return "error: " & errMsg
            end try
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode != 0 or "error" in result.stdout.lower():
                logger.warning("Failed to create note: %s", result.stderr)
                return False
            logger.info("Created note: %s", title[:50])
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Timed out creating note")
            return False
        except FileNotFoundError:
            logger.error("osascript not found - requires macOS")
            return False
        except Exception as exc:
            logger.warning("Error creating note: %s", exc)
            return False

    def log_event(self, event_type: str, details: dict) -> bool:
        if not self.folder_name:
            return False

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"[{event_type}] {now_str}"

        lines = [f"**Event:** {event_type}", f"**Time:** {now_str}", ""]
        for key, value in details.items():
            lines.append(f"**{key}:** {value}")

        body = "\n".join(lines)
        return self.create_note(title, body)
