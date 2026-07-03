"""
file_browser.py — Sidebar with a simple filesystem tree viewer.
Clicking a file sends its path to the chat panel.
"""

import os
import shutil
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk
from typing import Callable
from app import i18n


class FileBrowser(ctk.CTkFrame):
    def __init__(
        self,
        master,
        on_file_selected: Callable[[str], None],
        on_open_folder: Callable[[], None] | None = None,
        on_new_project: Callable[[], None] | None = None,
        on_open_recent_projects: Callable[[], None] | None = None,
        initial_path: str = "~",
        **kwargs,
    ):
        super().__init__(master, **kwargs)
        self._on_file_selected = on_file_selected
        self._on_open_folder = on_open_folder
        self._on_new_project = on_new_project
        self._on_open_recent_projects = on_open_recent_projects
        self._tree_style_name = "Willy.Treeview"
        self._v_scroll_style_name = "Willy.Tree.Vertical.TScrollbar"
        self._h_scroll_style_name = "Willy.Tree.Horizontal.TScrollbar"
        self._tree_min_content_width = 180
        self._tree_max_content_width = 300
        self._tree_content_width = self._tree_min_content_width
        self._tree_text_font = tkfont.Font(family="Segoe UI", size=11)
        candidate = os.path.expanduser(initial_path)
        if os.path.isdir(candidate):
            self._root_path = candidate
        else:
            self._root_path = os.path.expanduser("~")
        self._build_ui()
        self._populate(self._root_path)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._configure_tree_style()

        # Header
        header = ctk.CTkFrame(self, height=36, fg_color=("gray85", "gray20"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text=i18n.get("files_header"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
        ).grid(row=0, column=0, padx=8, pady=6, sticky="w")

        ctk.CTkButton(
            header,
            text=i18n.get("open_folder_btn"),
            width=44,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._handle_open_folder,
        ).grid(row=0, column=1, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text=i18n.get("new_project_btn"),
            width=44,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._handle_new_project,
        ).grid(row=0, column=2, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text=i18n.get("recent_projects_btn"),
            width=58,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._handle_open_recent_projects,
        ).grid(row=0, column=3, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text="↑",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._go_up,
        ).grid(row=0, column=4, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text="⟳",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=lambda: self._populate(self._root_path),
        ).grid(row=0, column=5, padx=(0, 6), pady=6)

        # Current path label
        self.path_label = ctk.CTkLabel(
            self,
            text=self._root_path,
            font=ctk.CTkFont(family="monospace", size=9),
            text_color=("gray45", "#8b949e"),
            anchor="w",
            wraplength=180,
        )
        self.path_label.grid(row=1, column=0, padx=8, pady=(2, 0), sticky="ew")

        # Tree frame
        tree_outer = ctk.CTkFrame(self, fg_color=("gray96", "#0d1117"))
        tree_outer.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        tree_outer.grid_rowconfigure(0, weight=1)
        tree_outer.grid_columnconfigure(0, weight=1)

        self.tree = tk.ttk.Treeview(
            tree_outer,
            selectmode="browse",
            style=self._tree_style_name,
        )
        self.tree.column("#0", anchor="w", stretch=False, width=self._tree_content_width)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)

        y_scroll = ttk.Scrollbar(
            tree_outer,
            orient="vertical",
            command=self.tree.yview,
            style=self._v_scroll_style_name,
        )
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(
            tree_outer,
            orient="horizontal",
            command=self.tree.xview,
            style=self._h_scroll_style_name,
        )
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.bind("<MouseWheel>", self._on_mousewheel)
        self.tree.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.tree.bind("<Button-4>", self._on_mousewheel)
        self.tree.bind("<Button-5>", self._on_mousewheel)

        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Crear carpeta", command=self._create_folder)
        self._menu.add_command(label="Mover", command=self._move_selected)

    def _configure_tree_style(self) -> None:
        """Match FileBrowser visuals to ChatPanel color language."""
        appearance = ctk.get_appearance_mode().lower()
        dark_mode = appearance == "dark"
        style = ttk.Style(self)

        # On Windows, native themes like "vista" ignore many Treeview color
        # overrides. "clam" applies custom colors consistently.
        if os.name == "nt" and style.theme_use() in {"vista", "xpnative"}:
            style.theme_use("clam")

        if dark_mode:
            bg = "#0d1117"
            fg = "#c9d1d9"
            field_bg = "#0d1117"
            selected_bg = "#1f6feb"
            selected_fg = "#f0f6fc"
            scroll_bg = "#0d1117"
            scroll_trough = "#161b22"
        else:
            bg = "#f5f7fb"
            fg = "#1f2937"
            field_bg = "#f5f7fb"
            selected_bg = "#bfdbfe"
            selected_fg = "#0b2545"
            scroll_bg = "#d1d5db"
            scroll_trough = "#eef2f7"

        style.configure(
            self._tree_style_name,
            background=bg,
            foreground=fg,
            fieldbackground=field_bg,
            rowheight=26,
            font=self._tree_text_font,
        )
        style.map(
            self._tree_style_name,
            background=[("selected", selected_bg)],
            foreground=[("selected", selected_fg)],
        )
        style.layout(
            self._tree_style_name,
            [("Treeview.treearea", {"sticky": "nswe"})],
        )
        style.configure(
            self._v_scroll_style_name,
            background=scroll_bg,
            troughcolor=scroll_trough,
            bordercolor=scroll_trough,
            arrowcolor=fg,
        )
        style.configure(
            self._h_scroll_style_name,
            background=scroll_bg,
            troughcolor=scroll_trough,
            bordercolor=scroll_trough,
            arrowcolor=fg,
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _populate(self, path: str) -> None:
        self._root_path = path
        self.path_label.configure(text=path)
        self.tree.delete(*self.tree.get_children())
        root_id = self.tree.insert("", "end", text=path, values=(path,), open=True)
        self._reset_tree_width(path)
        self._populate_children(root_id, path)

    def _populate_children(self, node_id: str, path: str) -> None:
        self.tree.delete(*self.tree.get_children(node_id))
        depth = self._node_depth(node_id) + 1
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
            label = f"{icon} {name}"
            self._grow_tree_width(label, depth)
            child_id = self.tree.insert(node_id, "end", text=label, values=(full,))
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

    def current_root_path(self) -> str:
        return self._root_path

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

    def _handle_open_folder(self) -> None:
        if callable(self._on_open_folder):
            self._on_open_folder()

    def _handle_new_project(self) -> None:
        if callable(self._on_new_project):
            self._on_new_project()

    def _handle_open_recent_projects(self) -> None:
        if callable(self._on_open_recent_projects):
            self._on_open_recent_projects()

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

    def _on_mousewheel(self, event) -> str:
        """Scroll vertically with wheel on Windows/macOS/Linux."""
        if getattr(event, "state", 0) & 0x0001:
            return self._on_shift_mousewheel(event)

        if hasattr(event, "num") and event.num in (4, 5):
            delta = -1 if event.num == 4 else 1
        else:
            raw_delta = getattr(event, "delta", 0)
            steps = max(1, abs(raw_delta) // 120) if raw_delta else 1
            delta = -steps if raw_delta > 0 else steps
        self.tree.yview_scroll(delta, "units")
        return "break"

    def _on_shift_mousewheel(self, event) -> str:
        """Scroll horizontally with Shift + wheel."""
        raw_delta = getattr(event, "delta", 0)
        steps = max(1, abs(raw_delta) // 120) if raw_delta else 1
        delta = -steps if raw_delta > 0 else steps
        self.tree.xview_scroll(delta, "units")
        return "break"

    def _node_depth(self, node_id: str) -> int:
        depth = -1
        current = node_id
        while current:
            depth += 1
            current = self.tree.parent(current)
        return max(depth, 0)

    def _reset_tree_width(self, root_text: str) -> None:
        root_width = self._tree_text_font.measure(root_text) + 40
        self._tree_content_width = min(
            self._tree_max_content_width,
            max(self._tree_min_content_width, root_width),
        )
        self.tree.column("#0", width=self._tree_content_width)

    def _grow_tree_width(self, text: str, depth: int) -> None:
        required = self._tree_text_font.measure(text) + 44 + (depth * 22)
        if required > self._tree_content_width:
            self._tree_content_width = min(required, self._tree_max_content_width)
            self.tree.column("#0", width=self._tree_content_width)

    def _selected_path(self) -> str | None:
        selected = self.tree.selection()
        if not selected:
            return None
        values = self.tree.item(selected[0], "values")
        return values[0] if values else None

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
