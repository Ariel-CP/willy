"""
ai_agent.py — OpenAI client with tool/function calling for terminal operations.
"""

import html
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from typing import Callable, Optional

import openai
from app import i18n
from app.dependency_manager import DependencyManager
from app.flowchart_manager import FlowchartManager
from app.iot_diagram_manager import IoTDiagramManager
from app.security_utils import redact_sensitive_text

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
            "name": "manage_dependencies",
            "description": "Detect, snapshot, install, update or rollback project dependencies. Supports pip, apt, npm, platformio, arduino-cli. Snapshot is always taken before install/update so rollback is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "One of: detect, snapshot, install, update, rollback, summary.",
                        "enum": ["detect", "snapshot", "install", "update", "rollback", "summary"]
                    },
                    "ecosystem": {
                        "type": "string",
                        "description": "Ecosystem: pip, apt, npm, platformio, arduino-cli."
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names for install/update."
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project (needed for npm, platformio)."
                    },
                    "use_sudo": {
                        "type": "boolean",
                        "description": "Use sudo for apt commands. Only set true inside a confirmed plan.",
                        "default": False
                    },
                    "policy": {
                        "type": "string",
                        "description": "Update policy: balanced (patch+minor) or major.",
                        "enum": ["balanced", "major"],
                        "default": "balanced"
                    }
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_flowchart",
            "description": "Generate a Mermaid-first flowchart from a software project and save .mmd/.svg/.png outputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Path to the project directory.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional flowchart title.",
                    },
                },
                "required": ["project_path"],
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
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path of the active project directory. If provided, diagrams are also saved inside {project_path}/diagrams/.",
                    },
                },
                "required": ["title", "board", "components"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Willy, an intelligent AI assistant specialized in mechatronics, embedded systems, and technical lab work. You are fully integrated with the user's Linux terminal in a professional electronics and programming laboratory.

You have access to the following tools:

**General Tools:**
- run_command: execute any shell command
- read_file: read a file's contents
- write_file: create or edit a file
- list_directory: list directory contents
- get_weather: get current weather for any city via wttr.in
- search_web: search the internet and return ranked results with source quality scores
- fetch_webpage: fetch and summarize readable text from a webpage URL

**IoT & Embedded Systems Tools:**
- detect_microcontroller: detect connected Arduino, ESP32, or other microcontroller boards
- build_microcontroller: compile Arduino/ESP32 projects using PlatformIO
- upload_microcontroller: build and upload firmware to a connected microcontroller
- flash_sketch_file: full automatic flow from .ino to upload (prepare project + build + upload)
- generate_iot_schematic: create an electronic schematic diagram (PNG/SVG) and BOM
- generate_flowchart: generate a Mermaid flowchart from a project directory

**Lab Domain (Mechatronics):**
When researching or answering, apply this source priority per domain:
- Control (PID, loops, tuning): datasheet/appnotes > GitHub maintained > community
- Sensing (ADC, calibration, filters): datasheet > official lib > community
- Actuation (motors, drivers, PWM): datasheet+safety > official examples > community
- Industrial comms (CAN, Modbus, RS-485, MQTT): spec > vendor docs > maintained stack
- Vision (camera, inference): official framework > benchmarks > community
- Firmware/integration: PlatformIO docs > Arduino docs > community

Guidelines:
- When asked about microcontrollers (Arduino, ESP32, etc.), prefer using IoT tools (detect, build, upload).
- When asked to design a circuit or wiring diagram, use generate_iot_schematic.
- For terminal commands, use run_command. For file operations, use read_file/write_file.
- SSH is allowed for Raspberry/system administration tasks. Use `ssh user@host 'command'` pattern and explain what will run.
- For commands that could be destructive (rm, sudo, overwriting files, etc.), briefly explain what you are about to do before the tool call. The UI will ask the user for confirmation.
- SSH/SCP/RSYNC remote commands must always request confirmation before execution.
- For read-only operations (ls, cat, pwd, search_web, fetch_webpage, detect_microcontroller, etc.) you can proceed directly.
- Always show relevant command or tool output to the user in your response.
- **Traceability (mandatory):** When using web data, ALWAYS include: source URL, date consulted, and source quality level (official/community). Example: "Source: https://... | consulted: 2026-06-20 | quality: official_docs"
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
        environment_context_provider: Optional[Callable[[], str]] = None,
        on_flowchart_generated: Optional[Callable[[str, str], None]] = None,
        on_usage_update: Optional[Callable[[dict], None]] = None,
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
        self.environment_context_provider = environment_context_provider
        self.diagram_manager = IoTDiagramManager(base_dir=os.path.dirname(os.path.dirname(__file__)))
        self.flowchart_manager = FlowchartManager(base_dir=os.path.dirname(os.path.dirname(__file__)))
        self.dep_manager = DependencyManager(base_dir=os.path.dirname(os.path.dirname(__file__)))
        self.on_flowchart_generated = on_flowchart_generated
        self.on_usage_update = on_usage_update
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._client: Optional[openai.OpenAI] = None
        self.session_token_budget = int(self.config.get("session_token_budget", 100_000) or 100_000)
        self.session_total_tokens = 0
        
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

    def _build_request_messages(self) -> list[dict]:
        """Build request messages with optional dynamic environment context."""
        messages = list(self.history)
        if not callable(self.environment_context_provider):
            return messages

        try:
            context = (self.environment_context_provider() or "").strip()
        except Exception:
            context = ""

        if context:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Use this live environment context to make practical decisions "
                        "for Linux/system/electronics workflows:\n" + context
                    ),
                }
            )
        return messages

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
            if source == "env":
                api_key = env_key if self._is_configured_api_key(env_key) else config_key
            else:
                api_key = config_key if self._is_configured_api_key(config_key) else env_key

            if not self._is_configured_api_key(api_key):
                raise ValueError(
                    "API key not configured. Set OPENAI_API_KEY or save it in Settings."
                )
            self._client = openai.OpenAI(api_key=api_key)
        return self._client

    _MAX_PLAN_STEPS = 15

    def _extract_plan_steps(self, text: str) -> list[str]:
        """Extract plan steps from XML tags in assistant response."""
        import re
        steps = []
        pattern = r'<step\s+number="(\d+)">(.+?)</step>'
        matches = re.findall(pattern, text, re.DOTALL)
        for num, content in matches:
            steps.append(content.strip())

        if steps:
            return steps[: self._MAX_PLAN_STEPS]

        # Fallback for plain-text numbered plans.
        for line in text.splitlines():
            stripped = line.strip()
            m = re.match(r"^(\d+)\.\s+(.+)$", stripped)
            if m:
                steps.append(m.group(2).strip())
                if len(steps) >= self._MAX_PLAN_STEPS:
                    break
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
                        messages=self._build_request_messages(),
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
                self._record_response_usage(getattr(response, "usage", None), model=model)
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
            "manage_dependencies": self._tool_manage_dependencies,
            "generate_flowchart": self._tool_generate_flowchart,
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

        lowered = command.strip().lower()
        first_token = lowered.split()[0] if lowered else ""

        # SSH-like remote operations ALWAYS require explicit approval,
        # even inside a confirmed plan window.
        if first_token in {"ssh", "scp", "sftp", "rsync"}:
            return True

        # always_confirm list has absolute priority over plan window.
        always = self.config.get("always_confirm", [])
        if first_token in always:
            return True

        # Skip remaining confirmations if plan was just confirmed (5-min window).
        if self.skip_confirmations_until is not None and time.time() < self.skip_confirmations_until:
            return False

        if self.config.get("confirm_readonly", False):
            return True

        return False

    def _tool_run_command(self, args: dict) -> str:
        command = args.get("command", "").strip()
        if not command:
            return "Error: empty command."
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

    # ------------------------------------------------------------------
    # Source scoring — mechatronics-oriented priority
    # ------------------------------------------------------------------

    # (domain, hostname_fragment, bonus)
    _SOURCE_SCORES: list[tuple[str, str, int]] = [
        ("official_docs",    "docs.arduino.cc",          10),
        ("official_docs",    "docs.espressif.com",       10),
        ("official_docs",    "platformio.org",            9),
        ("official_docs",    "micropython.org",           9),
        ("official_docs",    "docs.python.org",           8),
        ("official_docs",    "docs.ros.org",              9),
        ("official_docs",    "cppreference.com",          8),
        ("official_docs",    "modbus.org",                9),
        ("official_docs",    "can-cia.org",               9),
        ("github",           "github.com",                7),
        ("community",        "stackoverflow.com",         5),
        ("community",        "electronics.stackexchange", 5),
        ("community",        "hackaday.com",              4),
        ("community",        "instructables.com",         3),
        ("community",        "reddit.com",                2),
    ]

    def _score_url(self, url: str) -> tuple[int, str]:
        """Return (score, domain_label) for a URL. Higher is more trustworthy."""
        lowered = (url or "").lower()
        for domain_label, fragment, bonus in self._SOURCE_SCORES:
            if fragment in lowered:
                return bonus, domain_label
        return 1, "web"

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

        # Fetch more raw results so we can re-rank by source quality.
        fetch_limit = min(max_results * 3, 30)
        search_date = datetime.now().strftime("%Y-%m-%d")

        try:
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://duckduckgo.com/html/?q={encoded_query}"
            req = urllib.request.Request(url, headers={"User-Agent": "Willy/1.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_html = resp.read().decode("utf-8", errors="replace")

            raw_results: list[tuple[str, str]] = []
            marker = 'class="result__a"'
            pos = 0
            while len(raw_results) < fetch_limit:
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
                    raw_results.append((title, clean_url))

                pos = text_end + 4

            if not raw_results:
                return f"No web results found for: {query}"

            # Re-rank: sort by source score descending, keep position as tiebreaker.
            scored = [
                (self._score_url(link)[0], self._score_url(link)[1], pos_idx, title, link)
                for pos_idx, (title, link) in enumerate(raw_results)
            ]
            scored.sort(key=lambda x: (-x[0], x[2]))
            top = scored[:max_results]

            lines = [f"Web results for: {query}  [consulted: {search_date}]"]
            for rank, (score, domain_label, _pos, title, link) in enumerate(top, start=1):
                lines.append(f"{rank}. [{domain_label}] {title}")
                lines.append(f"   URL: {link}")
                lines.append(f"   source_quality: {score}/10  date_consulted: {search_date}")
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
        project_path = self._resolve_path((args.get("project_path") or "").strip())

        if not isinstance(components, list) or not components:
            return "Error: components must be a non-empty array."
        if not isinstance(connections, list):
            return "Error: connections must be an array."

        result = self.diagram_manager.generate_schematic(
            title=title,
            board=board,
            components=components,
            connections=connections,
            project_path=project_path,
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

    def _tool_manage_dependencies(self, args: dict) -> str:
        action = (args.get("action") or "").strip().lower()
        ecosystem = (args.get("ecosystem") or "").strip().lower()
        packages = [str(p) for p in (args.get("packages") or [])]
        project_path = (args.get("project_path") or "").strip()
        use_sudo = bool(args.get("use_sudo", False))
        policy = (args.get("policy") or "balanced").strip().lower()

        if project_path:
            project_path = self._resolve_path(project_path)

        if action == "detect":
            ecosystems = self.dep_manager.detect_ecosystem(project_path or None)
            if not ecosystems:
                return "No ecosystems detected for this project."
            return "Detected ecosystems: " + ", ".join(ecosystems)

        if action == "summary":
            if not ecosystem:
                return "Error: ecosystem is required for summary."
            return self.dep_manager.summary(ecosystem, project_path or None)

        if action == "snapshot":
            if not ecosystem:
                return "Error: ecosystem is required for snapshot."
            snap = self.dep_manager.snapshot(ecosystem, project_path or None)
            if snap is None:
                return f"Could not capture snapshot for {ecosystem}."
            return f"Snapshot saved: {len(snap.packages)} packages in {ecosystem} at {snap.timestamp}."

        if action == "install":
            if not ecosystem:
                return "Error: ecosystem is required for install."
            if not packages:
                return "Error: packages list is required for install."
            result = self.dep_manager.install(
                ecosystem, packages,
                project_path=project_path or None,
                use_sudo=use_sudo,
            )
            status = "OK" if result.ok else "FAILED"
            rb = " | rollback_available: yes" if result.rollback_available else ""
            return f"[{status}] install {ecosystem}: {result.message}{rb}"

        if action == "update":
            if not ecosystem:
                return "Error: ecosystem is required for update."
            result = self.dep_manager.update(
                ecosystem, packages or None,
                project_path=project_path or None,
                use_sudo=use_sudo,
                policy=policy,
            )
            status = "OK" if result.ok else "FAILED"
            rb = " | rollback_available: yes" if result.rollback_available else ""
            return f"[{status}] update {ecosystem} (policy={policy}): {result.message}{rb}"

        if action == "rollback":
            if not ecosystem:
                return "Error: ecosystem is required for rollback."
            result = self.dep_manager.rollback(ecosystem, project_path or None)
            status = "OK" if result.ok else "FAILED"
            return f"[{status}] rollback {ecosystem}: {result.message}"

        return f"Error: unknown action '{action}'. Use: detect, snapshot, install, update, rollback, summary."

    def _tool_generate_flowchart(self, args: dict) -> str:
        project_path = self._resolve_path((args.get("project_path") or "").strip())
        title = (args.get("title") or "").strip()

        if not project_path:
            return "Error: project_path is required."

        result = self.flowchart_manager.generate_from_project(project_path=project_path, title=title)
        if not result.ok:
            return f"Error generating flowchart: {result.message}"

        if callable(self.on_flowchart_generated):
            try:
                self.on_flowchart_generated(result.svg_path, result.mmd_path)
            except Exception:
                pass

        lines = [
            "Flowchart generated successfully.",
            f"Project: {result.project_path}",
            f"Mermaid: {result.mmd_path}",
        ]
        if result.svg_path:
            lines.append(f"SVG: {result.svg_path}")
        if result.png_path:
            lines.append(f"PNG: {result.png_path}")
        lines.append(f"Notes: {result.message}")
        return "\n".join(lines)

    def generate_flowchart_for_project(self, project_path: str, title: str = "") -> None:
        def _run() -> None:
            output = self._tool_generate_flowchart({"project_path": project_path, "title": title})
            if callable(self.on_message):
                try:
                    self.on_message("system", output)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    def _record_response_usage(self, usage, *, model: str | None = None) -> dict | None:
        if usage is None:
            return None

        prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", 0) or 0)

        self.session_total_tokens += total_tokens
        remaining = max(0, int(self.session_token_budget) - int(self.session_total_tokens))
        credit_percent = int((remaining / max(1, int(self.session_token_budget))) * 100)

        payload = {
            "model": model or self.config.get("model", "gpt-4o"),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "session_total_tokens": int(self.session_total_tokens),
            "session_remaining_tokens": remaining,
            "session_credit_percent": credit_percent,
            "session_budget_tokens": int(self.session_token_budget),
            "status_text": f"AI tokens: {self.session_total_tokens}/{self.session_token_budget}",
        }

        if callable(self.on_usage_update):
            try:
                self.on_usage_update(payload)
            except Exception:
                pass

        return payload

    def _log_event(self, event_type: str, payload: dict) -> None:
        """Best-effort local logging for debugging tool-call failures."""
        try:
            stamp = datetime.now().isoformat(timespec="seconds")
            line = json.dumps(
                {
                    "timestamp": stamp,
                    "event": event_type,
                    "payload": {
                        k: redact_sensitive_text(str(v), max_chars=20_000)
                        for k, v in (payload or {}).items()
                    },
                },
                ensure_ascii=False,
            )
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            # Logging must never break the chat flow.
            pass
