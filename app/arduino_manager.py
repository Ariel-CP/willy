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
import time
import logging
from typing import Dict, List, Optional, Callable, Tuple
from pathlib import Path


logger = logging.getLogger(__name__)


LIBRARY_RULES: Dict[str, Dict[str, object]] = {
    "tm1637": {
        "include_tokens": ["tm1637display.h"],
        "canonical": "https://github.com/avishorp/TM1637.git",
        "aliases": [],
        "fallback_versions": [],
    },
    "rtclib": {
        "include_tokens": ["rtclib.h"],
        "canonical": "adafruit/RTClib@^1.14.2",
        "aliases": [],
        "fallback_versions": ["^1.14.1", "^1.14.0"],
    },
    "liquidcrystal_i2c": {
        "include_tokens": ["liquidcrystal_i2c.h"],
        "canonical": "marcoschwartz/LiquidCrystal_I2C@1.1.4",
        "aliases": [
            "johnrickman/LiquidCrystal_I2C@^1.1.4",
            "johnrickman/LiquidCrystal_I2C@1.1.4",
            "johnrickman/LiquidCrystal_I2C",
            "johnrickman/LiquidCrystal_I2C @ ^1.1.4",
            "johnrickman/LiquidCrystal_I2C @ 1.1.4",
            "marcoschwartz/LiquidCrystal I2C @ ^1.1.4",
            "marcoschwartz/LiquidCrystal I2C@^1.1.4",
            "marcoschwartz/LiquidCrystal I2C",
            "marcoschwartz/LiquidCrystal_I2C@^1.1.4",
            "marcoschwartz/LiquidCrystal_I2C",
            "fdebrabander/Arduino-LiquidCrystal-I2C-library",
        ],
        "fallback_versions": ["1.1.3", "1.1.2", "latest"],
    },
    "dht": {
        "include_tokens": ["dht.h", "dht_u.h"],
        "canonical": "adafruit/DHT sensor library@^1.4.6",
        "aliases": [],
        "fallback_versions": ["^1.4.5", "^1.4.4"],
    },
    "adafruit_gfx": {
        "include_tokens": ["adafruit_gfx.h"],
        "canonical": "adafruit/Adafruit GFX Library@^1.12.1",
        "aliases": [],
        "fallback_versions": ["^1.11.11", "^1.11.10"],
    },
    "adafruit_busio": {
        "include_tokens": ["adafruit_busio_register.h", "adafruit_busio.h"],
        "canonical": "adafruit/Adafruit BusIO@^1.17.0",
        "aliases": [],
        "fallback_versions": ["^1.16.2", "^1.16.1"],
    },
}


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

        # Try local venv / interpreter-adjacent executables first (Windows/Linux/macOS).
        scripts_dir = Path(sys.executable).resolve().parent
        cwd = Path.cwd()
        candidate_bins = [
            scripts_dir / "pio.exe",
            scripts_dir / "platformio.exe",
            scripts_dir / "pio",
            scripts_dir / "platformio",
            cwd / ".venv" / "Scripts" / "pio.exe",
            cwd / ".venv" / "Scripts" / "platformio.exe",
            cwd / ".venv" / "bin" / "pio",
            cwd / ".venv" / "bin" / "platformio",
        ]
        for candidate in candidate_bins:
            if candidate.exists():
                self.platformio_path = str(candidate)
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
        
        # Try common installation paths
        appdata = os.environ.get("APPDATA", "")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        common_paths = [
            Path.home() / ".local" / "bin" / "pio",
            Path("/usr/local/bin/pio"),
            Path("/usr/bin/pio"),
            Path(appdata) / "Python" / "Scripts" / "pio.exe" if appdata else None,
            Path(local_appdata) / "Programs" / "Python" / "Python311" / "Scripts" / "pio.exe" if local_appdata else None,
            Path(local_appdata) / "Programs" / "Python" / "Python312" / "Scripts" / "pio.exe" if local_appdata else None,
            Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "Scripts" / "pio.exe",
            Path.home() / "AppData" / "Roaming" / "Python" / "Python313" / "Scripts" / "pio.exe",
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
            if self._is_noise_serial_device(description, hwid):
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
            if self._is_noise_serial_device(description, hwid):
                continue

            board = self._infer_board_from_hwid(hwid, description)
            devices.append({
                "port": port,
                "description": description,
                "hwid": hwid,
                "board": board,
            })

        devices.sort(
            key=lambda d: self._device_priority(
                d.get("board", "unknown"),
                d.get("description", ""),
                d.get("hwid", ""),
            )
        )
        return devices

    def _is_noise_serial_device(self, description: str, hwid: str) -> bool:
        """Filter common non-MCU serial endpoints (e.g., Windows Bluetooth COM ports)."""
        desc_lower = (description or "").lower()
        hwid_lower = (hwid or "").lower()
        return (
            "bluetooth" in desc_lower
            or "bthenum" in hwid_lower
        )

    def _device_priority(self, board: str, description: str, hwid: str) -> Tuple[int, int, str]:
        """Lower tuple means higher priority when auto-selecting a device."""
        board_rank = {
            "arduino_uno": 0,
            "arduino_compatible": 1,
            "esp32": 2,
            "pico": 3,
            "stm32": 4,
            "unknown": 9,
        }

        text = f"{description} {hwid}".lower()
        usb_hint = 0 if any(k in text for k in ("usb", "ch340", "ch341", "cp210", "ftdi", "vid:pid")) else 1
        return (board_rank.get(board, 8), usb_hint, (description or "").lower())

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

    def _is_windows_com_port(self, port: str) -> bool:
        """Return True for Windows COM-style serial ports like COM5."""
        return bool(re.fullmatch(r"(?i)COM\d+", (port or "").strip()))
    
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
        logger.info(
            "Preflight start: action=%s env=%s port=%s project=%s",
            action,
            env or "default",
            port or "",
            project_path,
        )

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

            prefetch_msgs = self._prefetch_declared_libraries(project_path, env=env)
            messages.extend(prefetch_msgs)
        except Exception as exc:  # noqa: BLE001
            return False, messages, f"Dependency preflight failed: {exc}"

        if action == "upload":
            if not port:
                return False, messages, "No serial port provided for upload"
            if self._is_windows_com_port(port):
                # On Windows COM ports are not regular filesystem paths.
                logger.info("Preflight upload: accepting Windows COM port %s", port)
            else:
                if not os.path.exists(port):
                    return False, messages, f"Serial port not found: {port}"
                if not os.access(port, os.R_OK | os.W_OK):
                    return False, messages, f"No read/write permission on serial port: {port}"

        # Mandatory dependency sync before build/upload.
        ok_sync, sync_msgs, sync_err = self._sync_dependencies_with_recovery(
            project_path,
            env=env,
        )
        messages.extend(sync_msgs)
        if not ok_sync:
            logger.error("Preflight failed after dependency sync: %s", sync_err)
            return False, messages, sync_err

        logger.info("Preflight OK: action=%s env=%s", action, env or "default")

        return True, messages, ""

    def _sync_dependencies_with_recovery(
        self,
        project_path: str,
        env: Optional[str] = None,
    ) -> Tuple[bool, List[str], str]:
        """Run `pio pkg install` with retries and library-specific recovery."""
        messages: List[str] = []
        max_attempts = 3
        timeout_seconds = 300
        output_excerpt_limit = 2000
        last_output = ""

        target_specs = self._collect_lib_deps_from_ini(project_path, env=env)
        if target_specs:
            messages.append("Dependency targets: " + ", ".join(target_specs))

        for attempt in range(1, max_attempts + 1):
            self.on_status(
                f"Preflight: verificando librerias (intento {attempt}/{max_attempts})..."
            )
            logger.info(
                "Dependency sync attempt %s/%s (env=%s)",
                attempt,
                max_attempts,
                env or "default",
            )
            ok, output, err_type, library_key = self._run_pkg_install_once(
                project_path,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            last_output = output

            if ok:
                logger.info("Dependency sync OK (attempt %s/%s)", attempt, max_attempts)
                messages.append("Dependency sync OK (pio pkg install).")
                if attempt > 1:
                    messages.append(
                        f"Dependency sync recovered on retry {attempt}/{max_attempts}."
                    )
                return True, messages, ""

            if err_type in {"timeout", "network"} and attempt < max_attempts:
                messages.append(
                    f"Dependency sync attempt {attempt}/{max_attempts} failed ({err_type}); retrying..."
                )
                time.sleep(2)
                continue

            if err_type in {"not_found", "version", "dependency"} and library_key:
                logger.warning(
                    "Dependency sync failed (%s), trying fallback for library_key=%s",
                    err_type,
                    library_key,
                )
                recovered, recover_note = self._try_library_version_fallback(
                    project_path,
                    library_key,
                    env=env,
                    timeout_seconds=timeout_seconds,
                )
                if recover_note:
                    messages.append(recover_note)
                if recovered:
                    messages.append(
                        "Dependency sync recovered after automatic library fallback."
                    )
                    return True, messages, ""

            break

        error_detail = last_output.strip()[:output_excerpt_limit]
        logger.error(
            "Dependency sync failed after retries (env=%s): %s",
            env or "default",
            (error_detail or "no details")[:300],
        )
        if error_detail:
            return (
                False,
                messages,
                "Preflight package install failed after automatic retries. "
                f"Details:\n{error_detail}",
            )
        return False, messages, "Preflight package install failed after automatic retries."

    def _run_pkg_install_once(
        self,
        project_path: str,
        env: Optional[str],
        timeout_seconds: int,
    ) -> Tuple[bool, str, str, Optional[str]]:
        """Execute one dependency sync run and classify errors."""
        cmd = [self.platformio_path, "pkg", "install"]
        if env:
            cmd.extend(["-e", env])

        try:
            pkg_result = subprocess.run(
                cmd,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return False, "pio pkg install timeout", "timeout", None
        except Exception as exc:  # noqa: BLE001
            return False, f"pio pkg install exception: {exc}", "exception", None

        pkg_output = (pkg_result.stdout + pkg_result.stderr).strip()
        if pkg_result.returncode == 0:
            return True, pkg_output, "", None

        err_type, library_key = self._classify_pkg_install_error(pkg_output)
        return False, pkg_output, err_type, library_key

    def _classify_pkg_install_error(self, output: str) -> Tuple[str, Optional[str]]:
        """Classify common PlatformIO dependency failures."""
        text = (output or "").lower()

        library_key = self._detect_library_key_in_text(text)

        if any(k in text for k in ("timed out", "timeout", "read timed out")):
            return "timeout", library_key
        if any(k in text for k in ("connection", "temporarily unavailable", "dns", "ssl", "network")):
            return "network", library_key
        if any(k in text for k in ("could not find", "unknown package", "not found")):
            return "not_found", library_key
        if any(k in text for k in ("version", "constraint", "incompatible")):
            return "version", library_key
        if any(k in text for k in ("dependency", "package")):
            return "dependency", library_key
        return "generic", library_key

    def _detect_library_key_in_text(self, text: str) -> Optional[str]:
        """Try to map error text to a known library rule key."""
        for key, rule in LIBRARY_RULES.items():
            canonical = str(rule.get("canonical", "")).lower()
            aliases = [str(a).lower() for a in list(rule.get("aliases", []))]
            tokens = [str(t).lower() for t in list(rule.get("include_tokens", []))]

            candidates = [canonical, key] + aliases + tokens
            for candidate in candidates:
                if candidate and candidate in text:
                    return key

        if "liquidcrystal" in text:
            return "liquidcrystal_i2c"
        return None

    def _try_library_version_fallback(
        self,
        project_path: str,
        library_key: str,
        env: Optional[str],
        timeout_seconds: int,
    ) -> Tuple[bool, str]:
        """Apply fallback versions for a known library and re-run pkg install."""
        rule = LIBRARY_RULES.get(library_key)
        if not rule:
            return False, ""

        canonical = str(rule.get("canonical", "")).strip()
        if not canonical:
            return False, ""

        project_name = self._lib_project_name(canonical)
        current_version = self._lib_version(canonical)
        fallback_versions = [
            str(v).strip() for v in list(rule.get("fallback_versions", [])) if str(v).strip()
        ]
        if not fallback_versions:
            return False, ""

        attempted_specs: List[str] = []

        for fallback_version in fallback_versions:
            if fallback_version == current_version:
                continue

            fallback_spec = self._compose_lib_spec(project_name, fallback_version)
            attempted_specs.append(fallback_spec)
            changed = self._replace_lib_dep_in_ini(project_path, project_name, fallback_spec)
            if not changed:
                continue

            ok, output, _err_type, _lib = self._run_pkg_install_once(
                project_path,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            if ok:
                attempts_text = ", ".join(attempted_specs) if attempted_specs else fallback_spec
                return (
                    True,
                    "Auto-fix: switched "
                    f"{project_name} to {fallback_spec} and dependency sync succeeded "
                    f"(attempts: {attempts_text}).",
                )

            # Keep trying the next fallback, but keep config close to what we're testing.
            _ = output

        attempts_text = ", ".join(attempted_specs) if attempted_specs else "none"
        return (
            False,
            "Auto-fix: tried fallback versions for "
            f"{project_name} ({attempts_text}) but dependency sync still failed.",
        )

    def _lib_project_name(self, spec: str) -> str:
        """Return project name from a lib_deps specification."""
        text = (spec or "").strip()
        if "@" in text:
            text = text.split("@", 1)[0].strip()
        return text

    def _lib_version(self, spec: str) -> str:
        """Return version segment from a lib_deps specification."""
        text = (spec or "").strip()
        if "@" in text:
            return text.split("@", 1)[1].strip()
        return ""

    def _compose_lib_spec(self, project_name: str, version: str) -> str:
        """Compose a valid PlatformIO lib spec from project name + version."""
        if version == "latest":
            return project_name
        if not version.startswith("@"):
            return f"{project_name}@{version}"
        return f"{project_name}{version}"

    def _canonicalize_lib_dep_spec(self, spec: str) -> str:
        """Map known aliases to canonical dependency specifications."""
        candidate = (spec or "").strip()
        if not candidate:
            return ""

        # Normalize malformed specs like name@1.2.3@1.2.3 (keep first version only).
        if candidate.count("@") > 1:
            project, remainder = candidate.split("@", 1)
            first_version = remainder.split("@", 1)[0].strip()
            candidate = f"{project.strip()}@{first_version}" if first_version else project.strip()

        for rule in LIBRARY_RULES.values():
            canonical = str(rule.get("canonical", "")).strip()
            aliases = [str(a).strip() for a in list(rule.get("aliases", []))]
            canonical_project = self._lib_project_name(canonical)

            # If candidate starts with the canonical full spec and has trailing junk,
            # force canonical to avoid repeated @version growth.
            if canonical and candidate.startswith(canonical + "@"):
                return canonical

            # If project matches canonical and version is malformed/repeated, fallback to canonical.
            if canonical_project and self._lib_project_name(candidate) == canonical_project and candidate.count("@") > 1:
                return canonical

            if candidate == canonical or candidate in aliases:
                return canonical
        return candidate

    def _collect_lib_deps_from_ini(
        self,
        project_path: str,
        env: Optional[str] = None,
    ) -> List[str]:
        """Extract effective lib_deps entries from a PlatformIO env section."""
        ini_path = os.path.join(project_path, "platformio.ini")
        if not os.path.exists(ini_path):
            return []

        with open(ini_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()

        target_env = (env or "").strip().lower()
        section_start: Optional[int] = None
        first_env_start: Optional[int] = None
        section_end = len(lines)

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[env:") and stripped.endswith("]"):
                env_name = stripped[5:-1].strip().lower()
                if first_env_start is None:
                    first_env_start = idx
                if target_env and env_name == target_env:
                    section_start = idx
                    break

        if section_start is None:
            section_start = first_env_start
        if section_start is None:
            return []

        for idx in range(section_start + 1, len(lines)):
            if lines[idx].strip().startswith("["):
                section_end = idx
                break

        specs: List[str] = []
        for idx in range(section_start + 1, section_end):
            stripped = lines[idx].strip()
            lower = stripped.lower()
            if not stripped or stripped.startswith(("#", ";")):
                continue

            if lower.startswith("lib_deps"):
                _, _, rhs = stripped.partition("=")
                inline = rhs.strip()
                if inline and not inline.startswith(("#", ";")):
                    specs.append(inline)

                nested_idx = idx + 1
                while nested_idx < section_end:
                    nested_line = lines[nested_idx]
                    nested_stripped = nested_line.strip()
                    if not nested_line.startswith((" ", "\t")):
                        break
                    if nested_stripped and not nested_stripped.startswith(("#", ";")):
                        specs.append(nested_stripped)
                    nested_idx += 1
                break

        unique_specs: List[str] = []
        seen_projects: set[str] = set()
        for spec in specs:
            canonical_spec = self._canonicalize_lib_dep_spec(spec)
            project_name = self._lib_project_name(canonical_spec).lower()
            if not project_name or project_name in seen_projects:
                continue
            seen_projects.add(project_name)
            unique_specs.append(canonical_spec)
        return unique_specs

    def _prefetch_declared_libraries(
        self,
        project_path: str,
        env: Optional[str] = None,
        timeout_seconds: int = 45,
    ) -> List[str]:
        """Best-effort prefetch of declared lib_deps before global sync."""
        messages: List[str] = []
        specs = self._collect_lib_deps_from_ini(project_path, env=env)
        if not specs:
            return messages

        messages.append("Dependency prefetch targets: " + ", ".join(specs))

        for spec in specs:
            cmd = [self.platformio_path, "pkg", "install", "--library", spec]
            try:
                result = subprocess.run(
                    cmd,
                    cwd=project_path,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                messages.append(f"Dependency prefetch warning: timeout while prefetching {spec}.")
                continue
            except Exception as exc:  # noqa: BLE001
                messages.append(
                    f"Dependency prefetch warning: could not prefetch {spec}: {exc}"
                )
                continue

            if result.returncode == 0:
                messages.append(f"Dependency prefetch OK: {spec}")
                continue

            output = (result.stdout + result.stderr).strip()
            err_type, _library_key = self._classify_pkg_install_error(output)
            messages.append(
                "Dependency prefetch warning: "
                f"{spec} failed ({err_type}), continuing with global dependency sync."
            )

        return messages

    def _replace_lib_dep_in_ini(
        self,
        project_path: str,
        project_name: str,
        replacement_spec: str,
    ) -> bool:
        """Replace a dependency entry in platformio.ini by project name."""
        ini_path = os.path.join(project_path, "platformio.ini")
        if not os.path.exists(ini_path):
            return False

        with open(ini_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()

        changed = False
        normalized_target = project_name.lower()
        replacement_line = f"    {replacement_spec}"
        target_rule_key = self._detect_library_key_in_text(replacement_spec.lower())

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";", "[")):
                continue
            if stripped.lower().startswith("lib_deps"):
                continue
            if line.startswith(" ") or line.startswith("\t"):
                existing_project = self._lib_project_name(stripped).lower()
                same_rule = False
                if target_rule_key:
                    existing_rule_key = self._detect_library_key_in_text(stripped.lower())
                    same_rule = existing_rule_key == target_rule_key

                if (existing_project == normalized_target or same_rule) and stripped != replacement_spec:
                    lines[idx] = replacement_line
                    changed = True

        if changed:
            content = "\n".join(lines).rstrip() + "\n"
            with open(ini_path, "w", encoding="utf-8") as fh:
                fh.write(content)
        return changed
    
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
        logger.info("Build start: env=%s project=%s", env or "default", project_path)
        history_summary = self._recent_project_history_summary(project_path)

        ok_preflight, preflight_msgs, preflight_err = self._preflight_before_build_upload(
            project_path,
            env=env,
            action="build",
        )

        if not ok_preflight:
            elapsed = time.time() - start
            logger.error("Build aborted at preflight: %s", preflight_err)
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
                logger.info("Build successful: env=%s time=%.2fs", env or "default", elapsed)
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
            logger.error("Build failed: env=%s code=%s", env or "default", result.returncode)
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
            logger.error("Build timeout: env=%s", env or "default")
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
            logger.exception("Build exception: env=%s", env or "default")
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
        logger.info(
            "Upload start: env=%s port=%s project=%s",
            env or "default",
            port,
            project_path,
        )
        history_summary = self._recent_project_history_summary(project_path)

        ok_preflight, preflight_msgs, preflight_err = self._preflight_before_build_upload(
            project_path,
            env=env,
            action="upload",
            port=port,
        )

        if not ok_preflight:
            elapsed = time.time() - start
            logger.error("Upload aborted at preflight: %s", preflight_err)
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
                logger.info("Upload successful: env=%s port=%s time=%.2fs", env or "default", port, elapsed)
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
            logger.error(
                "Upload failed: env=%s port=%s code=%s",
                env or "default",
                port,
                result.returncode,
            )
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
            logger.error("Upload timeout: env=%s port=%s", env or "default", port)
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
            logger.exception("Upload exception: env=%s port=%s", env or "default", port)
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

    def _render_i2c_scanner_sketch(self, address_start: int, address_end: int) -> str:
        """Return an Arduino sketch that scans I2C addresses and prints results."""
        return (
            "#include <Arduino.h>\n"
            "#include <Wire.h>\n\n"
            f"const uint8_t I2C_START = 0x{address_start:02X};\n"
            f"const uint8_t I2C_END = 0x{address_end:02X};\n\n"
            "void setup() {\n"
            "  Serial.begin(9600);\n"
            "  while (!Serial) { }\n"
            "  Wire.begin();\n"
            "  delay(300);\n"
            "  Serial.println(\"I2C scan start\");\n"
            "}\n\n"
            "void loop() {\n"
            "  uint8_t found = 0;\n"
            "  for (uint8_t addr = I2C_START; addr <= I2C_END; addr++) {\n"
            "    Wire.beginTransmission(addr);\n"
            "    uint8_t err = Wire.endTransmission();\n"
            "    if (err == 0) {\n"
            "      Serial.print(\"I2C found at 0x\");\n"
            "      if (addr < 16) Serial.print('0');\n"
            "      Serial.println(addr, HEX);\n"
            "      found++;\n"
            "    }\n"
            "  }\n"
            "  if (found == 0) {\n"
            "    Serial.println(\"I2C no devices found\");\n"
            "  } else {\n"
            "    Serial.print(\"I2C devices total: \");\n"
            "    Serial.println(found);\n"
            "  }\n"
            "  Serial.println(\"I2C scan end\");\n"
            "  delay(2000);\n"
            "}\n"
        )

    def scan_i2c_bus(
        self,
        project_path: str,
        port: str,
        env: Optional[str] = None,
        address_start: int = 0x03,
        address_end: int = 0x77,
        baud: int = 9600,
        monitor_seconds: int = 8,
    ) -> Dict:
        """Compile/upload a temporary I2C scanner sketch and parse found addresses."""
        if not self.platformio_path:
            return {"ok": False, "addresses": [], "output": "", "error": "PlatformIO not available"}

        proj_abs = os.path.abspath(project_path)
        src_dir = os.path.join(proj_abs, "src")
        main_cpp = os.path.join(src_dir, "main.cpp")
        if not os.path.isdir(proj_abs):
            return {"ok": False, "addresses": [], "output": "", "error": f"Project directory not found: {proj_abs}"}

        os.makedirs(src_dir, exist_ok=True)

        original_exists = os.path.exists(main_cpp)
        original_content = ""
        if original_exists:
            with open(main_cpp, "r", encoding="utf-8", errors="replace") as fh:
                original_content = fh.read()

        logger.info("I2C scan start: env=%s port=%s project=%s", env or "default", port, proj_abs)

        scanner_output = ""
        found_addresses: List[str] = []
        try:
            scanner_code = self._render_i2c_scanner_sketch(address_start, address_end)
            with open(main_cpp, "w", encoding="utf-8") as fh:
                fh.write(scanner_code)

            build_result = self.build_sketch(proj_abs, env=env)
            if not build_result.get("ok"):
                return {
                    "ok": False,
                    "addresses": [],
                    "output": build_result.get("output", ""),
                    "error": build_result.get("error", "Build failed while preparing I2C scanner"),
                }

            upload_result = self.upload_firmware(proj_abs, port=port, env=env)
            if not upload_result.get("ok"):
                return {
                    "ok": False,
                    "addresses": [],
                    "output": upload_result.get("output", ""),
                    "error": upload_result.get("error", "Upload failed while preparing I2C scanner"),
                }

            monitor_cmd = [
                self.platformio_path,
                "device",
                "monitor",
                "--port",
                port,
                "--baud",
                str(baud),
                "--quiet",
                "--raw",
            ]
            try:
                mon = subprocess.run(
                    monitor_cmd,
                    cwd=proj_abs,
                    capture_output=True,
                    text=True,
                    timeout=max(2, monitor_seconds),
                )
                scanner_output = (mon.stdout + mon.stderr).strip()
            except subprocess.TimeoutExpired as exc:
                scanner_output = ((exc.stdout or "") + (exc.stderr or "")).strip()

            addr_matches = re.findall(r"0x([0-9A-Fa-f]{2})", scanner_output)
            found_addresses = sorted({f"0x{m.upper()}" for m in addr_matches})

            logger.info("I2C scan complete: found=%s", ", ".join(found_addresses) if found_addresses else "none")
            return {
                "ok": True,
                "addresses": found_addresses,
                "output": scanner_output,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("I2C scan exception")
            return {
                "ok": False,
                "addresses": [],
                "output": scanner_output,
                "error": str(exc),
            }
        finally:
            try:
                if original_exists:
                    with open(main_cpp, "w", encoding="utf-8") as fh:
                        fh.write(original_content)
                elif os.path.exists(main_cpp):
                    os.remove(main_cpp)
            except Exception as restore_exc:  # noqa: BLE001
                self.on_error(f"I2C scanner restore warning: {restore_exc}")
    
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
        for rule in LIBRARY_RULES.values():
            tokens = [str(t).lower() for t in list(rule.get("include_tokens", []))]
            canonical = str(rule.get("canonical", "")).strip()
            if not canonical:
                continue
            if any(token in includes for token in tokens):
                needed.append(canonical)

        with open(ini_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        alias_fixed = False
        normalized_lines: List[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if line.startswith((" ", "\t")) and stripped and not stripped.startswith(("#", ";")):
                canonical_spec = self._canonicalize_lib_dep_spec(stripped)
                if canonical_spec and canonical_spec != stripped:
                    line = f"    {canonical_spec}"
                    alias_fixed = True
            normalized_lines.append(line)
        content = "\n".join(normalized_lines)

        # Remove duplicate entries by canonical project name while keeping first appearance.
        deduped_lines: List[str] = []
        seen_projects: set[str] = set()
        for line in content.splitlines():
            stripped = line.strip()
            if line.startswith(" ") or line.startswith("\t"):
                if stripped and not stripped.startswith(("#", ";")):
                    project_name = self._lib_project_name(stripped).lower()
                    if project_name in seen_projects:
                        alias_fixed = True
                        continue
                    seen_projects.add(project_name)
            deduped_lines.append(line)
        content = "\n".join(deduped_lines)

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
