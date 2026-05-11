import math
import customtkinter as ctk
import tkinter as tk
import random

class ClippyWidget(ctk.CTkFrame):
    """
    Un widget animado tipo "Clippy": una cara simple con ojos y boca animados.
    Mejoras: Frequency bands, enhanced expressions, phoneme detection.
    """
    def __init__(self, master=None, size=80, **kwargs):
        super().__init__(master, width=size, height=size, fg_color=("#f0f0f0", "#222"), corner_radius=16, **kwargs)
        self.size = size
        self.canvas = tk.Canvas(self, width=size, height=size, bg="#fffdf8", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.eyes_open = True
        self.mouth_smile = True
        self._speaking = False
        self._spectrum_phase = 0
        self._spectrum_level = 0.0
        self._spectrum_bands = {"low": 0.0, "mid": 0.0, "high": 0.0}
        self._saved_face_state = None
        
        # Enhanced expressions
        self._head_tilt = 0.0  # -1.0 to 1.0 (left to right)
        self._eyebrow_height = 0.0  # 0.0 to 1.0
        self._blink_counter = 0
        self._rhythm_counter = 0  # For synchronized animations
        
        # Phoneme detection
        self._current_phoneme = "neutral"
        self._phoneme_history = []
        self._max_history = 5

        # Modo ultra amable: expresiones calmadas y sin señales negativas.
        self._ultra_friendly_mode = True

        # Perfil visual amigable para adultos mayores.
        self._palette = {
            "face": "#ffeaa7",
            "face_outline": "#d9bd70",
            "eye": "#2d3436",
            "eye_shine": "#ffffff",
            "eyebrow": "#8d6e63",
            "mouth": "#2d3436",
            "band_low": "#f4a261",
            "band_mid": "#2a9d8f",
            "band_high": "#90caf9",
        }
        self._idle_blink_probability = 0.07
        
        self._draw_face()
        self._animate()

    def _draw_face(self):
        s = self.size
        self.canvas.delete("all")
        
        # Apply head tilt transformation
        offset_x = self._head_tilt * s * 0.15
        
        # Cara (círculo con leve inclinación)
        self.canvas.create_oval(5 + offset_x, 5, s-5 + offset_x, s-5, fill=self._palette["face"], outline=self._palette["face_outline"], width=2)
        
        # Cejas dinámicas
        eyebrow_lift = self._eyebrow_height * s * 0.08
        left_brow_y = s * 0.28 - eyebrow_lift
        right_brow_y = s * 0.28 - eyebrow_lift
        self.canvas.create_line(s*0.22 + offset_x, left_brow_y, s*0.42 + offset_x, left_brow_y - eyebrow_lift*0.5, 
                    fill=self._palette["eyebrow"], width=2)
        self.canvas.create_line(s*0.58 + offset_x, right_brow_y - eyebrow_lift*0.5, s*0.78 + offset_x, right_brow_y, 
                    fill=self._palette["eyebrow"], width=2)
        
        # Ojos
        if self.eyes_open:
            # Ojos abiertos con leve movimiento basado en energía
            eye_offset_y = self._spectrum_bands.get("mid", 0.0) * s * 0.02
            self.canvas.create_oval(s*0.26 + offset_x, s*0.37 + eye_offset_y, s*0.40 + offset_x, s*0.56 + eye_offset_y, 
                                    fill=self._palette["eye"], outline="")
            self.canvas.create_oval(s*0.60 + offset_x, s*0.37 + eye_offset_y, s*0.74 + offset_x, s*0.56 + eye_offset_y, 
                                    fill=self._palette["eye"], outline="")
            # Shine/pupilas
            self.canvas.create_oval(s*0.31 + offset_x, s*0.42 + eye_offset_y, s*0.35 + offset_x, s*0.46 + eye_offset_y, 
                                    fill=self._palette["eye_shine"], outline="")
            self.canvas.create_oval(s*0.65 + offset_x, s*0.42 + eye_offset_y, s*0.69 + offset_x, s*0.46 + eye_offset_y, 
                                    fill=self._palette["eye_shine"], outline="")
        else:
            # Ojos cerrados (líneas suaves)
            self.canvas.create_line(s*0.28 + offset_x, s*0.46, s*0.38 + offset_x, s*0.46, fill=self._palette["eye"], width=3)
            self.canvas.create_line(s*0.62 + offset_x, s*0.46, s*0.72 + offset_x, s*0.46, fill=self._palette["eye"], width=3)
        
        # Boca
        if self.mouth_smile:
            self.canvas.create_arc(s*0.30 + offset_x, s*0.58, s*0.70 + offset_x, s*0.82, 
                                   start=200, extent=140, style="arc", width=3, outline=self._palette["mouth"])
        else:
            self.canvas.create_line(s*0.38 + offset_x, s*0.74, s*0.62 + offset_x, s*0.74, fill=self._palette["mouth"], width=3)

    def _animate(self):
        if self._speaking:
            self._draw_spectrum_mouth()
            self._rhythm_counter += 1
            
            # Rhythmic blinking during speech (every ~10 frames, ~900ms)
            if self._rhythm_counter % 12 == 0:
                self._blink_counter = random.randint(1, 3)
            
            # Head tilt oscillation based on low frequency energy
            low_energy = self._spectrum_bands.get("low", 0.0)
            self._head_tilt = math.sin(self._rhythm_counter * 0.12) * low_energy * 0.18
            
            # Eyebrow height based on high frequency energy (surprise effect)
            high_energy = self._spectrum_bands.get("high", 0.0)
            self._eyebrow_height = high_energy * 0.45
            
            self.after(105, self._animate)
            return
        
        # Normal idle animation
        if random.random() < self._idle_blink_probability:
            self.eyes_open = False
            self._draw_face()
            self.after(220, self._open_eyes)
        else:
            if random.random() < 0.18:
                self.mouth_smile = not self.mouth_smile
                self._draw_face()
            self.after(480, self._animate)

    def _open_eyes(self):
        self.eyes_open = True
        self._draw_face()
        self.after(400, self._animate)

    def set_expression(self, expression: str = "smile"):
        """
        Cambia la expresión facial del muñeco.
        Opciones: 'smile', 'neutral', 'surprised', 'error', 'thinking', 'happy', 'sad', 'angry'
        """
        if self._ultra_friendly_mode:
            if expression in {"angry", "sad", "error"}:
                expression = "neutral"
            elif expression == "neutral":
                # En modo amable, neutral se mantiene con sonrisa suave.
                expression = "smile"

        if expression == "smile":
            self.mouth_smile = True
            self._draw_face()
        elif expression == "neutral":
            self.mouth_smile = False
            self._draw_face()
        elif expression == "surprised":
            self.mouth_smile = True
            self._draw_surprised_mouth()
        elif expression == "error":
            self.mouth_smile = False
            self._draw_error_mouth()
        elif expression == "thinking":
            self.mouth_smile = False
            self._draw_thinking()
        elif expression == "happy":
            self.mouth_smile = True
            self._draw_happy()
        elif expression == "sad":
            self.mouth_smile = False
            self._draw_sad()
        elif expression == "angry":
            self.mouth_smile = False
            self._draw_angry()

    def _draw_surprised_mouth(self):
        s = self.size
        self._draw_face()
        self.canvas.create_oval(s*0.45, s*0.68, s*0.55, s*0.80, fill="#222", outline="")

    def _draw_error_mouth(self):
        s = self.size
        self._draw_face()
        # Expresión suave de preocupación (evita gesto agresivo).
        self.canvas.create_arc(s*0.36, s*0.72, s*0.64, s*0.84, start=25, extent=130, style="arc", width=3, outline=self._palette["mouth"])

    def _draw_thinking(self):
        s = self.size
        self._draw_face()
        self.canvas.create_line(s*0.40, s*0.76, s*0.60, s*0.76, fill="#222", width=3)
        self.canvas.create_oval(s*0.28, s*0.34, s*0.38, s*0.50, fill="#222", outline="")
        self.canvas.create_oval(s*0.62, s*0.34, s*0.72, s*0.50, fill="#222", outline="")
        self.canvas.create_line(s*0.26, s*0.30, s*0.40, s*0.32, fill="#222", width=2)
        self.canvas.create_line(s*0.60, s*0.32, s*0.74, s*0.30, fill="#222", width=2)

    def _draw_happy(self):
        s = self.size
        self._draw_face()
        self.canvas.create_arc(s*0.28, s*0.60, s*0.72, s*0.88, start=200, extent=140, style="arc", width=4)
        self.canvas.create_oval(s*0.28, s*0.40, s*0.38, s*0.54, fill="#222", outline="")
        self.canvas.create_oval(s*0.62, s*0.40, s*0.72, s*0.54, fill="#222", outline="")

    def _draw_sad(self):
        s = self.size
        self._draw_face()
        self.canvas.create_arc(s*0.38, s*0.80, s*0.62, s*0.92, start=20, extent=140, style="arc", width=3)
        self.canvas.create_oval(s*0.28, s*0.46, s*0.38, s*0.58, fill="#222", outline="")
        self.canvas.create_oval(s*0.62, s*0.46, s*0.72, s*0.58, fill="#222", outline="")

    def _draw_angry(self):
        s = self.size
        self._draw_face()
        # Para público mayor, sustituimos "enojado" por "serio-amable".
        self.canvas.create_line(s*0.40, s*0.76, s*0.60, s*0.76, fill=self._palette["mouth"], width=3)
        self.canvas.create_oval(s*0.28, s*0.38, s*0.38, s*0.54, fill=self._palette["eye"], outline="")
        self.canvas.create_oval(s*0.62, s*0.38, s*0.72, s*0.54, fill=self._palette["eye"], outline="")
        self.canvas.create_line(s*0.26, s*0.34, s*0.38, s*0.33, fill=self._palette["eyebrow"], width=2)
        self.canvas.create_line(s*0.62, s*0.33, s*0.74, s*0.34, fill=self._palette["eyebrow"], width=2)

    def blink(self):
        """Forzar parpadeo inmediato."""
        self.eyes_open = False
        self._draw_face()
        self.after(180, self._open_eyes)

    def _detect_phoneme(self) -> str:
        """
        Detect approximate phoneme based on energy patterns.
        Returns: 'neutral', 'vowel_open', 'vowel_mid', 'consonant_stop', 'consonant_fricative'
        """
        low = self._spectrum_bands.get("low", 0.0)
        mid = self._spectrum_bands.get("mid", 0.0)
        high = self._spectrum_bands.get("high", 0.0)
        
        self._phoneme_history.append((low, mid, high))
        if len(self._phoneme_history) > self._max_history:
            self._phoneme_history.pop(0)
        
        if mid < 0.1:
            return "neutral"
        elif high > 0.6:
            return "consonant_stop"
        elif high > 0.3 and low < 0.2:
            return "consonant_fricative"
        elif mid > 0.6 and low > 0.4:
            return "vowel_open"
        elif mid > 0.5 and high < 0.2:
            return "vowel_mid"
        else:
            return "neutral"

    def _draw_mouth_for_phoneme(self):
        """Draw different mouth shapes based on detected phoneme."""
        s = self.size
        phoneme = self._detect_phoneme()
        self._current_phoneme = phoneme
        offset_x = self._head_tilt * s * 0.15
        
        if phoneme == "vowel_open":
            self.canvas.create_oval(s*0.40 + offset_x, s*0.65, s*0.60 + offset_x, s*0.85, fill=self._palette["mouth"], outline="")
        elif phoneme == "vowel_mid":
            self.canvas.create_arc(s*0.35 + offset_x, s*0.65, s*0.65 + offset_x, s*0.80, 
                                   start=200, extent=140, style="arc", width=3, outline=self._palette["mouth"])
        elif phoneme == "consonant_stop":
            self.canvas.create_arc(s*0.42 + offset_x, s*0.68, s*0.58 + offset_x, s*0.78, 
                                   start=200, extent=140, style="arc", width=3, outline=self._palette["mouth"])
        elif phoneme == "consonant_fricative":
            self.canvas.create_line(s*0.38 + offset_x, s*0.74, s*0.62 + offset_x, s*0.74, fill=self._palette["mouth"], width=2)
        else:
            self.canvas.create_line(s*0.38 + offset_x, s*0.74, s*0.62 + offset_x, s*0.74, fill=self._palette["mouth"], width=3)

    def _draw_spectrum_mouth(self):
        s = self.size
        self._draw_face()

        # Dibujar boca con detección de fonemas cuando hay energía suficiente
        mid_energy = self._spectrum_bands.get("mid", 0.0)
        if mid_energy > 0.15:
            self._draw_mouth_for_phoneme()

        # Visualizar 3 bandas de frecuencia debajo de la cara
        center_x = s * 0.50
        baseline_y = s * 0.76
        
        band_data = [
            (self._spectrum_bands.get("low", 0.0), self._palette["band_low"]),
            (self._spectrum_bands.get("mid", 0.0), self._palette["band_mid"]),
            (self._spectrum_bands.get("high", 0.0), self._palette["band_high"]),
        ]
        
        bars_per_band = 2
        bar_width = s * 0.035
        gap = s * 0.010
        total_width = (bars_per_band * 3) * (bar_width + gap)
        start_x = center_x - total_width / 2
        
        self._spectrum_phase += 1
        
        for band_idx, (energy, color) in enumerate(band_data):
            for bar_idx in range(bars_per_band):
                wave = 0.45 + 0.55 * abs(math.sin((self._spectrum_phase * 0.32) + band_idx * 1.2 + bar_idx * 0.6))
                jitter = random.uniform(0.94, 1.06)
                height = s * (0.02 + energy * (0.20 * wave)) * jitter
                height = max(s * 0.01, min(height, s * 0.25))
                
                x_offset = band_idx * (bars_per_band * (bar_width + gap)) + bar_idx * (bar_width + gap)
                x0 = start_x + x_offset
                x1 = x0 + bar_width
                
                self.canvas.create_rectangle(x0, baseline_y - height, x1, baseline_y + height * 0.12, 
                                             fill=color, outline="")

    def set_spectrum_level(self, level=None, bands=None) -> None:
        """
        Update spectrum visualization.
        Can accept either:
        - level: float (0.0-1.0) for backward compatibility
        - bands: dict with 'low', 'mid', 'high' keys
        """
        if bands is not None:
            if isinstance(bands, dict):
                self._spectrum_bands = {
                    "low": max(0.0, min(1.0, float(bands.get("low", 0.0)))),
                    "mid": max(0.0, min(1.0, float(bands.get("mid", 0.0)))),
                    "high": max(0.0, min(1.0, float(bands.get("high", 0.0))))
                }
            else:
                try:
                    self._spectrum_bands = {
                        "low": max(0.0, min(1.0, float(bands[0]))),
                        "mid": max(0.0, min(1.0, float(bands[1]))),
                        "high": max(0.0, min(1.0, float(bands[2])))
                    }
                except (TypeError, IndexError):
                    pass
        elif level is not None:
            level_val = max(0.0, min(1.0, float(level)))
            self._spectrum_bands = {"low": level_val, "mid": level_val, "high": level_val}
            self._spectrum_level = level_val
        else:
            self._spectrum_bands = {"low": 0.0, "mid": 0.0, "high": 0.0}
            self._spectrum_level = 0.0

    def start_spectrum(self, interval=120):
        """Inicia una boca tipo espectro mientras Willy habla."""
        self._saved_face_state = (self.eyes_open, self.mouth_smile)
        self._speaking = True
        self._spectrum_phase = 0
        self._spectrum_level = 0.0
        self._spectrum_bands = {"low": 0.0, "mid": 0.0, "high": 0.0}
        self._head_tilt = 0.0
        self._eyebrow_height = 0.0
        self._phoneme_history = []
        self._current_phoneme = "neutral"
        self._rhythm_counter = 0
        self._blink_counter = 0
        self._draw_spectrum_mouth()
        self.after(interval, self._animate)

    def stop_spectrum(self):
        """Detiene el espectro y restaura la expresión previa."""
        self._speaking = False
        self._head_tilt = 0.0
        self._eyebrow_height = 0.0
        self._rhythm_counter = 0
        if self._saved_face_state is not None:
            self.eyes_open, self.mouth_smile = self._saved_face_state
            self._saved_face_state = None
        if self._ultra_friendly_mode:
            self.mouth_smile = True
        self._draw_face()

    def enable_drag(self):
        self._drag_data = {"x": 0, "y": 0}
        self.bind("<ButtonPress-1>", self._on_drag_start)
        self.bind("<B1-Motion>", self._on_drag_move)
        self.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.configure(cursor="fleur")
        self.configure(cursor="fleur")

    def _on_drag_start(self, event):
        self._drag_data["x"] = event.x
        self._drag_data["y"] = event.y

    def _on_drag_move(self, event):
        dx = event.x - self._drag_data["x"]
        dy = event.y - self._drag_data["y"]
        x = self.winfo_x() + dx
        y = self.winfo_y() + dy
        parent = self.master
        parent.update_idletasks()
        max_x = parent.winfo_width() - self.winfo_width()
        max_y = parent.winfo_height() - self.winfo_height()
        x = max(0, min(x, max_x))
        y = max(0, min(y, max_y))
        self.place(x=x, y=y)

    def _on_drag_end(self, event):
        callback = getattr(self, "_on_move_end", None)
        if callable(callback):
            callback(self.winfo_x(), self.winfo_y())

    def set_drag_end_callback(self, callback):
        self._on_move_end = callback
