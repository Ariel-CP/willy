"""
Arduino/ESP32 Microcontroller Manager

Facade for PlatformIO and serial port detection.
Handles board detection, compilation, and firmware upload.
"""

import subprocess
import json
import re
import os
import sys
from typing import Dict, List, Optional, Callable, Tuple
from pathlib import Path


class ArduinoManager:
    """Manages microcontroller operations via PlatformIO."""
    
    def __init__(
        self,
        config: Dict,
        on_status: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize ArduinoManager.
        
        Args:
            config: Config dict with microcontroller_* keys
            on_status: Callback for status messages (e.g., "Building...")
            on_error: Callback for error messages
        """
        self.config = config
        self.on_status = on_status or (lambda x: None)
        self.on_error = on_error or (lambda x: None)
        self.platformio_path = None
        self._detect_platformio()
    
    def _detect_platformio(self) -> None:
        """Detect PlatformIO installation."""
        # Try config path first
        config_path = self.config.get("platformio_path")
        if config_path and os.path.exists(config_path):
            self.platformio_path = config_path
            return
        
        # Try global 'pio' command
        try:
            result = subprocess.run(
                ["pio", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                self.platformio_path = "pio"
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Try common installation paths by OS
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            local_appdata = os.environ.get("LOCALAPPDATA", "")
            common_paths = [
                Path(appdata) / "Python" / "Scripts" / "pio.exe" if appdata else None,
                Path(local_appdata) / "Programs" / "Python" / "Python311" / "Scripts" / "pio.exe" if local_appdata else None,
                Path(local_appdata) / "Programs" / "Python" / "Python312" / "Scripts" / "pio.exe" if local_appdata else None,
            ]
        else:
            common_paths = [
                Path.home() / ".local" / "bin" / "pio",
                Path("/usr/local/bin/pio"),
                Path("/usr/bin/pio"),
            ]

        for path in common_paths:
            if path and path.exists():
                self.platformio_path = str(path)
                return
        
        self.on_error(
            "PlatformIO not found. Install with: pip install platformio"
        )
    
    def validate_env(self) -> Dict:
        """
        Validate PlatformIO environment.
        
        Returns:
            {
                "ok": bool,
                "version": str (if ok),
                "errors": [str],
                "info": str (summary)
            }
        """
        if not self.platformio_path:
            return {
                "ok": False,
                "errors": [
                    "PlatformIO not found. Install with: pip install platformio"
                ],
                "info": "PlatformIO environment invalid.",
            }
        
        try:
            result = subprocess.run(
                [self.platformio_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return {
                    "ok": False,
                    "errors": [f"PlatformIO error: {result.stderr}"],
                    "info": "PlatformIO validation failed.",
                }
            
            version = result.stdout.strip()
            return {
                "ok": True,
                "version": version,
                "errors": [],
                "info": f"PlatformIO environment ready ({version}).",
            }
        except Exception as e:
            return {
                "ok": False,
                "errors": [str(e)],
                "info": "PlatformIO validation error.",
            }
    
    def detect_microcontrollers(self) -> List[Dict]:
        """
        Detect connected microcontrollers.
        
        Uses 'pio device list' to find boards.
        
        Returns:
            [
                {
                    "board": "esp32",
                    "port": "/dev/ttyUSB0",
                    "description": "USB Serial Device",
                    "hwid": "...",
                }
            ]
        """
        if not self.platformio_path:
            self.on_error("PlatformIO not available for device detection")
            return []
        
        try:
            result = subprocess.run(
                [self.platformio_path, "device", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode != 0:
                self.on_error(f"Device list error: {result.stderr}")
                return []
            
            raw_output = result.stdout.strip()
            if not raw_output:
                return []

            devices = self._parse_pio_device_output(raw_output)
            return devices
        except Exception as e:
            self.on_error(f"Device detection error: {str(e)}")
            return []

    def _parse_pio_device_output(self, output: str) -> List[Dict]:
        """Parse PlatformIO device list output (pipe or multiline formats)."""
        devices: List[Dict] = []

        # Format A (older): /dev/ttyUSB0 | USB Serial Device | HWID: 10c4:ea60
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Platform"):
                continue
            if "|" not in line:
                continue

            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue

            port = parts[0]
            description = parts[1]
            hwid = parts[2].replace("HWID:", "").strip() if len(parts) > 2 else ""
            if not self._is_serial_port(port):
                continue

            board = self._infer_board_from_hwid(hwid, description)
            devices.append({
                "port": port,
                "description": description,
                "hwid": hwid,
                "board": board,
            })

        if devices:
            return devices

        # Format B (current):
        # /dev/ttyUSB0
        # ------------
        # Hardware ID: USB VID:PID=1A86:7523 LOCATION=1-4
        # Description: USB Serial
        blocks = [b.strip() for b in re.split(r"\n\s*\n", output) if b.strip()]
        for block in blocks:
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            if not lines:
                continue

            port = lines[0]
            if not self._is_serial_port(port):
                continue

            hwid = ""
            description = ""
            for ln in lines[1:]:
                if ln.lower().startswith("hardware id:"):
                    hwid = ln.split(":", 1)[1].strip()
                elif ln.lower().startswith("description:"):
                    description = ln.split(":", 1)[1].strip()

            # Skip noise entries like ttyS* with n/a metadata.
            if description.lower() == "n/a" and (not hwid or hwid.lower() == "n/a"):
                continue

            board = self._infer_board_from_hwid(hwid, description)
            devices.append({
                "port": port,
                "description": description,
                "hwid": hwid,
                "board": board,
            })

        return devices

    def _is_serial_port(self, port: str) -> bool:
        """Accept only likely microcontroller serial ports on Linux/macOS/Windows."""
        port_lower = port.lower()
        return (
            port.startswith("/dev/ttyUSB")
            or port.startswith("/dev/ttyACM")
            or port.startswith("/dev/cu.")
            or port.startswith("COM")
            or "/serial" in port_lower
        )
    
    def _infer_board_from_hwid(self, hwid: str, description: str) -> str:
        """Infer board type from HWID or description."""
        normalized_hwid = self._normalize_hwid(hwid)

        # Common chip/board VID:PID mappings.
        hwid_map = {
            # Arduino Uno official USB interface IDs
            "2341:0043": "arduino_uno",
            "2a03:0043": "arduino_uno",
            "2341:0001": "arduino_uno",
            # CH340/CH341 USB-UART bridge (common Uno/Nano clones)
            "1a86:7523": "arduino_uno",
            # CP210x USB-UART bridge
            "10c4:ea60": "arduino_compatible",
            # Raspberry Pi Pico
            "2e8a:0005": "pico",
            # Common ESP32 bridges
            "303a:1001": "esp32",
        }

        if normalized_hwid in hwid_map:
            return hwid_map[normalized_hwid]
        
        # Infer from description
        desc_lower = description.lower()
        if "arduino uno" in desc_lower or "uno" in desc_lower:
            return "arduino_uno"
        elif "arduino" in desc_lower:
            return "arduino_compatible"
        elif "ch340" in desc_lower or "usb serial" in desc_lower:
            return "arduino_uno"
        elif "esp32" in desc_lower:
            return "esp32"
        elif "pico" in desc_lower:
            return "pico"
        elif "stm32" in desc_lower:
            return "stm32"
        else:
            return "unknown"

    def _normalize_hwid(self, hwid: str) -> str:
        """Extract normalized VID:PID from PlatformIO HWID text."""
        if not hwid:
            return ""

        text = hwid.strip()
        # Handles values like: USB VID:PID=1A86:7523 LOCATION=1-4
        match = re.search(r"([0-9a-fA-F]{4}:[0-9a-fA-F]{4})", text)
        if match:
            return match.group(1).lower()
        return text.lower()
    
    def get_board_info(self, board: str) -> Dict:
        """
        Get board capabilities (RAM, Flash, GPIO, etc.).
        
        Args:
            board: Board ID (e.g., "esp32", "arduino:avr:uno")
        
        Returns:
            {
                "name": "ESP32",
                "ram": "320 KB",
                "flash": "4 MB",
                "gpio": 36,
                "cpu": "Xtensa 240 MHz",
                "connectivity": ["WiFi", "Bluetooth"]
            }
        """
        # Hardcoded board profiles (can extend to read from pio)
        boards_db = {
            "esp32": {
                "name": "ESP32",
                "ram": "320 KB",
                "flash": "4 MB",
                "gpio": 36,
                "cpu": "Xtensa 240 MHz",
                "connectivity": ["WiFi", "Bluetooth LE", "BLE 5.0"],
            },
            "esp32-s3": {
                "name": "ESP32-S3",
                "ram": "512 KB",
                "flash": "8 MB",
                "gpio": 45,
                "cpu": "Xtensa 240 MHz",
                "connectivity": ["WiFi 6", "Bluetooth LE", "BLE 5.3"],
            },
            "arduino:avr:uno": {
                "name": "Arduino UNO",
                "ram": "2 KB",
                "flash": "32 KB",
                "gpio": 14,
                "cpu": "ATmega328P 16 MHz",
                "connectivity": [],
            },
            "arduino_uno": {
                "name": "Arduino UNO",
                "ram": "2 KB",
                "flash": "32 KB",
                "gpio": 14,
                "cpu": "ATmega328P 16 MHz",
                "connectivity": [],
            },
            "arduino_compatible": {
                "name": "Arduino-Compatible Board",
                "ram": "2 KB",
                "flash": "32 KB",
                "gpio": 14,
                "cpu": "ATmega328P-class",
                "connectivity": [],
            },
            "arduino:avr:nano": {
                "name": "Arduino Nano",
                "ram": "2 KB",
                "flash": "32 KB",
                "gpio": 14,
                "cpu": "ATmega328P 16 MHz",
                "connectivity": [],
            },
            "pico": {
                "name": "Raspberry Pi Pico",
                "ram": "264 KB",
                "flash": "2 MB",
                "gpio": 28,
                "cpu": "Dual ARM Cortex-M0+ 133 MHz",
                "connectivity": [],
            },
        }
        
        return boards_db.get(board, {
            "name": "Unknown Board",
            "ram": "?",
            "flash": "?",
            "gpio": "?",
            "cpu": "?",
            "connectivity": [],
        })

    def _history_file_path(self, project_path: str) -> str:
        return os.path.join(project_path, ".willy_build_history.json")

    def _load_project_history(self, project_path: str) -> List[Dict]:
        history_path = self._history_file_path(project_path)
        if not os.path.exists(history_path):
            return []
        try:
            with open(history_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_project_history(self, project_path: str, history: List[Dict]) -> None:
        history_path = self._history_file_path(project_path)
        trimmed = history[-100:]
        try:
            with open(history_path, "w", encoding="utf-8") as fh:
                json.dump(trimmed, fh, indent=2)
        except Exception as exc:  # noqa: BLE001
            self.on_error(f"Build history save warning: {exc}")

    def _append_project_history(
        self,
        project_path: str,
        action: str,
        success: bool,
        env: Optional[str] = None,
        port: Optional[str] = None,
        error_msg: str = "",
        notes: str = "",
        changes: Optional[List[str]] = None,
        time_seconds: float = 0.0,
    ) -> None:
        from datetime import datetime

        history = self._load_project_history(project_path)
        history.append({
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "success": bool(success),
            "env": env or "",
            "port": port or "",
            "error": (error_msg or "")[:500],
            "notes": (notes or "")[:1200],
            "changes": changes or [],
            "time_seconds": round(float(time_seconds), 3),
        })
        self._save_project_history(project_path, history)

    def _recent_project_history_summary(self, project_path: str, limit: int = 5) -> str:
        history = self._load_project_history(project_path)
        if not history:
            return ""

        recent = history[-limit:]
        lines = ["Recent project history:"]
        for idx, item in enumerate(reversed(recent), start=1):
            ok = "OK" if item.get("success") else "FAIL"
            action = str(item.get("action", "?")).upper()
            env = item.get("env") or "default"
            port = item.get("port")
            port_part = f" @ {port}" if port else ""
            err = str(item.get("error", "")).strip()
            err_part = f" - {err[:90]}" if err else ""
            lines.append(f"  {idx}. [{ok}] {action} ({env}{port_part}){err_part}")
        return "\n".join(lines)

    def _preflight_before_build_upload(
        self,
        project_path: str,
        env: Optional[str] = None,
        action: str = "build",
        port: Optional[str] = None,
    ) -> Tuple[bool, List[str], str]:
        messages: List[str] = []

        if not self.platformio_path:
            return False, messages, "PlatformIO not available"

        if not os.path.isdir(project_path):
            return False, messages, f"Project directory not found: {project_path}"

        ini_path = os.path.join(project_path, "platformio.ini")
        if not os.path.exists(ini_path):
            return False, messages, f"platformio.ini not found in {project_path}"

        info = self.get_project_info(project_path)
        if not info.get("ok"):
            return False, messages, info.get("error", "Could not inspect project metadata")

        envs = [str(e).strip().lower() for e in info.get("environments", []) if str(e).strip()]
        if env and envs and env.strip().lower() not in envs:
            return False, messages, f"Environment '{env}' not found in platformio.ini ({', '.join(envs)})"

        prep_msg = self._prepare_platformio_sources(project_path)
        if prep_msg:
            messages.append(prep_msg)

        try:
            main_cpp = os.path.join(project_path, "src", "main.cpp")
            if os.path.exists(main_cpp):
                with open(main_cpp, "r", encoding="utf-8", errors="replace") as fh:
                    source_text = fh.read()
            else:
                source_text = ""
            dep_msg = self._ensure_lib_deps_from_source(project_path, source_text)
            if dep_msg:
                messages.append(dep_msg)
        except Exception as exc:  # noqa: BLE001
            return False, messages, f"Dependency preflight failed: {exc}"

        if action == "upload":
            if not port:
                return False, messages, "No serial port provided for upload"
            if not os.path.exists(port):
                return False, messages, f"Serial port not found: {port}"
            if not os.access(port, os.R_OK | os.W_OK):
                return False, messages, f"No read/write permission on serial port: {port}"

        # Mandatory dependency sync before build/upload.
        cmd = [self.platformio_path, "pkg", "install"]
        if env:
            cmd.extend(["-e", env])
        try:
            self.on_status("Preflight: verificando librerias...")
            pkg_result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return False, messages, "Preflight timeout: pio pkg install (>3 min)"
        except Exception as exc:  # noqa: BLE001
            return False, messages, f"Preflight package install error: {exc}"

        pkg_output = (pkg_result.stdout + pkg_result.stderr).strip()
        if pkg_result.returncode != 0:
            return False, messages, f"Preflight package install failed: {pkg_output[:500]}"

        if pkg_output:
            messages.append("Dependency sync OK (pio pkg install).")

        return True, messages, ""
    
    def build_sketch(
        self,
        project_path: str,
        env: str = None,
    ) -> Dict:
        """
        Build sketch/firmware with PlatformIO.
        
        Args:
            project_path: Path to PlatformIO project
            env: Environment (e.g., "esp32"). If None, uses first in platformio.ini
        
        Returns:
            {
                "ok": bool,
                "output": str (build output),
                "error": str (if error),
                "time_seconds": float
            }
        """
        import time

        start = time.time()
        history_summary = self._recent_project_history_summary(project_path)

        ok_preflight, preflight_msgs, preflight_err = self._preflight_before_build_upload(
            project_path,
            env=env,
            action="build",
        )

        if not ok_preflight:
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="preflight",
                success=False,
                env=env,
                error_msg=preflight_err,
                notes="\n".join(preflight_msgs),
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": preflight_err,
                "time_seconds": elapsed,
            }

        try:
            self.on_status(f"Building {project_path}...")
            cmd = [self.platformio_path, "run"]
            if env:
                cmd.extend(["-e", env])

            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = (result.stdout + result.stderr).strip()
            elapsed = time.time() - start

            if result.returncode == 0:
                self.on_status("Build successful")
                self._append_project_history(
                    project_path,
                    action="build",
                    success=True,
                    env=env,
                    notes=output[:1200],
                    changes=preflight_msgs,
                    time_seconds=elapsed,
                )
                return {
                    "ok": True,
                    "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs), output] if x])).strip(),
                    "error": "",
                    "time_seconds": elapsed,
                }

            error_msg = f"Build failed (exit code {result.returncode})"
            self._append_project_history(
                project_path,
                action="build",
                success=False,
                env=env,
                error_msg=error_msg,
                notes=output[:1200],
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs), output] if x])).strip(),
                "error": error_msg,
                "time_seconds": elapsed,
            }
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="build",
                success=False,
                env=env,
                error_msg="Build timeout (>5 min)",
                notes="",
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": "Build timeout (>5 min)",
                "time_seconds": elapsed,
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="build",
                success=False,
                env=env,
                error_msg=str(exc),
                notes="",
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": str(exc),
                "time_seconds": elapsed,
            }
    
    def upload_firmware(
        self,
        project_path: str,
        port: str,
        env: str = None,
    ) -> Dict:
        """
        Build and upload firmware to microcontroller.
        
        Args:
            project_path: Path to PlatformIO project
            port: Serial port (e.g., "/dev/ttyUSB0")
            env: Environment (e.g., "esp32")
        
        Returns:
            {
                "ok": bool,
                "output": str,
                "error": str (if error),
                "time_seconds": float
            }
        """
        import time

        start = time.time()
        history_summary = self._recent_project_history_summary(project_path)

        ok_preflight, preflight_msgs, preflight_err = self._preflight_before_build_upload(
            project_path,
            env=env,
            action="upload",
            port=port,
        )

        if not ok_preflight:
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="preflight",
                success=False,
                env=env,
                port=port,
                error_msg=preflight_err,
                notes="\n".join(preflight_msgs),
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": preflight_err,
                "time_seconds": elapsed,
            }

        try:
            self.on_status(f"Uploading to {port}...")
            cmd = [self.platformio_path, "run", "--target", "upload"]
            if env:
                cmd.extend(["-e", env])
            cmd.extend(["--upload-port", port])

            result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = (result.stdout + result.stderr).strip()
            elapsed = time.time() - start

            if result.returncode == 0:
                self.on_status("Upload successful ✓")
                self._append_project_history(
                    project_path,
                    action="upload",
                    success=True,
                    env=env,
                    port=port,
                    notes=output[:1200],
                    changes=preflight_msgs,
                    time_seconds=elapsed,
                )
                return {
                    "ok": True,
                    "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs), output] if x])).strip(),
                    "error": "",
                    "time_seconds": elapsed,
                }

            error_msg = f"Upload failed (exit code {result.returncode})"
            self._append_project_history(
                project_path,
                action="upload",
                success=False,
                env=env,
                port=port,
                error_msg=error_msg,
                notes=output[:1200],
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs), output] if x])).strip(),
                "error": error_msg,
                "time_seconds": elapsed,
            }
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="upload",
                success=False,
                env=env,
                port=port,
                error_msg="Upload timeout (>5 min)",
                notes="",
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": "Upload timeout (>5 min)",
                "time_seconds": elapsed,
            }
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - start
            self._append_project_history(
                project_path,
                action="upload",
                success=False,
                env=env,
                port=port,
                error_msg=str(exc),
                notes="",
                changes=preflight_msgs,
                time_seconds=elapsed,
            )
            return {
                "ok": False,
                "output": ("\n\n".join([x for x in [history_summary, "\n".join(preflight_msgs)] if x])).strip(),
                "error": str(exc),
                "time_seconds": elapsed,
            }
    
    def get_project_info(self, project_path: str) -> Dict:
        """
        Read PlatformIO project metadata (board, env, etc.).
        
        Args:
            project_path: Path to project (should contain platformio.ini)
        
        Returns:
            {
                "ok": bool,
                "environments": [str],
                "default_env": str,
                "error": str (if error)
            }
        """
        ini_path = os.path.join(project_path, "platformio.ini")
        
        if not os.path.exists(ini_path):
            return {
                "ok": False,
                "environments": [],
                "default_env": None,
                "error": f"platformio.ini not found in {project_path}",
            }
        
        try:
            with open(ini_path, "r") as f:
                content = f.read()
            
            # Extract [env:*] sections
            env_pattern = r"\[env:(\w+)\]"
            environments = re.findall(env_pattern, content)
            
            # Find default env (first one or 'default')
            default_env = "default" if "default" in environments else (
                environments[0] if environments else None
            )
            
            return {
                "ok": True,
                "environments": environments,
                "default_env": default_env,
                "error": "",
            }
        except Exception as e:
            return {
                "ok": False,
                "environments": [],
                "default_env": None,
                "error": str(e),
            }

    def prepare_project_from_ino(
        self,
        sketch_path: str,
        project_path: Optional[str] = None,
        board: str = "uno",
    ) -> Dict:
        """
        Prepare (or create) a PlatformIO project and copy an .ino as src/main.cpp.

        Returns:
            {
                "ok": bool,
                "project_path": str,
                "output": str,
                "error": str,
            }
        """
        if not self.platformio_path:
            return {
                "ok": False,
                "project_path": "",
                "output": "",
                "error": "PlatformIO not available",
            }

        sketch_abs = os.path.abspath(sketch_path)
        if not os.path.exists(sketch_abs):
            return {
                "ok": False,
                "project_path": "",
                "output": "",
                "error": f"Sketch not found: {sketch_abs}",
            }

        proj_abs = os.path.abspath(project_path or os.path.dirname(sketch_abs))
        os.makedirs(proj_abs, exist_ok=True)
        out_lines: List[str] = []

        ini_path = os.path.join(proj_abs, "platformio.ini")
        if not os.path.exists(ini_path):
            try:
                init = subprocess.run(
                    [self.platformio_path, "project", "init", "--board", board],
                    cwd=proj_abs,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                out_lines.append((init.stdout + init.stderr).strip())
                if init.returncode != 0:
                    return {
                        "ok": False,
                        "project_path": proj_abs,
                        "output": "\n".join(line for line in out_lines if line),
                        "error": f"Failed to initialize PlatformIO project (exit code {init.returncode})",
                    }
            except Exception as exc:  # noqa: BLE001
                return {
                    "ok": False,
                    "project_path": proj_abs,
                    "output": "\n".join(line for line in out_lines if line),
                    "error": f"Project initialization error: {exc}",
                }

        try:
            with open(sketch_abs, "r", encoding="utf-8", errors="replace") as fh:
                sketch = fh.read().strip()

            if "#include <Arduino.h>" not in sketch:
                sketch = "#include <Arduino.h>\n\n" + sketch + "\n"

            src_dir = os.path.join(proj_abs, "src")
            os.makedirs(src_dir, exist_ok=True)
            main_cpp = os.path.join(src_dir, "main.cpp")
            with open(main_cpp, "w", encoding="utf-8") as fh:
                fh.write(sketch)
            out_lines.append(f"Sketch copied to {main_cpp}")
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "project_path": proj_abs,
                "output": "\n".join(line for line in out_lines if line),
                "error": f"Failed to prepare source files: {exc}",
            }

        try:
            lib_notes = self._ensure_lib_deps_from_source(proj_abs, sketch)
            if lib_notes:
                out_lines.append(lib_notes)
        except Exception as exc:  # noqa: BLE001
            out_lines.append(f"Dependency auto-detect warning: {exc}")

        return {
            "ok": True,
            "project_path": proj_abs,
            "output": "\n".join(line for line in out_lines if line),
            "error": "",
        }

    def _ensure_lib_deps_from_source(self, project_path: str, source_text: str) -> str:
        """Add common PlatformIO lib_deps inferred from #include usage."""
        ini_path = os.path.join(project_path, "platformio.ini")
        if not os.path.exists(ini_path):
            return ""

        includes = source_text.lower()
        needed: List[str] = []
        if "tm1637display.h" in includes:
            needed.append("https://github.com/avishorp/TM1637.git")
        if "rtclib.h" in includes:
            needed.append("adafruit/RTClib@^1.14.2")
        if "liquidcrystal_i2c.h" in includes:
            needed.append("johnrickman/LiquidCrystal_I2C@^1.1.4")

        with open(ini_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        # Auto-fix known invalid/deprecated dependency aliases seen in logs.
        bad_aliases = [
            "marcoschwartz/LiquidCrystal I2C @ ^1.1.4",
            "marcoschwartz/LiquidCrystal I2C@^1.1.4",
            "marcoschwartz/LiquidCrystal I2C",
        ]
        replacement = "johnrickman/LiquidCrystal_I2C@^1.1.4"
        alias_fixed = False
        for alias in bad_aliases:
            if alias in content:
                content = content.replace(alias, replacement)
                alias_fixed = True

        if not needed and not alias_fixed:
            return ""

        changed = False
        lines = content.splitlines()
        content_l = content.lower()

        if "lib_deps" not in content:
            # Insert a new lib_deps block into the first env section.
            env_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("[env:")), None)
            if env_idx is not None:
                insert_at = env_idx + 1
                while insert_at < len(lines) and not lines[insert_at].strip().startswith("["):
                    insert_at += 1
                block = ["lib_deps ="] + [f"    {dep}" for dep in needed]
                lines[insert_at:insert_at] = block
                changed = True
        else:
            lib_idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("lib_deps")), None)
            if lib_idx is not None:
                insert_at = lib_idx + 1
                while insert_at < len(lines):
                    cur = lines[insert_at]
                    if cur.strip().startswith("["):
                        break
                    if cur and not cur.startswith(" ") and not cur.startswith("\t"):
                        break
                    insert_at += 1

                for dep in needed:
                    if dep.lower() not in content_l:
                        lines.insert(insert_at, f"    {dep}")
                        insert_at += 1
                        changed = True

        if changed or alias_fixed:
            content = "\n".join(lines).rstrip() + "\n"
            with open(ini_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            if changed and alias_fixed:
                return "Updated platformio.ini with inferred lib_deps and fixed invalid library aliases."
            if changed:
                return "Updated platformio.ini with inferred lib_deps."
            return "Fixed invalid library aliases in platformio.ini."
        return ""

    def _prepare_platformio_sources(self, project_path: str) -> str:
        """
        Ensure project has source files under src/.

        If src/ is missing or empty and an .ino exists in project root,
        create src/main.cpp from that sketch so PlatformIO can build.
        """
        try:
            src_dir = os.path.join(project_path, "src")
            main_cpp = os.path.join(src_dir, "main.cpp")
            if os.path.isdir(src_dir):
                has_sources = any(
                    name.endswith((".c", ".cc", ".cpp", ".cxx", ".ino", ".S"))
                    for name in os.listdir(src_dir)
                )
                if has_sources:
                    # Common issue: main.cpp exists but misses Arduino.h include.
                    if os.path.exists(main_cpp):
                        try:
                            with open(main_cpp, "r", encoding="utf-8", errors="replace") as fh:
                                current = fh.read()
                            if "#include <Arduino.h>" not in current:
                                with open(main_cpp, "w", encoding="utf-8") as fh:
                                    fh.write("#include <Arduino.h>\n\n" + current)
                                return "Auto-fixed src/main.cpp: added missing #include <Arduino.h>."
                        except Exception as exc:  # noqa: BLE001
                            self.on_error(f"Source auto-prepare warning: {exc}")
                    return ""
            else:
                os.makedirs(src_dir, exist_ok=True)

            root_files = os.listdir(project_path)
            ino_files = sorted(
                [name for name in root_files if name.lower().endswith(".ino")]
            )
            if not ino_files:
                return ""

            chosen_ino = ino_files[0]
            ino_path = os.path.join(project_path, chosen_ino)
            # Respect existing source file if user already created one.
            if os.path.exists(main_cpp):
                return ""

            with open(ino_path, "r", encoding="utf-8", errors="replace") as fh:
                ino_content = fh.read().strip()

            # Arduino.h include is harmless and improves compatibility in C++ mode.
            content = "#include <Arduino.h>\n\n" + ino_content + "\n"
            with open(main_cpp, "w", encoding="utf-8") as fh:
                fh.write(content)

            return (
                f"Auto-prepared PlatformIO sources: created src/main.cpp from {chosen_ino}."
            )
        except Exception as exc:  # noqa: BLE001
            # Never block build/upload because of migration helper.
            self.on_error(f"Source auto-prepare warning: {exc}")
            return ""
