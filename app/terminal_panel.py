"""
terminal_panel.py — Right panel: shows live terminal output + cwd bar + kill button.
"""

import tkinter as tk
import customtkinter as ctk
from app import i18n


class TerminalPanel(ctk.CTkFrame):
    def __init__(self, master, terminal_manager, **kwargs):
        super().__init__(master, **kwargs)
        self.tm = terminal_manager
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Header bar ──────────────────────────────────────────────────
        header = ctk.CTkFrame(self, height=36, fg_color=("gray85", "gray20"))
        header.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
                text=i18n.get("terminal_header"),
            font=ctk.CTkFont(family="monospace", size=12, weight="bold"),
            text_color=("gray30", "gray80"),
        ).grid(row=0, column=0, padx=(10, 6), pady=6, sticky="w")

        self.cwd_label = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(family="monospace", size=11),
            text_color=("gray40", "#7ec8e3"),
            anchor="w",
        )
        self.cwd_label.grid(row=0, column=1, padx=4, pady=6, sticky="ew")

        self.kill_btn = ctk.CTkButton(
            header,
                text=i18n.get("stop_btn"),
            width=70,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#c0392b",
            hover_color="#922b21",
            command=self._kill,
        )
        self.kill_btn.grid(row=0, column=2, padx=(0, 8), pady=6)

        self.clear_btn = ctk.CTkButton(
            header,
                text=i18n.get("clear_btn"),
            width=60,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self.clear,
        )
        self.clear_btn.grid(row=0, column=3, padx=(0, 8), pady=6)

        # ── Output text area ────────────────────────────────────────────
        output_frame = ctk.CTkFrame(self, fg_color=("gray95", "#0d1117"))
        output_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        output_frame.grid_rowconfigure(0, weight=1)
        output_frame.grid_columnconfigure(0, weight=1)

        self.output_text = tk.Text(
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
        self.output_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ctk.CTkScrollbar(output_frame, command=self.output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=scrollbar.set)

        # Colour tags
        self.output_text.tag_configure("cmd", foreground="#7ec8e3", font=("monospace", 11, "bold"))
        self.output_text.tag_configure("error", foreground="#f87171")
        self.output_text.tag_configure("done", foreground="#6ee7b7", font=("monospace", 10))

        # ── Input row ───────────────────────────────────────────────────
        input_frame = ctk.CTkFrame(self, fg_color=("gray90", "gray15"), height=40)
        input_frame.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        input_frame.grid_columnconfigure(0, weight=1)

        self.cmd_entry = ctk.CTkEntry(
            input_frame,
                placeholder_text=i18n.get("cmd_placeholder"),
            font=ctk.CTkFont(family="monospace", size=12),
            fg_color=("gray95", "#161b22"),
            border_color=("gray70", "gray30"),
        )
        self.cmd_entry.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
        self.cmd_entry.bind("<Return>", self._on_enter)

        run_btn = ctk.CTkButton(
            input_frame,
                text=i18n.get("run_btn"),
            width=60,
            height=28,
            font=ctk.CTkFont(size=12),
            command=self._on_enter,
        )
        run_btn.grid(row=0, column=1, padx=(0, 8), pady=6)

        self._update_cwd()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_output(self, text: str, tag: str = "") -> None:
        """Append *text* to the terminal output area (thread-safe via after)."""
        self.after(0, self._insert_text, text, tag)

    def clear(self) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", "end")
        self.output_text.configure(state="disabled")

    def update_cwd(self) -> None:
        self.after(0, self._update_cwd)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _insert_text(self, text: str, tag: str) -> None:
        self.output_text.configure(state="normal")
        if tag:
            self.output_text.insert("end", text, tag)
        else:
            self._insert_ansi_stripped(text)
        self.output_text.configure(state="disabled")
        self.output_text.see("end")

    def _insert_ansi_stripped(self, text: str) -> None:
        """Strip basic ANSI escape codes before inserting."""
        import re
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[mGKHFJ]|\x1b\].*?\x07|\x1b[@-Z\\-_]")
        clean = ansi_escape.sub("", text)
        # Colour lines that look like errors
        if any(kw in clean.lower() for kw in ("error", "traceback", "command not found", "no such file")):
            self.output_text.insert("end", clean, "error")
        elif clean.startswith("[Done]"):
            self.output_text.insert("end", clean, "done")
        else:
            self.output_text.insert("end", clean)

    def _update_cwd(self) -> None:
        self.cwd_label.configure(text=f"  {self.tm.get_cwd()}")

    def _on_enter(self, _event=None) -> None:
        command = self.cmd_entry.get().strip()
        self.cmd_entry.delete(0, "end")
        if not command:
            return

        # If a process is waiting for stdin (e.g., sudo password), send input to it.
        if self.tm.has_active_process():
            sent = self.tm.send_input(command)
            if not sent:
                self.append_output("[No hay proceso activo para recibir entrada]\n", "error")
            return

        self.append_output(f"$ {command}\n", "cmd")
        if command.startswith("cd "):
            path = command[3:].strip()
            msg = self.tm.change_directory(path)
            if msg.startswith("cd:"):
                self.append_output(msg + "\n", "error")
            self.update_cwd()
        else:
            self.tm.run_command_async(command)

    def _kill(self) -> None:
        self.tm.kill_active()
        self.append_output(i18n.get("interrupted"), "error")
