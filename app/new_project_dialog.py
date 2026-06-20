"""
new_project_dialog.py — Diálogo para crear un nuevo proyecto.

Permite:
  - Elegir un nombre de proyecto.
  - Seleccionar la carpeta de destino desde un explorador de archivos.
  - Acceso rápido a pen drives y unidades de red detectados.
  - Elegir una plantilla básica (Arduino, PlatformIO, Python, Vacío).
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk


# ---------------------------------------------------------------------------
# Detección de unidades externas / de red
# ---------------------------------------------------------------------------

def _detect_drives() -> list[tuple[str, str, str]]:
    """
    Devuelve lista de (tipo, etiqueta, ruta_completa).
    tipo puede ser "USB" o "Red".
    """
    drives: list[tuple[str, str, str]] = []

    # --- Pen drives / USB (Linux) ---
    user = os.environ.get("USER", "")
    media_roots = [
        f"/run/media/{user}",
        f"/media/{user}",
        "/media",
        "/run/media",
    ]
    seen: set[str] = set()
    for media_dir in media_roots:
        if not os.path.isdir(media_dir):
            continue
        try:
            for name in os.listdir(media_dir):
                full = os.path.join(media_dir, name)
                real = os.path.realpath(full)
                if real in seen:
                    continue
                if os.path.isdir(full) and os.path.ismount(full):
                    seen.add(real)
                    drives.append(("USB", name or media_dir, full))
        except PermissionError:
            pass

    # --- Unidades de red / mounts en /mnt ---
    if os.path.isdir("/mnt"):
        try:
            for name in os.listdir("/mnt"):
                full = os.path.join("/mnt", name)
                real = os.path.realpath(full)
                if real in seen:
                    continue
                if os.path.isdir(full) and os.path.ismount(full):
                    seen.add(real)
                    drives.append(("Red", name, full))
        except PermissionError:
            pass

    return drives


# ---------------------------------------------------------------------------
# Plantillas de proyecto
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict] = {
    "Vacío": {
        "description": "Solo la carpeta del proyecto.",
        "files": [
            ("diagrams/.gitkeep", ""),
        ],
    },
    "Arduino (.ino)": {
        "description": "Sketch básico de Arduino IDE.",
        "files": [
            ("{name}/{name}.ino", "void setup() {{\n  // inicialización\n}}\n\nvoid loop() {{\n  // lógica principal\n}}\n"),
            ("diagrams/.gitkeep", ""),
        ],
    },
    "PlatformIO": {
        "description": "Proyecto PlatformIO con src/ y platformio.ini.",
        "files": [
            ("platformio.ini", "[env:uno]\nplatform = atmelavr\nboard = uno\nframework = arduino\n"),
            ("src/main.cpp", '#include <Arduino.h>\n\nvoid setup() {{\n  Serial.begin(115200);\n}}\n\nvoid loop() {{\n}}\n'),
            ("include/README", "Put project header files here.\n"),
            ("lib/README", "Put project libraries here.\n"),
            ("test/README", "Put project tests here.\n"),
            ("diagrams/.gitkeep", ""),
        ],
    },
    "Python": {
        "description": "Script Python con requirements.txt.",
        "files": [
            ("main.py", "# Proyecto: {name}\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"),
            ("requirements.txt", "# dependencias\n"),
            ("diagrams/.gitkeep", ""),
        ],
    },
}


# ---------------------------------------------------------------------------
# Diálogo principal
# ---------------------------------------------------------------------------

class NewProjectDialog(ctk.CTkToplevel):
    """
    Diálogo modal para crear un nuevo proyecto.

    Args:
        master: ventana padre.
        initial_dir: directorio inicial para el explorador.
        on_created: callback(project_path: str) llamado al crear el proyecto.
    """

    def __init__(
        self,
        master,
        initial_dir: str = "~",
        on_created: Callable[[str], None] | None = None,
    ):
        super().__init__(master)
        self.title("Nuevo proyecto")
        self.resizable(False, False)
        self._on_created = on_created
        self._dest_var = ctk.StringVar(value=os.path.expanduser(initial_dir))
        self._name_var = ctk.StringVar()
        self._template_var = ctk.StringVar(value=list(TEMPLATES.keys())[0])
        self._drives: list[tuple[str, str, str]] = []

        self._build_ui()
        self.after(80, self._safe_grab)
        self.after(120, self._refresh_drives)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        # --- Título ---
        ctk.CTkLabel(
            self,
            text="Nuevo proyecto",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 4), sticky="ew")

        # --- Nombre del proyecto ---
        ctk.CTkLabel(self, text="Nombre del proyecto", anchor="w").grid(
            row=1, column=0, columnspan=2, padx=20, pady=(8, 2), sticky="w"
        )
        self._name_entry = ctk.CTkEntry(
            self,
            width=420,
            textvariable=self._name_var,
            placeholder_text="mi_proyecto",
        )
        self._name_entry.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="ew")

        # --- Destino ---
        ctk.CTkLabel(self, text="Carpeta de destino", anchor="w").grid(
            row=3, column=0, columnspan=2, padx=20, pady=(8, 2), sticky="w"
        )

        dest_row = ctk.CTkFrame(self, fg_color="transparent")
        dest_row.grid(row=4, column=0, columnspan=2, padx=20, pady=(0, 4), sticky="ew")
        dest_row.grid_columnconfigure(0, weight=1)

        self._dest_entry = ctk.CTkEntry(
            dest_row,
            textvariable=self._dest_var,
            placeholder_text="/home/usuario/proyectos",
        )
        self._dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            dest_row,
            text="Explorar...",
            width=100,
            height=28,
            command=self._browse_dest,
        ).grid(row=0, column=1, sticky="e")

        # --- Acceso rápido a drives ---
        ctk.CTkLabel(
            self,
            text="Acceso rápido",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray40", "gray65"),
            anchor="w",
        ).grid(row=5, column=0, columnspan=2, padx=20, pady=(10, 2), sticky="w")

        self._drives_frame = ctk.CTkFrame(self, fg_color=("gray90", "#161b22"), corner_radius=6)
        self._drives_frame.grid(row=6, column=0, columnspan=2, padx=20, pady=(0, 8), sticky="ew")
        self._drives_frame.grid_columnconfigure(0, weight=1)

        self._drives_placeholder = ctk.CTkLabel(
            self._drives_frame,
            text="Buscando unidades externas...",
            text_color=("gray50", "gray60"),
            font=ctk.CTkFont(size=10),
        )
        self._drives_placeholder.grid(row=0, column=0, padx=10, pady=8)

        # --- Plantilla ---
        ctk.CTkLabel(self, text="Plantilla", anchor="w").grid(
            row=7, column=0, columnspan=2, padx=20, pady=(4, 2), sticky="w"
        )

        self._template_menu = ctk.CTkOptionMenu(
            self,
            variable=self._template_var,
            values=list(TEMPLATES.keys()),
            width=220,
            command=self._on_template_change,
        )
        self._template_menu.grid(row=8, column=0, padx=20, pady=(0, 2), sticky="w")

        self._template_desc = ctk.CTkLabel(
            self,
            text=TEMPLATES[self._template_var.get()]["description"],
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray60"),
            anchor="w",
        )
        self._template_desc.grid(row=9, column=0, columnspan=2, padx=22, pady=(0, 8), sticky="w")

        # --- Vista previa del path final ---
        self._preview_label = ctk.CTkLabel(
            self,
            text="",
            font=ctk.CTkFont(family="monospace", size=10),
            text_color=("gray45", "#7ec8e3"),
            anchor="w",
            wraplength=420,
        )
        self._preview_label.grid(row=10, column=0, columnspan=2, padx=20, pady=(0, 8), sticky="ew")

        self._name_var.trace_add("write", lambda *_: self._update_preview())
        self._dest_var.trace_add("write", lambda *_: self._update_preview())
        self._update_preview()

        # --- Botones ---
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=11, column=0, columnspan=2, padx=20, pady=(4, 16), sticky="e")

        ctk.CTkButton(
            btn_row,
            text="Cancelar",
            width=90,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self.destroy,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Crear proyecto",
            width=130,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._create,
        ).pack(side="left")

        self._name_entry.focus()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except Exception:
            pass

    def _on_template_change(self, value: str) -> None:
        self._template_desc.configure(text=TEMPLATES[value]["description"])

    def _update_preview(self) -> None:
        name = self._name_var.get().strip()
        dest = self._dest_var.get().strip()
        if name and dest:
            full = os.path.join(dest, name)
            self._preview_label.configure(text=f"→ {full}")
        else:
            self._preview_label.configure(text="")

    def _browse_dest(self) -> None:
        current = self._dest_var.get().strip()
        initial = current if os.path.isdir(current) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(
            parent=self,
            title="Seleccionar carpeta de destino",
            initialdir=initial,
        )
        if chosen:
            self._dest_var.set(chosen)

    def _refresh_drives(self) -> None:
        """Detecta drives y actualiza el panel de acceso rápido."""
        self._drives = _detect_drives()

        # Limpiar placeholder
        for w in self._drives_frame.winfo_children():
            w.destroy()

        # Agregar botón "Inicio" siempre
        home = os.path.expanduser("~")
        shortcuts = [("🏠", "Inicio", home)] + [
            ("💾" if t == "USB" else "🌐", label, path)
            for t, label, path in self._drives
        ]

        if len(shortcuts) == 1:
            ctk.CTkLabel(
                self._drives_frame,
                text="No se detectaron pen drives ni unidades de red.",
                text_color=("gray50", "gray60"),
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=0, padx=10, pady=6)
            return

        col = 0
        for icon, label, path in shortcuts:
            short_label = label[:14] + "…" if len(label) > 14 else label
            btn = ctk.CTkButton(
                self._drives_frame,
                text=f"{icon} {short_label}",
                width=110,
                height=28,
                font=ctk.CTkFont(size=10),
                fg_color=("gray80", "#1f2937"),
                hover_color=("gray70", "#374151"),
                text_color=("gray20", "gray85"),
                command=lambda p=path: self._dest_var.set(p),
            )
            btn.grid(row=0, column=col, padx=4, pady=6)
            col += 1

    # ------------------------------------------------------------------
    # Acción principal
    # ------------------------------------------------------------------

    def _create(self) -> None:
        name = self._name_var.get().strip()
        dest = self._dest_var.get().strip()
        template_key = self._template_var.get()

        if not name:
            messagebox.showerror("Error", "Ingresá un nombre para el proyecto.", parent=self)
            return

        # Validar caracteres del nombre
        invalid = set(name) & set(r'\/:*?"<>|')
        if invalid:
            messagebox.showerror(
                "Error",
                f"El nombre contiene caracteres no válidos: {' '.join(invalid)}",
                parent=self,
            )
            return

        if not dest or not os.path.isdir(dest):
            messagebox.showerror(
                "Error",
                f"La carpeta de destino no existe o no es accesible:\n{dest}",
                parent=self,
            )
            return

        project_path = os.path.join(dest, name)

        if os.path.exists(project_path):
            messagebox.showerror(
                "Error",
                f"Ya existe un elemento con ese nombre en el destino:\n{project_path}",
                parent=self,
            )
            return

        # Crear directorio y archivos de plantilla
        try:
            os.makedirs(project_path, exist_ok=False)
            template = TEMPLATES[template_key]
            for rel_path_tpl, content_tpl in template["files"]:
                rel_path = rel_path_tpl.format(name=name)
                content = content_tpl.format(name=name)
                full_file = os.path.join(project_path, rel_path)
                os.makedirs(os.path.dirname(full_file), exist_ok=True)
                with open(full_file, "w", encoding="utf-8") as fh:
                    fh.write(content)
        except OSError as exc:
            messagebox.showerror("Error al crear el proyecto", str(exc), parent=self)
            return

        self.destroy()

        if self._on_created:
            self._on_created(project_path)
