"""
gui.py — Main application window.
Layout:  [FileBrowser (sidebar)] | [ChatPanel] | [TerminalPanel]
"""

import json
import os
import platform
import re
import socket
import queue
import threading
import traceback
import webbrowser
from datetime import datetime, timedelta
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


CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
STATION_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "station_policy.json",
)
AUDIT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "outputs",
    "audit",
)

PROJECT_PRESETS = {
    "Arduino Uno": {
        "board": "uno",
        "platform": "atmelavr",
        "framework": "arduino",
    },
    "ESP32 DevKit": {
        "board": "esp32dev",
        "platform": "espressif32",
        "framework": "arduino",
    },
    "ESP8266 NodeMCU": {
        "board": "nodemcuv2",
        "platform": "espressif8266",
        "framework": "arduino",
    },
    "Raspberry Pi Pico": {
        "board": "rpipico",
        "platform": "raspberrypi",
        "framework": "arduino",
    },
}

PROJECT_TEMPLATES = {
    "Base Generica": {
        "label": "Base Generica",
        "code": (
            "#include <Arduino.h>\n\n"
            "// Punto de entrada de inicializacion.\n"
            "void setup() {\n"
            "  // TODO: configura pines, buses y perifericos\n"
            "}\n\n"
            "// Bucle principal del firmware.\n"
            "void loop() {\n"
            "  // TODO: logica principal no bloqueante\n"
            "}\n"
        ),
    },
    "Blink": {
        "label": "Blink",
        "code": (
            "#include <Arduino.h>\n\n"
            "void setup() {\n"
            "  pinMode(LED_BUILTIN, OUTPUT);\n"
            "}\n\n"
            "void loop() {\n"
            "  digitalWrite(LED_BUILTIN, HIGH);\n"
            "  delay(500);\n"
            "  digitalWrite(LED_BUILTIN, LOW);\n"
            "  delay(500);\n"
            "}\n"
        ),
    },
    "Serial Monitor": {
        "label": "Serial Monitor",
        "code": (
            "#include <Arduino.h>\n\n"
            "void setup() {\n"
            "  Serial.begin(115200);\n"
            "  while (!Serial) { }\n"
            "  Serial.println(\"Willy listo para monitoreo serial\");\n"
            "}\n\n"
            "void loop() {\n"
            "  Serial.println(\"Heartbeat\");\n"
            "  delay(1000);\n"
            "}\n"
        ),
    },
    "I2C Scanner": {
        "label": "I2C Scanner",
        "code": (
            "#include <Arduino.h>\n"
            "#include <Wire.h>\n\n"
            "void setup() {\n"
            "  Wire.begin();\n"
            "  Serial.begin(115200);\n"
            "  while (!Serial) { }\n"
            "  Serial.println(\"I2C scan iniciado\");\n"
            "}\n\n"
            "void loop() {\n"
            "  byte found = 0;\n"
            "  for (byte address = 1; address < 127; address++) {\n"
            "    Wire.beginTransmission(address);\n"
            "    if (Wire.endTransmission() == 0) {\n"
            "      Serial.print(\"Dispositivo en 0x\");\n"
            "      if (address < 16) { Serial.print('0'); }\n"
            "      Serial.println(address, HEX);\n"
            "      found++;\n"
            "    }\n"
            "  }\n"
            "  if (!found) {\n"
            "    Serial.println(\"No se detectaron dispositivos I2C\");\n"
            "  }\n"
            "  Serial.println(\"---\");\n"
            "  delay(3000);\n"
            "}\n"
        ),
    },
}


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


def _load_station_policy() -> dict:
    try:
        with open(STATION_POLICY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _apply_station_policy(config: dict, station_policy: dict) -> tuple[dict, set[str]]:
    merged = dict(config or {})
    enforced = station_policy.get("enforced", {})
    locked_keys: set[str] = set()

    if isinstance(enforced, dict):
        for key, value in enforced.items():
            merged[key] = value
            locked_keys.add(str(key))

    return merged, locked_keys


class WillyApp(ctk.CTk):
    def __init__(self):
        config = _load_config()
        station_policy = _load_station_policy()
        config, locked_keys = _apply_station_policy(config, station_policy)
        i18n.set_language(config.get("language", "es"))
        ctk.set_appearance_mode(config.get("theme", "dark"))
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.config_data = config
        self._station_policy = station_policy
        self._locked_config_keys = locked_keys
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
        self.serial_popup_output_text = None
        self.serial_terminal_manager = None
        self.serial_status_var = tk.StringVar(value="Monitor serial inactivo")
        self.serial_timestamps_var = tk.BooleanVar(value=True)
        self.serial_freeze_var = tk.BooleanVar(value=False)
        self.serial_paused_buffer: list[str] = []
        self.serial_paused_buffer_max = 5000
        self._current_code_path = ""
        self._active_project_path = ""
        self._active_project_info: dict = {}
        self._active_netlist_path = ""
        self._project_code_selection: dict[str, str] = {}
        self._project_view_snapshot: dict = {}
        self._sidebar_width = int(self.config_data.get("sidebar_width", 220) or 220)
        self._sidebar_width = max(180, min(360, self._sidebar_width))
        self._sidebar_dragging = False
        self._project_poll_job = None
        self._last_iot_action_state = "idle"
        self._last_iot_action_kind = ""
        self._last_iot_action_ok: bool | None = None
        self._updating_project = False
        self._code_expand_window = None
        self._code_expand_text = None
        self._iot_action_running = False

        self._build_layout()
        self._wire_up()
        self.after(50, self._process_tts_visual_events)
        self.after(200, self._show_startup_greeting)
        self.after(500, self._update_active_project_if_changed)
        self.after(700, self._schedule_next_project_poll)
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
        self.grid_columnconfigure(0, weight=0, minsize=self._sidebar_width)
        self.grid_columnconfigure(1, weight=0, minsize=6)
        self.grid_columnconfigure(2, weight=1)
        self.grid_columnconfigure(3, weight=1)

        initial_dir = self.config_data.get("initial_directory", "~")
        self.session_logger = SessionLogger()
        self.session_logger.log_event(
            "app_start",
            component="gui",
            data={
                "cwd": os.getcwd(),
                "config_path": CONFIG_PATH,
                "station_policy_path": STATION_POLICY_PATH,
                "locked_keys": sorted(self._locked_config_keys),
            },
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
            on_open_folder=self._choose_workspace_folder,
            on_new_project=self._open_new_project_dialog,
            on_open_recent_projects=self._open_recent_projects_dialog,
            initial_path=initial_dir,
            width=self._sidebar_width,
            fg_color=("gray90", "gray12"),
        )
        self.file_browser.grid_propagate(False)
        self.file_browser.grid(row=0, column=0, sticky="nsew")

        self.sidebar_splitter = ctk.CTkFrame(
            self,
            width=6,
            corner_radius=0,
            fg_color=("gray78", "gray24"),
        )
        self.sidebar_splitter.grid(row=0, column=1, sticky="ns")
        self.sidebar_splitter.configure(cursor="sb_h_double_arrow")
        self.sidebar_splitter.bind("<ButtonPress-1>", self._on_sidebar_drag_start)
        self.sidebar_splitter.bind("<B1-Motion>", self._on_sidebar_drag_motion)
        self.sidebar_splitter.bind("<ButtonRelease-1>", self._on_sidebar_drag_end)

        self.chat_panel = ChatPanel(
            self,
            fg_color=("gray95", "#0a0f14"),
        )
        self.chat_panel.grid(row=0, column=2, sticky="nsew", padx=(1, 1))

        self.right_panel = ctk.CTkFrame(self, fg_color=("gray92", "#0a0f14"))
        self.right_panel.grid(row=0, column=3, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=1)

        self.right_tabview = ctk.CTkTabview(
            self.right_panel,
            fg_color=("gray92", "#0a0f14"),
            segmented_button_fg_color=("gray80", "gray26"),
            segmented_button_selected_color="#2563eb",
            segmented_button_selected_hover_color="#1d4ed8",
        )
        self.right_tabview.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        self._build_workspace_tabs(self.right_tabview)

        status_bar = ctk.CTkFrame(self, height=22, fg_color=("gray80", "gray18"))
        status_bar.grid(row=1, column=0, columnspan=4, sticky="ew")
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

    def _build_workspace_tabs(self, tabview) -> None:
        terminal_tab = tabview.add("Terminal + Consola")
        flow_tab = tabview.add("Flujo de Firmware")
        wiring_tab = tabview.add("Conexion Electrica")
        code_tab = tabview.add("Codigo del Programa")

        self._build_terminal_console_tab(terminal_tab)
        self._build_flow_tab(flow_tab)
        self._build_wiring_tab(wiring_tab)
        self._build_code_tab(code_tab)
        tabview.set("Terminal + Consola")

    def _build_terminal_console_tab(self, parent) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        device_card = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        device_card.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        device_card.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(device_card, fg_color="transparent")
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

        status_row = ctk.CTkFrame(device_card, fg_color="transparent")
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

        device_row = ctk.CTkFrame(device_card, fg_color="transparent")
        device_row.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 6))
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

        serial_card = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        serial_card.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 4))
        serial_card.grid_columnconfigure(0, weight=1)

        monitor_row = ctk.CTkFrame(serial_card, fg_color="transparent")
        monitor_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 6))
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
            text="Consola serial integrada en esta solapa (Abrir = vista flotante opcional)",
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "gray65"),
            anchor="w",
        )
        self.serial_hint_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=(2, 2))

        serial_output_frame = ctk.CTkFrame(monitor_row, fg_color=("gray96", "#0d1117"))
        serial_output_frame.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(0, 2))
        serial_output_frame.grid_columnconfigure(0, weight=1)
        serial_output_frame.grid_rowconfigure(0, weight=1)

        self.serial_output_text = tk.Text(
            serial_output_frame,
            wrap="word",
            state="disabled",
            font=("monospace", 10),
            bg="#0d1117",
            fg="#d0d0d0",
            insertbackground="white",
            selectbackground="#264f78",
            relief="flat",
            bd=0,
            padx=8,
            pady=6,
            height=7,
        )
        self.serial_output_text.grid(row=0, column=0, sticky="ew")

        serial_scroll = ctk.CTkScrollbar(serial_output_frame, command=self.serial_output_text.yview)
        serial_scroll.grid(row=0, column=1, sticky="ns")
        self.serial_output_text.configure(yscrollcommand=serial_scroll.set)

        self.serial_state_label = ctk.CTkLabel(
            monitor_row,
            textvariable=self.serial_status_var,
            font=ctk.CTkFont(size=9),
            text_color=("gray45", "#7ec8e3"),
            anchor="w",
        )
        self.serial_state_label.grid(row=3, column=0, columnspan=5, sticky="w", pady=(1, 0))

        terminal_card = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        terminal_card.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        terminal_card.grid_rowconfigure(0, weight=1)
        terminal_card.grid_columnconfigure(0, weight=1)

        self.terminal_panel = TerminalPanel(
            terminal_card,
            terminal_manager=self.terminal_manager,
            fg_color=("gray92", "#0a0f14"),
        )
        self.terminal_panel.grid(row=0, column=0, sticky="nsew")

    def _build_flow_tab(self, parent) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Diagrama de Compilacion y Carga",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        ctk.CTkButton(
            header,
            text="Actualizar",
            width=90,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._refresh_flow_diagram_text,
        ).grid(row=0, column=1, sticky="e", padx=(0, 8), pady=6)

        flow_frame = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        flow_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        flow_frame.grid_rowconfigure(0, weight=1)
        flow_frame.grid_columnconfigure(0, weight=1)

        self.flow_canvas = tk.Canvas(
            flow_frame,
            bg="#0d1117",
            highlightthickness=0,
            bd=0,
        )
        self.flow_canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.flow_canvas.bind("<Configure>", lambda _e: self._refresh_flow_diagram_text())
        self._refresh_flow_diagram_text()

    def _build_wiring_tab(self, parent) -> None:
        parent.grid_rowconfigure(2, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        top.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text="Diagrama de Conexion Electrica",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        diagram_row = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        diagram_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 4))
        diagram_row.grid_columnconfigure(0, weight=1)

        self.diagram_status_label = ctk.CTkLabel(
            diagram_row,
            text="Diagrama: sin generar",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
        )
        self.diagram_status_label.grid(row=0, column=0, sticky="w", padx=8, pady=6)

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
        self.diagram_refresh_btn.grid(row=0, column=1, sticky="e", padx=(6, 4), pady=6)

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
        self.diagram_open_btn.grid(row=0, column=2, sticky="e", padx=(0, 8), pady=6)

        preview_card = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        preview_card.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_rowconfigure(3, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            preview_card,
            text="Preview del esquema",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray30", "gray80"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(8, 2))

        self.diagram_preview = tk.Label(
            preview_card,
            text="Sin preview disponible",
            bg="#0d1117",
            fg="#9ca3af",
            anchor="center",
            justify="center",
            height=8,
        )
        self.diagram_preview.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        ctk.CTkLabel(
            preview_card,
            text="Conexiones detectadas (netlist/BOM)",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray30", "gray80"),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))

        self.wiring_summary_text = ctk.CTkTextbox(
            preview_card,
            height=120,
            font=ctk.CTkFont(family="monospace", size=10),
            fg_color=("gray96", "#0d1117"),
            border_color=("gray70", "gray40"),
            border_width=1,
            wrap="word",
        )
        self.wiring_summary_text.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self.wiring_summary_text.insert("0.0", "Esperando netlist/BOM del proyecto activo...")
        self.wiring_summary_text.configure(state="disabled")

    def _build_code_tab(self, parent) -> None:
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        code_header = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        code_header.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        code_header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            code_header,
            text="Codigo del Programa",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=8, pady=6)

        code_actions = ctk.CTkFrame(code_header, fg_color="transparent")
        code_actions.grid(row=0, column=1, sticky="e", padx=(0, 8), pady=6)

        self.code_action_indicator = tk.Canvas(
            code_actions,
            width=16,
            height=16,
            highlightthickness=0,
            bd=0,
            bg="#111821",
        )
        self.code_action_indicator.pack(side="left", padx=(0, 6))

        self.compile_btn = ctk.CTkButton(
            code_actions,
            text="Compilar",
            width=88,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._start_compile,
        )
        self.compile_btn.pack(side="left", padx=(0, 4))

        self.upload_btn = ctk.CTkButton(
            code_actions,
            text="Grabar",
            width=82,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._start_upload,
        )
        self.upload_btn.pack(side="left", padx=(0, 4))

        self.expand_code_btn = ctk.CTkButton(
            code_actions,
            text="Expandir",
            width=86,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._open_expanded_code_view,
        )
        self.expand_code_btn.pack(side="left")

        self.project_deps_btn = ctk.CTkButton(
            code_actions,
            text=i18n.get("project_deps_btn"),
            width=90,
            height=22,
            font=ctk.CTkFont(size=10),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._open_project_dependencies_dialog,
        )
        self.project_deps_btn.pack(side="left", padx=(4, 0))

        code_card = ctk.CTkFrame(parent, fg_color=("gray88", "#111821"))
        code_card.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        code_card.grid_rowconfigure(0, weight=1)
        code_card.grid_columnconfigure(0, weight=1)

        self.code_preview = ctk.CTkTextbox(
            code_card,
            height=140,
            font=ctk.CTkFont(family="monospace", size=11),
            fg_color=("gray96", "#0d1117"),
            border_color=("gray70", "gray40"),
            border_width=1,
            wrap="word",
        )
        self.code_preview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.code_preview.insert("0.0", "Selecciona un archivo para ver el codigo en desarrollo...")
        self.code_preview.configure(state="disabled")

        self._set_code_action_indicator("idle")
        self._set_device_indicator(False)

    def _refresh_flow_diagram_text(self) -> None:
        if not hasattr(self, "flow_canvas") or self.flow_canvas is None:
            return

        canvas = self.flow_canvas
        canvas.delete("all")

        width = max(860, canvas.winfo_width())
        height = max(520, canvas.winfo_height())

        project_path = self._active_project_path or ""
        project_name = os.path.basename(project_path) if project_path else "sin proyecto"
        source_path = self._resolve_project_code_path(project_path) if project_path else ""
        has_source = bool(source_path and os.path.isfile(source_path))

        ini_path = os.path.join(project_path, "platformio.ini") if project_path else ""
        has_ini = bool(ini_path and os.path.isfile(ini_path))

        info = self._active_project_info if isinstance(self._active_project_info, dict) else {}
        envs = [str(e).strip() for e in info.get("environments", []) if str(e).strip()]
        default_env = str(info.get("default_env") or "").strip()
        env_label = default_env or (envs[0] if envs else "sin env")

        selected_device = self.device_picker_var.get() if hasattr(self, "device_picker_var") else ""
        board_hint = ""
        if selected_device and selected_device != "Sin dispositivos":
            board_hint = selected_device.split(" - ", 1)[0].strip()
        if not board_hint:
            board_hint = str(self.config_data.get("default_board", "uno"))

        detected = len(self._detected_devices) if isinstance(self._detected_devices, list) else 0
        port = self._selected_or_default_port()

        firmware_path = self._find_latest_firmware_artifact(project_path, env_label)
        has_firmware = bool(firmware_path)

        action_state = self._last_iot_action_state
        action_kind = (self._last_iot_action_kind or "").strip().lower()
        action_ok = self._last_iot_action_ok

        compile_state = "blocked"
        if action_state == "compiling":
            compile_state = "active"
        elif action_kind == "compile" and action_ok is True:
            compile_state = "ok"
        elif action_kind == "compile" and action_ok is False:
            compile_state = "error"
        elif has_ini and has_source:
            compile_state = "ready"

        upload_state = "blocked"
        if action_state == "uploading":
            upload_state = "active"
        elif action_kind == "upload" and action_ok is True:
            upload_state = "ok"
        elif action_kind == "upload" and action_ok is False:
            upload_state = "error"
        elif has_ini and has_firmware and detected > 0:
            upload_state = "ready"

        source_state = "ready" if has_source else "blocked"
        config_state = "ready" if has_ini else "blocked"
        firmware_state = "ready" if has_firmware else ("active" if action_state == "compiling" else "blocked")
        board_state = "ready" if detected > 0 else "blocked"

        palette = {
            "blocked": "#334155",
            "ready": "#1e40af",
            "active": "#b45309",
            "ok": "#15803d",
            "error": "#b91c1c",
        }

        def node_color(state: str) -> str:
            return palette.get(state, palette["blocked"])

        def state_label(state: str) -> str:
            labels = {
                "blocked": "pendiente",
                "ready": "listo",
                "active": "ejecutando",
                "ok": "ok",
                "error": "error",
            }
            return labels.get(state, state)

        title_color = "#7ec8e3"
        text_color = "#d1d5db"
        edge_color = "#60a5fa"

        logic_view = self._build_firmware_logic_view(source_path) if has_source else {
            "steps": [
                ("Inicio", "Selecciona un archivo fuente del proyecto"),
                ("setup()", "No disponible"),
                ("loop()", "No disponible"),
            ],
            "loop_back_index": None,
            "pseudocode": [
                "INICIO",
                "1. Abrir un archivo fuente valido (ej: src/main.cpp)",
                "2. Definir setup() y loop()",
                "3. Compilar y ejecutar en placa",
            ],
        }

        canvas.create_text(
            14,
            16,
            anchor="w",
            fill=title_color,
            font=("Segoe UI", 12, "bold"),
            text="Flujo Logico del Firmware",
        )
        canvas.create_text(
            14,
            38,
            anchor="w",
            fill="#9ca3af",
            font=("Segoe UI", 9),
            text=f"Proyecto: {project_name} | Env: {env_label} | Board: {board_hint} | Puerto: {port}",
        )
        canvas.create_text(
            14,
            56,
            anchor="w",
            fill="#6b7280",
            font=("Segoe UI", 8),
            text=(
                f"Codigo: {self._truncate_flow_text(os.path.basename(source_path) if has_source else 'sin fuente activa', 58)} "
                f"| IoT: {self._last_iot_action_state}"
            ),
        )

        left_x = 14
        top_y = 84
        left_w = max(320, int(width * 0.52))
        node_w = left_w - 28
        node_h = 52
        node_gap = 10

        flow_steps = logic_view.get("steps", [])
        if not flow_steps:
            flow_steps = [("Inicio", "Sin pasos detectados")]

        max_nodes_height = (height - 280)
        total_nodes_height = len(flow_steps) * node_h + max(0, len(flow_steps) - 1) * node_gap
        if total_nodes_height > max_nodes_height and len(flow_steps) > 1:
            node_h = max(42, int((max_nodes_height - ((len(flow_steps) - 1) * node_gap)) / len(flow_steps)))

        canvas.create_rectangle(
            left_x,
            top_y,
            left_x + left_w,
            height - 190,
            outline="#334155",
            fill="#0b1220",
            width=1,
        )
        canvas.create_text(
            left_x + 10,
            top_y + 12,
            anchor="w",
            fill=title_color,
            font=("Segoe UI", 10, "bold"),
            text="Diagrama de Flujo del Codigo",
        )

        node_x = left_x + 14
        node_y = top_y + 28
        first_loop_index = logic_view.get("loop_back_index")
        node_positions: list[tuple[int, int]] = []

        for idx, (title, subtitle) in enumerate(flow_steps):
            self._draw_flow_node(
                node_x,
                node_y,
                node_w,
                node_h,
                title,
                self._truncate_flow_text(subtitle, 80),
                "#1f2937",
            )
            node_positions.append((node_x, node_y))

            if idx < len(flow_steps) - 1:
                self._draw_flow_arrow(
                    node_x + int(node_w / 2),
                    node_y + node_h,
                    node_x + int(node_w / 2),
                    node_y + node_h + node_gap,
                )
            node_y += node_h + node_gap

        if isinstance(first_loop_index, int) and 0 <= first_loop_index < len(node_positions) and len(node_positions) > 1:
            last_x, last_y = node_positions[-1]
            target_x, target_y = node_positions[first_loop_index]
            side_x = node_x + node_w + 20
            canvas.create_line(
                last_x + node_w,
                last_y + int(node_h / 2),
                side_x,
                last_y + int(node_h / 2),
                side_x,
                target_y + int(node_h / 2),
                target_x + node_w,
                target_y + int(node_h / 2),
                fill="#60a5fa",
                width=2,
                arrow=tk.LAST,
                smooth=True,
            )
            canvas.create_text(
                side_x - 4,
                target_y - 8,
                anchor="e",
                fill="#93c5fd",
                font=("Segoe UI", 8, "bold"),
                text="loop",
            )

        pseudo_x1 = left_x + left_w + 10
        pseudo_x2 = width - 14
        pseudo_y1 = top_y
        pseudo_y2 = height - 190
        canvas.create_rectangle(
            pseudo_x1,
            pseudo_y1,
            pseudo_x2,
            pseudo_y2,
            outline="#334155",
            fill="#0b1220",
            width=1,
        )
        canvas.create_text(
            pseudo_x1 + 10,
            pseudo_y1 + 12,
            anchor="w",
            fill=title_color,
            font=("Segoe UI", 10, "bold"),
            text="Pseudocodigo (Pro)",
        )

        pseudocode_text = "\n".join(logic_view.get("pseudocode", []))
        canvas.create_text(
            pseudo_x1 + 10,
            pseudo_y1 + 34,
            anchor="nw",
            fill="#cbd5e1",
            font=("Consolas", 9),
            justify="left",
            width=max(180, (pseudo_x2 - pseudo_x1 - 20)),
            text=pseudocode_text,
        )

        card_x1 = 14
        card_y1 = height - 180
        card_x2 = width - 14
        card_y2 = height - 14
        canvas.create_rectangle(card_x1, card_y1, card_x2, card_y2, outline="#334155", fill="#0b1220", width=1)
        canvas.create_text(
            card_x1 + 10,
            card_y1 + 12,
            anchor="w",
            fill=title_color,
            font=("Segoe UI", 10, "bold"),
            text="Estado de Compilacion y Carga",
        )

        source_label = os.path.basename(source_path) if has_source else "(no detectado)"
        firmware_label = os.path.basename(firmware_path) if has_firmware else "(no generado)"
        lines = [
            f"Proyecto activo: {project_name}",
            f"Fuente: {self._truncate_flow_text(source_label, 52)}",
            f"Config: {'ok' if has_ini else 'pendiente'} | Env: {env_label}",
            f"Firmware: {self._truncate_flow_text(firmware_label, 50)}",
            f"Upload: {state_label(upload_state)} | Puerto: {port}",
            f"Placa detectada: {'si' if detected > 0 else 'no'}",
        ]

        y_line = card_y1 + 36
        for line in lines:
            canvas.create_text(
                card_x1 + 10,
                y_line,
                anchor="w",
                fill=text_color,
                font=("Segoe UI", 9),
                text=line,
            )
            y_line += 18

        canvas.create_text(
            card_x1 + 10,
            card_y2 - 16,
            anchor="w",
            fill=edge_color,
            font=("Segoe UI", 8),
            text="Pipeline operativo: Codigo -> Compilar -> Firmware -> Upload",
        )

    def _find_latest_firmware_artifact(self, project_path: str, env_hint: str = "") -> str:
        if not project_path:
            return ""

        build_root = os.path.join(project_path, ".pio", "build")
        if not os.path.isdir(build_root):
            return ""

        preferred_env = (env_hint or "").strip()
        candidate_dirs: list[str] = []
        if preferred_env:
            env_path = os.path.join(build_root, preferred_env)
            if os.path.isdir(env_path):
                candidate_dirs.append(env_path)

        try:
            for name in os.listdir(build_root):
                path = os.path.join(build_root, name)
                if os.path.isdir(path) and path not in candidate_dirs:
                    candidate_dirs.append(path)
        except Exception:
            return ""

        exts = (".bin", ".hex", ".elf", ".uf2")
        newest_path = ""
        newest_mtime = 0.0

        for folder in candidate_dirs:
            try:
                for name in os.listdir(folder):
                    artifact = os.path.join(folder, name)
                    if not os.path.isfile(artifact):
                        continue
                    if not name.lower().endswith(exts):
                        continue
                    mtime = os.path.getmtime(artifact)
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_path = artifact
            except Exception:
                continue

        return newest_path

    def _truncate_flow_text(self, text: str, max_chars: int = 24) -> str:
        value = (text or "").strip()
        if len(value) <= max_chars:
            return value
        return value[: max_chars - 3].rstrip() + "..."

    def _build_firmware_logic_view(self, source_path: str) -> dict:
        try:
            with open(source_path, "r", encoding="utf-8", errors="replace") as fh:
                source = fh.read()
        except Exception:
            source = ""

        setup_body = self._extract_cpp_function_body(source, "setup")
        loop_body = self._extract_cpp_function_body(source, "loop")

        blink = re.search(
            r"digitalWrite\s*\(\s*([A-Za-z0-9_]+)\s*,\s*HIGH\s*\)\s*;\s*"
            r"delay\s*\(\s*(\d+)\s*\)\s*;\s*"
            r"digitalWrite\s*\(\s*\1\s*,\s*LOW\s*\)\s*;\s*"
            r"delay\s*\(\s*(\d+)\s*\)\s*;",
            loop_body,
            re.DOTALL,
        )

        if blink:
            led_pin = blink.group(1)
            on_ms = blink.group(2)
            off_ms = blink.group(3)
            setup_pin_mode = re.search(
                r"pinMode\s*\(\s*([A-Za-z0-9_]+)\s*,\s*(OUTPUT|INPUT|INPUT_PULLUP)\s*\)",
                setup_body,
            )
            setup_desc = "Configurar hardware inicial"
            if setup_pin_mode:
                setup_desc = f"pinMode({setup_pin_mode.group(1)}, {setup_pin_mode.group(2)})"

            return {
                "steps": [
                    ("Inicio", "Boot del firmware y runtime Arduino"),
                    ("setup()", setup_desc),
                    ("Entrar loop()", "Bucle principal infinito"),
                    ("Ciclo ON", f"digitalWrite({led_pin}, HIGH) + delay({on_ms} ms)"),
                    ("Ciclo OFF", f"digitalWrite({led_pin}, LOW) + delay({off_ms} ms)"),
                ],
                "loop_back_index": 3,
                "pseudocode": [
                    f"CONST T_ON_MS  = {on_ms}",
                    f"CONST T_OFF_MS = {off_ms}",
                    "",
                    "PROCEDURE setup():",
                    f"  pinMode({led_pin}, OUTPUT)",
                    "",
                    "PROCEDURE loop():",
                    "  WHILE true:",
                    f"    digitalWrite({led_pin}, HIGH)",
                    "    delay(T_ON_MS)",
                    f"    digitalWrite({led_pin}, LOW)",
                    "    delay(T_OFF_MS)",
                ],
            }

        setup_actions = self._extract_cpp_actions(setup_body)
        loop_actions = self._extract_cpp_actions(loop_body)

        setup_desc = "; ".join(setup_actions[:2]) if setup_actions else "Inicializacion de hardware"
        loop_desc = "; ".join(loop_actions[:2]) if loop_actions else "Ejecucion ciclica"
        extra_loop = []
        if len(loop_actions) > 2:
            extra_loop.append(("Loop extra", self._truncate_flow_text("; ".join(loop_actions[2:4]), 80)))

        pseudocode_lines = [
            "PROCEDURE setup():",
            f"  {setup_desc}",
            "",
            "PROCEDURE loop():",
            f"  {loop_desc}",
            "  REPEAT FOREVER",
        ]
        if len(loop_actions) > 2:
            for action in loop_actions[2:4]:
                pseudocode_lines.append(f"  {action}")

        steps = [
            ("Inicio", "Cargar firmware en memoria"),
            ("setup()", setup_desc),
            ("Entrar loop()", "Bucle principal"),
            ("Loop core", loop_desc),
        ] + extra_loop

        return {
            "steps": steps,
            "loop_back_index": 3,
            "pseudocode": pseudocode_lines,
        }

    def _extract_cpp_function_body(self, source: str, function_name: str) -> str:
        if not source:
            return ""
        start = re.search(rf"\b{function_name}\s*\([^)]*\)\s*\{{", source)
        if not start:
            return ""
        i = start.end()
        depth = 1
        while i < len(source):
            ch = source[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return source[start.end():i]
            i += 1
        return ""

    def _extract_cpp_actions(self, body: str) -> list[str]:
        if not body:
            return []

        actions: list[str] = []
        statements = [part.strip() for part in body.split(";") if part.strip()]
        for stmt in statements:
            line = re.sub(r"//.*", "", stmt).strip()
            if not line:
                continue

            pin_mode = re.search(
                r"pinMode\s*\(\s*([^,]+)\s*,\s*([A-Za-z0-9_]+)\s*\)",
                line,
            )
            if pin_mode:
                actions.append(f"pinMode({pin_mode.group(1).strip()}, {pin_mode.group(2).strip()})")
                continue

            dig_write = re.search(
                r"digitalWrite\s*\(\s*([^,]+)\s*,\s*([A-Za-z0-9_]+)\s*\)",
                line,
            )
            if dig_write:
                actions.append(
                    f"digitalWrite({dig_write.group(1).strip()}, {dig_write.group(2).strip()})"
                )
                continue

            delay_call = re.search(r"delay\s*\(\s*(\d+)\s*\)", line)
            if delay_call:
                actions.append(f"delay({delay_call.group(1)} ms)")
                continue

            analog_write = re.search(
                r"analogWrite\s*\(\s*([^,]+)\s*,\s*([^\)]+)\)",
                line,
            )
            if analog_write:
                actions.append(
                    f"analogWrite({analog_write.group(1).strip()}, {analog_write.group(2).strip()})"
                )
                continue

            serial_print = re.search(r"Serial\.(print|println)\s*\((.*)\)", line)
            if serial_print:
                actions.append(f"Serial.{serial_print.group(1)}(...)" )
                continue

            if line.startswith("if"):
                actions.append("if (...) { ... }")
                continue
            if line.startswith("for"):
                actions.append("for (...) { ... }")
                continue
            if line.startswith("while"):
                actions.append("while (...) { ... }")
                continue

            actions.append(self._truncate_flow_text(line, 46))

        return actions[:6]

    def _draw_flow_node(self, x: int, y: int, w: int, h: int, title: str, subtitle: str, fill: str) -> None:
        if not hasattr(self, "flow_canvas") or self.flow_canvas is None:
            return
        canvas = self.flow_canvas
        canvas.create_rectangle(x, y, x + w, y + h, outline="#475569", fill=fill, width=1)
        canvas.create_text(
            x + 10,
            y + 16,
            anchor="w",
            fill="#f8fafc",
            font=("Segoe UI", 10, "bold"),
            text=title,
        )
        canvas.create_text(
            x + 10,
            y + 34,
            anchor="w",
            fill="#cbd5e1",
            font=("Segoe UI", 9),
            width=w - 20,
            justify="left",
            text=subtitle,
        )

    def _draw_flow_arrow(self, x1: int, y1: int, x2: int, y2: int) -> None:
        if not hasattr(self, "flow_canvas") or self.flow_canvas is None:
            return
        self.flow_canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill="#60a5fa",
            width=2,
            arrow=tk.LAST,
            smooth=True,
        )

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

        try:
            self.ai_agent.set_active_project_context(
                self._active_project_path,
                self._active_project_info,
            )
        except Exception:
            pass

        def _logged_send(text: str, mode: str = "agent") -> None:
            self.session_logger.log_message("user", text)
            # Reacción: pensando cuando el usuario escribe
            if hasattr(self, "clippy") and self.clippy is not None:
                self.clippy.set_expression("thinking")
            try:
                self.ai_agent.send(text, mode=mode)
            except Exception as exc:
                self.session_logger.log_error(
                    "chat_send",
                    str(exc),
                    context={"mode": mode, "source": "_logged_send"},
                )
                self._on_status("Error enviando mensaje al agente")
                self.chat_panel.add_message("error", "No se pudo enviar el mensaje al agente.")

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
                        if hasattr(platform, "freedesktop_os_release"):
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
        try:
            if not hasattr(self, "clippy") or self.clippy is None:
                return
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
        except Exception as exc:
            self.session_logger.log_error(
                "chat_ui",
                str(exc),
                context={"role": role, "source": "_on_ai_message"},
            )

    def _on_confirm_request(self, title: str, detail: str, callback) -> None:
        self.chat_panel.show_confirm_dialog(title, detail, callback)
        # Reacción: parpadeo cuando se pide confirmación
        if hasattr(self, "clippy") and self.clippy is not None:
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
        self._current_code_path = path
        self.chat_panel.add_message("system", i18n.get("file_selected", path=path))
        self._update_code_preview(path)
        self._refresh_project_views_from_path(path, False)
        self.ai_agent.send(i18n.get("file_send_msg", path=path))

    def _on_schematic_generated(self, svg_path: str, bom_path: str) -> None:
        # Called from agent worker thread; marshal to UI thread.
        self.after(0, self._apply_generated_schematic, svg_path, bom_path)

    def _apply_generated_schematic(self, svg_path: str, bom_path: str) -> None:
        net_path = ""
        if svg_path:
            base = os.path.splitext(svg_path)[0]
            net_candidate = base + ".net"
            if os.path.isfile(net_candidate):
                net_path = net_candidate

        if self._active_project_path:
            self._store_project_artifacts(
                self._active_project_path,
                svg_path=svg_path,
                bom_path=bom_path,
                net_path=net_path,
            )

        self._refresh_project_views(force_code_refresh=False)

    def _on_ai_file_written(self, path: str, content: str) -> None:
        # Called from agent worker thread; marshal to UI thread.
        self.after(0, self._update_code_preview_from_content, path, content)
        self.after(0, self._refresh_project_views_from_path, path, False)

    def _update_code_preview_from_content(self, path: str, content: str) -> None:
        self._current_code_path = path
        preview = f"Archivo (editado por Willy): {path}\n\n{content}"
        if len(preview) > 6500:
            preview = preview[:6500] + "\n\n[...archivo truncado en 6500 caracteres...]"

        if hasattr(self, "code_preview"):
            self.code_preview.configure(state="normal")
            self.code_preview.delete("0.0", "end")
            self.code_preview.insert("0.0", preview)
            self.code_preview.configure(state="disabled")

        if self._code_expand_text is not None and self._code_expand_text.winfo_exists():
            self._code_expand_text.configure(state="normal")
            self._code_expand_text.delete("0.0", "end")
            self._code_expand_text.insert("0.0", preview)
            self._code_expand_text.configure(state="disabled")

        if self._active_project_path and self._path_belongs_to_project(path, self._active_project_path):
            self._project_code_selection[self._active_project_path] = path

        self._refresh_flow_diagram_text()

    def _set_device_indicator(self, connected: bool) -> None:
        if not hasattr(self, "device_indicator"):
            return
        self.device_indicator.delete("all")
        color = "#22c55e" if connected else "#ef4444"
        self.device_indicator.create_oval(3, 3, 17, 17, fill=color, outline=color)

    def _set_code_action_indicator(self, state: str) -> None:
        if not hasattr(self, "code_action_indicator"):
            return
        colors = {
            "idle": "#6b7280",
            "compiling": "#2563eb",
            "uploading": "#f59e0b",
            "success": "#22c55e",
            "error": "#ef4444",
        }
        color = colors.get(state, colors["idle"])
        self.code_action_indicator.delete("all")
        self.code_action_indicator.create_oval(3, 3, 13, 13, fill=color, outline=color)

    def _detect_active_project(self) -> str:
        candidates: list[str] = []
        if self._current_code_path:
            candidates.append(os.path.abspath(self._current_code_path))

        try:
            cwd = self.terminal_manager.get_cwd()
        except Exception:
            cwd = os.getcwd()

        candidates.append(os.path.join(cwd, "src", "main.cpp"))
        candidates.append(cwd)

        for file_candidate in candidates:
            base = file_candidate if os.path.isdir(file_candidate) else os.path.dirname(file_candidate)
            cur = os.path.abspath(base)
            while True:
                if os.path.exists(os.path.join(cur, "platformio.ini")):
                    return cur
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
        return ""

    def _update_active_project_if_changed(self) -> bool:
        if self._updating_project:
            return False

        self._updating_project = True
        try:
            project_path = self._detect_active_project()
            if project_path == self._active_project_path:
                return False

            info: dict = {}
            if project_path:
                try:
                    info = self.arduino_manager.get_project_info(project_path)
                except Exception:
                    info = {}

            self._on_project_changed(project_path, info)
            return True
        finally:
            self._updating_project = False

    def _on_project_changed(self, project_path: str, project_info: dict) -> None:
        self._active_project_path = project_path or ""
        self._active_project_info = project_info or {}

        if hasattr(self, "ai_agent") and self.ai_agent is not None:
            try:
                self.ai_agent.set_active_project_context(
                    self._active_project_path,
                    self._active_project_info,
                )
            except Exception:
                pass

        if self._active_project_path:
            self._remember_recent_project(self._active_project_path)
        else:
            self._latest_schematic_path = ""
            self._latest_bom_path = ""
            self._active_netlist_path = ""

        self._refresh_project_views(
            project_path=self._active_project_path,
            project_info=self._active_project_info,
            force_code_refresh=True,
        )

        self.session_logger.log_event(
            "project_activated",
            component="gui",
            data={
                "project_path": self._active_project_path,
                "environments": self._active_project_info.get("environments", []),
                "default_env": self._active_project_info.get("default_env", ""),
            },
        )

        if self._active_project_path and hasattr(self, "chat_panel"):
            agents_path = os.path.join(self._active_project_path, ".willy", "AGENTS.md")
            if os.path.isfile(agents_path):
                self.chat_panel.add_message(
                    "system",
                    i18n.get("project_context_loaded", path=agents_path),
                )

    def _load_code_for_project(self, project_path: str) -> None:
        code_path = self._resolve_project_code_path(project_path)
        if code_path and os.path.isfile(code_path):
            self._project_code_selection[project_path] = code_path
            self._update_code_preview(code_path)
            return
        self._show_project_code_placeholder(project_path)

    def _schedule_next_project_poll(self) -> None:
        if self._project_poll_job is not None:
            try:
                self.after_cancel(self._project_poll_job)
            except Exception:
                pass

        def _tick() -> None:
            self._update_active_project_if_changed()
            self._schedule_next_project_poll()

        self._project_poll_job = self.after(2500, _tick)

    def _resolve_project_path_for_actions(self) -> str:
        if self._active_project_path and os.path.isfile(os.path.join(self._active_project_path, "platformio.ini")):
            return self._active_project_path

        candidates: list[str] = []
        if self._current_code_path:
            candidates.append(os.path.abspath(self._current_code_path))
        candidates.append(os.path.join(self.terminal_manager.get_cwd(), "src", "main.cpp"))

        for file_candidate in candidates:
            base = file_candidate if os.path.isdir(file_candidate) else os.path.dirname(file_candidate)
            cur = os.path.abspath(base)
            while True:
                if os.path.exists(os.path.join(cur, "platformio.ini")):
                    return cur
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
        return self.terminal_manager.get_cwd()

    def _select_env_for_project(self, project_path: str) -> str | None:
        info = self.arduino_manager.get_project_info(project_path)
        if not info.get("ok"):
            return None
        envs = [str(e).strip() for e in info.get("environments", []) if str(e).strip()]
        if not envs:
            return None

        default_env = str(info.get("default_env") or "").strip().lower()
        if default_env and default_env in [e.lower() for e in envs]:
            return envs[[e.lower() for e in envs].index(default_env)]

        board_hint = ""
        selected = self.device_picker_var.get() if hasattr(self, "device_picker_var") else ""
        if selected and selected != "Sin dispositivos":
            board_hint = selected.split(" - ", 1)[0].strip().lower()
        if not board_hint:
            board_hint = str(self.config_data.get("default_board", "")).strip().lower()

        candidates: list[str] = []
        if board_hint in {"arduino_uno", "uno"}:
            candidates = ["uno", "arduino_uno", "arduino-avr-uno"]
        elif "esp32" in board_hint:
            candidates = ["esp32", "esp32dev", "esp32-s3", "esp32s3"]
        elif "pico" in board_hint:
            candidates = ["pico", "rp2040"]
        elif board_hint:
            candidates = [board_hint]

        envs_l = [e.lower() for e in envs]
        for cand in candidates:
            if cand in envs_l:
                return envs[envs_l.index(cand)]
            for idx, env_name in enumerate(envs_l):
                if cand in env_name or env_name in cand:
                    return envs[idx]

        return envs[0]

    def _save_config(self) -> None:
        with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
            json.dump(self.config_data, config_file, indent=4)

    def _normalized_recent_projects(self) -> list[dict]:
        raw_items = self.config_data.get("recent_projects", [])
        normalized: list[dict] = []
        seen_paths: set[str] = set()

        if not isinstance(raw_items, list):
            return normalized

        for item in raw_items:
            if isinstance(item, str):
                path = item
                label = os.path.basename(path) or path
                last_opened = ""
                favorite = False
            elif isinstance(item, dict):
                path = str(item.get("path", "")).strip()
                label = str(item.get("label", "")).strip() or (os.path.basename(path) or path)
                last_opened = str(item.get("last_opened", "")).strip()
                favorite = bool(item.get("favorite", False))
            else:
                continue

            if not path:
                continue

            abs_path = os.path.abspath(os.path.expanduser(path))
            if abs_path in seen_paths or not os.path.isdir(abs_path):
                continue

            seen_paths.add(abs_path)
            normalized.append(
                {
                    "path": abs_path,
                    "label": label,
                    "last_opened": last_opened,
                    "favorite": favorite,
                }
            )

        normalized.sort(key=lambda item: (not item.get("favorite", False), item.get("label", "").lower()))
        return normalized[:12]

    def _remember_recent_project(self, path: str) -> None:
        target = os.path.abspath(os.path.expanduser(path or ""))
        if not target or not os.path.isdir(target):
            return

        recent = self._normalized_recent_projects()
        recent = [item for item in recent if item["path"] != target]
        recent.insert(
            0,
            {
                "path": target,
                "label": os.path.basename(target) or target,
                "last_opened": datetime.now().isoformat(timespec="seconds"),
                "favorite": False,
            },
        )
        self.config_data["recent_projects"] = recent[:12]
        try:
            self._save_config()
        except Exception:
            pass

    def _project_metadata_path(self, project_path: str) -> str:
        return os.path.join(project_path, ".willy", "project.json")

    def _load_project_metadata(self, project_path: str) -> dict:
        meta_path = self._project_metadata_path(project_path)
        if not os.path.isfile(meta_path):
            return {}
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_project_metadata(self, project_path: str, metadata: dict) -> None:
        os.makedirs(os.path.join(project_path, ".willy"), exist_ok=True)
        with open(self._project_metadata_path(project_path), "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=4)

    def _store_project_artifacts(
        self,
        project_path: str,
        svg_path: str = "",
        bom_path: str = "",
        net_path: str = "",
    ) -> None:
        metadata = self._load_project_metadata(project_path)
        artifacts = dict(metadata.get("artifacts", {})) if isinstance(metadata.get("artifacts", {}), dict) else {}
        if svg_path:
            artifacts["svg"] = svg_path
        if bom_path:
            artifacts["bom"] = bom_path
        if net_path:
            artifacts["net"] = net_path
        metadata["artifacts"] = artifacts
        self._save_project_metadata(project_path, metadata)

    def _path_belongs_to_project(self, path: str, project_path: str) -> bool:
        if not path or not project_path:
            return False
        try:
            path_abs = os.path.abspath(path)
            project_abs = os.path.abspath(project_path)
            common = os.path.commonpath([path_abs, project_abs])
            return common == project_abs
        except Exception:
            return False

    def _project_name_tokens(self, project_path: str) -> list[str]:
        project_name = os.path.basename(project_path or "").strip().lower()
        if not project_name:
            return []
        normalized = project_name.replace("-", "_").replace(" ", "_")
        compact = normalized.replace("_", "")
        return list({project_name, normalized, compact})

    def _resolve_project_code_path(self, project_path: str) -> str:
        selected = self._project_code_selection.get(project_path, "")
        if selected and os.path.isfile(selected) and self._path_belongs_to_project(selected, project_path):
            return selected

        current = self._current_code_path
        if current and os.path.isfile(current) and self._path_belongs_to_project(current, project_path):
            return current

        main_cpp = os.path.join(project_path, "src", "main.cpp")
        return main_cpp if os.path.isfile(main_cpp) else ""

    def _resolve_project_artifacts(self, project_path: str) -> tuple[str, str, str]:
        metadata = self._load_project_metadata(project_path)
        artifacts = metadata.get("artifacts", {}) if isinstance(metadata.get("artifacts", {}), dict) else {}
        svg = str(artifacts.get("svg", "")).strip()
        bom = str(artifacts.get("bom", "")).strip()
        net = str(artifacts.get("net", "")).strip()
        svg = svg if svg and os.path.isfile(svg) else ""
        bom = bom if bom and os.path.isfile(bom) else ""
        net = net if net and os.path.isfile(net) else ""

        fallback_svg, fallback_bom, fallback_net = self._find_latest_schematic_assets(project_path)
        return (
            svg or fallback_svg,
            bom or fallback_bom,
            net or fallback_net,
        )

    def _build_project_view_snapshot(self, project_path: str, project_info: dict | None = None) -> dict:
        info = project_info or {}
        code_path = self._resolve_project_code_path(project_path) if project_path else ""
        svg_path, bom_path, net_path = self._resolve_project_artifacts(project_path) if project_path else ("", "", "")
        return {
            "project_path": project_path or "",
            "project_info": info,
            "code_path": code_path,
            "svg_path": svg_path,
            "bom_path": bom_path,
            "net_path": net_path,
        }

    def _apply_project_view_snapshot(self, snapshot: dict, force_code_refresh: bool = True) -> None:
        self._project_view_snapshot = snapshot
        self._latest_schematic_path = snapshot.get("svg_path", "") or ""
        self._latest_bom_path = snapshot.get("bom_path", "") or ""
        self._active_netlist_path = snapshot.get("net_path", "") or ""

        code_path = snapshot.get("code_path", "") or ""
        if force_code_refresh:
            if code_path and os.path.isfile(code_path):
                self._update_code_preview(code_path)
            else:
                self._show_project_code_placeholder(snapshot.get("project_path", ""))

        self._update_diagram_status()
        self._update_schematic_preview(self._latest_schematic_path)
        self._update_wiring_summary()
        self._refresh_flow_diagram_text()

    def _refresh_project_views(
        self,
        project_path: str | None = None,
        project_info: dict | None = None,
        force_code_refresh: bool = True,
    ) -> None:
        target_project = project_path if project_path is not None else self._active_project_path
        snapshot = self._build_project_view_snapshot(target_project or "", project_info=project_info)
        self._apply_project_view_snapshot(snapshot, force_code_refresh=force_code_refresh)

    def _refresh_project_views_from_path(self, path: str, force_code_refresh: bool = False) -> None:
        self._current_code_path = path
        self._update_active_project_if_changed()
        if self._active_project_path and self._path_belongs_to_project(path, self._active_project_path):
            self._project_code_selection[self._active_project_path] = path
        self._refresh_project_views(force_code_refresh=force_code_refresh)

    def _show_project_code_placeholder(self, project_path: str) -> None:
        preview = (
            f"Proyecto activo: {project_path}\n\n"
            "No se encontró src/main.cpp en este proyecto.\n"
            "Selecciona un archivo desde el explorador para ver su contenido."
        ) if project_path else "Selecciona un archivo para ver el codigo en desarrollo..."

        if hasattr(self, "code_preview"):
            self.code_preview.configure(state="normal")
            self.code_preview.delete("0.0", "end")
            self.code_preview.insert("0.0", preview)
            self.code_preview.configure(state="disabled")

        if self._code_expand_text is not None and self._code_expand_text.winfo_exists():
            self._code_expand_text.configure(state="normal")
            self._code_expand_text.delete("0.0", "end")
            self._code_expand_text.insert("0.0", preview)
            self._code_expand_text.configure(state="disabled")

    def _update_diagram_status(self) -> None:
        if not hasattr(self, "diagram_status_label"):
            return
        if self._latest_schematic_path and os.path.isfile(self._latest_schematic_path):
            display_name = os.path.basename(self._latest_schematic_path)
            self.diagram_status_label.configure(text=f"Diagrama: {display_name}")
            self.diagram_open_btn.configure(state="normal")
        else:
            self.diagram_status_label.configure(text="Diagrama: no disponible para el proyecto activo")
            self.diagram_open_btn.configure(state="disabled")

    def _ensure_project_downloads_dir(self, project_path: str) -> str:
        metadata = self._load_project_metadata(project_path)
        downloads_rel = str(metadata.get("downloads_dir", "")).strip() or ".willy/downloads"
        downloads_path = os.path.join(project_path, *downloads_rel.split("/"))
        os.makedirs(downloads_path, exist_ok=True)
        metadata["downloads_dir"] = downloads_rel
        self._save_project_metadata(project_path, metadata)
        return downloads_path

    def _append_lib_dep_to_ini(self, project_path: str, spec: str) -> tuple[bool, str]:
        dep_spec = spec.strip()
        if not dep_spec:
            return False, ""

        existing = self.arduino_manager._collect_lib_deps_from_ini(project_path)
        existing_names = {
            self.arduino_manager._lib_project_name(item).lower(): item
            for item in existing
        }
        project_name = self.arduino_manager._lib_project_name(dep_spec).lower()
        if project_name and project_name in existing_names:
            return False, existing_names[project_name]

        ini_path = os.path.join(project_path, "platformio.ini")
        with open(ini_path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()

        first_env_start = None
        section_end = len(lines)
        lib_deps_index = None
        insert_index = None

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("[env:") and stripped.endswith("]"):
                if first_env_start is None:
                    first_env_start = idx
                    continue
                section_end = idx
                break

        if first_env_start is None:
            return False, ""

        for idx in range(first_env_start + 1, section_end):
            stripped = lines[idx].strip()
            if stripped.lower().startswith("lib_deps"):
                lib_deps_index = idx
                insert_index = idx + 1
                while insert_index < section_end and lines[insert_index].startswith((" ", "\t")):
                    insert_index += 1
                break

        if lib_deps_index is None:
            insert_index = section_end
            lines[insert_index:insert_index] = ["", "lib_deps =", f"    {dep_spec}"]
        else:
            lines.insert(insert_index, f"    {dep_spec}")

        with open(ini_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip() + "\n")

        return True, dep_spec

    def _remove_recent_project(self, target_path: str) -> None:
        normalized = self._normalized_recent_projects()
        target = os.path.abspath(os.path.expanduser(target_path))
        self.config_data["recent_projects"] = [
            item for item in normalized if item["path"] != target
        ]
        try:
            self._save_config()
        except Exception:
            pass

    def _toggle_recent_project_favorite(self, target_path: str) -> None:
        normalized = self._normalized_recent_projects()
        target = os.path.abspath(os.path.expanduser(target_path))
        for item in normalized:
            if item["path"] == target:
                item["favorite"] = not bool(item.get("favorite", False))
                break
        normalized.sort(
            key=lambda item: (
                not item.get("favorite", False),
                item.get("label", "").lower(),
            )
        )
        self.config_data["recent_projects"] = normalized[:12]
        try:
            self._save_config()
        except Exception:
            pass

    def _choose_workspace_folder(self) -> None:
        initial_dir = self.terminal_manager.get_cwd()
        folder = tk.filedialog.askdirectory(
            initialdir=initial_dir,
            title=i18n.get("open_folder_btn"),
        )
        if folder:
            self._apply_workspace_root(folder)

    def _apply_workspace_root(self, folder: str, announce: bool = True) -> None:
        root = os.path.abspath(os.path.expanduser(folder))
        if not os.path.isdir(root):
            return

        self.terminal_manager.change_directory(root)
        if hasattr(self, "file_browser"):
            self.file_browser.navigate_to(root)

        if "initial_directory" not in self._locked_config_keys:
            self.config_data["initial_directory"] = root
            try:
                self._save_config()
            except Exception:
                pass

        self._current_code_path = ""
        self._update_active_project_if_changed()
        self._remember_recent_project(self._active_project_path or root)

        if announce:
            self.chat_panel.add_message(
                "system",
                i18n.get("workspace_opened", path=root),
            )

    def _default_project_preset_label(self) -> str:
        default_board = str(self.config_data.get("default_board", "")).strip().lower()
        for label, preset in PROJECT_PRESETS.items():
            if preset["board"].lower() == default_board:
                return label
        return "Arduino Uno"

    def _render_platformio_ini(self, preset: dict) -> str:
        return (
            f"[env:{preset['board']}]\n"
            f"platform = {preset['platform']}\n"
            f"board = {preset['board']}\n"
            f"framework = {preset['framework']}\n\n"
            "; Agrega dependencias reproducibles aqui cuando Willy instale librerias remotas\n"
            "; lib_deps =\n"
        )

    def _render_main_cpp(self, template_label: str) -> str:
        template = PROJECT_TEMPLATES.get(template_label, PROJECT_TEMPLATES["Blink"])
        return str(template.get("code", PROJECT_TEMPLATES["Blink"]["code"]))

    def _render_project_agents_md(self, project_name: str, preset: dict, template_label: str) -> str:
        board = str(preset.get("board", "")).strip() or "(definir)"
        platform_name = str(preset.get("platform", "")).strip() or "(definir)"
        framework = str(preset.get("framework", "")).strip() or "(definir)"
        return (
            f"# AGENTS\n\n"
            f"## Objetivo\n"
            f"Proyecto {project_name} para firmware embebido con enfoque IoT. "
            f"Template inicial: {template_label}.\n\n"
            f"## Hardware\n"
            f"- Board principal: {board}\n"
            f"- Plataforma: {platform_name}\n"
            f"- Framework: {framework}\n"
            f"- Componentes conectados: completar segun laboratorio\n\n"
            f"## Reglas\n"
            f"- Priorizar respuestas sobre este proyecto activo antes que ejemplos genericos.\n"
            f"- Si falta un dato de cableado o pinout, pedir confirmacion breve y continuar.\n"
            f"- Proponer pasos ejecutables en PlatformIO y validar antes de upload.\n"
            f"- Mantener respuestas tecnicas, claras y orientadas a implementacion.\n"
        )

    def _create_project_structure(
        self,
        project_path: str,
        project_name: str,
        preset_label: str,
        template_label: str,
        create_downloads_dir: bool,
    ) -> str:
        preset = PROJECT_PRESETS[preset_label]
        os.makedirs(project_path, exist_ok=False)

        for relative_dir in ["src", "lib", "include", "test", "outputs", ".willy"]:
            os.makedirs(os.path.join(project_path, relative_dir), exist_ok=True)

        downloads_rel = ".willy/downloads"
        if create_downloads_dir:
            os.makedirs(os.path.join(project_path, ".willy", "downloads"), exist_ok=True)

        with open(os.path.join(project_path, "platformio.ini"), "w", encoding="utf-8") as fh:
            fh.write(self._render_platformio_ini(preset))

        main_cpp_path = os.path.join(project_path, "src", "main.cpp")
        with open(main_cpp_path, "w", encoding="utf-8") as fh:
            fh.write(self._render_main_cpp(template_label))

        metadata = {
            "name": project_name,
            "board": preset["board"],
            "platform": preset["platform"],
            "framework": preset["framework"],
            "template": template_label,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "custom_lib_dir": "lib",
            "downloads_dir": downloads_rel if create_downloads_dir else "",
        }
        with open(
            os.path.join(project_path, ".willy", "project.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(metadata, fh, indent=4)

        agents_path = os.path.join(project_path, ".willy", "AGENTS.md")
        with open(agents_path, "w", encoding="utf-8") as fh:
            fh.write(self._render_project_agents_md(project_name, preset, template_label))

        return main_cpp_path

    def _open_new_project_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(i18n.get("project_dialog_title"))
        dialog.geometry("560x320")
        dialog.minsize(520, 300)
        dialog.transient(self)

        try:
            dialog.grab_set()
        except tk.TclError:
            pass

        card = ctk.CTkFrame(dialog, corner_radius=14)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card,
            text=i18n.get("project_dialog_title"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(16, 4))

        ctk.CTkLabel(
            card,
            text=i18n.get("project_dialog_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(0, 10))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        form.grid_columnconfigure(1, weight=1)

        name_var = tk.StringVar(value="")
        base_var = tk.StringVar(value=self.terminal_manager.get_cwd())
        preset_label_var = tk.StringVar(value=self._default_project_preset_label())
        template_label_var = tk.StringVar(value="Base Generica")
        downloads_var = tk.BooleanVar(value=True)
        feedback_var = tk.StringVar(value="")

        ctk.CTkLabel(form, text=i18n.get("project_name_label")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ctk.CTkEntry(form, textvariable=name_var, width=280).grid(
            row=0, column=1, sticky="ew", pady=(0, 8)
        )

        ctk.CTkLabel(form, text=i18n.get("project_location_label")).grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )
        base_row = ctk.CTkFrame(form, fg_color="transparent")
        base_row.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        base_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(base_row, textvariable=base_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 8)
        )

        def _browse_project_base() -> None:
            selected = tk.filedialog.askdirectory(
                initialdir=os.path.expanduser(base_var.get() or "~"),
                title=i18n.get("project_location_label"),
            )
            if selected:
                base_var.set(selected)

        ctk.CTkButton(
            base_row,
            text=i18n.get("browse_btn"),
            width=100,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=_browse_project_base,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(form, text=i18n.get("project_board_label")).grid(
            row=2, column=0, sticky="w", pady=(0, 8)
        )
        ctk.CTkOptionMenu(
            form,
            values=list(PROJECT_PRESETS.keys()),
            variable=preset_label_var,
        ).grid(row=2, column=1, sticky="w", pady=(0, 8))

        ctk.CTkLabel(form, text=i18n.get("project_template_label")).grid(
            row=3, column=0, sticky="w", pady=(0, 8)
        )
        ctk.CTkOptionMenu(
            form,
            values=list(PROJECT_TEMPLATES.keys()),
            variable=template_label_var,
        ).grid(row=3, column=1, sticky="w", pady=(0, 8))

        ctk.CTkCheckBox(
            form,
            text=i18n.get("project_downloads_label"),
            variable=downloads_var,
            onvalue=True,
            offvalue=False,
        ).grid(row=4, column=1, sticky="w", pady=(2, 8))

        ctk.CTkLabel(
            form,
            textvariable=feedback_var,
            text_color=("#b91c1c", "#fca5a5"),
            anchor="w",
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        button_row = ctk.CTkFrame(card, fg_color="transparent")
        button_row.pack(fill="x", padx=18, pady=(0, 16))

        def _create_project() -> None:
            project_name = name_var.get().strip()
            base_folder = os.path.abspath(os.path.expanduser(base_var.get().strip() or "~"))
            preset_label = preset_label_var.get().strip()
            template_label = template_label_var.get().strip()

            if not project_name:
                feedback_var.set(i18n.get("project_name_label"))
                return
            if preset_label not in PROJECT_PRESETS:
                feedback_var.set(i18n.get("project_board_label"))
                return
            if template_label not in PROJECT_TEMPLATES:
                feedback_var.set(i18n.get("project_template_label"))
                return
            if not os.path.isdir(base_folder):
                feedback_var.set("La carpeta base no existe.")
                return

            project_path = os.path.join(base_folder, project_name)
            if os.path.exists(project_path):
                feedback_var.set("Ya existe una carpeta con ese nombre.")
                return

            try:
                main_cpp_path = self._create_project_structure(
                    project_path,
                    project_name,
                    preset_label,
                    template_label,
                    create_downloads_dir=bool(downloads_var.get()),
                )
            except Exception as exc:
                feedback_var.set(f"No se pudo crear el proyecto: {exc}")
                return

            preset = PROJECT_PRESETS[preset_label]
            self.config_data["default_board"] = preset["board"]
            try:
                self._save_config()
            except Exception:
                pass

            self._apply_workspace_root(project_path, announce=False)
            self._update_code_preview(main_cpp_path)
            self._update_active_project_if_changed()
            self.chat_panel.add_message(
                "system",
                i18n.get("project_created", path=project_path),
            )
            dialog.destroy()

        ctk.CTkButton(
            button_row,
            text=i18n.get("settings_cancel"),
            width=120,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=dialog.destroy,
        ).pack(side="left")

        ctk.CTkButton(
            button_row,
            text=i18n.get("project_create_btn"),
            width=160,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=_create_project,
        ).pack(side="right")

    def _open_recent_projects_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title(i18n.get("recent_projects_title"))
        dialog.geometry("520x360")
        dialog.minsize(460, 280)
        dialog.transient(self)

        card = ctk.CTkFrame(dialog, corner_radius=14)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card,
            text=i18n.get("recent_projects_title"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(16, 10))

        recent = self._normalized_recent_projects()
        body = ctk.CTkScrollableFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 12))

        if not recent:
            ctk.CTkLabel(
                body,
                text=i18n.get("recent_projects_empty"),
                text_color=("gray45", "gray65"),
                anchor="w",
            ).pack(anchor="w")
        else:
            for item in recent:
                label = item["label"]
                path = item["path"]
                last_opened = item.get("last_opened", "")
                favorite = bool(item.get("favorite", False))
                row = ctk.CTkFrame(body, fg_color=("gray93", "gray17"), corner_radius=10)
                row.pack(fill="x", pady=(0, 8))
                ctk.CTkLabel(
                    row,
                    text=f"{'★ ' if favorite else ''}{label}\n{path}",
                    justify="left",
                    anchor="w",
                ).pack(side="left", fill="x", expand=True, padx=12, pady=10)
                if last_opened:
                    ctk.CTkLabel(
                        row,
                        text=last_opened,
                        font=ctk.CTkFont(size=10),
                        text_color=("gray45", "gray65"),
                    ).pack(side="left", padx=(0, 10))
                ctk.CTkButton(
                    row,
                    text=(
                        i18n.get("recent_projects_unfavorite_btn")
                        if favorite else i18n.get("recent_projects_favorite_btn")
                    ),
                    width=108,
                    fg_color=("gray70", "gray35"),
                    hover_color=("gray60", "gray45"),
                    command=lambda p=path, win=dialog: (
                        self._toggle_recent_project_favorite(p),
                        win.destroy(),
                        self._open_recent_projects_dialog(),
                    ),
                ).pack(side="right", padx=(0, 8), pady=10)
                ctk.CTkButton(
                    row,
                    text=i18n.get("recent_projects_remove_btn"),
                    width=86,
                    fg_color=("gray70", "gray35"),
                    hover_color=("gray60", "gray45"),
                    command=lambda p=path, win=dialog: (
                        self._remove_recent_project(p),
                        win.destroy(),
                        self._open_recent_projects_dialog(),
                    ),
                ).pack(side="right", padx=(0, 8), pady=10)
                ctk.CTkButton(
                    row,
                    text=i18n.get("open_folder_btn"),
                    width=92,
                    fg_color="#2563eb",
                    hover_color="#1d4ed8",
                    command=lambda p=path, win=dialog: (self._apply_workspace_root(p), win.destroy()),
                ).pack(side="right", padx=10, pady=10)

        ctk.CTkButton(
            card,
            text=i18n.get("settings_cancel"),
            width=120,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=dialog.destroy,
        ).pack(anchor="e", padx=18, pady=(0, 16))

    def _open_project_dependencies_dialog(self) -> None:
        project_path = self._resolve_project_path_for_actions()
        if not project_path or not os.path.isfile(os.path.join(project_path, "platformio.ini")):
            self.chat_panel.add_message("error", i18n.get("project_deps_no_active"))
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(i18n.get("project_deps_title"))
        dialog.geometry("620x420")
        dialog.minsize(560, 360)
        dialog.transient(self)

        metadata = self._load_project_metadata(project_path)
        current_specs = self.arduino_manager._collect_lib_deps_from_ini(project_path)
        feedback_var = tk.StringVar(value="")
        spec_var = tk.StringVar(value="")
        search_var = tk.StringVar(value="")

        card = ctk.CTkFrame(dialog, corner_radius=14)
        card.pack(fill="both", expand=True, padx=18, pady=18)

        ctk.CTkLabel(
            card,
            text=i18n.get("project_deps_title"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(16, 6))

        ctk.CTkLabel(
            card,
            text=project_path,
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).pack(anchor="w", padx=18, pady=(0, 10))

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text=i18n.get("project_deps_current")).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        deps_box = ctk.CTkTextbox(body, height=160, wrap="word")
        deps_box.grid(row=1, column=0, sticky="nsew")
        deps_box.insert(
            "0.0",
            "\n".join(current_specs) if current_specs else "(sin dependencias declaradas)",
        )
        deps_box.configure(state="disabled")

        downloads_hint = str(metadata.get("downloads_dir", "")).strip() or ".willy/downloads"
        ctk.CTkLabel(
            body,
            text=f"Downloads del proyecto: {downloads_hint}",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).grid(row=2, column=0, sticky="w", pady=(8, 6))

        add_row = ctk.CTkFrame(body, fg_color="transparent")
        add_row.grid(row=3, column=0, sticky="ew")
        add_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(add_row, text=i18n.get("project_deps_add")).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ctk.CTkEntry(add_row, textvariable=spec_var).grid(row=0, column=1, sticky="ew")

        ctk.CTkLabel(
            body,
            textvariable=feedback_var,
            text_color=("#166534", "#86efac"),
            anchor="w",
        ).grid(row=4, column=0, sticky="ew", pady=(8, 0))

        search_row = ctk.CTkFrame(body, fg_color="transparent")
        search_row.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        search_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(search_row, text=i18n.get("project_deps_search")).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        ctk.CTkEntry(search_row, textvariable=search_var).grid(
            row=0, column=1, sticky="ew"
        )

        search_results = ctk.CTkScrollableFrame(body, fg_color=("gray93", "gray17"), height=120)
        search_results.grid(row=6, column=0, sticky="nsew", pady=(8, 0))

        def _clear_search_results() -> None:
            for widget in search_results.winfo_children():
                widget.destroy()

        def _use_search_result(spec: str) -> None:
            spec_var.set(spec)
            feedback_var.set(spec)

        def _render_search_results(items: list[dict]) -> None:
            _clear_search_results()
            if not items:
                ctk.CTkLabel(
                    search_results,
                    text=i18n.get("project_deps_search_empty"),
                    text_color=("gray45", "gray65"),
                    anchor="w",
                ).pack(anchor="w", padx=10, pady=10)
                return

            for item in items:
                row = ctk.CTkFrame(search_results, fg_color=("gray88", "gray20"), corner_radius=8)
                row.pack(fill="x", padx=4, pady=4)
                title = item.get("name", item.get("spec", ""))
                version = item.get("version", "")
                description = item.get("description", "")
                summary = title if not version else f"{title} @ {version}"
                ctk.CTkLabel(
                    row,
                    text=f"{summary}\n{description}".strip(),
                    justify="left",
                    anchor="w",
                    wraplength=360,
                ).pack(side="left", fill="x", expand=True, padx=10, pady=8)
                ctk.CTkButton(
                    row,
                    text=i18n.get("project_deps_add_btn"),
                    width=92,
                    fg_color="#2563eb",
                    hover_color="#1d4ed8",
                    command=lambda spec=item.get("spec", ""): _use_search_result(spec),
                ).pack(side="right", padx=10, pady=8)

        def _search_dependencies() -> None:
            query = search_var.get().strip()
            if not query:
                _clear_search_results()
                feedback_var.set(i18n.get("project_deps_search"))
                return

            feedback_var.set(i18n.get("project_deps_searching"))

            def _worker() -> None:
                result = self.arduino_manager.search_libraries(query)

                def _finish() -> None:
                    if not result.get("ok"):
                        feedback_var.set(result.get("error", i18n.get("project_deps_search_empty")))
                        _clear_search_results()
                        return
                    _render_search_results(result.get("results", []))
                    if result.get("results"):
                        feedback_var.set("")
                    else:
                        feedback_var.set(i18n.get("project_deps_search_empty"))

                self.after(0, _finish)

            threading.Thread(target=_worker, daemon=True).start()

        button_row = ctk.CTkFrame(card, fg_color="transparent")
        button_row.pack(fill="x", padx=18, pady=(0, 16))

        def _refresh_dependency_view() -> None:
            updated_specs = self.arduino_manager._collect_lib_deps_from_ini(project_path)
            deps_box.configure(state="normal")
            deps_box.delete("0.0", "end")
            deps_box.insert(
                "0.0",
                "\n".join(updated_specs) if updated_specs else "(sin dependencias declaradas)",
            )
            deps_box.configure(state="disabled")

        def _add_dependency() -> None:
            changed, resolved_spec = self._append_lib_dep_to_ini(project_path, spec_var.get())
            if not resolved_spec:
                feedback_var.set(i18n.get("project_deps_add"))
                return
            if not changed:
                feedback_var.set(i18n.get("project_deps_exists"))
                return

            latest_specs = self.arduino_manager._collect_lib_deps_from_ini(project_path)
            latest_meta = self._load_project_metadata(project_path)
            latest_meta["managed_dependencies"] = latest_specs
            self._save_project_metadata(project_path, latest_meta)
            spec_var.set("")
            feedback_var.set(i18n.get("project_deps_added", spec=resolved_spec))
            self.chat_panel.add_message("system", i18n.get("project_deps_added", spec=resolved_spec))
            _refresh_dependency_view()

        def _install_dependencies(add_current_spec: bool = False) -> None:
            if add_current_spec:
                changed, resolved_spec = self._append_lib_dep_to_ini(project_path, spec_var.get())
                if not resolved_spec:
                    feedback_var.set(i18n.get("project_deps_add"))
                    return
                if changed:
                    latest_meta = self._load_project_metadata(project_path)
                    latest_meta["managed_dependencies"] = self.arduino_manager._collect_lib_deps_from_ini(project_path)
                    self._save_project_metadata(project_path, latest_meta)
                    spec_var.set("")
                    _refresh_dependency_view()

            feedback_var.set(i18n.get("project_deps_installing"))
            self.chat_panel.add_message("system", i18n.get("project_deps_installing"))
            env = self._select_env_for_project(project_path)

            def _worker() -> None:
                result = self.arduino_manager.install_declared_dependencies(project_path, env=env)

                def _finish() -> None:
                    if result.get("ok"):
                        feedback_var.set(i18n.get("project_deps_installed"))
                        self.chat_panel.add_message("system", i18n.get("project_deps_installed"))
                    else:
                        error_text = result.get("error", "Error desconocido")
                        feedback_var.set(i18n.get("project_deps_install_error", error=error_text))
                        self.chat_panel.add_message(
                            "error",
                            i18n.get("project_deps_install_error", error=error_text),
                        )

                self.after(0, _finish)

            threading.Thread(target=_worker, daemon=True).start()

        def _prepare_downloads_dir() -> None:
            downloads_path = self._ensure_project_downloads_dir(project_path)
            feedback_var.set(i18n.get("project_deps_ready", path=downloads_path))
            self.chat_panel.add_message("system", i18n.get("project_deps_ready", path=downloads_path))

        ctk.CTkButton(
            button_row,
            text=i18n.get("project_deps_downloads_btn"),
            width=220,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=_prepare_downloads_dir,
        ).pack(side="left")

        ctk.CTkButton(
            button_row,
            text=i18n.get("project_deps_search_btn"),
            width=110,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=_search_dependencies,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            button_row,
            text=i18n.get("project_deps_add_btn"),
            width=110,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=_add_dependency,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            button_row,
            text=i18n.get("project_deps_install_btn"),
            width=150,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=lambda: _install_dependencies(add_current_spec=True),
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            button_row,
            text=i18n.get("settings_cancel"),
            width=110,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=dialog.destroy,
        ).pack(side="right")

    def _set_iot_action_buttons_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        if hasattr(self, "compile_btn"):
            self.compile_btn.configure(state=state)
        if hasattr(self, "upload_btn"):
            self.upload_btn.configure(state=state)

    def _start_compile(self) -> None:
        if self._iot_action_running:
            return
        self._iot_action_running = True
        self._last_iot_action_kind = "compile"
        self._last_iot_action_ok = None
        self._last_iot_action_state = "compiling"
        self._set_iot_action_buttons_state(False)
        self._set_code_action_indicator("compiling")
        self._refresh_flow_diagram_text()
        threading.Thread(target=self._compile_worker, daemon=True).start()

    def _compile_worker(self) -> None:
        project_path = self._resolve_project_path_for_actions()
        env = self._select_env_for_project(project_path)
        result = self.arduino_manager.build_sketch(project_path, env)
        self.after(0, self._finish_compile, result, project_path, env)

    def _finish_compile(self, result: dict, project_path: str, env: str | None) -> None:
        self._iot_action_running = False
        self._set_iot_action_buttons_state(True)
        ok = bool(result.get("ok"))
        self._last_iot_action_kind = "compile"
        self._last_iot_action_ok = ok
        self._last_iot_action_state = "success" if ok else "error"
        self._set_code_action_indicator("success" if ok else "error")
        if ok:
            self._on_status(f"Compilacion OK ({env or 'default'})")
            self.chat_panel.add_message("system", f"Compilacion completada en {project_path}")
        else:
            err = result.get("error", "Error desconocido")
            self.chat_panel.add_message("error", f"Fallo compilacion: {err}")
        self._update_active_project_if_changed()
        self._refresh_flow_diagram_text()
        self.after(2200, lambda: self._set_code_action_indicator("idle"))

    def _start_upload(self) -> None:
        if self._iot_action_running:
            return
        self._iot_action_running = True
        self._last_iot_action_kind = "upload"
        self._last_iot_action_ok = None
        self._last_iot_action_state = "uploading"
        self._set_iot_action_buttons_state(False)
        self._set_code_action_indicator("uploading")
        self._refresh_flow_diagram_text()
        threading.Thread(target=self._upload_worker, daemon=True).start()

    def _upload_worker(self) -> None:
        project_path = self._resolve_project_path_for_actions()
        env = self._select_env_for_project(project_path)
        port = self._selected_or_default_port()
        result = self.arduino_manager.upload_firmware(project_path, port, env)
        self.after(0, self._finish_upload, result, project_path, port, env)

    def _finish_upload(self, result: dict, project_path: str, port: str, env: str | None) -> None:
        self._iot_action_running = False
        self._set_iot_action_buttons_state(True)
        ok = bool(result.get("ok"))
        self._last_iot_action_kind = "upload"
        self._last_iot_action_ok = ok
        self._last_iot_action_state = "success" if ok else "error"
        self._set_code_action_indicator("success" if ok else "error")
        if ok:
            self._on_status(f"Grabacion OK en {port} ({env or 'default'})")
            self.chat_panel.add_message("system", f"Grabacion completada en {port} desde {project_path}")
        else:
            err = result.get("error", "Error desconocido")
            self.chat_panel.add_message("error", f"Fallo grabacion: {err}")
        self._update_active_project_if_changed()
        self._refresh_flow_diagram_text()
        self.after(2200, lambda: self._set_code_action_indicator("idle"))

    def _open_expanded_code_view(self) -> None:
        if self._code_expand_window is not None and self._code_expand_window.winfo_exists():
            self._code_expand_window.focus_force()
            return

        self._code_expand_window = ctk.CTkToplevel(self)
        self._code_expand_window.title("Codigo en desarrollo")
        self._code_expand_window.geometry("1100x700")
        self._code_expand_window.minsize(780, 420)
        self._code_expand_window.transient(self)

        container = ctk.CTkFrame(self._code_expand_window)
        container.pack(fill="both", expand=True, padx=12, pady=12)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        self._code_expand_text = ctk.CTkTextbox(
            container,
            font=ctk.CTkFont(family="monospace", size=12),
            wrap="none",
            fg_color=("gray96", "#0d1117"),
            border_color=("gray70", "gray40"),
            border_width=1,
        )
        self._code_expand_text.grid(row=0, column=0, sticky="nsew")

        content = ""
        if hasattr(self, "code_preview"):
            try:
                self.code_preview.configure(state="normal")
                content = self.code_preview.get("0.0", "end")
                self.code_preview.configure(state="disabled")
            except Exception:
                content = ""

        self._code_expand_text.insert("0.0", content)
        self._code_expand_text.configure(state="disabled")

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
        self._refresh_flow_diagram_text()

    def _selected_or_default_port(self) -> str:
        selected = self.device_picker_var.get() if hasattr(self, "device_picker_var") else ""
        if selected and selected != "Sin dispositivos":
            for dev in self._detected_devices:
                label = f"{dev.get('board', 'unknown')} - {dev.get('port', '?')}"
                if label == selected:
                    return dev.get("port", self.config_data.get("default_port", "/dev/ttyUSB0"))
        return self.config_data.get("default_port", "/dev/ttyUSB0")

    def _start_serial_monitor(self) -> None:
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
        win.minsize(700, 380)
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(win, fg_color=("gray85", "gray20"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        header.grid_columnconfigure(2, weight=0)

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

        controls = ctk.CTkFrame(header, fg_color="transparent")
        controls.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="e")

        ctk.CTkCheckBox(
            controls,
            text="Timestamp",
            variable=self.serial_timestamps_var,
            width=90,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkCheckBox(
            controls,
            text="Pausa",
            variable=self.serial_freeze_var,
            width=70,
            command=self._toggle_serial_freeze,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            controls,
            text="Limpiar",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            command=self._clear_serial_monitor,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            controls,
            text="Detener",
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#c0392b",
            hover_color="#922b21",
            command=self._stop_serial_monitor,
        ).pack(side="left")

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
        self.serial_popup_output_text = output

        def on_close() -> None:
            self.serial_window = None
            self.serial_popup_output_text = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self._serial_append_output("[Consola serial lista]\n")

    def _clear_serial_monitor(self) -> None:
        self.serial_paused_buffer.clear()
        for widget in (self.serial_output_text, self.serial_popup_output_text):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")

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
        for widget in (self.serial_output_text, self.serial_popup_output_text):
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.insert("end", text)
            widget.configure(state="disabled")
            if not self.serial_freeze_var.get():
                widget.see("end")

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
        self._refresh_project_views(force_code_refresh=False)

        self._schedule_next_diagram_poll()

    def _find_latest_schematic_assets(self, project_path: str = "") -> tuple[str, str, str]:
        schem_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "outputs", "schematics")
        if not os.path.isdir(schem_dir):
            return "", "", ""

        project_tokens = self._project_name_tokens(project_path)

        def _latest(paths: list[str]) -> str:
            return max(paths, key=os.path.getmtime) if paths else ""

        def _matches_project(path: str) -> bool:
            if not project_tokens:
                return False
            name = os.path.basename(path).lower().replace("-", "_").replace(" ", "_")
            compact = name.replace("_", "")
            return any(token and (token in name or token in compact) for token in project_tokens)

        def _paths_for(ext: str) -> list[str]:
            return [
                os.path.join(schem_dir, name)
                for name in os.listdir(schem_dir)
                if name.lower().endswith(ext)
            ]

        all_svgs = _paths_for(".svg")
        all_boms = _paths_for("_bom.csv")
        all_nets = _paths_for(".net")

        if project_tokens:
            related_svgs = [path for path in all_svgs if _matches_project(path)]
            related_boms = [path for path in all_boms if _matches_project(path)]
            related_nets = [path for path in all_nets if _matches_project(path)]
            svg = _latest(related_svgs)
            bom = _latest(related_boms)
            net = _latest(related_nets)
            return svg, bom, net

        session_svgs = [path for path in all_svgs if os.path.getmtime(path) >= (self._app_session_start_ts - 1.0)]
        session_boms = [path for path in all_boms if os.path.getmtime(path) >= (self._app_session_start_ts - 1.0)]
        session_nets = [path for path in all_nets if os.path.getmtime(path) >= (self._app_session_start_ts - 1.0)]
        svg = _latest(session_svgs or all_svgs)
        bom = _latest(session_boms or all_boms)
        net = _latest(session_nets or all_nets)
        return svg, bom, net

    def _update_wiring_summary(self) -> None:
        if not hasattr(self, "wiring_summary_text") or self.wiring_summary_text is None:
            return

        lines: list[str] = []
        if self._active_project_path:
            lines.append(f"Proyecto activo: {self._active_project_path}")
        else:
            lines.append("Proyecto activo: no detectado")

        if self._active_netlist_path and os.path.isfile(self._active_netlist_path):
            lines.append(f"Netlist: {os.path.basename(self._active_netlist_path)}")
            try:
                with open(self._active_netlist_path, "r", encoding="utf-8", errors="replace") as fh:
                    net_lines = fh.readlines()
                conn_lines = [ln.strip() for ln in net_lines if "->" in ln]
                if conn_lines:
                    lines.append("")
                    lines.append("Conexiones:")
                    lines.extend(conn_lines[:20])
            except Exception as exc:
                lines.append(f"No se pudo leer netlist: {exc}")
        else:
            lines.append("Netlist: no disponible para este proyecto")

        if self._latest_bom_path and os.path.isfile(self._latest_bom_path):
            lines.append("")
            lines.append(f"BOM: {os.path.basename(self._latest_bom_path)}")

        text = "\n".join(lines)
        self.wiring_summary_text.configure(state="normal")
        self.wiring_summary_text.delete("0.0", "end")
        self.wiring_summary_text.insert("0.0", text)
        self.wiring_summary_text.configure(state="disabled")

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
        self._current_code_path = path
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

        if self._code_expand_text is not None and self._code_expand_text.winfo_exists():
            self._code_expand_text.configure(state="normal")
            self._code_expand_text.delete("0.0", "end")
            self._code_expand_text.insert("0.0", preview)
            self._code_expand_text.configure(state="disabled")

        self._refresh_flow_diagram_text()

    def _clippy_default_position(self) -> tuple[int, int]:
        return 8, 48

    def _clamp_clippy_position(self, x: int, y: int) -> tuple[int, int]:
        if not hasattr(self, "clippy") or self.clippy is None:
            return 0, 0
        panel_w = max(1, self.chat_panel.winfo_width())
        panel_h = max(1, self.chat_panel.winfo_height())
        widget_w = max(1, self.clippy.winfo_width())
        widget_h = max(1, self.clippy.winfo_height())
        max_x = max(0, panel_w - widget_w)
        max_y = max(0, panel_h - widget_h)
        return max(0, min(int(x), max_x)), max(0, min(int(y), max_y))

    def _restore_clippy_position(self) -> None:
        if not hasattr(self, "clippy") or self.clippy is None:
            return
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
                if not hasattr(self, "clippy") or self.clippy is None:
                    continue
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

    def _apply_sidebar_width(self, width: int, persist: bool = False) -> None:
        clamped = max(180, min(360, int(width)))
        self._sidebar_width = clamped
        self.grid_columnconfigure(0, minsize=clamped)
        if hasattr(self, "file_browser") and self.file_browser is not None:
            self.file_browser.configure(width=clamped)

        if persist and "sidebar_width" not in self._locked_config_keys:
            self.config_data["sidebar_width"] = clamped
            try:
                self._save_config()
            except Exception:
                pass

    def _on_sidebar_drag_start(self, _event=None) -> None:
        self._sidebar_dragging = True

    def _on_sidebar_drag_motion(self, _event=None) -> None:
        if not self._sidebar_visible:
            return
        pointer_x = self.winfo_pointerx()
        root_x = self.winfo_rootx()
        new_width = pointer_x - root_x
        self._apply_sidebar_width(new_width, persist=False)

    def _on_sidebar_drag_end(self, _event=None) -> None:
        if not self._sidebar_dragging:
            return
        self._sidebar_dragging = False
        self._apply_sidebar_width(self._sidebar_width, persist=True)

    def _toggle_sidebar(self) -> None:
        if self._sidebar_visible:
            self.file_browser.grid_remove()
            if hasattr(self, "sidebar_splitter"):
                self.sidebar_splitter.grid_remove()
            self.grid_columnconfigure(0, minsize=0)
            self.grid_columnconfigure(1, minsize=0)
            self._sidebar_visible = False
        else:
            self.file_browser.grid()
            if hasattr(self, "sidebar_splitter"):
                self.sidebar_splitter.grid()
            self.grid_columnconfigure(1, minsize=6)
            self._apply_sidebar_width(self._sidebar_width, persist=False)
            self._sidebar_visible = True

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        """Open the improved settings dialog with validation and sync."""
        settings_window = ctk.CTkToplevel(self)
        settings_window.title(i18n.get("settings_title"))
        settings_window.geometry("620x520")
        settings_window.minsize(560, 460)
        settings_window.transient(self)
        settings_window.update_idletasks()

        def _safe_grab_set() -> None:
            try:
                settings_window.grab_set()
            except tk.TclError:
                pass

        settings_window.after(0, _safe_grab_set)
        settings_window.resizable(True, True)

        frame = ctk.CTkFrame(settings_window, corner_radius=14)
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 8))

        ctk.CTkLabel(
            header,
            text=i18n.get("settings_title"),
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Configura tu API key y carpeta de trabajo por defecto.",
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        body = ctk.CTkScrollableFrame(frame, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=(4, 10))

        # API Key
        api_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("gray93", "gray17"))
        api_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            api_card,
            text=i18n.get("settings_api_key"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(anchor="w", padx=12, pady=(10, 2))
        api_source_actual = _resolve_api_source(self.config_data)
        api_source_var = tk.StringVar(value=api_source_actual)
        api_key_var = tk.StringVar(value=self.config_data.get("openai_api_key", ""))
        api_key_visible = tk.BooleanVar(value=False)

        source_row = ctk.CTkFrame(api_card, fg_color="transparent")
        source_row.pack(anchor="w", fill="x", padx=12, pady=(0, 6))

        ctk.CTkLabel(
            source_row,
            text=i18n.get("settings_api_source"),
            font=ctk.CTkFont(size=11),
            text_color=("gray35", "gray70"),
        ).pack(side="left", padx=(0, 8))

        source_labels = {
            "env": i18n.get("api_source_env"),
            "config": i18n.get("api_source_config"),
        }
        source_from_label = {label: key for key, label in source_labels.items()}
        source_label_var = tk.StringVar(value=source_labels.get(api_source_actual, source_labels["env"]))

        source_menu = ctk.CTkOptionMenu(
            source_row,
            values=[source_labels["env"], source_labels["config"]],
            variable=source_label_var,
            width=240,
            command=lambda label: api_source_var.set(source_from_label.get(label, "env")),
        )
        source_menu.pack(side="left")

        api_row = ctk.CTkFrame(api_card, fg_color="transparent")
        api_row.pack(anchor="w", fill="x", padx=12, pady=(0, 8))

        api_key_entry = ctk.CTkEntry(
            api_row,
            textvariable=api_key_var,
            width=390,
            show="*",
        )
        api_key_entry.pack(side="left", padx=(0, 8))

        def toggle_api_visibility() -> None:
            visible = not api_key_visible.get()
            api_key_visible.set(visible)
            api_key_entry.configure(show="" if visible else "*")
            toggle_btn.configure(text=i18n.get("hide_btn") if visible else i18n.get("show_btn"))

        toggle_btn = ctk.CTkButton(
            api_row,
            text=i18n.get("show_btn"),
            width=110,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=toggle_api_visibility,
        )
        toggle_btn.pack(side="left")

        locked_keys = getattr(self, "_locked_config_keys", set())
        if "api_key_source" in locked_keys:
            source_menu.configure(state="disabled")
        if "openai_api_key" in locked_keys:
            api_key_entry.configure(state="disabled")
            toggle_btn.configure(state="disabled")

        ctk.CTkLabel(
            api_card,
            text="Tip: usa Variable de entorno para laboratorios y equipos compartidos.",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # Default folder
        folder_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("gray93", "gray17"))
        folder_card.pack(fill="x")
        ctk.CTkLabel(
            folder_card,
            text=i18n.get("settings_initial_dir"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        ).pack(anchor="w", padx=12, pady=(10, 2))
        folder_var = tk.StringVar(value=self.config_data.get("initial_directory", "~"))
        folder_row = ctk.CTkFrame(folder_card, fg_color="transparent")
        folder_row.pack(anchor="w", fill="x", padx=12, pady=(0, 8))
        folder_entry = ctk.CTkEntry(
            folder_row,
            textvariable=folder_var,
            width=390,
        )
        folder_entry.pack(side="left", padx=(0, 8))

        def select_folder():
            folder = tk.filedialog.askdirectory(initialdir=os.path.expanduser(folder_var.get()))
            if folder:
                folder_var.set(folder)

        browse_btn = ctk.CTkButton(
            folder_row,
            text=i18n.get("browse_btn") if hasattr(i18n, "get") else "Examinar",
            width=110,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=select_folder,
        )
        browse_btn.pack(side="left")

        if "initial_directory" in locked_keys:
            folder_entry.configure(state="disabled")
            browse_btn.configure(state="disabled")

        ctk.CTkLabel(
            folder_card,
            text="Se aplicará al terminal y al explorador de archivos.",
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 10))

        # Security profile
        security_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("gray93", "gray17"))
        security_card.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            security_card,
            text=i18n.get("settings_security_profile"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 2))

        security_labels = {
            "lab_safe": i18n.get("security_profile_lab_safe"),
            "standard": i18n.get("security_profile_standard"),
            "permissive": i18n.get("security_profile_permissive"),
        }
        security_from_label = {label: key for key, label in security_labels.items()}
        current_profile = str(self.config_data.get("security_profile", "lab_safe")).strip().lower()
        if current_profile not in security_labels:
            current_profile = "lab_safe"
        security_profile_var = tk.StringVar(value=current_profile)
        security_label_var = tk.StringVar(value=security_labels[current_profile])

        security_row = ctk.CTkFrame(security_card, fg_color="transparent")
        security_row.pack(anchor="w", fill="x", padx=12, pady=(0, 8))

        security_menu = ctk.CTkOptionMenu(
            security_row,
            values=[
                security_labels["lab_safe"],
                security_labels["standard"],
                security_labels["permissive"],
            ],
            variable=security_label_var,
            width=300,
            command=lambda label: security_profile_var.set(
                security_from_label.get(label, "lab_safe")
            ),
        )
        security_menu.pack(side="left")
        if "security_profile" in locked_keys:
            security_menu.configure(state="disabled")

        ctk.CTkLabel(
            security_card,
            text=i18n.get("settings_security_hint"),
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        role_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("gray93", "gray17"))
        role_card.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            role_card,
            text=i18n.get("settings_operation_role"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 2))

        role_labels = {
            "student": i18n.get("operation_role_student"),
            "instructor": i18n.get("operation_role_instructor"),
            "admin": i18n.get("operation_role_admin"),
        }
        role_from_label = {label: key for key, label in role_labels.items()}
        current_role = str(self.config_data.get("operation_role", "instructor")).strip().lower()
        if current_role not in role_labels:
            current_role = "instructor"
        operation_role_var = tk.StringVar(value=current_role)
        operation_role_label_var = tk.StringVar(value=role_labels[current_role])

        role_row = ctk.CTkFrame(role_card, fg_color="transparent")
        role_row.pack(anchor="w", fill="x", padx=12, pady=(0, 8))

        role_menu = ctk.CTkOptionMenu(
            role_row,
            values=[
                role_labels["student"],
                role_labels["instructor"],
                role_labels["admin"],
            ],
            variable=operation_role_label_var,
            width=300,
            command=lambda label: operation_role_var.set(
                role_from_label.get(label, "instructor")
            ),
        )
        role_menu.pack(side="left")
        if "operation_role" in locked_keys:
            role_menu.configure(state="disabled")

        ctk.CTkLabel(
            role_card,
            text=i18n.get("settings_operation_role_hint"),
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        audit_card = ctk.CTkFrame(body, corner_radius=12, fg_color=("gray93", "gray17"))
        audit_card.pack(fill="x", pady=(10, 0))
        ctk.CTkLabel(
            audit_card,
            text=i18n.get("settings_audit_export"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(10, 2))

        ctk.CTkLabel(
            audit_card,
            text=i18n.get("settings_audit_hint"),
            font=ctk.CTkFont(size=10),
            text_color=("gray45", "gray65"),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        audit_status_var = tk.StringVar(value="")

        def export_audit(days: int | None = None) -> None:
            now = datetime.now()
            start_iso = ""
            suffix = "all"
            if days is not None:
                start_iso = (now - timedelta(days=days)).isoformat(timespec="seconds")
                suffix = f"last_{days}d"

            if days == 0:
                start_iso = datetime.fromtimestamp(
                    self._app_session_start_ts
                ).isoformat(timespec="seconds")
                suffix = "current_session"

            end_iso = now.isoformat(timespec="seconds")
            os.makedirs(AUDIT_OUTPUT_DIR, exist_ok=True)
            stamp = now.strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(
                AUDIT_OUTPUT_DIR,
                f"willy_audit_{suffix}_{stamp}.json",
            )

            try:
                path = self.session_logger.export_audit_report(
                    output_path,
                    start_iso=start_iso or None,
                    end_iso=end_iso,
                )
                audit_status_var.set(i18n.get("audit_export_ok", path=path))
            except Exception as exc:
                audit_status_var.set(i18n.get("audit_export_error", error=str(exc)))

        audit_btn_row = ctk.CTkFrame(audit_card, fg_color="transparent")
        audit_btn_row.pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkButton(
            audit_btn_row,
            text=i18n.get("export_audit_7d_btn"),
            width=170,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: export_audit(days=7),
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            audit_btn_row,
            text=i18n.get("export_audit_session_btn"),
            width=210,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: export_audit(days=0),
        ).pack(side="left")

        ctk.CTkLabel(
            audit_card,
            textvariable=audit_status_var,
            font=ctk.CTkFont(size=10),
            text_color=("gray35", "gray75"),
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        if locked_keys:
            ctk.CTkLabel(
                frame,
                text=i18n.get(
                    "settings_locked_notice",
                    keys=", ".join(sorted(locked_keys)),
                ),
                font=ctk.CTkFont(size=10),
                text_color=("#8a5a00", "#f5c26b"),
                anchor="w",
                justify="left",
                wraplength=560,
            ).pack(anchor="w", padx=20, pady=(0, 6))

        # Feedback label
        feedback_var = tk.StringVar(value="")
        feedback_label = ctk.CTkLabel(
            frame,
            textvariable=feedback_var,
            font=ctk.CTkFont(size=10),
            text_color="#c0392b",
            anchor="w"
        )
        feedback_label.pack(anchor="w", padx=20, pady=(0, 2))

        # Action buttons
        btn_row = ctk.CTkFrame(frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(8, 16))

        def on_cancel():
            settings_window.destroy()

        def save_settings():
            # Validación de carpeta
            folder = os.path.expanduser(folder_var.get())
            folder = os.path.abspath(folder)
            if not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                except Exception as e:
                    feedback_var.set(f"Error: {str(e)}")
                    return
            if not os.path.isdir(folder):
                feedback_var.set("La ruta no es un directorio válido.")
                return
            if not os.access(folder, os.W_OK):
                feedback_var.set("No tienes permisos de escritura en la carpeta.")
                return
            # Guardar config
            selected_source = api_source_var.get().strip().lower() or "env"
            if selected_source not in {"env", "config"}:
                selected_source = "env"

            api_key_value = api_key_var.get().strip()
            if "api_key_source" not in locked_keys:
                self.config_data["api_key_source"] = selected_source
            selected_source = self.config_data.get("api_key_source", "env")

            # Security default: if source is env, avoid persisting secrets in config.
            if "openai_api_key" not in locked_keys:
                if selected_source == "env":
                    self.config_data["openai_api_key"] = ""
                else:
                    self.config_data["openai_api_key"] = api_key_value

            if "initial_directory" not in locked_keys:
                self.config_data["initial_directory"] = folder
            if "security_profile" not in locked_keys:
                self.config_data["security_profile"] = (
                    security_profile_var.get().strip().lower() or "lab_safe"
                )
            if "operation_role" not in locked_keys:
                self.config_data["operation_role"] = (
                    operation_role_var.get().strip().lower() or "instructor"
                )
            with open(CONFIG_PATH, "w", encoding="utf-8") as config_file:
                json.dump(self.config_data, config_file, indent=4)
            # Sincronizar terminal y file browser
            self.terminal_manager.change_directory(folder)
            if hasattr(self, "file_browser"):
                self.file_browser.navigate_to(folder)
            settings_window.destroy()

        ctk.CTkButton(
            btn_row,
            text=i18n.get("settings_cancel"),
            width=120,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=on_cancel,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row,
            text=i18n.get("settings_save"),
            width=150,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=save_settings,
        ).pack(side="right")

        settings_window.bind("<Escape>", lambda _e: on_cancel())
        settings_window.bind("<Return>", lambda _e: save_settings())
