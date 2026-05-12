from pathlib import Path

from app.arduino_manager import ArduinoManager


def _mgr() -> ArduinoManager:
    # Use an existing binary path to avoid noisy platform detection errors in tests.
    return ArduinoManager({"platformio_path": "/bin/echo"})


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
