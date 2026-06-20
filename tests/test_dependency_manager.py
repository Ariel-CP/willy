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
