from pathlib import Path

from app.environment_memory import EnvironmentMemory


def test_refresh_creates_snapshot_and_history(tmp_path: Path) -> None:
    memory = EnvironmentMemory(base_dir=str(tmp_path))

    snapshot, changed = memory.refresh(
        preferences={"language": "es", "theme": "dark"},
        microcontrollers=[{"board": "esp32", "port": "/dev/ttyUSB0"}],
    )

    assert changed is True
    assert snapshot.get("system", {}).get("hostname")
    assert (tmp_path / "environment_memory.json").exists()
    assert (tmp_path / "environment_memory_history").exists()


def test_summary_for_prompt_contains_core_sections(tmp_path: Path) -> None:
    memory = EnvironmentMemory(base_dir=str(tmp_path))
    memory.refresh(
        preferences={"language": "es", "model": "gpt-4o"},
        microcontrollers=[{"board": "uno", "port": "/dev/ttyUSB1"}],
    )

    summary = memory.summary_for_prompt()

    assert "ENVIRONMENT_CONTEXT" in summary
    assert "tools_available=" in summary
    assert "microcontrollers=" in summary


def test_summary_for_prompt_includes_raspberry_hosts(tmp_path: Path) -> None:
    memory = EnvironmentMemory(base_dir=str(tmp_path))
    memory.refresh(
        preferences={"language": "es"},
        microcontrollers=[],
    )

    snapshot = memory.get_snapshot()
    snapshot.setdefault("network", {})["raspberry_candidates"] = ["raspberrypi.local"]
    memory._data["snapshot"] = snapshot

    summary = memory.summary_for_prompt()
    assert "raspberry_hosts=raspberrypi.local" in summary
