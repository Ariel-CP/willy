import json
from pathlib import Path

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


def test_session_logger_redacts_secrets_in_message_and_command(tmp_path: Path) -> None:
    session_logger_module.SESSIONS_DIR = str(tmp_path)

    logger = SessionLogger()
    logger.log_message("user", "mi key es sk-proj-1234567890abcdef1234567890abcdef")
    logger.log_command(
        "export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz123456",
        "Authorization: Bearer top-secret-token-value",
    )

    data = json.loads(Path(logger.path).read_text(encoding="utf-8"))
    events = data.get("events", [])

    msg_event = next(e for e in events if e.get("type") == "message")
    cmd_event = next(e for e in events if e.get("type") == "command")

    assert "sk-proj-" not in msg_event.get("text", "")
    assert "[REDACTED_API_KEY]" in msg_event.get("text", "")
    assert "top-secret-token-value" not in cmd_event.get("output", "")
    assert "[REDACTED_TOKEN]" in cmd_event.get("output", "")
