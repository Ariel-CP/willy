"""learned_memory.py - Dual local memory for lab-wide and per-project lessons."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class LearnedMemory:
    def __init__(
        self,
        base_dir: str,
        *,
        global_file_name: str = "willy_global_lab_memory.json",
        project_file_name: str = ".willy_project_memory.json",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.global_path = self.base_dir / global_file_name
        self.project_file_name = project_file_name
        self.taxonomy = {
            "control": ["pid", "control", "lazo", "setpoint", "stability", "anti-windup"],
            "sensado": ["sensor", "adc", "calibr", "noise", "filtr", "imu", "temperature"],
            "actuacion": ["motor", "driver", "pwm", "relay", "servo", "stepper", "actuator"],
            "comunicaciones": ["can", "modbus", "rs485", "uart", "i2c", "spi", "mqtt"],
            "vision": ["camera", "opencv", "vision", "inference", "latency"],
            "cad_cam": ["cad", "cam", "gerber", "bom", "manufactur", "pcb"],
            "integracion_hw_sw": ["integration", "firmware", "hardware", "software", "platformio"],
        }

    def summary_for_prompt(
        self,
        *,
        project_path: str | None,
        max_chars: int = 2200,
        project_limit: int = 4,
        global_limit: int = 4,
    ) -> str:
        project_entries = self._top_entries(self._load_project_data(project_path), limit=project_limit)
        global_entries = self._top_entries(self._load_global_data(), limit=global_limit)

        if not project_entries and not global_entries:
            return ""

        lines = ["LEARNED_CONTEXT"]
        if project_entries:
            lines.append("project_lessons:")
            for item in project_entries:
                lines.append(self._entry_line(item))

        if global_entries:
            lines.append("global_lab_lessons:")
            for item in global_entries:
                lines.append(self._entry_line(item))

        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[:max_chars] + "\n[...truncated learned context...]"
        return text

    def record_project_event(
        self,
        *,
        project_path: str,
        action: str,
        success: bool,
        summary: str,
        error: str = "",
    ) -> None:
        clean_summary = " ".join((summary or "").strip().split())[:240]
        if not clean_summary:
            clean_summary = f"{action} {'ok' if success else 'failed'}"

        domain = self._infer_domain(f"{action} {clean_summary} {error}")
        now = datetime.now().isoformat(timespec="seconds")

        data = self._load_project_data(project_path)
        entries = data.setdefault("entries", [])
        key = f"{action}|{clean_summary.lower()}"

        found = None
        for entry in entries:
            if entry.get("key") == key:
                found = entry
                break

        if found is None:
            found = {
                "key": key,
                "action": action,
                "summary": clean_summary,
                "domain": domain,
                "success_count": 0,
                "failure_count": 0,
                "last_error": "",
                "last_seen": now,
                "confidence": 0.0,
            }
            entries.append(found)

        if success:
            found["success_count"] = int(found.get("success_count", 0)) + 1
        else:
            found["failure_count"] = int(found.get("failure_count", 0)) + 1
            found["last_error"] = (error or "")[:220]

        found["last_seen"] = now
        found["confidence"] = self._confidence(found)

        data["updated_at"] = now
        self._save_project_data(project_path, data)

        # Promote stable project lessons to global lab memory.
        if found["success_count"] >= 3 and found["failure_count"] == 0:
            self._promote_to_global(found)

    def _entry_line(self, item: dict[str, Any]) -> str:
        status = f"ok={item.get('success_count', 0)} fail={item.get('failure_count', 0)}"
        domain = item.get("domain", "integracion_hw_sw")
        summary = item.get("summary", "")
        return f"- [{domain}] {summary} ({status})"

    def _confidence(self, item: dict[str, Any]) -> float:
        ok = float(item.get("success_count", 0))
        fail = float(item.get("failure_count", 0))
        total = ok + fail
        if total <= 0:
            return 0.0
        return round(ok / total, 3)

    def _top_entries(self, data: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
        entries = [e for e in data.get("entries", []) if isinstance(e, dict)]
        entries.sort(
            key=lambda e: (
                float(e.get("confidence", 0.0)),
                int(e.get("success_count", 0)) - int(e.get("failure_count", 0)),
                e.get("last_seen", ""),
            ),
            reverse=True,
        )
        return entries[: max(0, limit)]

    def _infer_domain(self, text: str) -> str:
        lowered = (text or "").lower()
        best_domain = "integracion_hw_sw"
        best_score = 0
        for domain, tokens in self.taxonomy.items():
            score = sum(1 for token in tokens if token in lowered)
            if score > best_score:
                best_score = score
                best_domain = domain
        return best_domain

    def _promote_to_global(self, entry: dict[str, Any]) -> None:
        data = self._load_global_data()
        entries = data.setdefault("entries", [])
        key = entry.get("key")
        if not key:
            return

        now = datetime.now().isoformat(timespec="seconds")
        found = None
        for item in entries:
            if item.get("key") == key:
                found = item
                break

        if found is None:
            found = {
                "key": key,
                "action": entry.get("action", ""),
                "summary": entry.get("summary", ""),
                "domain": entry.get("domain", "integracion_hw_sw"),
                "success_count": 0,
                "failure_count": 0,
                "last_seen": now,
                "confidence": 0.0,
            }
            entries.append(found)

        found["success_count"] = max(int(found.get("success_count", 0)), int(entry.get("success_count", 0)))
        found["failure_count"] = int(found.get("failure_count", 0)) + int(entry.get("failure_count", 0))
        found["last_seen"] = now
        found["confidence"] = self._confidence(found)
        data["updated_at"] = now
        self._save_json(self.global_path, data)

    def _load_global_data(self) -> dict[str, Any]:
        return self._load_json(self.global_path)

    def _load_project_data(self, project_path: str | None) -> dict[str, Any]:
        return self._load_json(self._project_path(project_path))

    def _save_project_data(self, project_path: str | None, data: dict[str, Any]) -> None:
        self._save_json(self._project_path(project_path), data)

    def _project_path(self, project_path: str | None) -> Path:
        if project_path:
            return Path(project_path) / self.project_file_name
        return self.base_dir / self.project_file_name

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return self._default_data()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("updated_at", "")
                data.setdefault("entries", [])
                return data
        except Exception:
            pass
        return self._default_data()

    def _save_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    @staticmethod
    def _default_data() -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": "",
            "entries": [],
        }
