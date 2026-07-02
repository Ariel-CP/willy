"""
session_logger.py — Persists chat messages and terminal commands to a JSON session file.
Each run of the app creates a new file under sessions/YYYY-MM-DD_HH-MM-SS.json
"""

import json
import os
import re
import threading
import traceback
from datetime import datetime

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")
MAX_EVENTS = 3000
MAX_TEXT_FIELD_CHARS = 12000
SESSION_RETENTION_DAYS = 30
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(openai[_-]?api[_-]?key\s*[=:]\s*)([^\s\"']+)") ,
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)([^\s\"']+)"),
]


class SessionLogger:
    def __init__(self) -> None:
        os.makedirs(SESSIONS_DIR, exist_ok=True)
        self._prune_old_sessions()
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

    def export_audit_report(
        self,
        output_path: str,
        *,
        start_iso: str | None = None,
        end_iso: str | None = None,
    ) -> str:
        """Export an audit summary from session JSON files within a time window."""
        start_dt = self._parse_iso_timestamp(start_iso) if start_iso else None
        end_dt = self._parse_iso_timestamp(end_iso) if end_iso else None

        session_files = sorted(
            name
            for name in os.listdir(SESSIONS_DIR)
            if name.endswith(".json") and not name.endswith("_audit.json")
        )

        report_sessions: list[dict] = []
        totals = {
            "sessions": 0,
            "events": 0,
            "messages": 0,
            "commands": 0,
            "system_events": 0,
            "errors": 0,
        }

        for name in session_files:
            path = os.path.join(SESSIONS_DIR, name)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                continue

            events = payload.get("events", [])
            if not isinstance(events, list):
                continue

            filtered_events = []
            for event in events:
                if not isinstance(event, dict):
                    continue
                event_dt = self._parse_iso_timestamp(event.get("timestamp"))
                if start_dt and event_dt and event_dt < start_dt:
                    continue
                if end_dt and event_dt and event_dt > end_dt:
                    continue
                filtered_events.append(event)

            if not filtered_events:
                continue

            counts = {
                "events": len(filtered_events),
                "messages": 0,
                "commands": 0,
                "system_events": 0,
                "errors": 0,
            }

            for event in filtered_events:
                kind = event.get("type", "")
                if kind == "message":
                    counts["messages"] += 1
                elif kind == "command":
                    counts["commands"] += 1
                elif kind == "system_event":
                    counts["system_events"] += 1
                elif kind == "system_error":
                    counts["errors"] += 1

            report_sessions.append(
                {
                    "file": name,
                    "started_at": payload.get("started_at", ""),
                    "counts": counts,
                }
            )

            totals["sessions"] += 1
            totals["events"] += counts["events"]
            totals["messages"] += counts["messages"]
            totals["commands"] += counts["commands"]
            totals["system_events"] += counts["system_events"]
            totals["errors"] += counts["errors"]

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "range": {
                "start_iso": start_iso or "",
                "end_iso": end_iso or "",
            },
            "totals": totals,
            "sessions": report_sessions,
        }

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        return output_path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, event: dict) -> None:
        event["timestamp"] = datetime.now().isoformat()
        event = self._sanitize_event(event)
        with self._lock:
            self._data["events"].append(event)
            if len(self._data["events"]) > MAX_EVENTS:
                self._data["events"] = self._data["events"][-MAX_EVENTS:]
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
        safe_message = self._sanitize_text(message)
        if len(safe_message) > MAX_TEXT_FIELD_CHARS:
            safe_message = safe_message[:MAX_TEXT_FIELD_CHARS] + "...[truncated]"
        line = f"[{stamp}] {level} [{component}] {safe_message}\n"
        try:
            with open(self._diag_path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass

    def _sanitize_text(self, text: str) -> str:
        safe = text or ""
        for pattern in _SECRET_PATTERNS:
            if pattern.groups == 2:
                safe = pattern.sub(r"\1[REDACTED]", safe)
            else:
                safe = pattern.sub("[REDACTED]", safe)
        return safe

    def _parse_iso_timestamp(self, raw) -> datetime | None:
        value = str(raw or "").strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def _sanitize_event(self, value):
        if isinstance(value, str):
            safe = self._sanitize_text(value)
            if len(safe) > MAX_TEXT_FIELD_CHARS:
                safe = safe[:MAX_TEXT_FIELD_CHARS] + "...[truncated]"
            return safe
        if isinstance(value, dict):
            return {k: self._sanitize_event(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._sanitize_event(v) for v in value]
        return value

    def _prune_old_sessions(self) -> None:
        cutoff = datetime.now().timestamp() - (SESSION_RETENTION_DAYS * 24 * 60 * 60)
        try:
            for name in os.listdir(SESSIONS_DIR):
                if not (name.endswith(".json") or name.endswith(".log")):
                    continue
                path = os.path.join(SESSIONS_DIR, name)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.remove(path)
                except Exception:
                    continue
        except Exception:
            pass
