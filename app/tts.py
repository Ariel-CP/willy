"""
tts.py — Text-to-speech using espeak + pw-play (PipeWire).
Runs in a background thread so the GUI never blocks.
"""

import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from typing import Optional


def _strip_for_speech(text: str) -> str:
    """Remove markdown/code syntax before speaking."""
    text = re.sub(r"```[\s\S]*?```", "bloque de código", text)
    text = re.sub(r"`[^`]+`", "", text)
    text = re.sub(r"[*_]{1,3}", "", text)
    text = re.sub(r"[•►→\-–] ?", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _check_available() -> bool:
    return shutil.which("espeak") is not None and shutil.which("pw-play") is not None


def _generate_chime_wav(path: str, volume: float = 0.35) -> None:
    """Generate a soft 3-note ascending chime (like a notification bell)."""
    sample_rate = 44100
    # Three gentle bell tones: C5, E5, G5
    notes = [
        (0.00, 523.25),   # C5
        (0.18, 659.25),   # E5
        (0.36, 783.99),   # G5
    ]
    duration = 1.1
    n_samples = int(sample_rate * duration)
    samples = []
    gain = max(0.05, min(1.0, volume)) * 0.80  # scale with volume, cap at 0.80

    for i in range(n_samples):
        t = i / sample_rate
        val = 0.0
        for start, freq in notes:
            if t >= start:
                age = t - start
                env = math.exp(-age * 5.0)
                val += env * (
                    0.55 * math.sin(2 * math.pi * freq * age)
                    + 0.20 * math.sin(2 * math.pi * freq * 2 * age)
                    + 0.08 * math.sin(2 * math.pi * freq * 3 * age)
                )
        samples.append(int(val * gain * 32767))

    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class TTSEngine:
    def __init__(self, lang: str = "es") -> None:
        self._lang = lang
        self._volume: float = 0.35  # 0.0 - 1.0
        self._available = _check_available()
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

    def is_available(self) -> bool:
        return self._available

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def speak(self, text: str) -> None:
        """Speak *text* in a background thread (non-blocking)."""
        if not self._available:
            return
        clean = _strip_for_speech(text)
        if not clean:
            return
        self.stop()
        self._thread = threading.Thread(target=self._run, args=(clean, self._volume), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Kill ongoing speech immediately."""
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _run(self, text: str, volume: float) -> None:
        tmp_speech = None
        tmp_chirp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_speech = f.name
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_chirp = f.name

            # Synthesize speech to WAV
            voice = "es" if self._lang == "es" else "en"
            # espeak amplitude: 0-200, default 100; scale by volume
            amp = int(volume * 180)
            subprocess.run(
                ["espeak", "-v", voice, "-s", "160", "-a", str(amp), "-w", tmp_speech, text],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # Generate chime scaled to volume
            _generate_chime_wav(tmp_chirp, volume=volume)

            # Play speech
            for wav in (tmp_speech, tmp_chirp):
                proc = subprocess.Popen(
                    ["pw-play", wav],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with self._lock:
                    self._proc = proc
                proc.wait()
                # If killed mid-way, stop both
                with self._lock:
                    if self._proc is None:
                        return

        except Exception:
            pass
        finally:
            with self._lock:
                self._proc = None
            for tmp in (tmp_speech, tmp_chirp):
                if tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
