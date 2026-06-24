"""
ai_agent.py — OpenAI client with tool/function calling for terminal operations.
"""

import html
import json
import os
import platform
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable, Optional

import openai
from app import i18n
from app.iot_diagram_manager import IoTDiagramManager

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command in the user's terminal. "
                "Use this to run system commands, scripts, or programs. "
                "Always prefer safe, non-destructive commands. "
                "For destructive operations, warn the user first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run the command in the background (non-blocking).",
                        "default": False,
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write or overwrite a file with the given content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The full text content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and subdirectories in a given directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list. Defaults to current working directory.",
                        "default": ".",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "change_directory",
            "description": "Change the terminal's current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The target directory path.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a location using wttr.in.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City or location name, e.g. Madrid.",
                    },
                    "lang": {
                        "type": "string",
                        "description": "Language code for the weather response, e.g. es or en.",
                        "default": "es",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for relevant pages and return top results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to look up on the web.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of links to return (1-10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_webpage",
            "description": "Fetch a webpage URL and return readable text content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The webpage URL to fetch.",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum number of characters to return.",
                        "default": 12000,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_microcontroller",
            "description": "Detect connected Arduino, ESP32, or other microcontroller boards. Returns port, description, and board type.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_microcontroller",
            "description": "Compile an Arduino/ESP32 project using PlatformIO. Requires a platformio.ini in the project directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the PlatformIO project directory.",
                    },
                    "env": {
                        "type": "string",
                        "description": "Target environment (e.g., esp32, arduino). If not specified, uses default from platformio.ini.",
                    },
                },
                "required": ["project_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_microcontroller",
            "description": "Build and upload firmware to a connected microcontroller board via serial port. Requires PlatformIO.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the PlatformIO project directory.",
                    },
                    "port": {
                        "type": "string",
                        "description": "Serial port (e.g., /dev/ttyUSB0). If not specified, uses default from config.",
                    },
                    "env": {
                        "type": "string",
                        "description": "Target environment (e.g., esp32, arduino).",
                    },
                },
                "required": ["project_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flash_sketch_file",
            "description": "End-to-end flow: prepare PlatformIO project from an .ino file, compile, and upload to detected microcontroller.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sketch_path": {
                        "type": "string",
                        "description": "Path to .ino sketch file.",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Optional PlatformIO project path. If omitted, sketch folder is used.",
                    },
                    "port": {
                        "type": "string",
                        "description": "Optional serial port (e.g., /dev/ttyUSB0). If omitted, auto-detect first board.",
                    },
                    "board": {
                        "type": "string",
                        "description": "PlatformIO board ID for new projects (default: uno).",
                        "default": "uno",
                    },
                    "env": {
                        "type": "string",
                        "description": "Optional PlatformIO environment to build/upload.",
                    },
                },
                "required": ["sketch_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_iot_schematic",
            "description": "Generate an IoT electronic schematic diagram (PNG/SVG) and BOM from components and connections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Project title, e.g. Greenhouse Monitor.",
                    },
                    "board": {
                        "type": "string",
                        "description": "Main board/controller, e.g. esp32.",
                    },
                    "components": {
                        "type": "array",
                        "description": "List of electronic components.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "type": {"type": "string"},
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "notes": {"type": "string"},
                            },
                        },
                    },
                    "connections": {
                        "type": "array",
                        "description": "Net connections between pins/components.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "signal": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["title", "board", "components"],
            },
        },
    },
]

def _build_system_prompt() -> str:
    os_name = platform.system() or "Unknown"
    terminal_hint = (
        "PowerShell/Windows shell"
        if os_name == "Windows"
        else ("Unix shell (Linux/macOS)" if os_name in {"Linux", "Darwin"} else "system shell")
    )

    return f"""You are Willy, an intelligent AI assistant and IoT programming specialist fully integrated with the user's terminal.

Current host OS: {os_name}
Expected shell style: {terminal_hint}

You have access to the following tools:

**General Tools:**
- run_command: execute any shell command
- read_file: read a file's contents
- write_file: create or edit a file
- list_directory: list directory contents
- get_weather: get current weather for any city via wttr.in
- search_web: search the internet and return relevant links
- fetch_webpage: fetch and summarize readable text from a webpage URL

**IoT & Embedded Systems Tools:**
- detect_microcontroller: detect connected Arduino, ESP32, or other microcontroller boards
- build_microcontroller: compile Arduino/ESP32 projects using PlatformIO
- upload_microcontroller: build and upload firmware to a connected microcontroller
- flash_sketch_file: full automatic flow from .ino to upload (prepare project + build + upload)
- generate_iot_schematic: create an electronic schematic diagram (PNG/SVG) and BOM

Guidelines:
- When asked about microcontrollers (Arduino, ESP32, etc.), prefer using IoT tools (detect, build, upload).
- When asked to design a circuit, wiring, or component diagram, use generate_iot_schematic.
- For terminal commands, use run_command. For file operations, use read_file/write_file.
- Use commands that match the host OS. If a Unix command is requested on Windows, use the Windows/PowerShell equivalent.
- Example equivalents:
    - Disk usage: `df -h` (Linux/macOS) -> `powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem"` (Windows)
    - Memory usage: `free -h` (Linux/macOS) -> `powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory"` (Windows)
    - Process list: `ps aux` (Linux/macOS) -> `powershell -NoProfile -Command "Get-Process | Sort-Object CPU -Descending | Select-Object -First 30"` (Windows)
- For commands that could be destructive (rm, sudo, overwriting files, etc.), briefly explain what you are about to do before the tool call. The UI will ask the user for confirmation.
- For read-only operations (ls, cat, pwd, search_web, fetch_webpage, detect_microcontroller, etc.) you can proceed directly.
- Always show relevant command or tool output to the user in your response.
- When using web data, include source URLs in your final answer.
- Be concise and helpful. Respond in the same language the user uses.
- If a tool or command fails, analyze the error output and suggest a fix.

**PLAN MODE (for multi-step operations):**
When the user asks you to perform multiple steps (e.g., "create a Python project", "set up a server", "configure something"), you MUST:
1. First, create a structured PLAN in XML format with all steps BEFORE executing any commands
2. Present the plan to the user (do NOT execute commands yet)
3. Wait for user confirmation (the UI will ask for it)
4. ONLY after confirmation, execute all commands WITHOUT asking for more confirmations
5. Do not ask for confirmation in plain text chat; rely on the UI confirmation dialog.

Plan format:
<plan>
<step number="1">Description of what this step does</step>
<step number="2">Description of what this step does</step>
<step number="N">Description of what this step does</step>
</plan>

Example workflow:
User: "Create a Python project with requirements.txt"
You respond: "I'll create a Python project for you. Here's my plan:
<plan>
<step number="1">Create project directory</step>
<step number="2">Create requirements.txt with initial dependencies</step>
<step number="3">Create virtual environment</step>
</plan>
Should I proceed with this plan?"

After user confirms: Execute all steps WITHOUT asking again.

Limits for safety:
- Maximum 15 steps per plan (prevents infinite loops)
- If a step fails, pause and explain the error to the user before continuing
- Always summarize what was executed after completion
"""


SYSTEM_PROMPT = _build_system_prompt()

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "willy_tool_errors.log")


class _TextExtractor(HTMLParser):
    """Extract visible text from HTML while ignoring scripts/styles."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self._parts.append(text)

    def text(self) -> str:
        return "\n".join(self._parts)


class AIAgent:
    def __init__(
        self,
        config: dict,
        terminal_manager,
        on_message: Callable[[str, str], None],
        on_confirm_request: Callable[[str, str, Callable], None],
        on_status: Callable[[str], None],
        on_progress: Optional[Callable[[float, str], None]] = None,
        arduino_manager=None,
        on_file_written: Optional[Callable[[str, str], None]] = None,
        on_schematic_generated: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Parameters
        ----------
        config              : loaded config dict
        terminal_manager    : TerminalManager instance
        on_message          : callback(role, text) — add a message to chat
        on_confirm_request  : callback(title, detail, proceed_fn) — ask user to confirm
        on_status           : callback(status_text) — update status bar
        arduino_manager     : ArduinoManager instance (optional)
        """
        self.config = config
        self.tm = terminal_manager
        self.on_message = on_message
        self.on_confirm = on_confirm_request
        self.on_status = on_status
        self.on_progress = on_progress
        self.arduino_manager = arduino_manager
        self.on_file_written = on_file_written
        self.on_schematic_generated = on_schematic_generated
        self.diagram_manager = IoTDiagramManager(base_dir=os.path.dirname(os.path.dirname(__file__)))
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._client: Optional[openai.OpenAI] = None
        
        # Plan mode state
        self.plan_steps: list[str] = []
        self.awaiting_plan_confirmation = False
        self.queued_commands: list[dict] = []
        self.skip_confirmations_until = None  # Unix timestamp or None
        self._progress_value = 0.0

    def _emit_progress(self, percent: float, detail: str = "") -> None:
        """Send monotonic progress updates to the UI (0-100)."""
        try:
            value = max(0.0, min(100.0, float(percent)))
        except Exception:
            value = 0.0

        # Avoid visual jitter going backwards across internal loop iterations.
        if value < self._progress_value:
            value = self._progress_value

        self._progress_value = value
        if callable(self.on_progress):
            try:
                self.on_progress(value, detail)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def send(self, user_text: str) -> None:
        """Process a user message asynchronously."""
        threading.Thread(target=self._process, args=(user_text,), daemon=True).start()

    def clear_history(self) -> None:
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    @staticmethod
    def _is_configured_api_key(value: str) -> bool:
        return bool(value) and not value.startswith("sk-YOUR")

    def _resolve_api_source(self, config_key: str) -> str:
        source = self.config.get("api_key_source", "")
        if source in {"env", "config"}:
            return source
        # Backward compatible behavior for older config.json files.
        return "config" if self._is_configured_api_key(config_key) else "env"

    def _get_client(self) -> openai.OpenAI:
        if self._client is None:
            config_key = self.config.get("openai_api_key", "").strip()
            env_key = os.getenv("OPENAI_API_KEY", "").strip()
            source = self._resolve_api_source(config_key)
            api_key = env_key if source == "env" else config_key

            if not self._is_configured_api_key(api_key):
                raise ValueError(
                    "API key not configured. Set OPENAI_API_KEY or save it in Settings."
                )
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    def _extract_plan_steps(self, text: str) -> list[str]:
        """Extract plan steps from XML tags in assistant response."""
        import re
        steps = []
        pattern = r'<step\s+number="(\d+)">(.+?)</step>'
        matches = re.findall(pattern, text, re.DOTALL)
        for num, content in matches:
            steps.append(content.strip())

        if steps:
            return steps

        # Fallback for plain-text numbered plans.
        for line in text.splitlines():
            stripped = line.strip()
            m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
            if m:
                steps.append(m.group(2).strip())
        return steps

    def _has_plan(self, text: str) -> bool:
        """Check if text contains a <plan> tag."""
        return "<plan>" in text and "</plan>" in text

    def _looks_like_textual_plan(self, text: str) -> bool:
        """Heuristic for plan-style responses without XML tags."""
        if not text:
            return False

        lowered = text.lower()
        has_plan_word = "plan" in lowered
        has_numbered_steps = any(f"{i}." in lowered for i in range(1, 7))
        asks_confirmation = (
            "confirma" in lowered
            or "confirm" in lowered
            or "deseas que contin" in lowered
            or "should i proceed" in lowered
        )
        return has_plan_word and has_numbered_steps and asks_confirmation

    def _format_plan_display(self, steps: list[str]) -> str:
        """Format plan steps for display."""
        if not steps:
            return ""
        lines = ["📋 **Plan:**"]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        return "\n".join(lines)

    def _request_plan_confirmation(self, steps: list[str]) -> bool:
        """Request user confirmation for plan execution. Returns True if confirmed."""
        confirmed = False
        event = threading.Event()

        self._emit_progress(30, "Esperando confirmacion del plan")

        def on_user_decision(user_confirmed: bool) -> None:
            nonlocal confirmed
            confirmed = user_confirmed
            event.set()

        plan_display = self._format_plan_display(steps)
        self.on_confirm(
            "Confirmar plan de ejecución",
            plan_display + "\n\n¿Ejecutar estos pasos?",
            on_user_decision,
        )
        event.wait(timeout=120)
        
        # If confirmed, skip command confirmations for the next 5 minutes
        if confirmed:
            self.skip_confirmations_until = time.time() + 300
        
        return confirmed

    def _process(self, user_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.on_status(i18n.get("ai_thinking"))
        self._progress_value = 0.0
        self._emit_progress(5, "Analizando solicitud")
        try:
            client = self._get_client()
            model = self.config.get("model", "gpt-4o")
            recovered_bad_history = False
            # Agentic loop: keep going until no more tool calls
            while True:
                self._emit_progress(12, "Consultando modelo")
                try:
                    response = client.chat.completions.create(
                        model=model,
                        messages=self.history,
                        tools=TOOLS,
                        tool_choice="auto",
                    )
                except openai.BadRequestError as exc:
                    err_text = str(exc)
                    self._log_event("bad_request", {
                        "error": err_text,
                        "user_text": user_text,
                    })
                    # Recover once if history was left with dangling tool calls.
                    if (
                        not recovered_bad_history
                        and "tool_call_ids did not have response messages" in err_text
                    ):
                        recovered_bad_history = True
                        self.history = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_text},
                        ]
                        self.on_message(
                            "system",
                            "Se reinició el contexto de la conversación por un error interno de tool-calls. Podés continuar normalmente.",
                        )
                        continue
                    raise

                msg = response.choices[0].message
                self.history.append(msg.to_dict())

                # Check for plan in assistant's response
                assistant_text = msg.content or ""
                is_plan_text = False
                plan_cancelled = False
                if assistant_text:
                    is_plan_text = self._has_plan(assistant_text) or self._looks_like_textual_plan(assistant_text)

                if assistant_text and is_plan_text:
                    self._emit_progress(25, "Plan detectado")
                    # Show the plan message first
                    self.on_message("assistant", assistant_text)
                    
                    # Extract plan steps
                    plan_steps = self._extract_plan_steps(assistant_text)
                    if plan_steps:
                        self.plan_steps = plan_steps
                        
                        # Request confirmation for the plan
                        if self._request_plan_confirmation(plan_steps):
                            self._emit_progress(35, "Plan confirmado")
                            # User confirmed — set flag to skip confirmations for next commands
                            self.awaiting_plan_confirmation = False
                            # Force immediate execution on next loop (avoid re-planning loop).
                            self.history.append({
                                "role": "user",
                                "content": "Plan confirmed in UI. Execute now directly with tools and do not ask for confirmation in chat.",
                            })
                        else:
                            # User cancelled — break the loop
                            self.on_message("system", "Plan cancelled by user.")
                            plan_cancelled = True

                    # If this response only contained plan text, request another turn.
                    # If it also contains tool_calls, do NOT skip tool processing.
                    if not msg.tool_calls:
                        continue

                if plan_cancelled:
                    break

                if msg.tool_calls:
                    # Process each tool call
                    total_calls = max(1, len(msg.tool_calls))
                    for idx, tc in enumerate(msg.tool_calls, start=1):
                        step_pct = 35 + (idx / total_calls) * 55
                        self._emit_progress(step_pct, f"Ejecutando: {tc.function.name}")
                        try:
                            result = self._dispatch_tool(tc)
                        except Exception as exc:  # noqa: BLE001
                            self._log_event("tool_error", {
                                "tool": tc.function.name,
                                "arguments": tc.function.arguments,
                                "error": repr(exc),
                            })
                            result = f"Error executing tool '{tc.function.name}': {exc}"
                        self.history.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result,
                        })
                    # Continue the loop so the model can process tool results
                    self._emit_progress(92, "Procesando resultados")
                    continue

                # No tool calls — final text response
                if assistant_text and not is_plan_text:
                    self.on_message("assistant", assistant_text)
                self._emit_progress(100, "Completado")
                break

        except ValueError as exc:
            self.on_message("error", str(exc))
            self._emit_progress(100, "Completado con error")
        except openai.AuthenticationError:
            self.on_message("error", "Invalid API key. Please check config.json.")
            self._emit_progress(100, "Completado con error")
        except openai.RateLimitError:
            self.on_message("error", "Rate limit reached. Please wait a moment.")
            self._emit_progress(100, "Completado con error")
        except Exception as exc:  # noqa: BLE001
            self.on_message("error", f"Unexpected error: {exc}")
            self._emit_progress(100, "Completado con error")
        finally:
            self.on_status("")

    # ------------------------------------------------------------------
    # Tool dispatcher
    # ------------------------------------------------------------------

    def _dispatch_tool(self, tool_call) -> str:
        name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError:
            return "Error: could not parse tool arguments."

        dispatch = {
            "run_command": self._tool_run_command,
            "read_file": self._tool_read_file,
            "write_file": self._tool_write_file,
            "list_directory": self._tool_list_directory,
            "change_directory": self._tool_change_directory,
            "get_weather": self._tool_get_weather,
            "search_web": self._tool_search_web,
            "fetch_webpage": self._tool_fetch_webpage,
            "detect_microcontroller": self._tool_detect_microcontroller,
            "build_microcontroller": self._tool_build_microcontroller,
            "upload_microcontroller": self._tool_upload_microcontroller,
            "flash_sketch_file": self._tool_flash_sketch_file,
            "generate_iot_schematic": self._tool_generate_iot_schematic,
        }
        handler = dispatch.get(name)
        if handler is None:
            return f"Error: unknown tool '{name}'."
        return handler(args)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _needs_confirmation(self, command: str) -> bool:
        import time
        
        # Skip confirmation if plan was just confirmed (within 5 minute window)
        if self.skip_confirmations_until is not None and time.time() < self.skip_confirmations_until:
            return False
        
        if self.config.get("confirm_readonly", False):
            return True
        always = self.config.get("always_confirm", [])
        first_token = command.strip().split()[0] if command.strip() else ""
        return first_token in always

    def _tool_run_command(self, args: dict) -> str:
        command = args.get("command", "").strip()
        if not command:
            return "Error: empty command."
        command = self._normalize_command_for_platform(command)
        background = args.get("background", False)

        if self._needs_confirmation(command):
            result_holder: list[str] = []
            confirmed_event = threading.Event()

            def on_user_decision(confirmed: bool) -> None:
                if confirmed:
                    result_holder.append("__run__")
                else:
                    result_holder.append("__cancelled__")
                confirmed_event.set()

            self.on_confirm(
                f"Run command?",
                command,
                on_user_decision,
            )
            confirmed_event.wait(timeout=120)
            if not result_holder or result_holder[0] == "__cancelled__":
                return "Command cancelled by user."

        output_parts: list[str] = []

        def collect(text: str) -> None:
            output_parts.append(text)
            if callable(original_cb):
                original_cb(text)

        # Swap callback temporarily to capture output
        original_cb = self.tm.output_callback
        self.tm.output_callback = collect
        try:
            if background:
                self.tm.run_command_async(command)
                return f"Command started in background: {command}"
            else:
                self.tm.run_command(command)
        finally:
            self.tm.output_callback = original_cb

        result = "".join(output_parts)
        return result if result.strip() else "(no output)"

    @staticmethod
    def _as_windows_powershell(ps_command: str) -> str:
        escaped = ps_command.replace('"', '\\"')
        return f'powershell -NoProfile -Command "{escaped}"'

    @staticmethod
    def _normalize_command_for_platform(command: str) -> str:
        """Translate common Unix-only commands to Windows equivalents when needed."""
        if platform.system() != "Windows":
            return command

        normalized = command.strip()
        lower = normalized.lower()

        if lower in {"df", "df -h"}:
            return AIAgent._as_windows_powershell("Get-PSDrive -PSProvider FileSystem")

        if lower in {"free", "free -h"}:
            return AIAgent._as_windows_powershell(
                "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory"
            )

        if lower in {"ps", "ps aux"}:
            return AIAgent._as_windows_powershell(
                "Get-Process | Sort-Object CPU -Descending | Select-Object -First 30"
            )

        if lower in {"top", "htop"}:
            return AIAgent._as_windows_powershell(
                "Get-Process | Sort-Object CPU -Descending | Select-Object -First 20 Name,Id,CPU,WS"
            )

        if lower in {"uname", "uname -a"}:
            return AIAgent._as_windows_powershell(
                "$os = Get-CimInstance Win32_OperatingSystem; Write-Output \"$($os.Caption) $($os.Version)\""
            )

        return command

    def _tool_read_file(self, args: dict) -> str:
        raw_path = args.get("path", "").strip()
        path = self._resolve_path(raw_path)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            # Truncate very large files to avoid token overflow
            if len(content) > 20_000:
                content = content[:20_000] + "\n\n[...file truncated at 20,000 chars...]"
            return content
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        except Exception as exc:  # noqa: BLE001
            return f"Error reading file: {exc}"

    def _tool_write_file(self, args: dict) -> str:
        raw_path = args.get("path", "").strip()
        content = args.get("content", "")
        path = self._resolve_path(raw_path)

        # Always confirm writes
        confirmed_event = threading.Event()
        decision: list[bool] = []

        def on_decision(confirmed: bool) -> None:
            decision.append(confirmed)
            confirmed_event.set()

        preview = content[:300] + ("…" if len(content) > 300 else "")
        self.on_confirm(
            f"Write file: {os.path.basename(path)}",
            f"Path: {path}\n\nPreview:\n{preview}",
            on_decision,
        )
        confirmed_event.wait(timeout=120)
        if not decision or not decision[0]:
            return "Write cancelled by user."

        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)

            if callable(self.on_file_written):
                try:
                    self.on_file_written(path, content)
                except Exception:
                    pass

            return f"File written successfully: {path}"
        except PermissionError:
            return f"Error: permission denied writing to {path}"
        except Exception as exc:  # noqa: BLE001
            return f"Error writing file: {exc}"

    def _tool_list_directory(self, args: dict) -> str:
        raw_path = args.get("path", self.tm.get_cwd()).strip() or self.tm.get_cwd()
        path = self._resolve_path(raw_path)
        try:
            entries = sorted(os.listdir(path))
            lines = []
            for name in entries:
                full = os.path.join(path, name)
                kind = "/" if os.path.isdir(full) else ""
                lines.append(f"{name}{kind}")
            return f"Contents of {path}:\n" + "\n".join(lines) if lines else f"{path} is empty."
        except FileNotFoundError:
            return f"Error: directory not found: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        except Exception as exc:  # noqa: BLE001
            return f"Error listing directory: {exc}"

    def _tool_change_directory(self, args: dict) -> str:
        path = args.get("path", "~").strip()
        result = self.tm.change_directory(path)
        return f"Changed directory to: {result}"

    def _tool_get_weather(self, args: dict) -> str:
        location = args.get("location", "").strip()
        lang = args.get("lang", "es").strip() or "es"
        if not location:
            return "Error: location is required."
        try:
            encoded = urllib.parse.quote(location)
            url = f"https://wttr.in/{encoded}?format=4&lang={lang}"
            req = urllib.request.Request(url, headers={"User-Agent": "Willy/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.read().decode("utf-8", errors="replace").strip()
        except Exception as exc:
            return f"Error obteniendo el clima: {exc}"

    def _tool_search_web(self, args: dict) -> str:
        query = args.get("query", "").strip()
        if not query:
            return "Error: query is required."

        requested = args.get("max_results", 5)
        try:
            max_results = int(requested)
        except (TypeError, ValueError):
            max_results = 5
        max_results = max(1, min(max_results, 10))

        try:
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://duckduckgo.com/html/?q={encoded_query}"
            req = urllib.request.Request(url, headers={"User-Agent": "Willy/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_html = resp.read().decode("utf-8", errors="replace")

            results: list[tuple[str, str]] = []
            marker = 'class="result__a"'
            pos = 0
            while len(results) < max_results:
                idx = raw_html.find(marker, pos)
                if idx == -1:
                    break
                href_attr = raw_html.rfind("href=", pos, idx)
                if href_attr == -1:
                    pos = idx + len(marker)
                    continue

                quote_char = raw_html[href_attr + 5:href_attr + 6]
                if quote_char not in {'"', "'"}:
                    pos = idx + len(marker)
                    continue

                href_start = href_attr + 6
                href_end = raw_html.find(quote_char, href_start)
                if href_end == -1:
                    pos = idx + len(marker)
                    continue

                href = raw_html[href_start:href_end]
                text_start = raw_html.find(">", idx)
                text_end = raw_html.find("</a>", text_start + 1)
                if text_start == -1 or text_end == -1:
                    pos = idx + len(marker)
                    continue

                title = html.unescape(raw_html[text_start + 1:text_end].strip())
                clean_url = self._decode_duckduckgo_redirect(href)
                if title and clean_url:
                    results.append((title, clean_url))

                pos = text_end + 4

            if not results:
                return f"No web results found for: {query}"

            lines = [f"Web results for: {query}"]
            for i, (title, link) in enumerate(results, start=1):
                lines.append(f"{i}. {title}\n   URL: {link}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Error searching web: {exc}"

    def _tool_fetch_webpage(self, args: dict) -> str:
        raw_url = args.get("url", "").strip()
        if not raw_url:
            return "Error: url is required."

        normalized_url = self._normalize_url(raw_url)
        requested = args.get("max_chars", 12000)
        try:
            max_chars = int(requested)
        except (TypeError, ValueError):
            max_chars = 12000
        max_chars = max(1000, min(max_chars, 40000))

        # First attempt: use jina AI reader endpoint for cleaner extraction.
        reader_url = "https://r.jina.ai/http://" + normalized_url.split("://", maxsplit=1)[1]
        try:
            req = urllib.request.Request(reader_url, headers={"User-Agent": "Willy/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            content = content.strip()
            if content:
                return self._limit_web_output(normalized_url, content, max_chars)
        except Exception:
            pass

        # Fallback: fetch raw HTML and extract visible text.
        try:
            req = urllib.request.Request(normalized_url, headers={"User-Agent": "Willy/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html_content = resp.read().decode("utf-8", errors="replace")
            text = self._html_to_text(html_content)
            if not text:
                return f"No readable text found at: {normalized_url}"
            return self._limit_web_output(normalized_url, text, max_chars)
        except Exception as exc:
            return f"Error fetching webpage: {exc}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        if path.startswith("~"):
            return os.path.expanduser(path)
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.tm.get_cwd(), path))

    def _normalize_url(self, raw_url: str) -> str:
        if raw_url.startswith(("http://", "https://")):
            return raw_url
        return f"https://{raw_url}"

    def _decode_duckduckgo_redirect(self, link: str) -> str:
        if not link:
            return ""
        parsed = urllib.parse.urlparse(link)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            params = urllib.parse.parse_qs(parsed.query)
            candidate = params.get("uddg", [""])[0]
            return urllib.parse.unquote(candidate) if candidate else ""
        return link

    def _html_to_text(self, html_content: str) -> str:
        parser = _TextExtractor()
        parser.feed(html_content)
        text = parser.text()
        return "\n".join(line for line in text.splitlines() if line.strip())

    def _limit_web_output(self, source_url: str, content: str, max_chars: int) -> str:
        if len(content) > max_chars:
            clipped = content[:max_chars]
            suffix = f"\n\n[...web content truncated at {max_chars} chars...]"
        else:
            clipped = content
            suffix = ""
        return f"Source URL: {source_url}\n\n{clipped}{suffix}"

    def _board_env_candidates(self, board_hint: str) -> list[str]:
        """Return likely PlatformIO env names for a detected board hint."""
        if not board_hint:
            return []

        b = board_hint.strip().lower()
        if b in {"arduino_uno", "arduino:avr:uno", "uno"}:
            return ["uno", "arduino_uno", "arduino-avr-uno"]
        if b in {"arduino_compatible", "arduino", "arduino:avr:nano", "nano"}:
            return ["uno", "nano", "arduino"]
        if "esp32-s3" in b:
            return ["esp32-s3", "esp32s3", "s3"]
        if "esp32" in b:
            return ["esp32", "esp32dev"]
        if "pico" in b:
            return ["pico", "rp2040"]
        return [b]

    def _resolve_project_env(
        self,
        project_path: str,
        requested_env: Optional[str] = None,
        port: Optional[str] = None,
    ) -> tuple[Optional[str], str]:
        """
        Pick the best PlatformIO env for this project.

        Priority:
        1) explicit env requested by tool call
        2) env inferred from detected board on selected port
        3) env inferred from configured default board
        4) project's default_env / first env
        """
        if not self.arduino_manager:
            return requested_env, ""

        info = self.arduino_manager.get_project_info(project_path)
        if not info.get("ok"):
            # If we cannot inspect project metadata, keep requested value as-is.
            return requested_env, ""

        envs = [str(e).strip() for e in info.get("environments", []) if str(e).strip()]
        envs_l = [e.lower() for e in envs]
        if not envs:
            return requested_env, ""

        # 1) Explicit env
        if requested_env:
            req = requested_env.strip()
            if req.lower() in envs_l:
                chosen = envs[envs_l.index(req.lower())]
                return chosen, f"Using requested env: {chosen}"

        candidates: list[str] = []
        if requested_env:
            candidates.append(requested_env.strip().lower())

        # 2) Detect board from selected port, then infer likely env names.
        detected_board = ""
        try:
            devices = self.arduino_manager.detect_microcontrollers()
            selected = None
            if port:
                selected = next((d for d in devices if d.get("port") == port), None)
            if selected is None and devices:
                selected = devices[0]
            if selected:
                detected_board = str(selected.get("board", "")).strip().lower()
                candidates.extend(self._board_env_candidates(detected_board))
        except Exception:
            pass

        # 3) Configured default board hint.
        default_board = str(self.config.get("default_board", "")).strip().lower()
        candidates.extend(self._board_env_candidates(default_board))

        # De-duplicate while preserving order.
        seen = set()
        uniq_candidates: list[str] = []
        for cand in candidates:
            if not cand or cand in seen:
                continue
            seen.add(cand)
            uniq_candidates.append(cand)

        # Exact match first.
        for cand in uniq_candidates:
            if cand in envs_l:
                chosen = envs[envs_l.index(cand)]
                note = f"Auto-selected env '{chosen}'"
                if detected_board:
                    note += f" from detected board '{detected_board}'"
                return chosen, note

        # Fuzzy match by containment.
        for cand in uniq_candidates:
            for idx, env_name in enumerate(envs_l):
                if cand in env_name or env_name in cand:
                    chosen = envs[idx]
                    note = f"Auto-selected env '{chosen}' via heuristic"
                    if detected_board:
                        note += f" (board '{detected_board}')"
                    return chosen, note

        # 4) Fallback to project default or first env.
        default_env = info.get("default_env")
        if default_env and str(default_env).strip().lower() in envs_l:
            chosen = envs[envs_l.index(str(default_env).strip().lower())]
            return chosen, f"Using project default env: {chosen}"

        return envs[0], f"Using first project env: {envs[0]}"


    def _tool_detect_microcontroller(self, args: dict) -> str:
        """Detect connected microcontroller boards."""
        if not self.arduino_manager:
            return "Error: Arduino support not available (ArduinoManager not initialized)."
        
        try:
            devices = self.arduino_manager.detect_microcontrollers()
            if not devices:
                return "No microcontroller boards detected. Check USB connections."
            
            lines = ["Detected microcontroller boards:"]
            for i, device in enumerate(devices, 1):
                port = device.get("port", "?")
                board = device.get("board", "unknown")
                desc = device.get("description", "")
                lines.append(f"{i}. {board.upper()} on {port} - {desc}")
            
            return "\n".join(lines)
        except Exception as exc:
            return f"Error detecting microcontrollers: {exc}"
    
    def _tool_build_microcontroller(self, args: dict) -> str:
        """Build/compile a PlatformIO project."""
        if not self.arduino_manager:
            return "Error: Arduino support not available."
        
        project_path = args.get("project_path", "").strip()
        if not project_path:
            return "Error: project_path is required."
        
        env_arg = args.get("env")
        env, env_note = self._resolve_project_env(project_path, requested_env=env_arg)
        
        try:
            result = self.arduino_manager.build_sketch(project_path, env)
            if result["ok"]:
                if env_note:
                    return f"✓ Build successful\n{env_note}\n\n{result['output']}"
                return f"✓ Build successful\n\n{result['output']}"
            else:
                if env_note:
                    return f"✗ Build failed: {result['error']}\n{env_note}\n\n{result['output']}"
                return f"✗ Build failed: {result['error']}\n\n{result['output']}"
        except Exception as exc:
            return f"Error building microcontroller project: {exc}"
    
    def _tool_upload_microcontroller(self, args: dict) -> str:
        """Build and upload firmware to microcontroller."""
        if not self.arduino_manager:
            return "Error: Arduino support not available."
        
        project_path = args.get("project_path", "").strip()
        port = (args.get("port") or "").strip()
        env_arg = args.get("env")
        
        if not project_path:
            return "Error: project_path is required."

        if not port:
            try:
                devices = self.arduino_manager.detect_microcontrollers()
                if devices:
                    port = str(devices[0].get("port", "")).strip()
            except Exception:
                port = ""

        if not port:
            port = self.config.get("default_port", "/dev/ttyUSB0")
        
        env, env_note = self._resolve_project_env(
            project_path,
            requested_env=env_arg,
            port=port,
        )

        # Ask for confirmation
        confirmed_event = threading.Event()
        decision: list[bool] = []
        
        def on_decision(confirmed: bool) -> None:
            decision.append(confirmed)
            confirmed_event.set()
        
        self.on_confirm(
            "Upload firmware?",
            f"Project: {project_path}\nPort: {port}\nEnvironment: {env or '(auto)'}"
            + (f"\n{env_note}" if env_note else ""),
            on_decision,
        )
        confirmed_event.wait(timeout=120)
        if not decision or not decision[0]:
            return "Upload cancelled by user."
        
        try:
            result = self.arduino_manager.upload_firmware(project_path, port, env)
            if result["ok"]:
                return f"✓ Firmware uploaded successfully\n\n{result['output']}"
            else:
                return f"✗ Upload failed: {result['error']}\n\n{result['output']}"
        except Exception as exc:
            return f"Error uploading firmware: {exc}"

    def _tool_flash_sketch_file(self, args: dict) -> str:
        """Prepare project from .ino, then compile and upload in one flow."""
        if not self.arduino_manager:
            return "Error: Arduino support not available."

        sketch_raw = args.get("sketch_path", "").strip()
        if not sketch_raw:
            return "Error: sketch_path is required."

        project_raw = args.get("project_path", "").strip()
        board = (args.get("board") or "uno").strip() or "uno"
        env_arg = args.get("env")
        port = (args.get("port") or "").strip()

        sketch_path = self._resolve_path(sketch_raw)
        project_path = self._resolve_path(project_raw) if project_raw else ""

        if not port:
            try:
                devices = self.arduino_manager.detect_microcontrollers()
                if devices:
                    port = str(devices[0].get("port", "")).strip()
            except Exception:
                port = ""
        if not port:
            port = self.config.get("default_port", "/dev/ttyUSB0")

        confirm_lines = [
            f"Sketch: {sketch_path}",
            f"Project: {project_path or '(same folder as sketch)'}",
            f"Board: {board}",
            f"Port: {port}",
            f"Env: {env_arg or '(auto)'}",
        ]

        confirmed_event = threading.Event()
        decision: list[bool] = []

        def on_decision(confirmed: bool) -> None:
            decision.append(confirmed)
            confirmed_event.set()

        self.on_confirm(
            "Compilar y cargar sketch?",
            "\n".join(confirm_lines),
            on_decision,
        )
        confirmed_event.wait(timeout=120)
        if not decision or not decision[0]:
            return "Flash cancelled by user."

        prep = self.arduino_manager.prepare_project_from_ino(
            sketch_path=sketch_path,
            project_path=project_path or None,
            board=board,
        )
        if not prep.get("ok"):
            return f"✗ Preparation failed: {prep.get('error', 'unknown error')}\n\n{prep.get('output', '')}"

        proj = prep.get("project_path", project_path)
        env, env_note = self._resolve_project_env(proj, requested_env=env_arg, port=port)
        result = self.arduino_manager.upload_firmware(proj, port, env)
        if not result.get("ok"):
            return (
                f"✗ Upload failed: {result.get('error', 'unknown error')}\n"
                + (f"{env_note}\n" if env_note else "")
                + f"\nPreparation:\n{prep.get('output', '')}\n\nBuild/Upload Output:\n{result.get('output', '')}"
            )

        lines = ["✓ Sketch compiled and uploaded successfully"]
        if env_note:
            lines.append(env_note)
        lines.append("")
        lines.append("Preparation:")
        lines.append(prep.get("output", ""))
        lines.append("")
        lines.append("Build/Upload Output:")
        lines.append(result.get("output", ""))
        return "\n".join(lines)

    def _tool_generate_iot_schematic(self, args: dict) -> str:
        title = (args.get("title") or "IoT Diagram").strip()
        board = (args.get("board") or "esp32").strip()
        components = args.get("components") or []
        connections = args.get("connections") or []

        if not isinstance(components, list) or not components:
            return "Error: components must be a non-empty array."
        if not isinstance(connections, list):
            return "Error: connections must be an array."

        result = self.diagram_manager.generate_schematic(
            title=title,
            board=board,
            components=components,
            connections=connections,
        )

        if not result.ok:
            return f"Error generating diagram: {result.message}"

        if callable(self.on_schematic_generated):
            try:
                self.on_schematic_generated(result.svg_path, result.bom_path)
            except Exception:
                pass

        lines = [
            f"Schematic generated successfully for '{title}'.",
            f"Board: {board}",
            f"Components: {len(components)}",
            f"Connections: {len(connections)}",
            f"PNG: {result.png_path}",
            f"SVG: {result.svg_path}",
            f"BOM: {result.bom_path}",
            f"NETLIST: {result.netlist_path}",
        ]
        return "\n".join(lines)

    def _log_event(self, event_type: str, payload: dict) -> None:
        """Best-effort local logging for debugging tool-call failures."""
        try:
            stamp = datetime.now().isoformat(timespec="seconds")
            line = json.dumps(
                {
                    "timestamp": stamp,
                    "event": event_type,
                    "payload": payload,
                },
                ensure_ascii=False,
            )
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            # Logging must never break the chat flow.
            pass
