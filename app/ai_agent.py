"""
ai_agent.py — OpenAI client with tool/function calling for terminal operations.
"""

import json
import os
import threading
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Callable, Optional

import openai
from app import i18n

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
]

SYSTEM_PROMPT = """You are Willy, an intelligent AI assistant fully integrated with the user's Linux (Lubuntu) terminal.

You have access to the following tools:
- run_command: execute any shell command
- read_file: read a file's contents
- write_file: create or edit a file
- list_directory: list directory contents
- get_weather: get current weather for any city via wttr.in

Guidelines:
- When asked to do something that requires terminal interaction, use the appropriate tool.
- For commands that could be destructive (rm, sudo, overwriting files, etc.), briefly explain what you are about to do before the tool call. The UI will ask the user for confirmation.
- For read-only operations (ls, cat, pwd, etc.) you can proceed directly.
- Always show the output of commands to the user in your response.
- Be concise and helpful. Respond in the same language the user uses.
- If a command fails, analyze the error output and suggest a fix.
"""

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "willy_tool_errors.log")


class AIAgent:
    def __init__(
        self,
        config: dict,
        terminal_manager,
        on_message: Callable[[str, str], None],
        on_confirm_request: Callable[[str, str, Callable], None],
        on_status: Callable[[str], None],
    ):
        """
        Parameters
        ----------
        config              : loaded config dict
        terminal_manager    : TerminalManager instance
        on_message          : callback(role, text) — add a message to chat
        on_confirm_request  : callback(title, detail, proceed_fn) — ask user to confirm
        on_status           : callback(status_text) — update status bar
        """
        self.config = config
        self.tm = terminal_manager
        self.on_message = on_message
        self.on_confirm = on_confirm_request
        self.on_status = on_status
        self.history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._client: Optional[openai.OpenAI] = None

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

    def _process(self, user_text: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.on_status(i18n.get("ai_thinking"))
        try:
            client = self._get_client()
            model = self.config.get("model", "gpt-4o")
            recovered_bad_history = False
            # Agentic loop: keep going until no more tool calls
            while True:
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

                if msg.tool_calls:
                    # Process each tool call
                    for tc in msg.tool_calls:
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
                    continue

                # No tool calls — final text response
                assistant_text = msg.content or ""
                if assistant_text:
                    self.on_message("assistant", assistant_text)
                break

        except ValueError as exc:
            self.on_message("error", str(exc))
        except openai.AuthenticationError:
            self.on_message("error", "Invalid API key. Please check config.json.")
        except openai.RateLimitError:
            self.on_message("error", "Rate limit reached. Please wait a moment.")
        except Exception as exc:  # noqa: BLE001
            self.on_message("error", f"Unexpected error: {exc}")
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
        }
        handler = dispatch.get(name)
        if handler is None:
            return f"Error: unknown tool '{name}'."
        return handler(args)

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _needs_confirmation(self, command: str) -> bool:
        if self.config.get("confirm_readonly", False):
            return True
        always = self.config.get("always_confirm", [])
        first_token = command.strip().split()[0] if command.strip() else ""
        return first_token in always

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
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, path: str) -> str:
        if path.startswith("~"):
            return os.path.expanduser(path)
        if os.path.isabs(path):
            return path
        return os.path.normpath(os.path.join(self.tm.get_cwd(), path))

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
