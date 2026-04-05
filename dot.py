#!/usr/bin/env python3
"""
dot.py — Backward-compatible entry point for the dot layout engine.

Delegates to ``gvcli.py`` with ``-Kdot`` as default.
For multi-engine support, use ``gvcli.py`` directly.
"""
from gvcli import main

if __name__ == "__main__":
    main()
