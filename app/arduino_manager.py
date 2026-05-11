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
        
        # Try common installation paths
        common_paths = [
            Path.home() / ".local" / "bin" / "pio",
            Path("/usr/local/bin/pio"),
            Path("/usr/bin/pio"),
        ]
        for path in common_paths:
            if path.exists():
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
            
            devices = []
            lines = result.stdout.strip().split("\n")
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith("Platform"):
                    continue
                
                # Parse: "/dev/ttyUSB0 | USB Serial Device | HWID: 10c4:ea60"
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 2:
                    port = parts[0]
                    description = parts[1]
                    hwid = parts[2].replace("HWID: ", "") if len(parts) > 2 else ""
                    
                    # Try to infer board type from description
                    board = self._infer_board_from_hwid(hwid, description)
                    
                    devices.append({
                        "port": port,
                        "description": description,
                        "hwid": hwid,
                        "board": board,
                    })
            
            return devices
        except Exception as e:
            self.on_error(f"Device detection error: {str(e)}")
            return []
    
    def _infer_board_from_hwid(self, hwid: str, description: str) -> str:
        """Infer board type from HWID or description."""
        # Common chip HWIDs
        hwid_map = {
            "10c4:ea60": "ch340",  # CH340
            "1a86:7523": "ch340",
            "2e8a:0005": "pico",   # Raspberry Pi Pico
            "1366:0105": "esp32",  # Espressif
            "1d6b:0109": "esp32",  # Generic USB Hub
        }
        
        if hwid in hwid_map:
            return hwid_map[hwid]
        
        # Infer from description
        desc_lower = description.lower()
        if "esp32" in desc_lower:
            return "esp32"
        elif "arduino" in desc_lower:
            return "arduino"
        elif "pico" in desc_lower:
            return "pico"
        elif "stm32" in desc_lower:
            return "stm32"
        else:
            return "unknown"
    
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
        if not self.platformio_path:
            return {
                "ok": False,
                "output": "",
                "error": "PlatformIO not available",
                "time_seconds": 0,
            }
        
        if not os.path.isdir(project_path):
            return {
                "ok": False,
                "output": "",
                "error": f"Project directory not found: {project_path}",
                "time_seconds": 0,
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
                timeout=300,  # 5 min timeout
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode == 0:
                self.on_status("Build successful")
                return {
                    "ok": True,
                    "output": output,
                    "error": "",
                    "time_seconds": 0,
                }
            else:
                return {
                    "ok": False,
                    "output": output,
                    "error": f"Build failed (exit code {result.returncode})",
                    "time_seconds": 0,
                }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "output": "",
                "error": "Build timeout (>5 min)",
                "time_seconds": 300,
            }
        except Exception as e:
            return {
                "ok": False,
                "output": "",
                "error": str(e),
                "time_seconds": 0,
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
        if not self.platformio_path:
            return {
                "ok": False,
                "output": "",
                "error": "PlatformIO not available",
                "time_seconds": 0,
            }
        
        if not os.path.isdir(project_path):
            return {
                "ok": False,
                "output": "",
                "error": f"Project directory not found: {project_path}",
                "time_seconds": 0,
            }
        
        # Check port access
        if not os.path.exists(port):
            return {
                "ok": False,
                "output": "",
                "error": f"Serial port not found: {port}",
                "time_seconds": 0,
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
                timeout=300,  # 5 min timeout
            )
            
            output = result.stdout + result.stderr
            
            if result.returncode == 0:
                self.on_status("Upload successful ✓")
                return {
                    "ok": True,
                    "output": output,
                    "error": "",
                    "time_seconds": 0,
                }
            else:
                return {
                    "ok": False,
                    "output": output,
                    "error": f"Upload failed (exit code {result.returncode})",
                    "time_seconds": 0,
                }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "output": "",
                "error": "Upload timeout (>5 min)",
                "time_seconds": 300,
            }
        except Exception as e:
            return {
                "ok": False,
                "output": "",
                "error": str(e),
                "time_seconds": 0,
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
