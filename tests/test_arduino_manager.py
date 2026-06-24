from pathlib import Path
import os
import sys
from unittest.mock import patch

from app.arduino_manager import ArduinoManager


def _mgr() -> ArduinoManager:
    # Use an existing binary path to avoid noisy platform detection errors in tests.
    fallback_bin = "C:\\Windows\\System32\\cmd.exe" if sys.platform == "win32" else "/bin/echo"
    return ArduinoManager({"platformio_path": fallback_bin})


def test_parse_platformio_multiline_output_detects_uno() -> None:
    manager = _mgr()
    output = """/dev/ttyS0
----------
Hardware ID: n/a
Description: n/a

/dev/ttyUSB0
------------
Hardware ID: USB VID:PID=1A86:7523 LOCATION=1-4
Description: USB Serial
"""

    devices = manager._parse_pio_device_output(output)

    assert len(devices) == 1
    assert devices[0]["port"] == "/dev/ttyUSB0"
    assert devices[0]["board"] == "arduino_uno"


def test_prepare_sources_adds_arduino_include_when_missing(tmp_path: Path) -> None:
    manager = _mgr()
    project = tmp_path
    src = project / "src"
    src.mkdir()
    main_cpp = src / "main.cpp"
    main_cpp.write_text("void setup(){}\nvoid loop(){}\n", encoding="utf-8")

    msg = manager._prepare_platformio_sources(str(project))
    content = main_cpp.read_text(encoding="utf-8")

    assert "Auto-fixed src/main.cpp" in msg
    assert content.startswith("#include <Arduino.h>")


def test_normalize_hwid_extracts_vid_pid() -> None:
    manager = _mgr()
    hwid = "USB VID:PID=1A86:7523 LOCATION=1-4"

    normalized = manager._normalize_hwid(hwid)

    assert normalized == "1a86:7523"


def test_ensure_lib_deps_infers_rtclib_and_lcd_i2c(tmp_path: Path) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )

    source = "#include <RTClib.h>\n#include <LiquidCrystal_I2C.h>\n"
    msg = manager._ensure_lib_deps_from_source(str(tmp_path), source)
    content = ini.read_text(encoding="utf-8")

    assert "inferred lib_deps" in msg
    assert "adafruit/RTClib@^1.14.2" in content
    assert "johnrickman/LiquidCrystal_I2C@^1.1.4" in content


def test_ensure_lib_deps_fixes_invalid_lcd_alias(tmp_path: Path) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    marcoschwartz/LiquidCrystal I2C @ ^1.1.4\n",
        encoding="utf-8",
    )

    msg = manager._ensure_lib_deps_from_source(str(tmp_path), "")
    content = ini.read_text(encoding="utf-8")

    assert "invalid library aliases" in msg
    assert "marcoschwartz/LiquidCrystal I2C" not in content
    assert "johnrickman/LiquidCrystal_I2C@^1.1.4" in content


def test_project_history_roundtrip(tmp_path: Path) -> None:
    manager = _mgr()
    project = tmp_path
    history_file = project / ".willy_build_history.json"

    manager._append_project_history(
        str(project),
        action="build",
        success=False,
        env="uno",
        error_msg="compile error",
        notes="details",
    )
    manager._append_project_history(
        str(project),
        action="upload",
        success=True,
        env="uno",
        port="/dev/ttyUSB0",
    )

    assert history_file.exists()
    hist = manager._load_project_history(str(project))
    assert len(hist) == 2
    summary = manager._recent_project_history_summary(str(project))
    assert "Recent project history" in summary
    assert "UPLOAD" in summary or "BUILD" in summary


def test_preflight_blocks_when_pkg_install_fails(tmp_path: Path) -> None:
    manager = _mgr()
    manager.platformio_path = "/bin/false"

    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    ok, _msgs, err = manager._preflight_before_build_upload(str(tmp_path), env="uno", action="build")
    assert ok is False
    assert "package install failed" in err.lower()


def test_build_blocks_on_preflight_failure(tmp_path: Path) -> None:
    manager = _mgr()
    manager.platformio_path = "/bin/echo"

    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    manager._preflight_before_build_upload = lambda *a, **k: (False, ["preflight failed"], "preflight failed")
    result = manager.build_sketch(str(tmp_path), env="uno")

    assert result["ok"] is False
    assert "preflight failed" in result["error"].lower()


def test_detect_platformio_uses_windows_common_paths() -> None:
    def fake_exists(path_obj) -> bool:
        return str(path_obj).lower().endswith("python\\scripts\\pio.exe")

    with patch("app.arduino_manager.sys.platform", "win32"), patch.dict(
        "app.arduino_manager.os.environ",
        {"APPDATA": "C:\\Users\\tester\\AppData\\Roaming", "LOCALAPPDATA": ""},
        clear=False,
    ), patch("app.arduino_manager.subprocess.run", side_effect=FileNotFoundError), patch(
        "app.arduino_manager.Path.exists", fake_exists
    ):
        mgr = ArduinoManager({})
        assert mgr.platformio_path is not None
        assert mgr.platformio_path.lower().endswith("python\\scripts\\pio.exe")
