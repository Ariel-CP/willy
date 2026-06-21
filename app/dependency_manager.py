"""dependency_manager.py - Professional dependency lifecycle for lab projects.

Supports: pip, apt, npm, platformio (pio lib), arduino-cli.
Provides: ecosystem detection, snapshot/rollback, balanced update policy.
"""

from __future__ import annotations

import configparser
import json
import os
import re
import subprocess
import threading
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
    _snapshot_lock = threading.Lock()  # protege lectura+escritura atómica del archivo

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
        if _which("arduino-cli") and proj and any(proj.glob("*.ino")):
            # Proyecto Arduino IDE nativo (contiene .ino) — prioridad
            ecosystems.insert(0, "arduino-cli")
        elif _which("arduino-cli"):
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
            packages = self._pio_read_lib_deps(Path(project_path) / "platformio.ini")

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
            ini_path = Path(project_path) / "platformio.ini"
            if not ini_path.exists():
                return DepResult(ok=False, ecosystem=ecosystem, action="install",
                                 message="platformio.ini not found in project path.")
            ok_add, msg_add = self._pio_append_lib_deps(ini_path, packages)
            if not ok_add:
                return DepResult(ok=False, ecosystem=ecosystem, action="install",
                                 message=msg_add)
            rc, out, err = _run(["pio", "pkg", "install"], cwd=project_path, timeout=120)
            ok = rc == 0
            detail = (out or err or ("OK" if ok else "Failed"))[:800]
            return DepResult(
                ok=ok,
                ecosystem=ecosystem,
                action="install",
                message=f"{msg_add} | pio pkg install: {detail}",
                packages_affected=packages,
                rollback_available=True,
            )
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
            rc, out, err = _run(["pio", "pkg", "update"], cwd=project_path, timeout=180)
            ok = rc == 0
            msg = (out or err or ("OK" if ok else "Failed"))[:1200]
            return DepResult(ok=ok, ecosystem=ecosystem, action="update",
                             message=msg, rollback_available=True)
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

        if ecosystem == "platformio":
            if not project_path:
                return DepResult(ok=False, ecosystem=ecosystem, action="rollback",
                                 message="project_path is required for PlatformIO rollback.")
            ini_path = Path(project_path) / "platformio.ini"
            if not ini_path.exists():
                return DepResult(ok=False, ecosystem=ecosystem, action="rollback",
                                 message="platformio.ini not found.")
            ok_r, msg_r = self._pio_restore_lib_deps(ini_path, snap.packages)
            if not ok_r:
                return DepResult(ok=False, ecosystem=ecosystem, action="rollback", message=msg_r)
            rc, out, err = _run(["pio", "pkg", "install"], cwd=project_path, timeout=120)
            ok = rc == 0
            detail = (out or err or ("OK" if ok else "Failed"))[:800]
            return DepResult(ok=ok, ecosystem=ecosystem, action="rollback",
                             message=f"{msg_r} | pio pkg install: {detail}",
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

    # -----------------------------------------------------------------------
    # PlatformIO helpers
    # -----------------------------------------------------------------------

    def _pio_read_lib_deps(self, ini_path: Path) -> dict[str, str]:
        """Lee todas las entradas de lib_deps de platformio.ini.

        Retorna {lib_entry: 'declared'} para cada línea no vacía.
        """
        if not ini_path.exists():
            return {}
        try:
            cfg = configparser.RawConfigParser()
            cfg.read(str(ini_path), encoding="utf-8")
            packages: dict[str, str] = {}
            for section in cfg.sections():
                raw = cfg.get(section, "lib_deps", fallback="")
                for line in raw.splitlines():
                    lib = line.strip()
                    if lib and not lib.startswith(("#", ";")):
                        packages[lib] = "declared"
            return packages
        except Exception:
            return {}

    def _pio_append_lib_deps(self, ini_path: Path, packages: list[str]) -> tuple[bool, str]:
        """Agrega packages al bloque lib_deps de platformio.ini evitando duplicados.

        Retorna (ok, mensaje).
        """
        def _base(entry: str) -> str:
            entry = re.split(r"\s*[;#]", entry.strip())[0].strip()
            name = re.split(r"\s*@", entry)[0].strip()
            if "/" in name:
                name = name.split("/", 1)[1]
            return name.strip().lower()

        try:
            content = ini_path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, str(exc)

        lines = content.splitlines(keepends=True)
        existing: set[str] = set()
        in_lib_deps = False
        insert_at: int | None = None

        for i, line in enumerate(lines):
            stripped = line.rstrip()
            if re.match(r"^\s*lib_deps\s*=", stripped):
                in_lib_deps = True
                inline = re.sub(r"^\s*lib_deps\s*=\s*", "", stripped).strip()
                if inline:
                    existing.add(_base(inline))
                continue
            if in_lib_deps:
                if stripped and not stripped.startswith((" ", "\t")):
                    insert_at = i
                    in_lib_deps = False
                    break
                entry = stripped.strip()
                if entry:
                    existing.add(_base(entry))

        if in_lib_deps:
            insert_at = len(lines)  # lib_deps al final del archivo

        to_add = [p for p in packages if _base(p) not in existing]

        if insert_at is not None:
            # Bloque lib_deps existente — insertar nuevas entradas.
            if not to_add:
                return True, "All packages already declared in lib_deps."
            additions = [f"    {pkg}\n" for pkg in to_add]
            new_lines = lines[:insert_at] + additions + lines[insert_at:]
            try:
                ini_path.write_text("".join(new_lines), encoding="utf-8")
                return True, f"Added to lib_deps: {', '.join(to_add)}"
            except OSError as exc:
                return False, str(exc)

        # No hay bloque lib_deps — crearlo en la primera sección [env:...].
        section_start: int | None = None
        section_end: int = len(lines)
        for i, line in enumerate(lines):
            s = line.rstrip()
            if re.match(r"^\[env:", s, re.IGNORECASE):
                section_start = i + 1
            elif section_start is not None and re.match(r"^\[", s):
                section_end = i
                break

        if section_start is None:
            return False, "No [env:...] section found in platformio.ini. Cannot create lib_deps."

        pkgs_to_write = to_add if to_add else packages
        additions = ["lib_deps =\n"] + [f"    {pkg}\n" for pkg in pkgs_to_write]
        new_lines = lines[:section_end] + additions + lines[section_end:]
        try:
            ini_path.write_text("".join(new_lines), encoding="utf-8")
            return True, f"Created lib_deps with: {', '.join(pkgs_to_write)}"
        except OSError as exc:
            return False, str(exc)

    def _pio_restore_lib_deps(self, ini_path: Path, saved: dict[str, str]) -> tuple[bool, str]:
        """Reemplaza el bloque lib_deps en platformio.ini con las entradas del snapshot.

        Retorna (ok, mensaje).
        """
        try:
            content = ini_path.read_text(encoding="utf-8")
        except OSError as exc:
            return False, str(exc)

        libs = [k for k in saved if k and not k.startswith(("#", ";"))]
        lines = content.splitlines(keepends=True)
        new_lines: list[str] = []
        in_lib_deps = False
        restored = False

        for line in lines:
            stripped = line.rstrip()
            if re.match(r"^\s*lib_deps\s*=", stripped):
                in_lib_deps = True
                new_lines.append("lib_deps =\n")
                for lib in libs:
                    new_lines.append(f"    {lib}\n")
                restored = True
                continue
            if in_lib_deps:
                if not stripped or (stripped and not stripped.startswith((" ", "\t"))):
                    in_lib_deps = False
                    new_lines.append(line)
                # else: omitir línea de continuación antigua
                continue
            new_lines.append(line)

        if not restored:
            return False, "No lib_deps block found to restore."
        try:
            ini_path.write_text("".join(new_lines), encoding="utf-8")
            return True, f"Restored {len(libs)} packages to lib_deps."
        except OSError as exc:
            return False, str(exc)

    def _snapshot_path(self, project_path: str | None) -> Path:
        base = Path(project_path) if project_path else self.base_dir
        return base / self.SNAPSHOT_FILE

    def _persist_snapshot(self, snap: DepSnapshot, project_path: str | None) -> None:
        path = self._snapshot_path(project_path)
        with self._snapshot_lock:
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
                # Escritura atómica: escribir en .tmp y renombrar
                tmp_path = path.with_suffix(".tmp")
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(existing, fh, ensure_ascii=False, indent=2)
                tmp_path.replace(path)
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
