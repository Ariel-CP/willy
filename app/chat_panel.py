"""
chat_panel.py — Left panel: chat history + input + confirmation dialogs.
"""

import logging
import tkinter as tk
import customtkinter as ctk
from typing import Callable
from app import i18n


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Confirmation dialog (modal)
# ---------------------------------------------------------------------------

class ConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, detail: str, callback: Callable[[bool], None]):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.minsize(520, 280)
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
            wrap="word",
        )
        detail_box.grid(row=1, column=0, padx=20, pady=8, sticky="ew")
        detail_box.insert("0.0", detail)
        detail_box.configure(state="disabled")

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=20, pady=(4, 16), sticky="ew")
        btn_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            btn_frame,
            text=i18n.get("confirm_cancel"),
            width=90,
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._cancel,
        ).grid(row=0, column=1, padx=(0, 8), sticky="e")

        ctk.CTkButton(
            btn_frame,
            text=i18n.get("confirm_ok"),
            width=90,
            fg_color="#16a34a",
            hover_color="#15803d",
            command=self._confirm,
        ).grid(row=0, column=2, sticky="e")

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
        self._send_callback: Callable[..., None] | None = None
        self._tts_callback: Callable[[str], None] | None = None
        self._tts_on = False  # default, overwritten in _build_ui
        self._vol_callback: Callable[[float], None] | None = None
        self._input_min_height = 36
        self._input_max_height = 220
        self._input_resize_after_id = None
        self._bubble_resize_after_id = None
        self._text_bubbles: list[ctk.CTkTextbox] = []
        self._last_chat_width = 0
        self._msg_row = 0
        self._is_fullscreen = False
        self._wheel_scroll_units = 6
        self._pending_scroll_job = None
        self._chat_mode_map = {
            i18n.get("chat_mode_ask"): "ask",
            i18n.get("chat_mode_plan"): "plan",
            i18n.get("chat_mode_agent"): "agent",
        }
        self._chat_mode_var = tk.StringVar(value=i18n.get("chat_mode_agent"))
        self._build_ui()

    def _get_scroll_canvas(self):
        """Return the internal canvas used by CTkScrollableFrame."""
        canvas = getattr(self.scroll_frame, "_parent_canvas", None)
        if canvas is not None:
            return canvas

        canvas = getattr(self.scroll_frame, "_canvas", None)
        if canvas is not None:
            return canvas

        for child in self.scroll_frame.winfo_children():
            if isinstance(child, tk.Canvas):
                return child
        return None

    def _bind_widget_scroll(self, widget) -> None:
        """Bind mouse wheel events so chat scroll works over message widgets."""
        if widget is None:
            return
        try:
            widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
            widget.bind("<Button-4>", self._on_mousewheel, add="+")
            widget.bind("<Button-5>", self._on_mousewheel, add="+")
        except Exception:
            pass

    def _on_mousewheel(self, event) -> str:
        canvas = self._get_scroll_canvas()
        if canvas is None:
            return "break"

        delta = getattr(event, "delta", 0)
        num = getattr(event, "num", None)

        if delta:
            units = -int(delta / 120)
            if units == 0:
                units = -1 if delta > 0 else 1
            canvas.yview_scroll(units * self._wheel_scroll_units, "units")
        elif num == 4:
            canvas.yview_scroll(-self._wheel_scroll_units, "units")
        elif num == 5:
            canvas.yview_scroll(self._wheel_scroll_units, "units")
        return "break"

    def _schedule_scroll_to_bottom(self) -> None:
        """Schedule a robust scroll-to-bottom after UI layout settles."""
        if self._pending_scroll_job is not None:
            try:
                self.after_cancel(self._pending_scroll_job)
            except Exception:
                pass

        def _run() -> None:
            self._pending_scroll_job = None
            self._scroll_to_bottom()
            # Run a second/third pass to catch late geometry updates.
            self.after(70, self._scroll_to_bottom)
            self.after(160, self._scroll_to_bottom)

        self._pending_scroll_job = self.after(10, _run)

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

        self.chat_mode_menu = ctk.CTkOptionMenu(
            header,
            values=list(self._chat_mode_map.keys()),
            variable=self._chat_mode_var,
            width=92,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            button_color=("gray65", "gray40"),
            button_hover_color=("gray60", "gray45"),
            dropdown_font=ctk.CTkFont(size=11),
        )
        self.chat_mode_menu.grid(row=0, column=2, padx=(0, 4), pady=6)

        ctk.CTkButton(
            header,
            text=i18n.get("new_chat_btn"),
            width=80,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color=("gray70", "gray35"),
            hover_color=("gray60", "gray45"),
            command=self._clear_chat,
        ).grid(row=0, column=3, padx=(0, 4), pady=6)

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
        self._fullscreen_btn.grid(row=0, column=4, padx=(0, 4), pady=6)

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
        self._tts_btn.grid(row=0, column=5, padx=(0, 2), pady=6)
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
        self._vol_slider.grid(row=0, column=6, padx=(0, 8), pady=6)

        self.scroll_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=("gray96", "#0d1117"),
            scrollbar_button_color=("gray70", "gray35"),
        )
        self.scroll_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self.scroll_frame.bind("<Configure>", self._on_chat_resized)
        self._bind_widget_scroll(self.scroll_frame)

        input_frame = ctk.CTkFrame(self, fg_color=("gray90", "gray15"))
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1)

        self.input_box = ctk.CTkTextbox(
            input_frame,
            height=self._input_min_height,
            font=ctk.CTkFont(size=13),
            fg_color=("gray95", "#161b22"),
            border_color=("gray70", "gray30"),
            border_width=1,
            wrap="word",
            activate_scrollbars=True,
        )
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=6)
        self.input_box.bind("<Return>", self._on_return)
        self.input_box.bind("<Shift-Return>", lambda e: None)
        self.input_box.bind("<KeyRelease>", self._on_input_changed)

        ctk.CTkButton(
            input_frame,
            text=i18n.get("send_btn"),
            width=70,
            height=36,
            font=ctk.CTkFont(size=13),
            command=self._send,
        ).grid(row=0, column=1, padx=(0, 8), pady=6)
        self._auto_resize_input_box()

    def set_send_callback(self, cb: Callable[..., None]) -> None:
        self._send_callback = cb

    def get_chat_mode(self) -> str:
        selected = (self._chat_mode_var.get() or "").strip()
        return self._chat_mode_map.get(selected, "agent")

    def set_tts_callback(self, cb: Callable[[str], None]) -> None:
        """Register callback that speaks a text string."""
        self._tts_callback = cb

    def set_volume_callback(self, cb: Callable[[float], None]) -> None:
        """Register callback to notify volume changes."""
        self._vol_callback = cb

    def add_message(self, role: str, text: str) -> None:
        """Add a chat bubble (thread-safe via after)."""
        safe_role = role if isinstance(role, str) else "system"
        safe_text = text if isinstance(text, str) else str(text)
        try:
            if not self.winfo_exists():
                return
            self.after(0, self._add_bubble, safe_role, safe_text)
        except Exception as exc:
            logger.debug("Skipping add_message because chat is closing: %s", exc)
            return
        if role == "assistant" and self._tts_on and callable(self._tts_callback):
            try:
                self.after(0, self._tts_callback, text)
            except Exception as exc:
                logger.debug("TTS callback skipped: %s", exc)

    def set_status(self, text: str) -> None:
        self.after(0, self.status_label.configure, {"text": text})

    def show_confirm_dialog(self, title: str, detail: str, callback: Callable[[bool], None]) -> None:
        """Show a modal confirmation dialog (must be called from main thread via after)."""
        self.after(0, self._open_confirm_dialog, title, detail, callback)

    def _add_bubble(self, role: str, text: str) -> None:
        try:
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
            self._bind_widget_scroll(outer)

            # Render segments: plain text and ```code``` blocks
            self._render_segments(outer, text, style, is_right)
            self.after(20, self._finalize_message_layout)
        except Exception as exc:
            logger.exception("Chat bubble render failed: %s", exc)
            self._add_fallback_bubble(role, text)

    def _add_fallback_bubble(self, role: str, text: str) -> None:
        """Safe fallback renderer used if rich bubble rendering fails."""
        style = BUBBLE_STYLES.get(role, BUBBLE_STYLES["system"])
        is_right = style.get("align") == "right"
        outer = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
        outer.grid(row=self._msg_row, column=0, sticky="ew", padx=8, pady=4)
        outer.grid_columnconfigure(0, weight=1)
        self._msg_row += 1

        role_label = {"user": "Vos", "assistant": "Willy", "error": "Error", "system": "Sistema"}
        ctk.CTkLabel(
            outer,
            text=role_label.get(role, role),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray50", "gray60"),
            anchor="e" if is_right else "w",
        ).grid(row=0, column=0, sticky="e" if is_right else "w", padx=4, pady=(0, 2))

        label = ctk.CTkLabel(
            outer,
            text=(text or "").strip() or "(sin contenido)",
            justify="left",
            anchor="w",
            corner_radius=6,
            fg_color=style["bg"],
            text_color=style["fg"],
            wraplength=max(260, self.scroll_frame.winfo_width() - 120),
            padx=10,
            pady=8,
        )
        label.grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(32 if is_right else 4, 4 if is_right else 32),
            pady=1,
        )
        self._bind_widget_scroll(outer)
        self._bind_widget_scroll(label)
        self._schedule_scroll_to_bottom()

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
        self._bind_widget_scroll(box)

        if not is_code:
            self._text_bubbles.append(box)
            parent.after(20, lambda b=box: self._autosize_textbox(b, scroll=False))

    def _autosize_textbox(self, box: ctk.CTkTextbox, scroll: bool = False) -> None:
        try:
            if not box.winfo_exists():
                return
            box.update_idletasks()
            display_lines = int(box._textbox.count("1.0", "end", "displaylines")[0])
            new_height = max(40, display_lines * 22 + 20)
            box.configure(height=new_height)
            if scroll:
                self.after(10, self._scroll_to_bottom)
        except AttributeError as exc:
            logger.warning("Chat autosize unavailable: %s", exc)
        except Exception as exc:
            logger.debug("Chat autosize skipped: %s", exc)

    def _finalize_message_layout(self) -> None:
        self._autosize_visible_bubbles(limit_to_recent=True)
        self._schedule_scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        try:
            canvas = self._get_scroll_canvas()
            if canvas is None:
                logger.debug("Chat scroll canvas not available")
                return
            canvas.update_idletasks()
            try:
                region = canvas.bbox("all")
                if region is not None:
                    canvas.configure(scrollregion=region)
            except Exception:
                pass
            canvas.yview_moveto(1.0)
        except Exception as exc:
            logger.debug("Chat scroll skipped: %s", exc)

    def _on_chat_resized(self, _event=None) -> None:
        width = self.scroll_frame.winfo_width()
        if width <= 1 or width == self._last_chat_width:
            return
        self._last_chat_width = width
        if self._bubble_resize_after_id is not None:
            try:
                self.after_cancel(self._bubble_resize_after_id)
            except Exception:
                pass
        self._bubble_resize_after_id = self.after(40, self._autosize_visible_bubbles)

    def _autosize_visible_bubbles(self, limit_to_recent: bool = False) -> None:
        self._bubble_resize_after_id = None
        try:
            self._text_bubbles = [box for box in self._text_bubbles if box.winfo_exists()]
            bubbles = self._text_bubbles[-6:] if limit_to_recent else self._text_bubbles
            for box in list(bubbles):
                self._autosize_textbox(box, scroll=False)
        except Exception as exc:
            logger.debug("Chat bubble resize skipped: %s", exc)

    def _send(self) -> None:
        text = self.input_box.get("0.0", "end").strip()
        if not text:
            return
        self.input_box.delete("0.0", "end")
        self._auto_resize_input_box(force_min=True)
        self._add_bubble("user", text)
        if self._send_callback:
            mode = self.get_chat_mode()
            try:
                self._send_callback(text, mode)
            except TypeError:
                # Backward compatibility with legacy callback signature.
                try:
                    self._send_callback(text)
                except Exception as exc:
                    logger.exception("Send callback failed (legacy signature): %s", exc)
                    self._add_bubble("error", "No se pudo enviar al agente. Reintenta.")
            except Exception as exc:
                logger.exception("Send callback failed: %s", exc)
                self._add_bubble("error", "No se pudo enviar al agente. Reintenta.")

    def _on_return(self, event) -> str:
        if not (event.state & 0x1):
            self._send()
            return "break"
        return None

    def _on_input_changed(self, _event=None) -> None:
        if self._input_resize_after_id is not None:
            try:
                self.after_cancel(self._input_resize_after_id)
            except Exception:
                pass
            self._input_resize_after_id = None
        self._input_resize_after_id = self.after(16, self._auto_resize_input_box)

    def _auto_resize_input_box(self, force_min: bool = False) -> None:
        try:
            if force_min:
                target = self._input_min_height
            else:
                self.input_box.update_idletasks()
                display_lines = int(
                    self.input_box._textbox.count(
                        "1.0",
                        "end-1c",
                        "displaylines",
                    )[0]
                )
                if display_lines < 1:
                    display_lines = 1
                target = max(
                    self._input_min_height,
                    min(self._input_max_height, display_lines * 22 + 12),
                )

            current = int(self.input_box.cget("height"))
            if current != target:
                self.input_box.configure(height=target)
            self.input_box._textbox.see("insert")
        except Exception:
            pass

    def _clear_chat(self) -> None:
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self._text_bubbles.clear()
        self._last_chat_width = 0
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
