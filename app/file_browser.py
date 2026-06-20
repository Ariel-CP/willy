"""
file_browser.py — Sidebar with a simple filesystem tree viewer.
Clicking a file sends its path to the chat panel.
"""

import os
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk
from typing import Callable
from app import i18n
from app.new_project_dialog import NewProjectDialog


class FileBrowser(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_file_selected: Callable[[str], None],
        on_new_project: Callable[[str], None] | None = None,
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._on_file_selected = on_file_selected
        self._on_new_project = on_new_project
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
            text="＋",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("#16a34a", "#15803d"),
            hover_color=("#15803d", "#166534"),
            command=self._open_new_project_dialog,
        ).grid(row=0, column=1, padx=(0, 2), pady=6)

        ctk.CTkButton(
            header,
            text="↑",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._go_up,
        ).grid(row=0, column=2, padx=(0, 2), pady=6)

        ctk.CTkButton(
            header,
            text="⟳",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: self._populate(self._root_path),
        ).grid(row=0, column=3, padx=(0, 6), pady=6)

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

        # Tree frame
        tree_outer = ctk.CTkFrame(self, fg_color=("gray94", "#0d1117"))
        tree_outer.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        tree_outer.grid_rowconfigure(0, weight=1)
        tree_outer.grid_columnconfigure(0, weight=1)

        self.tree = tk.ttk.Treeview(tree_outer, selectmode="browse")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        y_scroll = tk.Scrollbar(tree_outer, orient="vertical", command=self.tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = tk.Scrollbar(tree_outer, orient="horizontal", command=self.tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Crear carpeta", command=self._create_folder)
        self._menu.add_command(label="Mover", command=self._move_selected)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _populate(self, path: str) -> None:
        self._root_path = path
        self.path_label.configure(text=path)
        self.tree.delete(*self.tree.get_children())
        root_id = self.tree.insert("", "end", text=path, values=(path,), open=True)
        self._populate_children(root_id, path)

    def _populate_children(self, node_id: str, path: str) -> None:
        self.tree.delete(*self.tree.get_children(node_id))
        try:
            names = sorted(
                os.listdir(path),
                key=lambda n: (not os.path.isdir(os.path.join(path, n)), n.lower()),
            )
        except (PermissionError, FileNotFoundError):
            return

        for name in names:
            full = os.path.join(path, name)
            icon = "[DIR]" if os.path.isdir(full) else "[FILE]"
            child_id = self.tree.insert(node_id, "end", text=f"{icon} {name}", values=(full,))
            if os.path.isdir(full):
                # Placeholder for lazy loading
                self.tree.insert(child_id, "end", text="...")

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

    def _on_tree_open(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        node_id = selected[0]
        values = self.tree.item(node_id, "values")
        if not values:
            return
        full_path = values[0]
        if os.path.isdir(full_path):
            self._populate_children(node_id, full_path)

    def _on_double_click(self, _event=None) -> None:
        selected_item = self.tree.selection()
        if not selected_item:
            return
        values = self.tree.item(selected_item[0], "values")
        if not values:
            return
        full_path = values[0]
        if os.path.isdir(full_path):
            self._populate(full_path)
        else:
            self._on_file_selected(full_path)

    def _on_right_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
        self._menu.post(event.x_root, event.y_root)

    def _selected_path(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return values[0] if values else None

    def _open_new_project_dialog(self) -> None:
        NewProjectDialog(
            self,
            initial_dir=self._root_path,
            on_created=self._on_project_created,
        )

    def _on_project_created(self, project_path: str) -> None:
        """Navega al proyecto recién creado y notifica al callback externo."""
        self._populate(project_path)
        if self._on_new_project:
            self._on_new_project(project_path)

    def _create_folder(self) -> None:
        base = self._selected_path() or self._root_path
        if os.path.isfile(base):
            base = os.path.dirname(base)

        name = simpledialog.askstring("Crear carpeta", "Nombre de la carpeta:", parent=self)
        if not name:
            return

        target = os.path.join(base, name)
        try:
            os.makedirs(target, exist_ok=False)
            self._populate(self._root_path)
        except FileExistsError:
            messagebox.showerror("Error", "Ya existe una carpeta o archivo con ese nombre.")
        except OSError as exc:
            messagebox.showerror("Error", f"No se pudo crear la carpeta: {exc}")

    def _move_selected(self) -> None:
        source = self._selected_path()
        if not source:
            messagebox.showinfo("Mover", "Selecciona un archivo o carpeta para mover.")
            return

        destination_dir = filedialog.askdirectory(initialdir=self._root_path, title="Mover a carpeta...")
        if not destination_dir:
            return

        destination = os.path.join(destination_dir, os.path.basename(source))
        if os.path.abspath(destination) == os.path.abspath(source):
            return

        if os.path.exists(destination):
            messagebox.showerror("Error", "Ya existe un elemento con ese nombre en el destino.")
            return

        try:
            shutil.move(source, destination)
            self._populate(self._root_path)
        except OSError as exc:
            messagebox.showerror("Error", f"No se pudo mover el elemento: {exc}")
