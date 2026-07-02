#!/usr/bin/env python3
"""
main.py — Entry point for Willy, the AI terminal assistant.

Usage:
    python main.py
"""

import sys
import os
import logging

# Ensure the project root is on sys.path when running from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui import WillyApp


def _configure_runtime_logging() -> None:
    """Enable basic logging to terminal and runtime file."""
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "willy-runtime.log")

    handlers = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )

    def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return sys.__excepthook__(exc_type, exc_value, exc_traceback)
        logging.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = _log_uncaught_exception


def main() -> None:
    _configure_runtime_logging()
    logging.info("Starting Willy GUI")
    app = WillyApp()
    logging.info("GUI initialized, entering main loop")
    app.mainloop()
    logging.info("GUI main loop exited")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Fatal error while running Willy")
        raise
