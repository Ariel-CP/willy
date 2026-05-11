"""
tts.py — Text-to-speech using espeak + pw-play (PipeWire).
Runs in a background thread so the GUI never blocks.
"""

import math
import os
import re
import shutil
import struct
import hashlib
import subprocess
import tempfile
import threading
import time
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
    has_playback = shutil.which("pw-play") is not None
    has_espeak = shutil.which("espeak") is not None
    has_piper = shutil.which("piper") is not None
    return has_playback and (has_espeak or has_piper)


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


def _calculate_audio_energy(frames: bytes, sample_width: int) -> float:
    if not frames:
        return 0.0
    if sample_width != 2:
        return 0.0
    sample_count = len(frames) // 2
    if sample_count <= 0:
        return 0.0
    samples = struct.unpack(f"<{sample_count}h", frames[: sample_count * 2])
    mean_square = sum(sample * sample for sample in samples) / sample_count
    rms = math.sqrt(mean_square) / 32768.0
    return max(0.0, min(1.0, rms))


def _calculate_frequency_bands(frames: bytes, sample_width: int) -> tuple[float, float, float]:
    """
    Analyze audio into 3 frequency bands (simple approximation without FFT):
    - low: slow changes (simulated via downsampling)
    - mid: overall energy
    - high: fast changes (simulated via delta)
    Returns: (low_energy, mid_energy, high_energy) each 0.0-1.0
    """
    if not frames or sample_width != 2:
        return 0.0, 0.0, 0.0
    
    sample_count = len(frames) // 2
    if sample_count <= 0:
        return 0.0, 0.0, 0.0
    
    samples = list(struct.unpack(f"<{sample_count}h", frames[: sample_count * 2]))
    
    # Mid: overall RMS energy
    mean_square = sum(s * s for s in samples) / sample_count
    mid_energy = math.sqrt(mean_square) / 32768.0
    
    # Low: downsampled RMS (every 4th sample = ~1/4 frequency)
    downsampled = samples[::4] if len(samples) > 4 else samples
    if downsampled:
        low_mean_sq = sum(s * s for s in downsampled) / len(downsampled)
        low_energy = math.sqrt(low_mean_sq) / 32768.0
    else:
        low_energy = 0.0
    
    # High: energy of deltas (changes between consecutive samples)
    if len(samples) > 1:
        deltas = [samples[i+1] - samples[i] for i in range(len(samples)-1)]
        high_mean_sq = sum(d * d for d in deltas) / len(deltas) if deltas else 0
        high_energy = math.sqrt(high_mean_sq) / 32768.0
    else:
        high_energy = 0.0
    
    # Normalize to 0.0-1.0
    low_energy = max(0.0, min(1.0, low_energy * 1.3))  # Slight boost for low freq
    mid_energy = max(0.0, min(1.0, mid_energy))
    high_energy = max(0.0, min(1.0, high_energy * 0.8))  # Slight reduction for stability
    
    return low_energy, mid_energy, high_energy


class TTSEngine:
    def __init__(self, lang: str = "es", config: Optional[dict] = None) -> None:
        self._lang = lang
        self._volume: float = 0.35  # 0.0 - 1.0
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None

        self._config: dict = config or {}
        self._pwplay_cmd = shutil.which("pw-play")
        self._espeak_cmd = shutil.which("espeak")
        self._piper_cmd = shutil.which("piper")
        if self._piper_cmd is None:
            local_piper = os.path.expanduser("~/.local/bin/piper")
            if os.path.isfile(local_piper) and os.access(local_piper, os.X_OK):
                self._piper_cmd = local_piper

        self._engine_preference = str(self._config.get("tts_engine", "auto")).strip().lower()
        if self._engine_preference not in {"auto", "espeak", "piper"}:
            self._engine_preference = "auto"

        senior_default = True
        self._senior_mode = bool(self._config.get("tts_senior_mode", senior_default))

        configured_rate = self._config.get("tts_rate")
        if configured_rate is None:
            self._rate = 0.90 if self._senior_mode else 1.0
        else:
            try:
                self._rate = float(configured_rate)
            except (TypeError, ValueError):
                self._rate = 0.90 if self._senior_mode else 1.0
        self._rate = max(0.65, min(1.35, self._rate))

        self._piper_model = str(self._config.get("piper_model", "")).strip()
        self._piper_config = str(self._config.get("piper_config", "")).strip()
        self._cache_enabled = bool(self._config.get("tts_cache_enabled", True))
        self._cache_dir = os.path.join(tempfile.gettempdir(), "willy_tts_cache")
        if self._cache_enabled:
            try:
                os.makedirs(self._cache_dir, exist_ok=True)
            except Exception:
                self._cache_enabled = False

        self._available = self._check_runtime_available()

    def _check_runtime_available(self) -> bool:
        if not self._pwplay_cmd:
            return False
        return self._can_use_espeak() or self._can_use_piper()

    def _can_use_espeak(self) -> bool:
        return self._espeak_cmd is not None

    def _can_use_piper(self) -> bool:
        if self._piper_cmd is None:
            return False
        if not self._piper_model:
            return False
        return os.path.isfile(self._piper_model)

    def _resolve_engine(self) -> Optional[str]:
        if self._engine_preference == "piper":
            return "piper" if self._can_use_piper() else ("espeak" if self._can_use_espeak() else None)
        if self._engine_preference == "espeak":
            return "espeak" if self._can_use_espeak() else ("piper" if self._can_use_piper() else None)
        # auto: prefer piper when configured, then espeak
        if self._can_use_piper():
            return "piper"
        if self._can_use_espeak():
            return "espeak"
        return None

    def is_available(self) -> bool:
        return self._available

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def is_speaking(self) -> bool:
        with self._lock:
            proc_alive = self._proc is not None and self._proc.poll() is None
        thread_alive = self._thread is not None and self._thread.is_alive()
        return proc_alive or thread_alive

    def speak(
        self,
        text: str,
        on_energy=None,
        on_start=None,
        on_end=None,
    ) -> bool:
        """Speak *text* in a background thread (non-blocking). Returns True if started."""
        if not self._available:
            return False
        clean = _strip_for_speech(text)
        if not clean:
            return False
        self.stop()
        self._thread = threading.Thread(
            target=self._run,
            args=(clean, self._volume, on_energy, on_start, on_end),
            daemon=True,
        )
        self._thread.start()
        return True

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

    def _wave_energy_series(self, wav_path: str, chunk_duration: float = 0.08) -> tuple[list[tuple[float, float, float]], float]:
        """
        Precompute frequency bands for entire audio.
        Returns: (list of (low, mid, high) tuples, chunk_duration)
        """
        bands_series: list[tuple[float, float, float]] = []
        with wave.open(wav_path, "rb") as source:
            frame_rate = source.getframerate()
            frames_per_chunk = max(1, int(frame_rate * chunk_duration))
            total_frames = source.getnframes()
            current_frame = 0
            sample_width = source.getsampwidth()

            while current_frame < total_frames:
                remaining = total_frames - current_frame
                frame_count = min(frames_per_chunk, remaining)
                frames = source.readframes(frame_count)
                low, mid, high = _calculate_frequency_bands(frames, sample_width)
                bands_series.append((low, mid, high))
                current_frame += frame_count

        return bands_series, chunk_duration

    def _play_wav_file(self, path: str) -> None:
        proc = subprocess.Popen(
            ["pw-play", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._proc = proc
        proc.wait()

    def _cache_key(self, engine: str, text: str, volume: float) -> str:
        payload = "|".join([
            engine,
            self._lang,
            f"{self._rate:.3f}",
            "1" if self._senior_mode else "0",
            f"{volume:.3f}",
            self._piper_model,
            text,
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _synthesize_espeak(self, text: str, wav_path: str, volume: float) -> None:
        voice = "es" if self._lang == "es" else "en"
        base_speed = 160
        speed = max(110, min(230, int(base_speed * self._rate)))
        amp = int(volume * 180)
        subprocess.run(
            ["espeak", "-v", voice, "-s", str(speed), "-a", str(amp), "-w", wav_path, text],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _synthesize_piper(self, text: str, wav_path: str) -> None:
        if not self._piper_model:
            raise RuntimeError("Piper model path is not configured")
        length_scale = 1.10 if self._senior_mode else (1.0 / self._rate)
        length_scale = max(0.75, min(1.45, length_scale))

        cmd = [
            self._piper_cmd or "piper",
            "--model", self._piper_model,
            "--output_file", wav_path,
            "--length_scale", f"{length_scale:.3f}",
        ]
        if self._piper_config:
            cmd.extend(["--config", self._piper_config])

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        proc.communicate(text)
        if proc.returncode != 0:
            raise RuntimeError("Piper synthesis failed")

    def _synthesize_to_wav(self, engine: str, text: str, wav_path: str, volume: float) -> None:
        if engine == "piper":
            self._synthesize_piper(text, wav_path)
            return
        if engine == "espeak":
            self._synthesize_espeak(text, wav_path, volume)
            return
        raise RuntimeError(f"Unknown TTS engine: {engine}")

    def _get_cached_or_synthesized_wav(self, text: str, volume: float) -> tuple[str, bool]:
        engine = self._resolve_engine()
        if engine is None:
            raise RuntimeError("No TTS engine available")

        if self._cache_enabled:
            cache_file = os.path.join(self._cache_dir, f"{self._cache_key(engine, text, volume)}.wav")
            if os.path.isfile(cache_file):
                return cache_file, False
            self._synthesize_to_wav(engine, text, cache_file, volume)
            return cache_file, False

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp_path = f.name
        self._synthesize_to_wav(engine, text, tmp_path, volume)
        return tmp_path, True

    def _run(self, text: str, volume: float, on_energy=None, on_start=None, on_end=None) -> None:
        tmp_chirp = None
        speech_wav = None
        speech_is_temp = False
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_chirp = f.name

            speech_wav, speech_is_temp = self._get_cached_or_synthesized_wav(text, volume)

            if callable(on_start):
                on_start()

            energies, chunk_duration = self._wave_energy_series(speech_wav)

            proc = subprocess.Popen(
                ["pw-play", speech_wav],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._proc = proc

            next_tick = time.monotonic()
            for low, mid, high in energies:
                with self._lock:
                    if self._proc is None:
                        break
                now = time.monotonic()
                if now < next_tick:
                    time.sleep(min(0.02, next_tick - now))
                if callable(on_energy):
                    try:
                        on_energy({"low": low, "mid": mid, "high": high})
                    except Exception:
                        pass
                next_tick += chunk_duration
                if proc.poll() is not None:
                    break

            proc.wait()

            if callable(on_energy):
                try:
                    on_energy({"low": 0.0, "mid": 0.0, "high": 0.0})
                except Exception:
                    pass

            _generate_chime_wav(tmp_chirp, volume=volume)
            self._play_wav_file(tmp_chirp)

        except Exception:
            pass
        finally:
            if callable(on_end):
                try:
                    on_end()
                except Exception:
                    pass
            with self._lock:
                self._proc = None
            if speech_is_temp and speech_wav:
                try:
                    os.unlink(speech_wav)
                except Exception:
                    pass
            if tmp_chirp:
                try:
                    os.unlink(tmp_chirp)
                except Exception:
                    pass
