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
