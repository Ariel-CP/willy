"""
environment_memory.py - Persist and summarize local technical context.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


class EnvironmentMemory:
    def __init__(
        self,
        base_dir: str,
        *,
        file_name: str = "environment_memory.json",
        history_dir_name: str = "environment_memory_history",
    ) -> None:
        self.base_dir = Path(base_dir)
        self.path = self.base_dir / file_name
        self.history_dir = self.base_dir / history_dir_name
        self._data: dict[str, Any] = {
            "version": 1,
            "last_updated": "",
            "snapshot": {},
            "history": [],
        }
        self._lock = threading.Lock()
        self._load()

    def refresh(
        self,
        *,
        preferences: dict[str, Any] | None = None,
        microcontrollers: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        snapshot = self._collect_snapshot(
            preferences=preferences or {},
            microcontrollers=microcontrollers or [],
        )
        changed = snapshot != self._data.get("snapshot", {})
        if changed:
            now = datetime.now().isoformat(timespec="seconds")
            previous = self._data.get("snapshot", {})
            self._data["snapshot"] = snapshot
            self._data["last_updated"] = now
            self._data.setdefault("history", []).append(
                {
                    "timestamp": now,
                    "event": "snapshot_updated",
                    "previous": previous,
                    "current": snapshot,
                }
            )
            self._data["history"] = self._data["history"][-50:]
            self._write_history_snapshot(now, snapshot)
            self._flush()
        return snapshot, changed

    def get_snapshot(self) -> dict[str, Any]:
        return dict(self._data.get("snapshot", {}))

    def summary_for_prompt(self, max_chars: int = 2400) -> str:
        snap = self.get_snapshot()
        if not snap:
            return ""

        sys_info = snap.get("system", {})
        net = snap.get("network", {})
        tools = snap.get("tools", {})
        emb = snap.get("embedded", {})
        pref = snap.get("preferences", {})

        tool_names = [k for k, v in tools.items() if isinstance(v, dict) and v.get("available")]
        mcu_list = emb.get("microcontrollers", [])
        mcu_desc = ", ".join(
            f"{d.get('board', 'unknown')}@{d.get('port', '?')}" for d in mcu_list[:5]
        ) or "none"

        lines = [
            "ENVIRONMENT_CONTEXT",
            f"host={sys_info.get('hostname', 'unknown')} user={sys_info.get('username', 'unknown')}",
            f"os={sys_info.get('os', 'unknown')} {sys_info.get('release', '')} machine={sys_info.get('machine', '')}",
            f"python={sys_info.get('python_version', 'unknown')}",
            f"local_ips={', '.join(net.get('local_ips', [])[:4]) or 'none'}",
            f"raspberry_hosts={', '.join(net.get('raspberry_candidates', [])[:8]) or 'none'}",
            f"tools_available={', '.join(tool_names[:10]) or 'none'}",
            f"microcontrollers={mcu_desc}",
            f"preferences={json.dumps(pref, ensure_ascii=False)}",
        ]
        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[:max_chars] + "\n[...truncated context...]"
        return text

    def _collect_snapshot(
        self,
        *,
        preferences: dict[str, Any],
        microcontrollers: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "system": {
                "hostname": socket.gethostname(),
                "username": os.environ.get("USER") or os.environ.get("USERNAME") or "unknown",
                "os": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_version": platform.python_version(),
            },
            "network": {
                "local_ips": self._local_ips(),
                "raspberry_candidates": self._raspberry_candidates(),
            },
            "tools": self._tool_inventory(),
            "embedded": {
                "microcontrollers": microcontrollers,
            },
            "preferences": preferences,
        }

    def _local_ips(self) -> list[str]:
        values: set[str] = set()
        try:
            infos = socket.getaddrinfo(socket.gethostname(), None)
            for info in infos:
                addr = info[4][0]
                if ":" in addr or addr.startswith("127."):
                    continue
                values.add(addr)
        except Exception:
            return []
        return sorted(values)

    def _tool_inventory(self) -> dict[str, dict[str, Any]]:
        commands = {
            "python3": ["python3", "--version"],
            "git": ["git", "--version"],
            "ssh": ["ssh", "-V"],
            "pio": ["pio", "--version"],
            "arduino-cli": ["arduino-cli", "version"],
        }
        out: dict[str, dict[str, Any]] = {}
        for name, cmd in commands.items():
            path = shutil.which(cmd[0])
            if not path:
                out[name] = {"available": False}
                continue
            version = ""
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2, check=False)
                version = (proc.stdout or proc.stderr or "").strip().splitlines()[0] if (proc.stdout or proc.stderr) else ""
            except Exception:
                version = ""
            out[name] = {
                "available": True,
                "path": path,
                "version": version,
            }
        return out

    def _raspberry_candidates(self) -> list[str]:
        values: set[str] = set()

        # /etc/hosts entries are low-noise and local.
        etc_hosts = Path("/etc/hosts")
        if etc_hosts.exists():
            try:
                for raw in etc_hosts.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split()
                    for token in parts[1:]:
                        if self._looks_like_raspberry_name(token):
                            values.add(token)
            except Exception:
                pass

        # known_hosts may contain previously connected Raspberry hostnames.
        known_hosts = Path.home() / ".ssh" / "known_hosts"
        if known_hosts.exists():
            try:
                for raw in known_hosts.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or line.startswith("|"):
                        continue
                    host_field = line.split(" ", 1)[0]
                    for host in host_field.split(","):
                        clean = host.strip()
                        if clean.startswith("[") and "]:" in clean:
                            clean = clean[1:].split("]:", 1)[0]
                        if self._looks_like_raspberry_name(clean):
                            values.add(clean)
            except Exception:
                pass

        return sorted(values)

    def _looks_like_raspberry_name(self, token: str) -> bool:
        if not token:
            return False
        value = token.strip().lower()
        if value in {"raspberrypi", "raspberrypi.local", "rpi.local"}:
            return True
        return bool(re.search(r"(^|[._-])(raspberry|raspberrypi|rpi|pi)([._-]|$)", value))

    def _load(self) -> None:
        if not self.path.exists():
            return
        with self._lock:
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
                self._harden_permissions(self.path)
            except Exception:
                self._data = {
                    "version": 1,
                    "last_updated": "",
                    "snapshot": {},
                    "history": [],
                }

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.path)
        self._harden_permissions(self.path)

    def _write_history_snapshot(self, stamp: str, snapshot: dict[str, Any]) -> None:
        self.history_dir.mkdir(parents=True, exist_ok=True)
        fname = stamp.replace(":", "-") + ".json"
        history_file = self.history_dir / fname
        history_file.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._harden_permissions(history_file)

    def _harden_permissions(self, path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass