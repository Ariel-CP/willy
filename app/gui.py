"""
gui.py — Main application window.
Layout:  [FileBrowser (sidebar)] | [ChatPanel] | [TerminalPanel]
"""

import json
import os
import platform
import socket
import queue
import threading
import traceback
import webbrowser
from datetime import datetime
import tkinter as tk
import customtkinter as ctk
from PIL import Image, ImageTk

try:
    import cairosvg
except Exception:
    cairosvg = None

from app.terminal_manager import TerminalManager
from app.terminal_panel import TerminalPanel
from app.chat_panel import ChatPanel
from app.file_browser import FileBrowser
from app.ai_agent import AIAgent
from app.session_logger import SessionLogger
from app.tts import TTSEngine
from app.arduino_manager import ArduinoManager
from app import i18n
from app.clippy_widget import ClippyWidget


CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")


def _is_configured_api_key(value: str) -> bool:
    value = (value or "").strip()
    return bool(value) and not value.startswith("sk-YOUR")


def _resolve_api_source(config: dict) -> str:
    source = config.get("api_key_source", "")
    if source in {"env", "config"}:
        return source
    return "config" if _is_configured_api_key(config.get("openai_api_key", "")) else "env"


def _load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid config.json: {exc}") from exc


class WillyApp(ctk.CTk):
    def __init__(self):
        config = _load_config()
        i18n.set_language(config.get("language", "es"))
        ctk.set_appearance_mode(config.get("theme", "dark"))
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.config_data = config
        self.title(i18n.get("app_title"))
        self.geometry("1280x760")
        self.minsize(900, 600)
        self._app_session_start_ts = datetime.now().timestamp()

        self._device_scan_running = False
        self._device_poll_job = None
        self._detected_devices = []
        self._diagram_poll_job = None
        self._latest_schematic_path = ""
        self._latest_bom_path = ""
        self._schematic_preview_image = None
        self._schematic_preview_photo = None
        self.serial_window = None
        self.serial_output_text = None
        self.serial_terminal_manager = None
        self.serial_status_var = tk.StringVar(value="Monitor serial inactivo")
        self.serial_timestamps_var = tk.BooleanVar(value=True)
        self.serial_freeze_var = tk.BooleanVar(value=False)
        self.serial_paused_buffer: list[str] = []
        self.serial_paused_buffer_max = 5000

        self._build_layout()
        self._wire_up()
        self.after(50, self._process_tts_visual_events)
        self.after(200, self._show_startup_greeting)
        self.after(800, self._trigger_device_scan)
        self.after(1200, self._refresh_latest_schematic)

        self.bind("<Control-comma>", lambda _e: self._open_settings())
        self.bind("<Control-b>", lambda _e: self._toggle_sidebar())
        self._sidebar_visible = True

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=1)

        initial_dir = self.config_data.get("initial_directory", "~")
        self.session_logger = SessionLogger()
        self.session_logger.log_event(
            "app_start",
            component="gui",
            data={"cwd": os.getcwd(), "config_path": CONFIG_PATH},
        )
        self.terminal_manager = TerminalManager(
            output_callback=self._on_terminal_output,
            initial_dir=initial_dir,
            on_command_done=self.session_logger.log_command,
        )

        # Initialize ArduinoManager for microcontroller operations
        self.arduino_manager = ArduinoManager(
            config=self.config_data,
            on_status=self._on_status,
            on_error=lambda msg: self._on_system_error(msg, component="arduino"),
        )

        # Catch UI and background-thread exceptions into diagnostics logs.
        self.report_callback_exception = self._handle_tk_exception
        threading.excepthook = self._handle_thread_exception

        self.file_browser = FileBrowser(
            self,
            on_file_selected=self._on_file_selected,
            width=200,
            fg_color=("gray90", "gray12"),
        )
        self.file_browser.grid(row=0, column=0, sticky="nsew")

        self.chat_panel = ChatPanel(
            self,
            fg_color=("gray95", "#0a0f14"),
        )
        self.chat_panel.grid(row=0, column=1, sticky="nsew", padx=(1, 1))

        # --- ClippyWidget dentro del chat ---
        self.clippy = ClippyWidget(self.chat_panel, size=72)
        self.clippy.enable_drag()
        self.clippy.set_drag_end_callback(self._save_clippy_position)
        self.after_idle(self._restore_clippy_position)

        self.right_panel = ctk.CTkFrame(self, fg_color=("gray92", "#0a0f14"))
        self.right_panel.grid(row=0, column=2, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, minsize=260)
        self.right_panel.grid_rowconfigure(1, weight=1)

        self._build_iot_dashboard(self.right_panel)

        self.terminal_panel = TerminalPanel(
            self.right_panel,
            terminal_manager=self.terminal_manager,
            fg_color=("gray92", "#0a0f14"),
        )
        self.terminal_panel.grid(row=1, column=0, sticky="nsew")

        status_bar = ctk.CTkFrame(self, height=22, fg_color=("gray80", "gray18"))
        status_bar.grid(row=1, column=0, columnspan=3, sticky="ew")
        status_bar.grid_columnconfigure(0, weight=1)

        self.status_bar_label = ctk.CTkLabel(
            status_bar,
            text=f"  {i18n.get('ready')}",
            font=ctk.CTkFont(size=10),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.status_bar_label.grid(row=0, column=0, sticky="ew", padx=4)

        self.progress_bar = ctk.CTkProgressBar(
            status_bar,
            width=180,
            height=10,
            corner_radius=6,
            progress_color="#64748b",
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=0, column=1, padx=(0, 6), pady=4)

        self.progress_percent_label = ctk.CTkLabel(
            status_bar,
            text="0%",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray35", "gray70"),
            width=42,
            anchor="e",
        )
        self.progress_percent_label.grid(row=0, column=2, padx=(0, 8), pady=2, sticky="e")
        self._progress_state = "idle"
        self._progress_current = 0.0
        self._progress_target = 0.0
        self._progress_animation_job = None

        ctk.CTkButton(
            status_bar,
            text=i18n.get("settings_btn"),
            width=80,
            height=18,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=("gray70", "gray30"),
            command=self._open_settings,
        ).grid(row=0, column=3, padx=(0, 4))

    def _build_iot_dashboard(self, parent) -> None:
        dashboard = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        dashboard.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        dashboard.grid_columnconfigure(0, weight=1)
        dashboard.grid_rowconfigure(8, weight=1)

        top_row = ctk.CTkFrame(dashboard, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 4))
        top_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top_row,
            text="Estado IoT",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
        ).grid(row=0, column=0, sticky="w")

        self.scan_btn = ctk.CTkButton(
            top_row,
            text="Escanear",
            width=86,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._trigger_device_scan,
        )
        self.scan_btn.grid(row=0, column=2, sticky="e")

        status_row = ctk.CTkFrame(dashboard, fg_color="transparent")
        status_row.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        status_row.grid_columnconfigure(1, weight=1)

        self.device_indicator = tk.Canvas(
            status_row,
            width=20,
            height=20,
            highlightthickness=0,
            bd=0,
            bg="#111821",
        )
        self.device_indicator.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 8))

        self.device_status_label = ctk.CTkLabel(
            status_row,
            text="Dispositivo: no conectado",
            font=ctk.CTkFont(size=11),
            anchor="w",
            justify="left",
        )
        self.device_status_label.grid(row=0, column=1, sticky="w")

        self.device_detail_label = ctk.CTkLabel(
            status_row,
            text="Esperando escaneo...",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
        )
        self.device_detail_label.grid(row=1, column=1, sticky="w")

        device_row = ctk.CTkFrame(dashboard, fg_color="transparent")
        device_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 4))
        device_row.grid_columnconfigure(0, weight=1)

        self.device_picker_var = tk.StringVar(value="Sin dispositivos")
        self.device_picker = ctk.CTkOptionMenu(
            device_row,
            variable=self.device_picker_var,
            values=["Sin dispositivos"],
            width=220,
        )
        self.device_picker.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.connect_btn = ctk.CTkButton(
            device_row,
            text="Conectar",
            width=92,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._connect_selected_device,
            state="disabled",
        )
        self.connect_btn.grid(row=0, column=1, sticky="e")

        monitor_row = ctk.CTkFrame(dashboard, fg_color="transparent")
        monitor_row.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 4))
        monitor_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            monitor_row,
            text="Monitor serial",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray35", "gray75"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.serial_baud_var = tk.StringVar(value=str(self.config_data.get("serial_baud", 115200)))
        self.serial_baud_entry = ctk.CTkEntry(
            monitor_row,
            width=86,
            textvariable=self.serial_baud_var,
            placeholder_text="115200",
        )
        self.serial_baud_entry.grid(row=0, column=1, sticky="w", padx=(0, 6))

        self.serial_start_btn = ctk.CTkButton(
            monitor_row,
            text="Iniciar",
            width=72,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._start_serial_monitor,
        )
        self.serial_start_btn.grid(row=0, column=2, sticky="e", padx=(0, 4))

        self.serial_open_btn = ctk.CTkButton(
            monitor_row,
            text="Abrir",
            width=62,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._open_serial_monitor_window,
        )
        self.serial_open_btn.grid(row=0, column=3, sticky="e", padx=(0, 4))

        self.serial_stop_btn = ctk.CTkButton(
            monitor_row,
            text="Detener",
            width=72,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#c0392b",
            hover_color="#922b21",
            command=self._stop_serial_monitor,
        )
        self.serial_stop_btn.grid(row=0, column=4, sticky="e")

        self.serial_hint_label = ctk.CTkLabel(
            monitor_row,
            text="Salida en ventana dedicada del monitor serial",
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "gray65"),
            anchor="w",
        )
        self.serial_hint_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(2, 0))

        self.serial_state_label = ctk.CTkLabel(
            monitor_row,
            textvariable=self.serial_status_var,
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "#7ec8e3"),
            anchor="w",
        )
        self.serial_state_label.grid(row=2, column=0, columnspan=5, sticky="w", pady=(1, 0))

        diagram_row = ctk.CTkFrame(dashboard, fg_color="transparent")
        diagram_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 4))
        diagram_row.grid_columnconfigure(0, weight=1)

        self.diagram_status_label = ctk.CTkLabel(
            diagram_row,
            text="Diagrama: sin generar",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
        )
        self.diagram_status_label.grid(row=0, column=0, sticky="w")

        self.diagram_refresh_btn = ctk.CTkButton(
            diagram_row,
            text="Actualizar",
            width=86,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._refresh_latest_schematic,
        )
        self.diagram_refresh_btn.grid(row=0, column=1, sticky="e", padx=(6, 4))

        self.diagram_open_btn = ctk.CTkButton(
            diagram_row,
            text="Abrir",
            width=62,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._open_latest_schematic,
            state="disabled",
        )
        self.diagram_open_btn.grid(row=0, column=2, sticky="e")

        ctk.CTkLabel(
            dashboard,
            text="Preview del esquema",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray30", "gray80"),
            anchor="w",
        ).grid(row=5, column=0, sticky="w", padx=8, pady=(4, 2))

        self.diagram_preview = tk.Label(
            dashboard,
            text="Sin preview disponible",
            bg="#0d1117",
            fg="#9ca3af",
            anchor="center",
            justify="center",
            height=6,
        )
        self.diagram_preview.grid(row=6, column=0, sticky="ew", padx=8, pady=(0, 6))

        ctk.CTkLabel(
            dashboard,
            text="Codigo en desarrollo",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray30", "gray80"),
            anchor="w",
        ).grid(row=7, column=0, sticky="w", padx=8, pady=(2, 2))

        self.code_preview = ctk.CTkTextbox(
            dashboard,
            height=140,
            font=ctk.CTkFont(family="monospace", size=11),
            fg_color=("gray96", "#0d1117"),
            border_color=("gray70", "gray40"),
            border_width=1,
            wrap="word",
        )
        self.code_preview.grid(row=8, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.code_preview.insert("0.0", "Selecciona un archivo para ver el codigo en desarrollo...")
        self.code_preview.configure(state="disabled")

        self._set_device_indicator(False)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def _wire_up(self) -> None:
        self.ai_agent = AIAgent(
            config=self.config_data,
            terminal_manager=self.terminal_manager,
            on_message=self._on_ai_message,
            on_confirm_request=self._on_confirm_request,
            on_status=self._on_status,
            on_progress=self._on_progress,
            arduino_manager=self.arduino_manager,
            on_file_written=self._on_ai_file_written,
            on_schematic_generated=self._on_schematic_generated,
        )

        def _logged_send(text: str) -> None:
            self.session_logger.log_message("user", text)
            # Reacción: pensando cuando el usuario escribe
            self.clippy.set_expression("thinking")
            self.ai_agent.send(text)

        self.chat_panel.set_send_callback(_logged_send)

        self.tts = TTSEngine(lang=self.config_data.get("language", "es"), config=self.config_data)
        self._tts_visual_events = queue.Queue()
        # --- Sincronizar animación de boca con TTS ---
        def tts_callback(text):
            self.tts.speak(
                text,
                on_energy=lambda energy: self._tts_visual_events.put(("energy", energy)),
                on_start=lambda: self._tts_visual_events.put(("start", None)),
                on_end=lambda: self._tts_visual_events.put(("end", None)),
            )
        self.chat_panel.set_tts_callback(tts_callback)
        self.chat_panel.set_volume_callback(self.tts.set_volume)
        self.tts.set_volume(0.35)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _show_startup_greeting(self) -> None:
        try:
            os_name = platform.system()
            os_ver = platform.release()
            distro = ""
            if os_name == "Linux":
                try:
                    import distro as _d
                    distro = f" ({_d.name(pretty=True)})"
                except ImportError:
                    try:
                        distro = f" ({platform.freedesktop_os_release().get('PRETTY_NAME', '')})"
                    except Exception:
                        pass
            username = os.environ.get("USER") or os.environ.get("USERNAME") or "desconocido"
            hostname = socket.gethostname()
            lang = self.config_data.get("language", "es")
            if lang == "es":
                msg = (
                    f"¡Hola, {username}! Estoy corriendo en:\n"
                    f"  • Sistema: {os_name} {os_ver}{distro}\n"
                    f"  • Usuario: {username}\n"
                    f"  • Equipo:  {hostname}"
                )
            else:
                msg = (
                    f"Hello, {username}! Running on:\n"
                    f"  • OS: {os_name} {os_ver}{distro}\n"
                    f"  • User: {username}\n"
                    f"  • Host: {hostname}"
                )
            self.chat_panel.add_message("system", msg)
        except Exception:
            pass

    def _on_terminal_output(self, text: str) -> None:
        self.terminal_panel.append_output(text)
        self.after(100, self.terminal_panel.update_cwd)

    def _on_ai_message(self, role: str, text: str) -> None:
        self.chat_panel.add_message(role, text)
        self.session_logger.log_message(role, text)
        if role == "error":
            self.session_logger.log_error("ai_agent", text)
        # Reacciones suaves para un asistente amigable orientado a adultos mayores.
        if role == "assistant":
            if "Web results for:" in text or "Source URL:" in text:
                self.clippy.set_expression("surprised")
            elif "¡Hola" in text or "Hello" in text:
                self.clippy.set_expression("happy")
            else:
                self.clippy.set_expression("smile")
        elif role == "error":
            self.clippy.set_expression("neutral")
        else:
            self.clippy.set_expression("smile")

    def _on_confirm_request(self, title: str, detail: str, callback) -> None:
        self.chat_panel.show_confirm_dialog(title, detail, callback)
        # Reacción: parpadeo cuando se pide confirmación
        self.clippy.blink()

    def _on_status(self, text: str) -> None:
        self.chat_panel.set_status(text)
        self.after(0, self.status_bar_label.configure, {
            "text": f"  {text}" if text else f"  {i18n.get('ready')}"
        })
        lowered = (text or "").lower()
        if any(token in lowered for token in ("error", "failed", "fallo", "exception")):
            self.session_logger.log_event(
                "status_warning",
                level="warning",
                component="status",
                data={"text": text},
            )

    def _on_progress(self, percent: float, detail: str = "") -> None:
        """Update bottom progress bar with completion percentage."""
        try:
            pct = max(0.0, min(100.0, float(percent)))
        except Exception:
            pct = 0.0

        detail_l = (detail or "").lower()
        if any(token in detail_l for token in ("error", "failed", "fallo", "exception")):
            state = "error"
        elif any(token in detail_l for token in ("confirm", "esperando", "plan detectado")):
            state = "waiting"
        elif pct >= 100.0:
            state = "success"
        elif pct > 0:
            state = "running"
        else:
            state = "idle"

        def _apply() -> None:
            self._progress_target = pct
            self._set_progress_theme(state)
            self._ensure_progress_animation()

            # Keep status and progress consistent for user confidence.
            if detail:
                self.status_bar_label.configure(text=f"  {detail} ({int(round(pct))}%)")

        self.after(0, _apply)

    def _ensure_progress_animation(self) -> None:
        if self._progress_animation_job is not None:
            return
        self._progress_animation_job = self.after(16, self._animate_progress)

    def _animate_progress(self) -> None:
        self._progress_animation_job = None

        current = float(self._progress_current)
        target = float(self._progress_target)
        delta = target - current

        # Ease-out interpolation: smooth at long jumps, precise near target.
        if abs(delta) < 0.2:
            current = target
        else:
            current = current + (delta * 0.24)

        self._progress_current = max(0.0, min(100.0, current))

        if hasattr(self, "progress_bar"):
            self.progress_bar.set(self._progress_current / 100.0)
        if hasattr(self, "progress_percent_label"):
            self.progress_percent_label.configure(text=f"{int(round(self._progress_current))}%")

        if abs(self._progress_target - self._progress_current) >= 0.2:
            self._progress_animation_job = self.after(16, self._animate_progress)

    def _set_progress_theme(self, state: str) -> None:
        if state == self._progress_state:
            return
        self._progress_state = state

        palette = {
            "idle": ("#64748b", ("gray35", "gray70")),
            "running": ("#2563eb", ("#1e3a8a", "#93c5fd")),
            "waiting": ("#f59e0b", ("#92400e", "#fcd34d")),
            "success": ("#22c55e", ("#166534", "#86efac")),
            "error": ("#ef4444", ("#991b1b", "#fca5a5")),
        }
        progress_color, text_color = palette.get(state, palette["idle"])

        if hasattr(self, "progress_bar"):
            self.progress_bar.configure(progress_color=progress_color)
        if hasattr(self, "progress_percent_label"):
            self.progress_percent_label.configure(text_color=text_color)

    def _on_system_error(self, message: str, component: str = "system") -> None:
        self.session_logger.log_error(component, message)

    def _on_file_selected(self, path: str) -> None:
        self.chat_panel.add_message("system", i18n.get("file_selected", path=path))
        self._update_code_preview(path)
        self.ai_agent.send(i18n.get("file_send_msg", path=path))

    def _on_schematic_generated(self, svg_path: str, bom_path: str) -> None:
        # Called from agent worker thread; marshal to UI thread.
        self.after(0, self._apply_generated_schematic, svg_path, bom_path)

    def _apply_generated_schematic(self, svg_path: str, bom_path: str) -> None:
        self._latest_schematic_path = svg_path or ""
        self._latest_bom_path = bom_path or ""

        if hasattr(self, "diagram_status_label"):
            if svg_path and os.path.isfile(svg_path):
                self.diagram_status_label.configure(text=f"Diagrama: {os.path.basename(svg_path)}")
                self.diagram_open_btn.configure(state="normal")
            else:
                self.diagram_status_label.configure(text="Diagrama: sin generar en esta sesión")
                self.diagram_open_btn.configure(state="disabled")

        self._update_schematic_preview(svg_path)

    def _on_ai_file_written(self, path: str, content: str) -> None:
        # Called from agent worker thread; marshal to UI thread.
        self.after(0, self._update_code_preview_from_content, path, content)

    def _update_code_preview_from_content(self, path: str, content: str) -> None:
        preview = f"Archivo (editado por Willy): {path}\n\n{content}"
        if len(preview) > 6500:
            preview = preview[:6500] + "\n\n[...archivo truncado en 6500 caracteres...]"

        if hasattr(self, "code_preview"):
            self.code_preview.configure(state="normal")
            self.code_preview.delete("0.0", "end")
            self.code_preview.insert("0.0", preview)
            self.code_preview.configure(state="disabled")

    def _set_device_indicator(self, connected: bool) -> None:
        if not hasattr(self, "device_indicator"):
            return
        self.device_indicator.delete("all")
        color = "#22c55e" if connected else "#ef4444"
        self.device_indicator.create_oval(3, 3, 17, 17, fill=color, outline=color)

    def _trigger_device_scan(self) -> None:
        if self._device_scan_running:
            return
        if hasattr(self, "scan_btn"):
            self.scan_btn.configure(state="disabled")
        threading.Thread(target=self._scan_devices_async, daemon=True).start()

    def _scan_devices_async(self) -> None:
        self._device_scan_running = True
        devices = []
        error = None
        try:
            if not hasattr(self, "arduino_manager") or self.arduino_manager is None:
                error = "Arduino manager no disponible"
            else:
                devices = self.arduino_manager.detect_microcontrollers()
        except Exception as exc:
            error = str(exc)
        finally:
            self.after(0, self._update_device_status, devices, error)

    def _update_device_status(self, devices, error=None) -> None:
        self._device_scan_running = False
        if hasattr(self, "scan_btn"):
            self.scan_btn.configure(state="normal")

        if error:
            self._on_system_error(str(error), component="device_scan")
            self._detected_devices = []
            self._refresh_device_picker()
            self._set_device_indicator(False)
            self.device_status_label.configure(text="Dispositivo: no disponible")
            self.device_detail_label.configure(text=f"Error: {error[:110]}")
            self._schedule_next_device_poll()
            return

        if not devices:
            self._detected_devices = []
            self._refresh_device_picker()
            self._set_device_indicator(False)
            self.device_status_label.configure(text="Dispositivo: no conectado")
            self.device_detail_label.configure(text="No se detectaron dispositivos")
            self._schedule_next_device_poll()
            return

        self._detected_devices = list(devices)
        self._refresh_device_picker()
        first = devices[0]
        board = first.get("board", "unknown")
        port = first.get("port", "?")
        self._set_device_indicator(True)
        self.device_status_label.configure(text=f"Conectado: {board} en {port}")
        self.device_detail_label.configure(text=f"Dispositivos detectados: {len(devices)}")
        self._schedule_next_device_poll()

    def _refresh_device_picker(self) -> None:
        if not hasattr(self, "device_picker"):
            return

        if not self._detected_devices:
            self.device_picker.configure(values=["Sin dispositivos"])
            self.device_picker_var.set("Sin dispositivos")
            self.connect_btn.configure(state="disabled")
            return

        labels = []
        for dev in self._detected_devices:
            board = dev.get("board", "unknown")
            port = dev.get("port", "?")
            labels.append(f"{board} - {port}")

        self.device_picker.configure(values=labels)
        if self.device_picker_var.get() not in labels:
            self.device_picker_var.set(labels[0])
        self.connect_btn.configure(state="normal")

    def _connect_selected_device(self) -> None:
        selected = self.device_picker_var.get() if hasattr(self, "device_picker_var") else ""
        if not selected or selected == "Sin dispositivos":
            return

        selected_dev = None
        for dev in self._detected_devices:
            label = f"{dev.get('board', 'unknown')} - {dev.get('port', '?')}"
            if label == selected:
                selected_dev = dev
                break

        if not selected_dev:
            return

        board = selected_dev.get("board", "esp32")
        port = selected_dev.get("port", "/dev/ttyUSB0")
        self.config_data["default_board"] = board
        self.config_data["default_port"] = port

        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.config_data, fh, indent=4)
        except Exception:
            pass

        self.device_status_label.configure(text=f"Conectado: {board} en {port}")
        self.device_detail_label.configure(text="Puerto y placa por defecto actualizados")
        self._on_status(f"IoT activo: {board} en {port}")

    def _selected_or_default_port(self) -> str:
        selected = self.device_picker_var.get() if hasattr(self, "device_picker_var") else ""
        if selected and selected != "Sin dispositivos":
            for dev in self._detected_devices:
                label = f"{dev.get('board', 'unknown')} - {dev.get('port', '?')}"
                if label == selected:
                    return dev.get("port", self.config_data.get("default_port", "/dev/ttyUSB0"))
        return self.config_data.get("default_port", "/dev/ttyUSB0")

    def _start_serial_monitor(self) -> None:
        self._open_serial_monitor_window()

        port = self._selected_or_default_port()
        baud_raw = self.serial_baud_var.get().strip() if hasattr(self, "serial_baud_var") else "115200"
        try:
            baud = int(baud_raw)
            if baud <= 0:
                raise ValueError("baud must be positive")
        except Exception:
            self.chat_panel.add_message("error", f"Baudrate inválido: {baud_raw}")
            return

        if self.serial_terminal_manager and self.serial_terminal_manager.has_active_process():
            self.chat_panel.add_message("system", "El monitor serial ya está activo.")
            return

        self.config_data["serial_baud"] = baud
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.config_data, fh, indent=4)
        except Exception:
            pass

        if self.serial_terminal_manager is None:
            self.serial_terminal_manager = TerminalManager(
                output_callback=self._on_serial_monitor_output,
                initial_dir=self.terminal_manager.get_cwd(),
            )

        pio_cmd = self.arduino_manager.platformio_path if getattr(self.arduino_manager, "platformio_path", None) else "pio"
        command = f"{pio_cmd} device monitor -p {port} -b {baud}"

        self.serial_paused_buffer.clear()
        self.serial_freeze_var.set(False)
        self._serial_append_output(f"$ {command}\n")
        self._serial_append_output("[Monitor serial iniciado - presiona 'Detener' para finalizar]\n")
        self.serial_terminal_manager.run_command_async(command)
        self.serial_status_var.set(f"Monitor activo en {port} @ {baud}")
        self._on_status(f"Monitor serial activo en {port} @ {baud}")
        self.session_logger.log_event(
            "serial_monitor_started",
            component="iot",
            data={"port": port, "baud": baud},
        )

    def _stop_serial_monitor(self) -> None:
        if self.serial_terminal_manager and self.serial_terminal_manager.has_active_process():
            self.serial_terminal_manager.kill_active()
            self._serial_append_output("[Monitor serial detenido]\n")
            self.serial_status_var.set("Monitor serial detenido")
            self._on_status("Monitor serial detenido")
            self.session_logger.log_event("serial_monitor_stopped", component="iot")
        else:
            self.chat_panel.add_message("system", "No hay monitor serial activo.")

    def _open_serial_monitor_window(self) -> None:
        if self.serial_window is not None and self.serial_window.winfo_exists():
            self.serial_window.lift()
            self.serial_window.focus_force()
            return

        win = ctk.CTkToplevel(self)
        win.title("Consola Serial")
        win.geometry("760x420")
        win.minsize(520, 300)
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(win, fg_color=("gray85", "gray20"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="Monitor Serial",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, padx=(10, 6), pady=6, sticky="w")

        ctk.CTkLabel(
            header,
            textvariable=self.serial_status_var,
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "#7ec8e3"),
            anchor="w",
        ).grid(row=0, column=1, padx=4, pady=6, sticky="ew")

        ctk.CTkCheckBox(
            header,
            text="Timestamp",
            variable=self.serial_timestamps_var,
            width=90,
        ).grid(row=0, column=2, padx=(0, 6), pady=6)

        ctk.CTkCheckBox(
            header,
            text="Pausa",
            variable=self.serial_freeze_var,
            width=70,
            command=self._toggle_serial_freeze,
        ).grid(row=0, column=3, padx=(0, 6), pady=6)

        ctk.CTkButton(
            header,
            text="Limpiar",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            command=self._clear_serial_monitor,
        ).grid(row=0, column=4, padx=(0, 8), pady=6)

        ctk.CTkButton(
            header,
            text="Detener",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#c0392b",
            hover_color="#922b21",
            command=self._stop_serial_monitor,
        ).grid(row=0, column=5, padx=(0, 8), pady=6)

        output_frame = ctk.CTkFrame(win, fg_color=("gray95", "#0d1117"))
        output_frame.grid(row=1, column=0, sticky="nsew")
        output_frame.grid_rowconfigure(0, weight=1)
        output_frame.grid_columnconfigure(0, weight=1)

        output = tk.Text(
            output_frame,
            wrap="word",
            state="disabled",
            font=("monospace", 11),
            bg="#0d1117",
            fg="#d0d0d0",
            insertbackground="white",
            selectbackground="#264f78",
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
        )
        output.grid(row=0, column=0, sticky="nsew")
        scrollbar = ctk.CTkScrollbar(output_frame, command=output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        output.configure(yscrollcommand=scrollbar.set)

        self.serial_window = win
        self.serial_output_text = output

        def on_close() -> None:
            self._stop_serial_monitor()
            self.serial_window = None
            self.serial_output_text = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._serial_append_output("[Consola serial lista]\n")

    def _clear_serial_monitor(self) -> None:
        if self.serial_output_text is None:
            return
        self.serial_paused_buffer.clear()
        self.serial_output_text.configure(state="normal")
        self.serial_output_text.delete("1.0", "end")
        self.serial_output_text.configure(state="disabled")

    def _toggle_serial_freeze(self) -> None:
        if self.serial_freeze_var.get():
            self.serial_status_var.set("Monitor serial en pausa")
            return

        # Flush buffered lines when pause/freeze is disabled.
        if self.serial_paused_buffer:
            buffered = "".join(self.serial_paused_buffer)
            self.serial_paused_buffer.clear()
            self._serial_append_output(buffered)

        if self.serial_terminal_manager and self.serial_terminal_manager.has_active_process():
            self.serial_status_var.set("Monitor serial activo")
        else:
            self.serial_status_var.set("Monitor serial inactivo")

    def _format_serial_with_timestamps(self, text: str) -> str:
        if not self.serial_timestamps_var.get():
            return text

        lines = text.splitlines(keepends=True)
        if not lines:
            return text

        stamp = datetime.now().strftime("%H:%M:%S")
        out: list[str] = []
        for line in lines:
            if line.strip():
                out.append(f"[{stamp}] {line}")
            else:
                out.append(line)
        return "".join(out)

    def _serial_append_output(self, text: str) -> None:
        if self.serial_output_text is None:
            return
        self.serial_output_text.configure(state="normal")
        self.serial_output_text.insert("end", text)
        self.serial_output_text.configure(state="disabled")
        if not self.serial_freeze_var.get():
            self.serial_output_text.see("end")

    def _on_serial_monitor_output(self, text: str) -> None:
        # Called from TerminalManager worker thread: always marshal to UI thread.
        self.after(0, self._handle_serial_monitor_output_main, text)

    def _handle_serial_monitor_output_main(self, text: str) -> None:
        formatted = self._format_serial_with_timestamps(text)
        if self.serial_freeze_var.get():
            self.serial_paused_buffer.append(formatted)
            if len(self.serial_paused_buffer) > self.serial_paused_buffer_max:
                # Keep most recent chunks to avoid unbounded memory growth.
                self.serial_paused_buffer = self.serial_paused_buffer[-self.serial_paused_buffer_max:]
            buffered_count = len(self.serial_paused_buffer)
            self.serial_status_var.set(f"Monitor serial en pausa ({buffered_count} bloques en buffer)")
        else:
            self._serial_append_output(formatted)
        if "[Done]" in text or "Process exited" in text:
            self.serial_status_var.set("Monitor serial inactivo")

    def _schedule_next_device_poll(self) -> None:
        if self._device_poll_job is not None:
            try:
                self.after_cancel(self._device_poll_job)
            except Exception:
                pass
        self._device_poll_job = self.after(5000, self._trigger_device_scan)

    def _refresh_latest_schematic(self) -> None:
        schem_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "schematics")
        latest_svg = ""
        latest_bom = ""

        try:
            if os.path.isdir(schem_dir):
                svgs = [
                    os.path.join(schem_dir, name)
                    for name in os.listdir(schem_dir)
                    if name.lower().endswith(".svg")
                ]
                session_svgs = [
                    path for path in svgs
                    if os.path.getmtime(path) >= (self._app_session_start_ts - 1.0)
                ]
                if session_svgs:
                    latest_svg = max(session_svgs, key=os.path.getmtime)

                boms = [
                    os.path.join(schem_dir, name)
                    for name in os.listdir(schem_dir)
                    if name.lower().endswith("_bom.csv")
                ]
                session_boms = [
                    path for path in boms
                    if os.path.getmtime(path) >= (self._app_session_start_ts - 1.0)
                ]
                if session_boms:
                    latest_bom = max(session_boms, key=os.path.getmtime)
        except Exception:
            latest_svg = ""
            latest_bom = ""

        # Keep already-known generated paths in this session if scan didn't find newer files.
        if latest_svg:
            self._latest_schematic_path = latest_svg
        if latest_bom:
            self._latest_bom_path = latest_bom

        if hasattr(self, "diagram_status_label"):
            if self._latest_schematic_path and os.path.isfile(self._latest_schematic_path):
                display_name = os.path.basename(self._latest_schematic_path)
                self.diagram_status_label.configure(text=f"Diagrama: {display_name}")
                self.diagram_open_btn.configure(state="normal")
            else:
                self.diagram_status_label.configure(text="Diagrama: sin generar en esta sesión")
                self.diagram_open_btn.configure(state="disabled")

        self._update_schematic_preview(self._latest_schematic_path)

        self._schedule_next_diagram_poll()

    def _handle_tk_exception(self, exc_type, exc_value, exc_tb) -> None:
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        self.session_logger.log_error(
            "tkinter",
            str(exc_value),
            context={"traceback": tb_text},
        )
        self._on_ai_message("error", f"UI exception: {exc_value}")

    def _handle_thread_exception(self, args) -> None:
        tb_text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        self.session_logger.log_error(
            "thread",
            str(args.exc_value),
            context={
                "thread_name": getattr(args.thread, "name", "unknown"),
                "traceback": tb_text,
            },
        )

    def _update_schematic_preview(self, svg_path: str) -> None:
        if not hasattr(self, "diagram_preview"):
            return

        if not svg_path or not os.path.isfile(svg_path):
            self._schematic_preview_image = None
            self._schematic_preview_photo = None
            self.diagram_preview.configure(image="", text="Sin preview disponible")
            return

        png_candidate = os.path.splitext(svg_path)[0] + ".png"
        source_image_path = ""

        if os.path.isfile(png_candidate):
            source_image_path = png_candidate
        else:
            preview_cache = os.path.splitext(svg_path)[0] + "_preview.png"
            try:
                if cairosvg is not None:
                    cairosvg.svg2png(url=svg_path, write_to=preview_cache, output_width=900)
                    source_image_path = preview_cache
            except Exception:
                source_image_path = ""

        if not source_image_path or not os.path.isfile(source_image_path):
            self._schematic_preview_image = None
            self._schematic_preview_photo = None
            self.diagram_preview.configure(
                image="",
                text="Preview no disponible. Usa 'Abrir' para ver el SVG.",
            )
            return

        try:
            image = Image.open(source_image_path)
            image.thumbnail((760, 300), Image.Resampling.LANCZOS)
            self._schematic_preview_photo = ImageTk.PhotoImage(image)
            self._schematic_preview_image = image
            self.diagram_preview.configure(image=self._schematic_preview_photo, text="")
        except Exception:
            self._schematic_preview_image = None
            self._schematic_preview_photo = None
            self.diagram_preview.configure(
                image="",
                text="No se pudo cargar preview del diagrama.",
            )

    def _schedule_next_diagram_poll(self) -> None:
        if self._diagram_poll_job is not None:
            try:
                self.after_cancel(self._diagram_poll_job)
            except Exception:
                pass
        self._diagram_poll_job = self.after(7000, self._refresh_latest_schematic)

    def _open_latest_schematic(self) -> None:
        if not self._latest_schematic_path:
            return
        try:
            webbrowser.open(f"file://{self._latest_schematic_path}")
        except Exception:
            pass

    def _update_code_preview(self, path: str) -> None:
        preview = ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read(6000)
            preview = f"Archivo: {path}\n\n{content}"
            if len(content) >= 6000:
                preview += "\n\n[...archivo truncado en 6000 caracteres...]"
        except Exception as exc:
            preview = f"No se pudo leer el archivo seleccionado.\n\n{exc}"

        if hasattr(self, "code_preview"):
            self.code_preview.configure(state="normal")
            self.code_preview.delete("0.0", "end")
            self.code_preview.insert("0.0", preview)
            self.code_preview.configure(state="disabled")

    def _clippy_default_position(self) -> tuple[int, int]:
        return 8, 48

    def _clamp_clippy_position(self, x: int, y: int) -> tuple[int, int]:
        panel_w = max(1, self.chat_panel.winfo_width())
        panel_h = max(1, self.chat_panel.winfo_height())
        widget_w = max(1, self.clippy.winfo_width())
        widget_h = max(1, self.clippy.winfo_height())
        max_x = max(0, panel_w - widget_w)
        max_y = max(0, panel_h - widget_h)
        return max(0, min(int(x), max_x)), max(0, min(int(y), max_y))

    def _restore_clippy_position(self) -> None:
        saved_x = self.config_data.get("clippy_x")
        saved_y = self.config_data.get("clippy_y")
        if isinstance(saved_x, int) and isinstance(saved_y, int):
            x, y = saved_x, saved_y
        else:
            x, y = self._clippy_default_position()
        x, y = self._clamp_clippy_position(x, y)
        self.clippy.place(x=x, y=y)

    def _save_clippy_position(self, x: int, y: int) -> None:
        clamped_x, clamped_y = self._clamp_clippy_position(x, y)
        self.config_data["clippy_x"] = int(clamped_x)
        self.config_data["clippy_y"] = int(clamped_y)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self.config_data, fh, indent=4)
        except Exception:
            pass

    def _process_tts_visual_events(self) -> None:
        try:
            while True:
                event_type, value = self._tts_visual_events.get_nowait()
                if event_type == "start":
                    self.clippy.start_spectrum()
                elif event_type == "energy":
                    if isinstance(value, dict):
                        self.clippy.set_spectrum_level(bands=value)
                    else:
                        self.clippy.set_spectrum_level(level=value)
                elif event_type == "end":
                    self.clippy.stop_spectrum()
        except queue.Empty:
            pass
        self.after(50, self._process_tts_visual_events)
    # ------------------------------------------------------------------
    # Sidebar toggle
    # ------------------------------------------------------------------

    def _toggle_sidebar(self) -> None:
        if self._sidebar_visible:
            self.file_browser.grid_remove()
            self._sidebar_visible = False
        else:
            self.file_browser.grid()
            self._sidebar_visible = True

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = ctk.CTkToplevel(self)
        dlg.title(i18n.get("settings_title"))
        dlg.geometry("560x460")
        dlg.resizable(False, False)
        dlg.wait_visibility()
        dlg.grab_set()

        dlg.grid_columnconfigure(1, weight=1)

        def row(r, label, widget_factory):
            ctk.CTkLabel(dlg, text=label, anchor="e").grid(
                row=r, column=0, padx=(16, 8), pady=8, sticky="e"
            )
            w = widget_factory(dlg)
            w.grid(row=r, column=1, padx=(0, 16), pady=8, sticky="ew")
            return w

        api_var = tk.StringVar(value=self.config_data.get("openai_api_key", ""))
        source_to_label = {
            "env": i18n.get("api_source_env"),
            "config": i18n.get("api_source_config"),
        }
        label_to_source = {v: k for k, v in source_to_label.items()}
        api_source_var = tk.StringVar(value=source_to_label[_resolve_api_source(self.config_data)])

        row(
            0,
            i18n.get("settings_api_source"),
            lambda p: ctk.CTkOptionMenu(
                p,
                variable=api_source_var,
                values=[source_to_label["env"], source_to_label["config"]],
                width=220,
            ),
        )

        api_row = ctk.CTkFrame(dlg, fg_color="transparent")
        row(1, i18n.get("settings_api_key"), lambda _p: api_row)
        api_row.grid_columnconfigure(0, weight=1)

        api_entry = ctk.CTkEntry(api_row, textvariable=api_var, show="*", width=300)
        api_entry.grid(row=0, column=0, sticky="ew")
        entry_widget = getattr(api_entry, "_entry", api_entry)

        def _paste_api_key(_event=None):
            try:
                text = dlg.clipboard_get()
            except tk.TclError:
                return "break"

            entry_widget.focus_set()
            try:
                sel_first = entry_widget.index("sel.first")
                sel_last = entry_widget.index("sel.last")
                entry_widget.delete(sel_first, sel_last)
                insert_at = sel_first
            except tk.TclError:
                insert_at = entry_widget.index("insert")
            entry_widget.insert(insert_at, text)
            return "break"

        # Force common paste shortcuts on Linux/X11 and avoid widget-specific quirks.
        entry_widget.bind("<Control-v>", _paste_api_key)
        entry_widget.bind("<Control-V>", _paste_api_key)
        entry_widget.bind("<Shift-Insert>", _paste_api_key)

        api_menu = tk.Menu(dlg, tearoff=0)
        api_menu.add_command(label="Pegar", command=_paste_api_key)

        def _show_api_menu(event):
            entry_widget.focus_set()
            api_menu.tk_popup(event.x_root, event.y_root)
            api_menu.grab_release()
            return "break"

        entry_widget.bind("<Button-3>", _show_api_menu)
        entry_widget.bind("<Button-2>", _show_api_menu)

        hide_var = tk.BooleanVar(value=True)

        def _toggle_key_visibility() -> None:
            hide_var.set(not hide_var.get())
            api_entry.configure(show="*" if hide_var.get() else "")
            toggle_btn.configure(text=i18n.get("show_btn") if hide_var.get() else i18n.get("hide_btn"))

        toggle_btn = ctk.CTkButton(
            api_row,
            text=i18n.get("show_btn"),
            width=90,
            command=_toggle_key_visibility,
        )
        toggle_btn.grid(row=0, column=1, padx=(8, 0))

        api_status_label = ctk.CTkLabel(
            dlg,
            text="",
            anchor="w",
            justify="left",
            text_color=("gray40", "gray60"),
        )
        api_status_label.grid(row=2, column=1, padx=(0, 16), pady=(0, 8), sticky="w")

        def _refresh_api_controls(*_args) -> None:
            selected_source = label_to_source.get(api_source_var.get(), "env")
            using_env = selected_source == "env"
            env_key = os.getenv("OPENAI_API_KEY", "").strip()
            status_ok = i18n.get("api_status_ok")
            status_missing = i18n.get("api_status_missing")

            if using_env:
                status_text = status_ok if _is_configured_api_key(env_key) else status_missing
                api_status_label.configure(
                    text=i18n.get(
                        "settings_api_hint_env",
                        env_name="OPENAI_API_KEY",
                        status=status_text,
                    )
                    + "\n"
                    + i18n.get("settings_api_hint_env_note")
                )
            else:
                status_text = status_ok if _is_configured_api_key(api_var.get()) else status_missing
                api_status_label.configure(
                    text=i18n.get(
                        "settings_api_hint_config",
                        status=status_text,
                    )
                )

        api_source_var.trace_add("write", _refresh_api_controls)
        api_var.trace_add("write", _refresh_api_controls)
        _refresh_api_controls()

        model_var = tk.StringVar(value=self.config_data.get("model", "gpt-4o"))
        row(3, i18n.get("settings_model"), lambda p: ctk.CTkEntry(p, textvariable=model_var, width=300))

        dir_var = tk.StringVar(value=self.config_data.get("initial_directory", "~"))
        row(4, i18n.get("settings_initial_dir"), lambda p: ctk.CTkEntry(p, textvariable=dir_var, width=300))

        theme_var = tk.StringVar(value=self.config_data.get("theme", "dark"))
        row(5, i18n.get("settings_theme"), lambda p: ctk.CTkOptionMenu(p, variable=theme_var, values=["dark", "light", "system"], width=160))

        confirm_ro_var = tk.BooleanVar(value=self.config_data.get("confirm_readonly", False))
        row(6, i18n.get("settings_confirm_readonly"), lambda p: ctk.CTkCheckBox(p, text="", variable=confirm_ro_var))

        lang_display = {"Español": "es", "English": "en"}
        lang_var = tk.StringVar(value="Español" if self.config_data.get("language", "es") == "es" else "English")
        row(7, i18n.get("settings_language"), lambda p: ctk.CTkOptionMenu(p, variable=lang_var, values=["Español", "English"], width=160))

        tts_engine_var = tk.StringVar(value=self.config_data.get("tts_engine", "auto"))
        row(8, "TTS Engine", lambda p: ctk.CTkOptionMenu(p, variable=tts_engine_var, values=["auto", "piper", "espeak"], width=160))

        tts_senior_var = tk.BooleanVar(value=self.config_data.get("tts_senior_mode", True))
        row(9, "TTS Modo Senior", lambda p: ctk.CTkCheckBox(p, text="", variable=tts_senior_var))

        tts_rate_var = tk.StringVar(value=str(self.config_data.get("tts_rate", "0.90")))
        row(10, "TTS Velocidad", lambda p: ctk.CTkEntry(p, textvariable=tts_rate_var, width=140))

        piper_model_var = tk.StringVar(value=self.config_data.get("piper_model", ""))
        row(11, "Piper Model (.onnx)", lambda p: ctk.CTkEntry(p, textvariable=piper_model_var, width=320))

        # Microcontroller Defaults
        default_board_var = tk.StringVar(value=self.config_data.get("default_board", "esp32"))
        row(12, "Placa por defecto", lambda p: ctk.CTkOptionMenu(p, variable=default_board_var, values=["esp32", "esp32-s3", "arduino:avr:uno", "arduino:avr:nano", "pico"], width=160))

        default_port_var = tk.StringVar(value=self.config_data.get("default_port", "/dev/ttyUSB0"))
        row(13, "Puerto Serial", lambda p: ctk.CTkEntry(p, textvariable=default_port_var, width=160))

        confirm_upload_var = tk.BooleanVar(value=self.config_data.get("confirm_upload", True))
        row(14, "Confirmar Upload", lambda p: ctk.CTkCheckBox(p, text="", variable=confirm_upload_var))

        def _save():
            selected_source = label_to_source.get(api_source_var.get(), "env")
            self.config_data["api_key_source"] = selected_source
            self.config_data["openai_api_key"] = api_var.get().strip()
            self.config_data["model"] = model_var.get().strip()
            self.config_data["initial_directory"] = dir_var.get().strip()
            self.config_data["theme"] = theme_var.get()
            self.config_data["confirm_readonly"] = confirm_ro_var.get()
            self.config_data["language"] = lang_display.get(lang_var.get(), "es")
            self.config_data["tts_engine"] = tts_engine_var.get().strip().lower()
            self.config_data["tts_senior_mode"] = bool(tts_senior_var.get())
            try:
                self.config_data["tts_rate"] = float(tts_rate_var.get().strip())
            except Exception:
                self.config_data["tts_rate"] = 0.90
            self.config_data["piper_model"] = piper_model_var.get().strip()
            self.config_data["tts_cache_enabled"] = True
            # Microcontroller settings
            self.config_data["default_board"] = default_board_var.get().strip()
            self.config_data["default_port"] = default_port_var.get().strip()
            self.config_data["confirm_upload"] = bool(confirm_upload_var.get())
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                    json.dump(self.config_data, fh, indent=4)
            except Exception:
                pass
            ctk.set_appearance_mode(self.config_data["theme"])
            self.ai_agent.config = self.config_data
            self.ai_agent._client = None
            self.tts = TTSEngine(lang=self.config_data.get("language", "es"), config=self.config_data)
            self.tts.set_volume(0.35)
            dlg.grab_release()
            dlg.destroy()
            from tkinter import messagebox
            messagebox.showinfo(
                i18n.get("settings_title"),
                i18n.get("restart_notice"),
            )

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=15, column=0, columnspan=2, pady=(8, 16))
        ctk.CTkButton(
            btn_row,
            text=i18n.get("settings_cancel"),
            width=90,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: (dlg.grab_release(), dlg.destroy()),
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            btn_row,
            text=i18n.get("settings_save"),
            width=90,
            command=_save,
        ).pack(side="left", padx=8)
