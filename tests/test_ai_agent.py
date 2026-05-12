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
