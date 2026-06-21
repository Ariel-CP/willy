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


def test_flush_is_atomic_no_partial_file(tmp_path: Path) -> None:
    """_flush escribe en .tmp y renombra, no deja un archivo parcial en error."""
    memory = EnvironmentMemory(base_dir=str(tmp_path))
    memory.refresh(preferences={"language": "es"}, microcontrollers=[])

    mem_file = tmp_path / "environment_memory.json"
    tmp_file = tmp_path / "environment_memory.tmp"

    # El archivo .json debe existir y el .tmp debe haber sido eliminado tras el rename
    assert mem_file.exists()
    assert not tmp_file.exists(), ".tmp no debe quedar después de _flush"


def test_concurrent_flush_does_not_corrupt(tmp_path: Path) -> None:
    """Múltiples threads llamando refresh simultáneamente no corrompen el JSON."""
    import threading
    memory = EnvironmentMemory(base_dir=str(tmp_path))
    errors: list[Exception] = []

    def worker():
        try:
            memory.refresh(preferences={"language": "es"}, microcontrollers=[])
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errores en threads: {errors}"
    # El archivo debe ser JSON válido al final
    import json
    data = json.loads((tmp_path / "environment_memory.json").read_text())
    assert isinstance(data, dict)
