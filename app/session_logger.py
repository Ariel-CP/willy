"""
session_logger.py — Persists chat messages and terminal commands to a JSON session file.
Each run of the app creates a new file under sessions/YYYY-MM-DD_HH-MM-SS.json
"""

import json
import os
import threading
import traceback
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")


class SessionLogger:
    def __init__(self) -> None:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._path = os.path.join(SESSIONS_DIR, f"{ts}.json")
        self._diag_path = os.path.join(SESSIONS_DIR, f"{ts}_diagnostics.log")
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

    def log_event(
        self,
        event_type: str,
        *,
        level: str = "info",
        component: str = "app",
        data: dict | None = None,
    ) -> None:
        """Log a structured system event."""
        payload = {
            "type": "system_event",
            "event": event_type,
            "level": level,
            "component": component,
            "data": data or {},
        }
        self._append(payload)
        self._append_diag_line(level.upper(), component, f"{event_type} | {data or {}}")

    def log_error(
        self,
        component: str,
        message: str,
        *,
        exc: Exception | None = None,
        context: dict | None = None,
    ) -> None:
        """Log an error with optional traceback/context."""
        tb = ""
        if exc is not None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        payload = {
            "type": "system_error",
            "level": "error",
            "component": component,
            "message": message,
            "context": context or {},
            "traceback": tb,
        }
        self._append(payload)

        diag_message = message
        if context:
            diag_message += f" | context={context}"
        if tb:
            diag_message += f"\n{tb.strip()}"
        self._append_diag_line("ERROR", component, diag_message)

    @property
    def path(self) -> str:
        return self._path

    @property
    def diagnostics_path(self) -> str:
        return self._diag_path

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

    def _append_diag_line(self, level: str, component: str, message: str) -> None:
        stamp = datetime.now().isoformat(timespec="seconds")
        line = f"[{stamp}] {level} [{component}] {message}\n"
        try:
            with open(self._diag_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass
