"""
session_logger.py — Persists chat messages and terminal commands to a JSON session file.
Each run of the app creates a new file under sessions/YYYY-MM-DD_HH-MM-SS.json
"""

import json
import os
import threading
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")


class SessionLogger:
    def __init__(self) -> None:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._path = os.path.join(SESSIONS_DIR, f"{ts}.json")
        self._lock = threading.Lock()
        self._data: dict = {
            "started_at": datetime.now().isoformat(),
            "events": [],
        }
        self._flush()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_message(self, role: str, text: str) -> None:
        """Log a chat message (user, assistant, system, error)."""
        self._append({"type": "message", "role": role, "text": text})

    def log_command(self, command: str, output: str) -> None:
        """Log a terminal command and its full output."""
        self._append({"type": "command", "command": command, "output": output})

    @property
    def path(self) -> str:
        return self._path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, event: dict) -> None:
        event["timestamp"] = datetime.now().isoformat()
        with self._lock:
            self._data["events"].append(event)
            self._flush_locked()

    def _flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass
