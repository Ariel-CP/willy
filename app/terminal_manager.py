"""
terminal_manager.py — Wrapper for subprocess/pty to run real terminal commands.
Streams output line-by-line via a callback; supports background processes.
"""

import os
import select
import subprocess
import threading
import signal
from typing import Callable, Optional

try:
    import fcntl
    import pty
    import termios

    HAS_PTY = True
except ImportError:
    HAS_PTY = False


class TerminalManager:
    def __init__(self, output_callback: Callable[[str], None], initial_dir: str = "~",
                 on_command_done: Callable[[str, str], None] | None = None):
        self.output_callback = output_callback
        self.on_command_done = on_command_done
        self.cwd = os.path.expanduser(initial_dir)
        self._active_process: Optional[subprocess.Popen] = None
        self._active_master_fd: Optional[int] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_command(self, command: str, background: bool = False) -> None:
        """Run *command* in a pty so interactive programs work correctly."""
        target = self._run_in_pty if HAS_PTY else self._run_with_pipes
        thread = threading.Thread(
            target=target,
            args=(command,),
            daemon=True,
        )
        thread.start()
        if not background:
            thread.join()

    def run_command_async(self, command: str) -> None:
        """Start command asynchronously (non-blocking for the caller)."""
        self.run_command(command, background=True)

    def kill_active(self) -> None:
        """Send SIGINT to the currently running process, if any."""
        with self._lock:
            if self._active_process and self._active_process.poll() is None:
                try:
                    if HAS_PTY:
                        os.killpg(os.getpgid(self._active_process.pid), signal.SIGINT)
                    elif os.name == "nt":
                        self._active_process.terminate()
                    else:
                        self._active_process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass

    def change_directory(self, path: str) -> str:
        """Change the working directory; returns the new cwd or an error string."""
        target = os.path.expanduser(path) if path.startswith("~") else path
        if not os.path.isabs(target):
            target = os.path.join(self.cwd, target)
        target = os.path.normpath(target)
        if os.path.isdir(target):
            self.cwd = target
            return self.cwd
        return f"cd: no such directory: {path}"

    def get_cwd(self) -> str:
        return self.cwd

    def has_active_process(self) -> bool:
        with self._lock:
            return self._active_process is not None and self._active_process.poll() is None

    def send_input(self, text: str) -> bool:
        """Send *text* plus newline to the active process stdin via PTY."""
        with self._lock:
            proc = self._active_process
            master_fd = self._active_master_fd

        if proc is None or proc.poll() is not None:
            return False

        try:
            if master_fd is not None:
                os.write(master_fd, (text + "\n").encode("utf-8", errors="replace"))
            elif proc.stdin is not None:
                proc.stdin.write(text + "\n")
                proc.stdin.flush()
            else:
                return False
            return True
        except OSError:
            return False
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_in_pty(self, command: str) -> None:
        """Execute *command* inside a pseudo-terminal, streaming output."""
        master_fd, slave_fd = pty.openpty()
        _output_buf: list[str] = []
        try:
            env = os.environ.copy()
            env["TERM"] = "xterm-256color"

            def _prepare_child_terminal() -> None:
                os.setsid()
                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)

            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                env=env,
                close_fds=True,
                preexec_fn=_prepare_child_terminal,
            )
            os.close(slave_fd)
            slave_fd = -1

            with self._lock:
                self._active_process = proc
                self._active_master_fd = master_fd

            # Stream output until the process finishes
            buf = b""
            while True:
                try:
                    rlist, _, _ = select.select([master_fd], [], [], 0.1)
                except ValueError:
                    break
                if rlist:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    # Decode and emit lines as they arrive
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", errors="replace").rstrip("\r")
                        self._emit(text + "\n", _output_buf)
                    # Interactive programs (e.g. sudo) often print prompts without newline.
                    if buf and b"\n" not in buf:
                        self._emit(buf.decode("utf-8", errors="replace").rstrip("\r"), _output_buf)
                        buf = b""
                elif proc.poll() is not None:
                    break

            # Flush remaining buffer
            if buf:
                self._emit(buf.decode("utf-8", errors="replace"), _output_buf)

            proc.wait()
            exit_code = proc.returncode
            if exit_code != 0:
                self._emit(f"\n[Process exited with code {exit_code}]\n", _output_buf)
            else:
                self._emit("\n[Done]\n", _output_buf)

            if callable(self.on_command_done):
                try:
                    self.on_command_done(command, "".join(_output_buf))
                except Exception:
                    pass

        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            if slave_fd != -1:
                try:
                    os.close(slave_fd)
                except OSError:
                    pass
            with self._lock:
                self._active_process = None
                self._active_master_fd = None

    def _run_with_pipes(self, command: str) -> None:
        """Execute *command* using stdio pipes (Windows-friendly fallback)."""
        _output_buf: list[str] = []
        proc: subprocess.Popen | None = None
        try:
            env = os.environ.copy()
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            proc = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=self.cwd,
                env=env,
                text=True,
                bufsize=1,
                creationflags=creationflags,
            )

            with self._lock:
                self._active_process = proc
                self._active_master_fd = None

            if proc.stdout is not None:
                for line in iter(proc.stdout.readline, ""):
                    self._emit(line, _output_buf)

            proc.wait()
            exit_code = proc.returncode
            if exit_code != 0:
                self._emit(f"\n[Process exited with code {exit_code}]\n", _output_buf)
            else:
                self._emit("\n[Done]\n", _output_buf)

            if callable(self.on_command_done):
                try:
                    self.on_command_done(command, "".join(_output_buf))
                except Exception:
                    pass
        finally:
            with self._lock:
                self._active_process = None
                self._active_master_fd = None

    def _emit(self, text: str, _buf: list[str] | None = None) -> None:
        """Send text to the registered output callback (thread-safe)."""
        if _buf is not None:
            _buf.append(text)
        if callable(self.output_callback):
            self.output_callback(text)
