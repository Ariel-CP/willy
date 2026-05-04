"""
gui.py — Main application window.
Layout:  [FileBrowser (sidebar)] | [ChatPanel] | [TerminalPanel]
"""

import json
import os
import platform
import socket
import tkinter as tk
import customtkinter as ctk

from app.terminal_manager import TerminalManager
from app.terminal_panel import TerminalPanel
from app.chat_panel import ChatPanel
from app.file_browser import FileBrowser
from app.ai_agent import AIAgent
from app.session_logger import SessionLogger
from app.tts import TTSEngine
from app import i18n


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

        self._build_layout()
        self._wire_up()
        self.after(200, self._show_startup_greeting)

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
        self.terminal_manager = TerminalManager(
            output_callback=self._on_terminal_output,
            initial_dir=initial_dir,
            on_command_done=self.session_logger.log_command,
        )

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

        self.terminal_panel = TerminalPanel(
            self,
            terminal_manager=self.terminal_manager,
            fg_color=("gray92", "#0a0f14"),
        )
        self.terminal_panel.grid(row=0, column=2, sticky="nsew")

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

        ctk.CTkButton(
            status_bar,
            text=i18n.get("settings_btn"),
            width=80,
            height=18,
            font=ctk.CTkFont(size=10),
            fg_color="transparent",
            hover_color=("gray70", "gray30"),
            command=self._open_settings,
        ).grid(row=0, column=1, padx=(0, 4))

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
        )

        def _logged_send(text: str) -> None:
            self.session_logger.log_message("user", text)
            self.ai_agent.send(text)

        self.chat_panel.set_send_callback(_logged_send)

        self.tts = TTSEngine(lang=self.config_data.get("language", "es"))
        self.chat_panel.set_tts_callback(self.tts.speak)
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

    def _on_confirm_request(self, title: str, detail: str, callback) -> None:
        self.chat_panel.show_confirm_dialog(title, detail, callback)

    def _on_status(self, text: str) -> None:
        self.chat_panel.set_status(text)
        self.after(0, self.status_bar_label.configure, {
            "text": f"  {text}" if text else f"  {i18n.get('ready')}"
        })

    def _on_file_selected(self, path: str) -> None:
        self.chat_panel.add_message("system", i18n.get("file_selected", path=path))
        self.ai_agent.send(i18n.get("file_send_msg", path=path))

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

        def _save():
            selected_source = label_to_source.get(api_source_var.get(), "env")
            self.config_data["api_key_source"] = selected_source
            self.config_data["openai_api_key"] = api_var.get().strip()
            self.config_data["model"] = model_var.get().strip()
            self.config_data["initial_directory"] = dir_var.get().strip()
            self.config_data["theme"] = theme_var.get()
            self.config_data["confirm_readonly"] = confirm_ro_var.get()
            self.config_data["language"] = lang_display.get(lang_var.get(), "es")
            try:
                with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                    json.dump(self.config_data, fh, indent=4)
            except Exception:
                pass
            ctk.set_appearance_mode(self.config_data["theme"])
            self.ai_agent.config = self.config_data
            self.ai_agent._client = None
            dlg.grab_release()
            dlg.destroy()
            from tkinter import messagebox
            messagebox.showinfo(
                i18n.get("settings_title"),
                i18n.get("restart_notice"),
            )

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.grid(row=8, column=0, columnspan=2, pady=(8, 16))
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
