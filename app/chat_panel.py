"""
chat_panel.py — Left panel: chat history + input + confirmation dialogs.
"""

import tkinter as tk
import customtkinter as ctk
from typing import Callable
from app import i18n


# ---------------------------------------------------------------------------
# Confirmation dialog (modal)
# ---------------------------------------------------------------------------

class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, detail: str, callback: Callable[[bool], None]):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self._callback = callback

        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

        detail_box = ctk.CTkTextbox(
            self,
            height=120,
            width=420,
            font=ctk.CTkFont(family="monospace", size=11),
            fg_color=("gray90", "#161b22"),
            border_color=("gray70", "gray40"),
            border_width=1,
        )
        detail_box.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        detail_box.insert("0.0", detail)
        detail_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=(4, 16), sticky="e")

        ctk.CTkButton(
            btn_frame,
            text=i18n.get("confirm_cancel"),
            width=90,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._cancel,
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            btn_frame,
            text=i18n.get("confirm_ok"),
            width=90,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._confirm,
        ).pack(side="left")

        self._center()

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _confirm(self) -> None:
        self.grab_release()
        self.destroy()
        self._callback(True)

    def _cancel(self) -> None:
        self.grab_release()
        self.destroy()
        self._callback(False)


# ---------------------------------------------------------------------------
# Message bubble helpers
# ---------------------------------------------------------------------------

BUBBLE_STYLES = {
    "user":      {"bg": ("#dbeafe", "#1e3a5f"), "fg": ("#1e3a8a", "#93c5fd"), "align": "right"},
    "assistant": {"bg": ("#f0fdf4", "#14532d"), "fg": ("#166534", "#86efac"), "align": "left"},
    "error":     {"bg": ("#fee2e2", "#450a0a"), "fg": ("#991b1b", "#fca5a5"), "align": "left"},
    "system":    {"bg": ("#fefce8", "#3b2f04"), "fg": ("#713f12", "#fde68a"), "align": "left"},
}

CODE_BG = ("#e8e8e8", "#1e1e2e")
CODE_FG = ("#1a1a2e", "#cdd6f4")


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

class ChatPanel(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._send_callback: Callable[[str], None] | None = None
        self._tts_callback: Callable[[str], None] | None = None
        self._tts_on = False  # default, overwritten in _build_ui
        self._vol_callback: Callable[[float], None] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, height=36, fg_color=("gray85", "gray20"))
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text=i18n.get("chat_header"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("gray20", "#7ec8e3"),
        ).grid(row=0, column=0, padx=10, pady=6, sticky="w")

        self.status_label = ctk.CTkLabel(
            header,
            text="",
            font=ctk.CTkFont(size=10),
            text_color=("gray50", "gray60"),
            anchor="w",
        )
        self.status_label.grid(row=0, column=1, padx=4, pady=6, sticky="ew")

        ctk.CTkButton(
            header,
            text=i18n.get("new_chat_btn"),
            width=80,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._clear_chat,
        ).grid(row=0, column=2, padx=(0, 4), pady=6)

        self._fullscreen_btn = ctk.CTkButton(
            header,
            text="⤢",
            width=28,
            height=24,
            font=ctk.CTkFont(size=13),
            fg_color="transparent",
            hover_color=("gray70", "gray30"),
            command=self._toggle_fullscreen,
        )
        self._fullscreen_btn.grid(row=0, column=3, padx=(0, 4), pady=6)
        self._is_fullscreen = False

        self._tts_btn = ctk.CTkButton(
            header,
            text="VOZ",
            width=40,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._toggle_tts,
        )
        self._tts_btn.grid(row=0, column=4, padx=(0, 2), pady=6)
        self._tts_on = False

        self._vol_slider = ctk.CTkSlider(
            header,
            from_=0.05,
            to=1.0,
            width=80,
            height=14,
            command=self._on_volume_change,
        )
        self._vol_slider.set(0.35)
        self._vol_slider.grid(row=0, column=5, padx=(0, 8), pady=6)

        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=("gray96", "#0d1117"),
            scrollbar_button_color=("gray70", "gray35"),
        )
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self._msg_row = 0

        input_frame = ctk.CTkFrame(self, fg_color=("gray90", "gray15"), height=48)
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            input_frame,
            height=36,
            font=ctk.CTkFont(size=13),
            fg_color=("gray95", "#161b22"),
            border_color=("gray70", "gray30"),
            border_width=1,
            wrap="word",
        )
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
        self.input_box.bind("<Return>", self._on_return)
        self.input_box.bind("<Shift-Return>", lambda e: None)

        ctk.CTkButton(
            input_frame,
            text=i18n.get("send_btn"),
            width=70,
            height=36,
            font=ctk.CTkFont(size=13),
            command=self._send,
        ).grid(row=0, column=1, padx=(0, 8), pady=6)

    def set_send_callback(self, cb: Callable[[str], None]) -> None:
        self._send_callback = cb

    def set_tts_callback(self, cb: Callable[[str], None]) -> None:
        """Register callback that speaks a text string."""
        self._tts_callback = cb

    def set_volume_callback(self, cb: Callable[[float], None]) -> None:
        """Register callback to notify volume changes."""
        self._vol_callback = cb

    def add_message(self, role: str, text: str) -> None:
        """Add a chat bubble (thread-safe via after)."""
        self.after(0, self._add_bubble, role, text)
        if role == "assistant" and self._tts_on and callable(self._tts_callback):
            self.after(0, self._tts_callback, text)

    def set_status(self, text: str) -> None:
        self.after(0, self.status_label.configure, {"text": text})

    def show_confirm_dialog(self, title: str, detail: str, callback: Callable[[bool], None]) -> None:
        """Show a modal confirmation dialog (must be called from main thread via after)."""
        self.after(0, self._open_confirm_dialog, title, detail, callback)

    def _add_bubble(self, role: str, text: str) -> None:
        style = BUBBLE_STYLES.get(role, BUBBLE_STYLES["system"])
        is_right = style["align"] == "right"

        outer = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        outer.grid(row=self._msg_row, column=0, sticky="ew", padx=8, pady=4)
        outer.grid_columnconfigure(0, weight=1)
        self._msg_row += 1

        # Role label
        role_label = {"user": "Vos", "assistant": "Willy", "error": "Error", "system": "Sistema"}
        ctk.CTkLabel(
            outer,
            text=role_label.get(role, role),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray60"),
            anchor="e" if is_right else "w",
        ).grid(row=0, column=0, sticky="e" if is_right else "w", padx=4, pady=(0, 2))

        # Render segments: plain text and ```code``` blocks
        self._render_segments(outer, text, style, is_right)

        self.after(50, self._scroll_to_bottom)

    def _render_segments(self, parent, text: str, style: dict, is_right: bool) -> None:
        """Split text on ```fences``` and render plain + code segments."""
        import re
        parts = re.split(r"(```[\s\S]*?```)", text)
        row = 1
        for part in parts:
            if part.startswith("```") and part.endswith("```"):
                # Strip fences and optional language tag
                code = re.sub(r"^```[^\n]*\n?", "", part)
                code = re.sub(r"\n?```$", "", code)
                self._add_segment(parent, row, code, is_code=True)
            elif part.strip():
                self._add_segment(parent, row, part, style=style, is_right=is_right)
            row += 1

    def _add_segment(self, parent, row: int, text: str, style: dict = None,
                     is_right: bool = False, is_code: bool = False) -> None:
        font = ctk.CTkFont(family="monospace", size=12) if is_code else ctk.CTkFont(size=13)
        bg = CODE_BG if is_code else (style or BUBBLE_STYLES["system"])["bg"]
        fg = CODE_FG if is_code else (style or BUBBLE_STYLES["system"])["fg"]

        if is_code:
            lines = text.split("\n")
            height = max(32, min(len(lines) * 22 + 16, 600))
        else:
            # Estimación inicial: ~55 chars por línea visual a 13px
            estimated_lines = sum(
                max(1, (len(ln) + 54) // 55) for ln in text.split("\n")
            )
            height = max(40, min(estimated_lines * 22 + 20, 1200))

        box = ctk.CTkTextbox(
            parent,
            font=font,
            fg_color=bg,
            text_color=fg,
            border_width=1 if is_code else 0,
            border_color=("gray70", "gray40"),
            corner_radius=6,
            wrap="none" if is_code else "word",
            activate_scrollbars=is_code,
            height=height,
        )
        box.grid(row=row, column=0, sticky="ew", padx=(32 if is_right else 4, 4 if is_right else 32), pady=1)
        box.insert("0.0", text.strip("\n"))
        box.configure(state="disabled")

        if not is_code:
            # Auto-redimensionar con el conteo real de líneas visuales tras el render
            parent.after(20, lambda b=box: self._autosize_textbox(b))

    def _autosize_textbox(self, box: ctk.CTkTextbox) -> None:
        try:
            box.update_idletasks()
            display_lines = int(box._textbox.count("1.0", "end", "displaylines")[0])
            new_height = max(40, display_lines * 22 + 20)
            box.configure(height=new_height)
            self.after(10, self._scroll_to_bottom)
        except Exception:
            pass

    def _scroll_to_bottom(self) -> None:
        try:
            self.scroll_frame._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _send(self) -> None:
        text = self.input_box.get("0.0", "end").strip()
        if not text:
            return
        self.input_box.delete("0.0", "end")
        self._add_bubble("user", text)
        if self._send_callback:
            self._send_callback(text)

    def _on_return(self, event) -> str:
        if not (event.state & 0x1):
            self._send()
            return "break"
        return None

    def _clear_chat(self) -> None:
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._msg_row = 0
        self._add_bubble("system", i18n.get("chat_cleared"))

    def _on_volume_change(self, value: float) -> None:
        if callable(self._vol_callback):
            self._vol_callback(value)

    def _toggle_tts(self) -> None:
        self._tts_on = not self._tts_on
        self._tts_btn.configure(
            text="VOZ ON" if self._tts_on else "VOZ",
            fg_color=("#16a34a", "#15803d") if self._tts_on else ("gray70", "gray35"),
        )

    def _toggle_fullscreen(self) -> None:
        """Expand chat to full width hiding sidebar and terminal, or restore."""
        app = self.winfo_toplevel()
        if not self._is_fullscreen:
            # Hide sidebar (column 0) and terminal (column 2)
            for col, widget_attr in [(0, "file_browser"), (2, "terminal_panel")]:
                w = getattr(app, widget_attr, None)
                if w:
                    w.grid_remove()
            app.grid_columnconfigure(0, weight=0, minsize=0)
            app.grid_columnconfigure(2, weight=0, minsize=0)
            app.grid_columnconfigure(1, weight=1)
            self._fullscreen_btn.configure(text="⤡")
            self._is_fullscreen = True
        else:
            for widget_attr in ["file_browser", "terminal_panel"]:
                w = getattr(app, widget_attr, None)
                if w:
                    w.grid()
            app.grid_columnconfigure(0, weight=0)
            app.grid_columnconfigure(1, weight=1)
            app.grid_columnconfigure(2, weight=1)
            self._fullscreen_btn.configure(text="⤢")
            self._is_fullscreen = False

    def _open_confirm_dialog(self, title: str, detail: str, callback: Callable[[bool], None]) -> None:
        ConfirmDialog(self.winfo_toplevel(), title, detail, callback)
