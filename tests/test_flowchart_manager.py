import os

from app.flowchart_manager import FlowchartManager


def test_generate_flowchart_creates_mmd_in_project_outputs(tmp_path) -> None:
    project = tmp_path / "demo_project"
    src = project / "src"
    src.mkdir(parents=True)
    (src / "main.cpp").write_text(
        """
#include <Arduino.h>

void setup() {
}

void loop() {
}
""".strip(),
        encoding="utf-8",
    )

    manager = FlowchartManager(base_dir=str(tmp_path))
    result = manager.generate_from_project(str(project), title="Demo Flow")

    assert result.ok is True
    assert result.project_path == str(project)
    assert result.mmd_path.endswith(".mmd")
    assert os.path.isfile(result.mmd_path)
    assert f"{os.sep}outputs{os.sep}flows{os.sep}" in result.mmd_path

    content = (project / "outputs" / "flows" / os.path.basename(result.mmd_path)).read_text(encoding="utf-8")
    assert "flowchart TD" in content
    assert "File: src/main.cpp" in content


def test_generate_flowchart_invalid_project_path() -> None:
    manager = FlowchartManager(base_dir=".")
    result = manager.generate_from_project("/path/that/does/not/exist")

    assert result.ok is False
    assert "Project path not found" in result.message


# ---------------------------------------------------------------------------
# Arduino-specific flowchart tests
# ---------------------------------------------------------------------------

LCD_SKETCH = """\
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C lcd(0x27, 20, 4);

void setup() {
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Hola Willy");
}

void loop() {
  delay(1000);
}
"""


def test_parse_arduino_flow_extracts_setup_and_loop(tmp_path) -> None:
    fm = FlowchartManager(base_dir=str(tmp_path))
    flow = fm._parse_arduino_flow(LCD_SKETCH)
    assert "lcd.init()" in flow["setup"]
    assert "lcd.backlight()" in flow["setup"]
    assert "delay(1000)" in flow["loop"]
    assert "Wire.h" in flow["includes"]
    assert "LiquidCrystal_I2C.h" in flow["includes"]


def test_build_arduino_mermaid_contains_key_nodes(tmp_path) -> None:
    fm = FlowchartManager(base_dir=str(tmp_path))
    flow = fm._parse_arduino_flow(LCD_SKETCH)
    mmd = fm._build_arduino_mermaid("hola_willy", flow)
    assert "flowchart TD" in mmd
    assert "setup()" in mmd
    assert "loop()" in mmd
    assert "Power On" in mmd
    assert "lcd.init()" in mmd


def test_generate_from_ino_sketch_creates_mmd(tmp_path) -> None:
    sketch_dir = tmp_path / "hola_willy"
    sketch_dir.mkdir()
    ino = sketch_dir / "hola_willy.ino"
    ino.write_text(LCD_SKETCH, encoding="utf-8")

    fm = FlowchartManager(base_dir=str(tmp_path))
    result = fm.generate_from_ino_sketch(str(ino), title="hola_willy")

    assert result.ok is True
    assert result.mmd_path and os.path.isfile(result.mmd_path)
    content = open(result.mmd_path).read()
    assert "setup()" in content
    assert "loop()" in content
    assert "lcd.init()" in content


def test_generate_from_ino_sketch_missing_file(tmp_path) -> None:
    fm = FlowchartManager(base_dir=str(tmp_path))
    result = fm.generate_from_ino_sketch("/nonexistent/path/sketch.ino")
    assert result.ok is False
    assert "not found" in result.message.lower()


def test_parse_arduino_flow_handles_empty_sketch(tmp_path) -> None:
    fm = FlowchartManager(base_dir=str(tmp_path))
    flow = fm._parse_arduino_flow("void setup(){} void loop(){}")
    assert isinstance(flow["setup"], list)
    assert isinstance(flow["loop"], list)
