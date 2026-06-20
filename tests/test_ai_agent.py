import time

import pytest

from app.ai_agent import AIAgent


class DummyTM:
    def __init__(self) -> None:
        self.output_callback = None

    def get_cwd(self) -> str:
        return "/tmp"

    def run_command(self, _command: str) -> None:
        return None

    def run_command_async(self, _command: str) -> None:
        return None


class DummyArduinoManager:
    def get_project_info(self, _project_path: str):
        return {
            "ok": True,
            "environments": ["uno", "esp32dev"],
            "default_env": "esp32dev",
            "error": "",
        }

    def detect_microcontrollers(self):
        return [{"port": "/dev/ttyUSB0", "board": "arduino_uno"}]


def _agent() -> AIAgent:
    return AIAgent(
        config={"default_board": "esp32"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )


def test_detects_textual_plan() -> None:
    agent = _agent()
    text = """Aquí un nuevo plan:
1. Ajustar directorio
2. Compilar proyecto
3. Subir programa
Confirma si deseas que continúe."""

    assert agent._looks_like_textual_plan(text) is True
    assert agent._extract_plan_steps(text) == [
        "Ajustar directorio",
        "Compilar proyecto",
        "Subir programa",
    ]


def test_resolve_project_env_prefers_uno_from_detected_board() -> None:
    agent = _agent()

    env, note = agent._resolve_project_env(
        "/tmp/project",
        requested_env=None,
        port="/dev/ttyUSB0",
    )

    assert env == "uno"
    assert "arduino_uno" in note


def test_resolve_project_env_uses_requested_env_when_available() -> None:
    agent = _agent()

    env, note = agent._resolve_project_env(
        "/tmp/project",
        requested_env="ESP32DEV",
        port=None,
    )

    assert env == "esp32dev"
    assert "requested env" in note.lower()


def test_resolve_project_env_falls_back_to_project_default() -> None:
    class ManagerNoDevices:
        def get_project_info(self, _project_path: str):
            return {
                "ok": True,
                "environments": ["uno", "esp32dev"],
                "default_env": "esp32dev",
                "error": "",
            }

        def detect_microcontrollers(self):
            return []

    agent = AIAgent(
        config={"default_board": ""},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=ManagerNoDevices(),
    )

    env, note = agent._resolve_project_env(
        "/tmp/project",
        requested_env=None,
        port=None,
    )

    assert env == "esp32dev"
    assert "project default" in note.lower()


def test_build_request_messages_includes_dynamic_environment_context() -> None:
    agent = AIAgent(
        config={"default_board": "esp32"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
        environment_context_provider=lambda: "ENVIRONMENT_CONTEXT\nos=Linux",
    )

    messages = agent._build_request_messages()

    assert len(messages) >= 2
    assert messages[-1]["role"] == "system"
    assert "ENVIRONMENT_CONTEXT" in messages[-1]["content"]


def test_ssh_command_always_requires_confirmation() -> None:
    agent = _agent()

    assert agent._needs_confirmation("ssh pi@raspberrypi.local 'uname -a'") is True
    assert agent._needs_confirmation("scp main.py pi@raspberrypi.local:/home/pi/") is True


def test_score_url_prioritizes_official_docs() -> None:
    agent = _agent()

    score_arduino, label_arduino = agent._score_url("https://docs.arduino.cc/learn/microcontrollers")
    score_reddit, label_reddit = agent._score_url("https://www.reddit.com/r/arduino/comments/xyz")
    score_github, _ = agent._score_url("https://github.com/some-org/some-repo")

    assert score_arduino > score_github > score_reddit
    assert label_arduino == "official_docs"


def test_score_url_unknown_domain_returns_one() -> None:
    agent = _agent()
    score, label = agent._score_url("https://somerandomblog.example.com/tutorial")
    assert score == 1
    assert label == "web"


def test_get_client_falls_back_to_config_key_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    class DummyClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("app.ai_agent.openai.OpenAI", DummyClient)

    agent = AIAgent(
        config={"api_key_source": "env", "openai_api_key": "sk-config-123"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    client = agent._get_client()

    assert isinstance(client, DummyClient)
    assert captured["api_key"] == "sk-config-123"


def test_ssh_always_confirmed_even_during_plan_window() -> None:
    """SSH/SCP must require confirmation even inside the plan skip-window."""
    agent = _agent()
    agent.skip_confirmations_until = time.time() + 300  # active window

    assert agent._needs_confirmation("ssh pi@raspberrypi.local 'ls'") is True
    assert agent._needs_confirmation("scp file.py pi@host:/tmp/") is True


def test_always_confirm_list_has_priority_over_plan_window() -> None:
    """always_confirm entries must be blocked even during a confirmed plan."""
    agent = AIAgent(
        config={"always_confirm": ["rm", "sudo"]},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )
    agent.skip_confirmations_until = time.time() + 300  # active window

    assert agent._needs_confirmation("rm -rf /tmp/test") is True
    assert agent._needs_confirmation("sudo apt-get install curl") is True


def test_plan_steps_capped_at_max() -> None:
    """_extract_plan_steps must not return more than _MAX_PLAN_STEPS items."""
    agent = _agent()
    lines = "\n".join(f"{i}. Step {i}" for i in range(1, 25))  # 24 steps
    steps = agent._extract_plan_steps(lines)

    assert len(steps) <= agent._MAX_PLAN_STEPS


def test_skip_confirmation_window_expires() -> None:
    """After the window expires, normal confirmation rules apply."""
    agent = _agent()
    agent.skip_confirmations_until = time.time() - 1  # already expired

    # A plain command with no explicit rule should NOT skip confirmation
    # when confirm_readonly is False (default) → returns False (no confirmation needed)
    # but should behave normally, not as if in plan window.
    assert agent._needs_confirmation("ls /tmp") is False  # low-risk, no rule
    # An SSH command must still require confirmation.
    assert agent._needs_confirmation("ssh user@host") is True
