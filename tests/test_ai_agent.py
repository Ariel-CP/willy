from app.ai_agent import AIAgent
from unittest.mock import patch
from types import SimpleNamespace


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

    def scan_i2c_bus(self, project_path: str, port: str, env: str = None, monitor_seconds: int = 8):
        _ = (project_path, port, env, monitor_seconds)
        return {
            "ok": True,
            "addresses": ["0x27"],
            "output": "I2C scan start\nI2C found at 0x27\nI2C scan end",
            "error": "",
        }


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


def test_normalize_command_translates_df_on_windows() -> None:
    with patch("app.ai_agent.platform.system", return_value="Windows"):
        normalized = AIAgent._normalize_command_for_platform("df -h")
        assert "powershell -NoProfile -Command" in normalized
        assert "Get-PSDrive -PSProvider FileSystem" in normalized


def test_normalize_command_translates_free_on_windows() -> None:
    with patch("app.ai_agent.platform.system", return_value="Windows"):
        normalized = AIAgent._normalize_command_for_platform("free -h")
        assert "powershell -NoProfile -Command" in normalized
        assert "Get-CimInstance Win32_OperatingSystem" in normalized


def test_normalize_command_translates_ps_on_windows() -> None:
    with patch("app.ai_agent.platform.system", return_value="Windows"):
        normalized = AIAgent._normalize_command_for_platform("ps aux")
        assert "powershell -NoProfile -Command" in normalized
        assert "Get-Process" in normalized


def test_normalize_command_translates_uname_on_windows() -> None:
    with patch("app.ai_agent.platform.system", return_value="Windows"):
        normalized = AIAgent._normalize_command_for_platform("uname -a")
        assert "powershell -NoProfile -Command" in normalized
        assert "Win32_OperatingSystem" in normalized

def test_detect_runtime_context_uses_platform_data(monkeypatch) -> None:
    monkeypatch.setattr("app.ai_agent.platform.system", lambda: "Windows")
    monkeypatch.setattr("app.ai_agent.platform.release", lambda: "11")
    monkeypatch.setattr(
        "app.ai_agent.platform.platform",
        lambda: "Windows-11-10.0.22631-SP0",
    )

    agent = _agent()

    assert agent.runtime_context["os_name"] == "Windows"
    assert agent.runtime_context["os_version"] == "11"
    assert "Windows-11" in agent.runtime_context["platform_name"]


def test_system_prompt_includes_runtime_os_context(monkeypatch) -> None:
    monkeypatch.setattr("app.ai_agent.platform.system", lambda: "Linux")
    monkeypatch.setattr("app.ai_agent.platform.release", lambda: "6.8.0")
    monkeypatch.setattr("app.ai_agent.platform.platform", lambda: "Linux-6.8.0-x86_64")

    agent = _agent()

    assert "Operating System: Linux" in agent.system_prompt
    assert "OS Version: 6.8.0" in agent.system_prompt
    assert "Platform: Linux-6.8.0-x86_64" in agent.system_prompt


def test_build_failure_reports_automatic_dependency_recovery_note() -> None:
    class ManagerDependencyFail(DummyArduinoManager):
        def build_sketch(self, _project_path: str, _env: str):
            return {
                "ok": False,
                "error": "Preflight package install failed",
                "output": "Dependency sync attempt 1/3 failed (network); retrying...",
            }

    agent = AIAgent(
        config={"default_board": "esp32"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=ManagerDependencyFail(),
    )

    msg = agent._tool_build_microcontroller({"project_path": "/tmp/project", "env": "uno"})

    assert "Build failed" in msg
    assert "Willy aplico recuperacion automatica" in msg
    assert "Error tecnico final:" in msg


def test_upload_failure_reports_automatic_flow_and_technical_error() -> None:
    class ManagerUploadDependencyFail(DummyArduinoManager):
        def upload_firmware(self, _project_path: str, _port: str, _env: str):
            return {
                "ok": False,
                "error": "Upload failed (exit code 1)",
                "output": "Unknown package 'johnrickman/LiquidCrystal_I2C@^1.1.4'",
            }

    agent = AIAgent(
        config={"default_board": "esp32"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=ManagerUploadDependencyFail(),
    )

    msg = agent._tool_upload_microcontroller(
        {"project_path": "/tmp/project", "env": "uno", "port": "/dev/ttyUSB0"}
    )

    assert "Upload failed" in msg
    assert "Error tecnico final:" in msg


def test_sanitize_assistant_text_blocks_unsolicited_arduino_ide_steps() -> None:
    agent = _agent()
    user_text = "sube el sketch al arduino"
    assistant_text = (
        "Hubo un problema con LiquidCrystal_I2C. "
        "Abre Arduino IDE y ve a Sketch > Include Library > Manage Libraries."
    )

    cleaned = agent._sanitize_assistant_text(assistant_text, user_text)

    assert "Arduino IDE" not in cleaned
    assert "PlatformIO" in cleaned


def test_sanitize_assistant_text_allows_arduino_ide_when_user_requests_it() -> None:
    agent = _agent()
    user_text = "dame pasos manuales en Arduino IDE"
    assistant_text = "Abre Arduino IDE y ve a Sketch > Include Library > Manage Libraries."

    cleaned = agent._sanitize_assistant_text(assistant_text, user_text)

    assert cleaned == assistant_text


def test_sanitize_assistant_text_blocks_unsolicited_manual_platformio_steps() -> None:
    agent = _agent()
    user_text = "sube el sketch"
    assistant_text = (
        "Instala la libreria manualmente: abre platformio.ini y agrega la linea "
        "marcoschwartz/LiquidCrystal_I2C@1.1.4. Si no funciona, descargala y colócala en la carpeta lib."
    )

    cleaned = agent._sanitize_assistant_text(assistant_text, user_text)

    assert "platformio.ini" not in cleaned.lower()
    assert "carpeta lib" not in cleaned.lower()
    assert "diagnóstico" in cleaned.lower() or "diagnostico" in cleaned.lower()


def test_tool_scan_i2c_bus_reports_detected_addresses() -> None:
    agent = _agent()

    msg = agent._tool_scan_i2c_bus({"project_path": "/tmp/project", "port": "/dev/ttyUSB0", "env": "uno"})

    assert "I2C scan completado" in msg
    assert "0x27" in msg


def test_emit_assistant_once_skips_immediate_duplicate() -> None:
    captured = []

    agent = AIAgent(
        config={"default_board": "esp32"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, t: captured.append(t),
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    msg = "Willy mantendra un flujo automatico con PlatformIO"
    agent._emit_assistant_once(msg, dedupe_window_seconds=60)
    agent._emit_assistant_once(msg, dedupe_window_seconds=60)

    assert captured == [msg]


def test_resolve_iot_project_path_uses_initial_directory(tmp_path) -> None:
    project = tmp_path / "pio_project"
    project.mkdir()
    (project / "platformio.ini").write_text("[env:uno]\n", encoding="utf-8")

    agent = AIAgent(
        config={"default_board": "esp32", "initial_directory": str(project)},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    resolved, note = agent._resolve_iot_project_path(".")

    assert resolved == str(project)
    assert "Auto-context" in note


def test_tool_call_fingerprint_is_stable_for_argument_order() -> None:
    agent = _agent()

    tc1 = SimpleNamespace(function=SimpleNamespace(name="upload_microcontroller", arguments='{"project_path":"a","port":"COM5"}'))
    tc2 = SimpleNamespace(function=SimpleNamespace(name="upload_microcontroller", arguments='{"port":"COM5","project_path":"a"}'))

    assert agent._tool_call_fingerprint(tc1) == agent._tool_call_fingerprint(tc2)


def test_tool_result_is_failure_heuristic() -> None:
    agent = _agent()

    assert agent._tool_result_is_failure("✗ Upload failed: boom") is True
    assert agent._tool_result_is_failure("Error: missing project") is True
    assert agent._tool_result_is_failure("✓ Firmware uploaded successfully") is False


def test_command_policy_lab_safe_blocks_unknown_command(monkeypatch) -> None:
    monkeypatch.setattr("app.ai_agent.platform.system", lambda: "Linux")
    agent = _agent()

    ok, reason = agent._validate_command_policy("curl https://example.com")

    assert ok is False
    assert "not allowed" in reason


def test_command_policy_standard_allows_unknown_but_blocks_dangerous(monkeypatch) -> None:
    monkeypatch.setattr("app.ai_agent.platform.system", lambda: "Linux")
    agent = AIAgent(
        config={"default_board": "esp32", "security_profile": "standard"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    ok_unknown, _ = agent._validate_command_policy("curl https://example.com")
    ok_danger, reason_danger = agent._validate_command_policy("rm -rf /")

    assert ok_unknown is True
    assert ok_danger is False
    assert "blocked dangerous pattern" in reason_danger


def test_command_policy_permissive_allows_any_command(monkeypatch) -> None:
    monkeypatch.setattr("app.ai_agent.platform.system", lambda: "Windows")
    agent = AIAgent(
        config={"default_board": "esp32", "security_profile": "permissive"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    ok, reason = agent._validate_command_policy("format C:")

    assert ok is True
    assert reason == ""


def test_role_policy_student_blocks_sensitive_tools() -> None:
    agent = AIAgent(
        config={"default_board": "esp32", "operation_role": "student"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    assert agent._is_tool_allowed_for_role("run_command") is False
    assert agent._is_tool_allowed_for_role("write_file") is False
    assert agent._is_tool_allowed_for_role("build_microcontroller") is True


def test_role_policy_instructor_allows_run_command() -> None:
    agent = AIAgent(
        config={"default_board": "esp32", "operation_role": "instructor"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    assert agent._is_tool_allowed_for_role("run_command") is True
    assert agent._is_tool_allowed_for_role("write_file") is True


def test_dispatch_tool_blocks_by_role_policy() -> None:
    agent = AIAgent(
        config={"default_board": "esp32", "operation_role": "student"},
        terminal_manager=DummyTM(),
        on_message=lambda _r, _t: None,
        on_confirm_request=lambda _title, _detail, callback: callback(True),
        on_status=lambda _s: None,
        arduino_manager=DummyArduinoManager(),
    )

    tc = SimpleNamespace(
        function=SimpleNamespace(name="run_command", arguments='{"command":"echo test"}')
    )

    result = agent._dispatch_tool(tc)

    assert "blocked by role policy" in result
    assert "operation_role=student" in result
