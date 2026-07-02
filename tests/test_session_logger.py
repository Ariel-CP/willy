import json
from pathlib import Path
from datetime import datetime, timedelta

import app.session_logger as session_logger_module
from app.session_logger import SessionLogger


def test_session_logger_writes_diagnostics_file(tmp_path: Path) -> None:
    # Redirect session files to temp directory for test isolation.
    session_logger_module.SESSIONS_DIR = str(tmp_path)

    logger = SessionLogger()
    logger.log_event("test_event", component="tests", data={"k": "v"})
    logger.log_error("tests", "boom")

    assert Path(logger.path).exists()
    assert Path(logger.diagnostics_path).exists()

    data = json.loads(Path(logger.path).read_text(encoding="utf-8"))
    event_types = [event.get("type") for event in data.get("events", [])]

    assert "system_event" in event_types
    assert "system_error" in event_types


def test_session_logger_exports_audit_report(tmp_path: Path) -> None:
    session_logger_module.SESSIONS_DIR = str(tmp_path)

    logger = SessionLogger()
    logger.log_message("user", "hola")
    logger.log_command("echo test", "ok")
    logger.log_event("custom_event", component="tests", data={"x": 1})

    output_path = tmp_path / "audit_report.json"
    exported = logger.export_audit_report(str(output_path))

    assert exported == str(output_path)
    assert output_path.exists()

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["totals"]["sessions"] >= 1
    assert report["totals"]["events"] >= 3
    assert report["totals"]["messages"] >= 1
    assert report["totals"]["commands"] >= 1


def test_session_logger_exports_audit_report_with_date_range(tmp_path: Path) -> None:
    session_logger_module.SESSIONS_DIR = str(tmp_path)

    logger = SessionLogger()
    logger.log_message("user", "mensaje en rango")

    output_path = tmp_path / "audit_range.json"
    start_iso = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
    logger.export_audit_report(str(output_path), start_iso=start_iso)

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["totals"]["events"] == 0
    assert report["totals"]["sessions"] == 0
