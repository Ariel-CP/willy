"""
file_browser.py — Sidebar with a simple filesystem tree viewer.
Clicking a file sends its path to the chat panel.
"""

import os
import tkinter as tk
import customtkinter as ctk
from typing import Callable
from app import i18n


class FileBrowser(ctk.CTkFrame):
    def __init__(self, master, on_file_selected: Callable[[str], None], **kwargs):
        super().__init__(master, **kwargs)
        self._on_file_selected = on_file_selected
        self._root_path = os.path.expanduser("~")
        self._build_ui()
        self._populate(self._root_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self, height=36, fg_color=("gray82", "gray18"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
                text=i18n.get("files_header"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray30", "gray80"),
        ).grid(row=0, column=0, padx=8, pady=6, sticky="w")

        ctk.CTkButton(
            header,
            text="↑",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._go_up,
        ).grid(row=0, column=1, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text="⟳",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: self._populate(self._root_path),
        ).grid(row=0, column=2, padx=(0, 6), pady=6)

        # Current path label
        self.path_label = ctk.CTkLabel(
            self,
            text=self._root_path,
            font=ctk.CTkFont(family="monospace", size=9),
            text_color=("gray50", "gray60"),
            anchor="w",
            wraplength=180,
        )
        self.path_label.grid(row=1, column=0, padx=8, pady=(2, 0), sticky="ew")

        # Tree frame (using plain tk.Listbox for simplicity and speed)
        tree_outer = ctk.CTkFrame(self, fg_color=("gray94", "#0d1117"))
        tree_outer.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        tree_outer.grid_rowconfigure(0, weight=1)
        tree_outer.grid_columnconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            tree_outer,
            selectmode="single",
            font=("monospace", 11),
            bg="#0d1117",
            fg="#d0d0d0",
            selectbackground="#264f78",
            selectforeground="white",
            relief="flat",
            bd=0,
            activestyle="none",
            highlightthickness=0,
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.listbox.bind("<Double-Button-1>", self._on_double_click)
        self.listbox.bind("<Return>", self._on_double_click)

        sb = ctk.CTkScrollbar(tree_outer, command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=sb.set)

        self._entries: list[str] = []  # full paths parallel to listbox items

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _populate(self, path: str) -> None:
        self._root_path = path
        self.path_label.configure(text=path)
        self.listbox.delete(0, "end")
        self._entries = []

        try:
            raw = sorted(os.listdir(path), key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower()))
        except PermissionError:
            self.listbox.insert("end", "[Permission denied]")
            return

        for name in raw:
            full = os.path.join(path, name)
            icon = "📁 " if os.path.isdir(full) else "📄 "
            self.listbox.insert("end", f"{icon}{name}")
            self._entries.append(full)

    def _go_up(self) -> None:
        parent = os.path.dirname(self._root_path)
        if parent and parent != self._root_path:
            self._populate(parent)

    def navigate_to(self, path: str) -> None:
        """Navigate the browser to *path* (called externally when cwd changes)."""
        target = path if os.path.isdir(path) else os.path.dirname(path)
        self._populate(target)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_double_click(self, _event=None) -> None:
        idx = self.listbox.curselection()
        if not idx:
            return
        full_path = self._entries[idx[0]]
        if os.path.isdir(full_path):
            self._populate(full_path)
        else:
            self._on_file_selected(full_path)
