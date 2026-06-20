"""dependency_manager.py - Professional dependency lifecycle for lab projects.

Supports: pip, apt, npm, platformio (pio lib), arduino-cli.
Provides: ecosystem detection, snapshot/rollback, balanced update policy.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DepSnapshot:
    ecosystem: str
    timestamp: str
    packages: dict[str, str]     # name -> version


@dataclass
class DepResult:
    ok: bool
    ecosystem: str
    action: str
    message: str
    packages_affected: list[str] = field(default_factory=list)
    rollback_available: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], *, timeout: int = 90, cwd: str | None = None) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def _which(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


# ---------------------------------------------------------------------------
# Core manager
# ---------------------------------------------------------------------------

class DependencyManager:
    """Detect ecosystem, snapshot, install/update with balanced policy, rollback."""

    SNAPSHOT_FILE = ".willy_dep_snapshot.json"

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir)

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def detect_ecosystem(self, project_path: str | None = None) -> list[str]:
        """Return list of detected ecosystems for a project path."""
        ecosystems: list[str] = []
        proj = Path(project_path) if project_path else None

        if proj and (proj / "platformio.ini").exists() and _which("pio"):
            ecosystems.append("platformio")
        if proj and (proj / "package.json").exists() and _which("npm"):
            ecosystems.append("npm")
        if (
            proj and (
                (proj / "requirements.txt").exists()
                or (proj / "pyproject.toml").exists()
                or (proj / "setup.py").exists()
            )
        ) and _which("pip3"):
            ecosystems.append("pip")
        if _which("apt"):
            ecosystems.append("apt")
        if _which("arduino-cli"):
            ecosystems.append("arduino-cli")
        return ecosystems

    def snapshot(self, ecosystem: str, project_path: str | None = None) -> DepSnapshot | None:
        """Capture current installed versions for an ecosystem."""
        packages: dict[str, str] = {}
        rc, out, _ = -1, "", ""

        if ecosystem == "pip":
            rc, out, _ = _run(["pip3", "list", "--format=json"], timeout=20)
            if rc == 0:
                try:
                    for item in json.loads(out):
                        packages[item["name"]] = item["version"]
                except Exception:
                    pass
        elif ecosystem == "apt":
            rc, out, _ = _run(["dpkg-query", "-W", "-f=${Package}=${Version}\n"], timeout=30)
            if rc == 0:
                for line in out.splitlines():
                    if "=" in line:
                        name, _, ver = line.partition("=")
                        packages[name.strip()] = ver.strip()
        elif ecosystem == "npm" and project_path:
            rc, out, _ = _run(["npm", "list", "--json", "--depth=0"], cwd=project_path, timeout=30)
            if rc == 0:
                try:
                    data = json.loads(out)
                    for name, info in (data.get("dependencies") or {}).items():
                        packages[name] = (info or {}).get("version", "?")
                except Exception:
                    pass
        elif ecosystem == "platformio" and project_path:
            rc, out, _ = _run(["pio", "lib", "list", "--json-output"], cwd=project_path, timeout=30)
            if rc == 0:
                try:
                    for lib in json.loads(out):
                        packages[lib.get("name", "?")] = lib.get("version", "?")
                except Exception:
                    pass

        if not packages:
            return None

        snap = DepSnapshot(
            ecosystem=ecosystem,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            packages=packages,
        )
        self._persist_snapshot(snap, project_path)
        return snap

    def install(
        self,
        ecosystem: str,
        packages: list[str],
        *,
        project_path: str | None = None,
        use_sudo: bool = False,
    ) -> DepResult:
        """Install packages. use_sudo only allowed when called from a confirmed plan."""
        if not packages:
            return DepResult(ok=False, ecosystem=ecosystem, action="install", message="No packages specified.")

        # Snapshot before install so rollback is available.
        self.snapshot(ecosystem, project_path)

        cmd: list[str] = []
        if ecosystem == "pip":
            cmd = ["pip3", "install"] + packages
        elif ecosystem == "apt":
            prefix = ["sudo"] if use_sudo else []
            cmd = prefix + ["apt-get", "install", "-y"] + packages
        elif ecosystem == "npm" and project_path:
            cmd = ["npm", "install"] + packages
        elif ecosystem == "platformio" and project_path:
            cmd = ["pio", "lib", "install"] + packages
        elif ecosystem == "arduino-cli":
            cmd = ["arduino-cli", "lib", "install"] + packages
        else:
            return DepResult(ok=False, ecosystem=ecosystem, action="install",
                             message=f"Unsupported ecosystem '{ecosystem}' or missing project_path.")

        rc, out, err = _run(cmd, timeout=120, cwd=project_path)
        ok = rc == 0
        msg = out or err or ("OK" if ok else "Failed")
        return DepResult(
            ok=ok,
            ecosystem=ecosystem,
            action="install",
            message=msg[:1200],
            packages_affected=packages,
            rollback_available=True,
        )

    def update(
        self,
        ecosystem: str,
        packages: list[str] | None = None,
        *,
        project_path: str | None = None,
        use_sudo: bool = False,
        policy: str = "balanced",   # "balanced" = patch+minor only; "major" = all
    ) -> DepResult:
        """Update packages following the configured policy. Snapshot first."""
        # Always snapshot before update so rollback is available.
        self.snapshot(ecosystem, project_path)

        cmd: list[str] = []
        if ecosystem == "pip":
            # Balanced: update listed packages or outdated patch/minor only.
            targets = packages or self._pip_outdated_balanced()
            if not targets:
                return DepResult(ok=True, ecosystem=ecosystem, action="update",
                                 message="All pip packages are up to date (balanced policy).",
                                 rollback_available=True)
            cmd = ["pip3", "install", "--upgrade"] + targets
        elif ecosystem == "apt":
            prefix = ["sudo"] if use_sudo else []
            if policy == "balanced":
                cmd = prefix + ["apt-get", "upgrade", "-y", "--only-upgrade"]
            else:
                cmd = prefix + ["apt-get", "dist-upgrade", "-y"]
        elif ecosystem == "npm" and project_path:
            if packages:
                cmd = ["npm", "update"] + packages
            else:
                cmd = ["npm", "update"]
        elif ecosystem == "platformio" and project_path:
            cmd = ["pio", "lib", "update"]
        elif ecosystem == "arduino-cli":
            cmd = ["arduino-cli", "lib", "upgrade"]
        else:
            return DepResult(ok=False, ecosystem=ecosystem, action="update",
                             message=f"Unsupported ecosystem '{ecosystem}'.")

        rc, out, err = _run(cmd, timeout=180, cwd=project_path)
        ok = rc == 0
        msg = out or err or ("OK" if ok else "Failed")
        return DepResult(
            ok=ok,
            ecosystem=ecosystem,
            action="update",
            message=msg[:1200],
            packages_affected=packages or [],
            rollback_available=True,
        )

    def rollback(self, ecosystem: str, project_path: str | None = None) -> DepResult:
        """Restore the last snapshot using pip freeze / apt / npm."""
        snap = self._load_last_snapshot(ecosystem, project_path)
        if snap is None:
            return DepResult(ok=False, ecosystem=ecosystem, action="rollback",
                             message="No snapshot available for rollback.")

        if ecosystem == "pip":
            pkgs = [f"{name}=={ver}" for name, ver in snap.packages.items()]
            if not pkgs:
                return DepResult(ok=False, ecosystem=ecosystem, action="rollback",
                                 message="Snapshot is empty.")
            rc, out, err = _run(["pip3", "install"] + pkgs, timeout=180)
            ok = rc == 0
            return DepResult(ok=ok, ecosystem=ecosystem, action="rollback",
                             message=(out or err or "OK")[:1200],
                             packages_affected=list(snap.packages.keys()))

        return DepResult(ok=False, ecosystem=ecosystem, action="rollback",
                         message=f"Rollback not yet implemented for '{ecosystem}'.")

    def summary(self, ecosystem: str, project_path: str | None = None) -> str:
        """Return a short human-readable summary of the last snapshot."""
        snap = self._load_last_snapshot(ecosystem, project_path)
        if snap is None:
            return f"No snapshot for {ecosystem}."
        count = len(snap.packages)
        ts = snap.timestamp
        return f"{ecosystem}: {count} packages snapshotted at {ts}."

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _pip_outdated_balanced(self) -> list[str]:
        """Return pip packages that have patch/minor updates (skip majors)."""
        rc, out, _ = _run(["pip3", "list", "--outdated", "--format=json"], timeout=30)
        if rc != 0:
            return []
        try:
            outdated = json.loads(out)
        except Exception:
            return []

        targets: list[str] = []
        for item in outdated:
            cur = str(item.get("version", "0")).split(".")
            lat = str(item.get("latest_version", "0")).split(".")
            # Skip major version bumps.
            if cur and lat and cur[0] != lat[0]:
                continue
            targets.append(item["name"])
        return targets

    def _snapshot_path(self, project_path: str | None) -> Path:
        base = Path(project_path) if project_path else self.base_dir
        return base / self.SNAPSHOT_FILE

    def _persist_snapshot(self, snap: DepSnapshot, project_path: str | None) -> None:
        path = self._snapshot_path(project_path)
        try:
            existing: list[Any] = []
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
            # Keep only last 3 per ecosystem.
            existing = [e for e in existing if e.get("ecosystem") != snap.ecosystem][-2:]
            existing.append({
                "ecosystem": snap.ecosystem,
                "timestamp": snap.timestamp,
                "packages": snap.packages,
            })
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_last_snapshot(self, ecosystem: str, project_path: str | None) -> DepSnapshot | None:
        path = self._snapshot_path(project_path)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for entry in reversed(data):
                if entry.get("ecosystem") == ecosystem:
                    return DepSnapshot(
                        ecosystem=ecosystem,
                        timestamp=entry.get("timestamp", ""),
                        packages=entry.get("packages", {}),
                    )
        except Exception:
            pass
        return None
