from pathlib import Path
import os
import sys
from unittest.mock import patch
from types import SimpleNamespace

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


def test_parse_windows_output_ignores_bluetooth_and_detects_ch340() -> None:
    manager = _mgr()
    output = """COM8
----
Hardware ID: BTHENUM\\{00001101-0000-1000-8000-00805F9B34FB}_VID&000105D6_PID&000A\\7&1A46A826&1&84AC60002D7B_C00000000
Description: Serie estandar sobre el vinculo Bluetooth (COM8)

COM5
----
Hardware ID: USB VID:PID=1A86:7523 SER= LOCATION=1-9
Description: USB-SERIAL CH340 (COM5)
"""

    devices = manager._parse_pio_device_output(output)

    assert len(devices) == 1
    assert devices[0]["port"] == "COM5"
    assert devices[0]["board"] == "arduino_uno"


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
    assert "marcoschwartz/LiquidCrystal_I2C@1.1.4" in content


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
    assert "marcoschwartz/LiquidCrystal_I2C@1.1.4" in content


def test_ensure_lib_deps_deduplicates_lcd_entries(tmp_path: Path) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    marcoschwartz/LiquidCrystal I2C\n"
        "    johnrickman/LiquidCrystal_I2C@^1.1.4\n",
        encoding="utf-8",
    )

    msg = manager._ensure_lib_deps_from_source(
        str(tmp_path),
        "#include <LiquidCrystal_I2C.h>\n",
    )
    content = ini.read_text(encoding="utf-8")

    assert "invalid library aliases" in msg
    assert content.count("marcoschwartz/LiquidCrystal_I2C@1.1.4") == 1


def test_ensure_lib_deps_does_not_duplicate_canonical_version(tmp_path: Path) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    marcoschwartz/LiquidCrystal_I2C@1.1.4\n",
        encoding="utf-8",
    )

    _ = manager._ensure_lib_deps_from_source(str(tmp_path), "")
    content = ini.read_text(encoding="utf-8")

    assert "marcoschwartz/LiquidCrystal_I2C@1.1.4@1.1.4" not in content
    assert content.count("marcoschwartz/LiquidCrystal_I2C@1.1.4") == 1


def test_canonicalize_lib_dep_collapses_repeated_at_version() -> None:
    manager = _mgr()

    normalized = manager._canonicalize_lib_dep_spec(
        "marcoschwartz/LiquidCrystal_I2C@1.1.4@1.1.4"
    )

    assert normalized == "marcoschwartz/LiquidCrystal_I2C@1.1.4"


def test_sync_dependencies_retries_network_and_recovers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Connection reset by peer while fetching packages",
            )
        return SimpleNamespace(returncode=0, stdout="Installed", stderr="")

    monkeypatch.setattr("app.arduino_manager.subprocess.run", fake_run)
    monkeypatch.setattr("app.arduino_manager.time.sleep", lambda _x: None)

    ok, messages, err = manager._sync_dependencies_with_recovery(str(tmp_path), env="uno")

    assert ok is True
    assert err == ""
    assert calls["n"] == 2
    assert any("recovered on retry" in m for m in messages)


def test_sync_dependencies_fallbacks_lcd_version(
    tmp_path: Path,
    monkeypatch,
) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    johnrickman/LiquidCrystal_I2C@^1.1.4\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def fake_run(*args, **kwargs):
        calls["n"] += 1
        current = ini.read_text(encoding="utf-8")
        if "johnrickman/LiquidCrystal_I2C@^1.1.4" in current:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Unknown package 'johnrickman/LiquidCrystal_I2C@^1.1.4'",
            )
        return SimpleNamespace(returncode=0, stdout="Installed", stderr="")

    monkeypatch.setattr("app.arduino_manager.subprocess.run", fake_run)

    ok, messages, err = manager._sync_dependencies_with_recovery(str(tmp_path), env="uno")
    content = ini.read_text(encoding="utf-8")

    assert ok is True
    assert err == ""
    assert "marcoschwartz/LiquidCrystal_I2C@1.1.3" in content
    assert any("automatic library fallback" in m for m in messages)


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
    err_lower = err.lower()
    assert (
        "package install failed" in err_lower
        or "package install error" in err_lower
    )


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

def test_collect_lib_deps_deduplicates_aliases(tmp_path: Path) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    marcoschwartz/LiquidCrystal I2C\n"
        "    johnrickman/LiquidCrystal_I2C@^1.1.4\n"
        "    adafruit/RTClib@^1.14.2\n",
        encoding="utf-8",
    )

    deps = manager._collect_lib_deps_from_ini(str(tmp_path), env="uno")

    assert deps == [
        "marcoschwartz/LiquidCrystal_I2C@1.1.4",
        "adafruit/RTClib@^1.14.2",
    ]


def test_preflight_prefetch_failure_is_non_blocking(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()

    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    adafruit/RTClib@^1.14.2\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        cmd = args[0]
        if "--library" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="Connection reset by peer")
        return SimpleNamespace(returncode=0, stdout="Installed", stderr="")

    monkeypatch.setattr("app.arduino_manager.subprocess.run", fake_run)

    ok, messages, err = manager._preflight_before_build_upload(str(tmp_path), env="uno", action="build")

    assert ok is True
    assert err == ""
    assert any("Dependency prefetch warning" in m for m in messages)
    assert any("Dependency sync OK" in m for m in messages)


def test_preflight_runs_prefetch_before_sync(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n"
        "lib_deps =\n"
        "    adafruit/RTClib@^1.14.2\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    order = []
    original_prefetch = manager._prefetch_declared_libraries

    def wrapped_prefetch(*args, **kwargs):
        order.append("prefetch")
        return original_prefetch(*args, **kwargs)

    def fake_sync(*args, **kwargs):
        order.append("sync")
        return True, ["Dependency sync OK (pio pkg install)."], ""

    monkeypatch.setattr(manager, "_prefetch_declared_libraries", wrapped_prefetch)
    monkeypatch.setattr(manager, "_sync_dependencies_with_recovery", fake_sync)
    monkeypatch.setattr(
        "app.arduino_manager.subprocess.run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="Installed", stderr=""),
    )

    ok, _messages, err = manager._preflight_before_build_upload(str(tmp_path), env="uno", action="build")

    assert ok is True
    assert err == ""
    assert order == ["prefetch", "sync"]


def test_preflight_upload_accepts_windows_com_port(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    monkeypatch.setattr(manager, "_sync_dependencies_with_recovery", lambda *a, **k: (True, [], ""))
    monkeypatch.setattr(manager, "_prefetch_declared_libraries", lambda *a, **k: [])

    ok, _messages, err = manager._preflight_before_build_upload(
        str(tmp_path),
        env="uno",
        action="upload",
        port="COM5",
    )

    assert ok is True
    assert err == ""


def test_preflight_upload_still_rejects_missing_non_windows_port(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\n"
        "platform = atmelavr\n"
        "board = uno\n"
        "framework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.cpp").write_text("#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n", encoding="utf-8")

    monkeypatch.setattr(manager, "_sync_dependencies_with_recovery", lambda *a, **k: (True, [], ""))
    monkeypatch.setattr(manager, "_prefetch_declared_libraries", lambda *a, **k: [])

    ok, _messages, err = manager._preflight_before_build_upload(
        str(tmp_path),
        env="uno",
        action="upload",
        port="/dev/ttyUSB_MISSING",
    )

    assert ok is False
    assert "Serial port not found" in err


def test_scan_i2c_bus_detects_addresses_and_restores_main(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    main_cpp = src / "main.cpp"
    original = "#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n"
    main_cpp.write_text(original, encoding="utf-8")

    monkeypatch.setattr(manager, "build_sketch", lambda *a, **k: {"ok": True, "output": "", "error": ""})
    monkeypatch.setattr(manager, "upload_firmware", lambda *a, **k: {"ok": True, "output": "", "error": ""})

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout="I2C scan start\nI2C found at 0x27\nI2C found at 0x3F\nI2C scan end\n",
            stderr="",
        )

    monkeypatch.setattr("app.arduino_manager.subprocess.run", fake_run)

    result = manager.scan_i2c_bus(str(tmp_path), port="COM5", env="uno", monitor_seconds=2)

    assert result["ok"] is True
    assert result["addresses"] == ["0x27", "0x3F"]
    assert main_cpp.read_text(encoding="utf-8") == original


def test_scan_i2c_bus_returns_build_error_and_restores_main(tmp_path: Path, monkeypatch) -> None:
    manager = _mgr()
    ini = tmp_path / "platformio.ini"
    ini.write_text(
        "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n",
        encoding="utf-8",
    )
    src = tmp_path / "src"
    src.mkdir()
    main_cpp = src / "main.cpp"
    original = "#include <Arduino.h>\nvoid setup(){}\nvoid loop(){}\n"
    main_cpp.write_text(original, encoding="utf-8")

    monkeypatch.setattr(
        manager,
        "build_sketch",
        lambda *a, **k: {"ok": False, "output": "build output", "error": "build failed"},
    )

    result = manager.scan_i2c_bus(str(tmp_path), port="COM5", env="uno", monitor_seconds=2)

    assert result["ok"] is False
    assert "build failed" in result["error"].lower()
    assert main_cpp.read_text(encoding="utf-8") == original
