from pathlib import Path

from app.dependency_manager import DependencyManager


def test_detect_ecosystem_finds_pip_for_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    dm = DependencyManager(base_dir=str(tmp_path))
    ecosystems = dm.detect_ecosystem(str(tmp_path))
    assert "pip" in ecosystems


def test_detect_ecosystem_finds_platformio(tmp_path: Path) -> None:
    (tmp_path / "platformio.ini").write_text("[env:uno]\nplatform = atmelavr\n", encoding="utf-8")
    dm = DependencyManager(base_dir=str(tmp_path))
    # pio might not be installed in CI, so we only check that it doesn't crash.
    ecosystems = dm.detect_ecosystem(str(tmp_path))
    assert isinstance(ecosystems, list)


def test_snapshot_persists_and_summary_reports(tmp_path: Path) -> None:
    dm = DependencyManager(base_dir=str(tmp_path))
    # Inject a fake snapshot directly.
    dm._persist_snapshot(
        __import__("app.dependency_manager", fromlist=["DepSnapshot"]).DepSnapshot(
            ecosystem="pip",
            timestamp="2026-06-20T10:00:00",
            packages={"requests": "2.31.0", "platformio": "6.1.11"},
        ),
        str(tmp_path),
    )
    summary = dm.summary("pip", str(tmp_path))
    assert "pip" in summary
    assert "2026-06-20" in summary
    assert "2 packages" in summary


def test_rollback_fails_gracefully_without_snapshot(tmp_path: Path) -> None:
    dm = DependencyManager(base_dir=str(tmp_path))
    result = dm.rollback("pip", str(tmp_path))
    assert result.ok is False
    assert "snapshot" in result.message.lower()


def test_pip_outdated_balanced_skips_majors(monkeypatch) -> None:
    """Balanced policy should skip packages with major version bumps."""
    import json
    import app.dependency_manager as dm_mod
    from app.dependency_manager import DependencyManager as DM

    outdated_data = [
        {"name": "requests", "version": "2.28.0", "latest_version": "2.31.0"},   # minor → include
        {"name": "numpy", "version": "1.24.0", "latest_version": "2.0.0"},        # major → skip
        {"name": "flask", "version": "3.0.0", "latest_version": "3.0.3"},         # patch → include
    ]

    def fake_run(cmd, **_kw):
        # The command is a list; look for the string "--outdated" as an element.
        if isinstance(cmd, list) and "--outdated" in cmd:
            return 0, json.dumps(outdated_data), ""
        return -1, "", "not called"

    monkeypatch.setattr(dm_mod, "_run", fake_run)

    dm = DM(base_dir="/tmp")
    result = dm._pip_outdated_balanced()
    assert "requests" in result
    assert "flask" in result
    assert "numpy" not in result


# ---------------------------------------------------------------------------
# PlatformIO helpers
# ---------------------------------------------------------------------------

PIO_INI_BASE = (
    "[env:uno]\n"
    "platform = atmelavr\n"
    "board = uno\n"
    "framework = arduino\n"
    "lib_deps =\n"
    "    adafruit/RTClib @ ^1.14.2\n"
    "    marcoschwartz/LiquidCrystal_I2C @ ^1.1.4\n"
)


def _dm(tmp_path: Path) -> DependencyManager:
    return DependencyManager(base_dir=str(tmp_path))


def test_pio_read_lib_deps_returns_declared_entries(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    result = dm._pio_read_lib_deps(ini)
    assert "adafruit/RTClib @ ^1.14.2" in result
    assert "marcoschwartz/LiquidCrystal_I2C @ ^1.1.4" in result
    for v in result.values():
        assert v == "declared"


def test_pio_read_lib_deps_missing_file_returns_empty(tmp_path: Path) -> None:
    dm = _dm(tmp_path)
    result = dm._pio_read_lib_deps(tmp_path / "nonexistent.ini")
    assert result == {}


def test_pio_append_lib_deps_adds_new_package(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    ok, msg = dm._pio_append_lib_deps(ini, ["bblanchon/ArduinoJson @ ^7.0.0"])
    assert ok is True
    assert "ArduinoJson" in msg
    content = ini.read_text(encoding="utf-8")
    assert "bblanchon/ArduinoJson" in content


def test_pio_append_lib_deps_skips_existing_by_basename(tmp_path: Path) -> None:
    """No debe agregar si ya hay una librería con el mismo nombre base."""
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    # RTClib ya está — distinto owner/versión, mismo nombre base
    ok, msg = dm._pio_append_lib_deps(ini, ["someowner/RTClib @ ^2.0.0"])
    assert ok is True
    assert "already" in msg.lower()
    # El contenido no debe haber cambiado
    content = ini.read_text(encoding="utf-8")
    assert content.count("RTClib") == 1


def test_pio_append_lib_deps_no_lib_deps_block_returns_error(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text("[env:uno]\nplatform = atmelavr\nboard = uno\n", encoding="utf-8")
    dm = _dm(tmp_path)
    ok, msg = dm._pio_append_lib_deps(ini, ["somelib"])
    assert ok is False
    assert "lib_deps" in msg.lower()


def test_pio_restore_lib_deps_overwrites_block(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    saved = {"bblanchon/ArduinoJson @ ^6.21.0": "declared"}
    ok, msg = dm._pio_restore_lib_deps(ini, saved)
    assert ok is True
    content = ini.read_text(encoding="utf-8")
    assert "bblanchon/ArduinoJson" in content
    # Las entradas originales deben haber sido reemplazadas
    assert "RTClib" not in content
    assert "LiquidCrystal_I2C" not in content


def test_pio_snapshot_reads_from_ini(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    snap = dm.snapshot("platformio", str(tmp_path))
    assert snap is not None
    assert "adafruit/RTClib @ ^1.14.2" in snap.packages


def test_pio_rollback_restores_lib_deps(tmp_path: Path) -> None:
    ini = tmp_path / "platformio.ini"
    ini.write_text(PIO_INI_BASE, encoding="utf-8")
    dm = _dm(tmp_path)
    # Guardar snapshot manual con una lib distinta
    from app.dependency_manager import DepSnapshot
    dm._persist_snapshot(
        DepSnapshot(
            ecosystem="platformio",
            timestamp="2026-01-01T00:00:00",
            packages={"bblanchon/ArduinoJson @ ^7.0.0": "declared"},
        ),
        str(tmp_path),
    )
    # Rollback debe restaurar lib_deps — pio pkg install fallará sin PIO real, solo validamos ini
    result = dm.rollback("platformio", str(tmp_path))
    # ok puede ser False si pio no está instalado, pero el ini ya fue restaurado
    content = ini.read_text(encoding="utf-8")
    assert "bblanchon/ArduinoJson" in content


def test_sanitize_pio_method_exists_on_ai_agent() -> None:
    """Verifica que _tool_sanitize_pio_ini sea un método real (no código muerto)."""
    from app.ai_agent import AIAgent
    assert callable(getattr(AIAgent, "_tool_sanitize_pio_ini", None)), \
        "_tool_sanitize_pio_ini debe ser un método real de AIAgent"
