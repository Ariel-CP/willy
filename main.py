#!/usr/bin/env python3
"""
main.py — Entry point for Willy, the AI terminal assistant.

Usage:
    python main.py
"""

import sys
import os

# Ensure the project root is on sys.path when running from any directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.gui import WillyApp


def main() -> None:
    app = WillyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
