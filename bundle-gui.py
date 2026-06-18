#!/usr/bin/env python3
"""
Mender Artifact Bundle GUI
Web-based helper to package Docker Compose projects into Mender artifacts.

Usage:
    pip install pyyaml
    python bundle-gui.py [--port 8888] [--host 127.0.0.1] [--no-browser]
"""

import argparse

from app.server import start

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Mender Artifact Bundle GUI")
    ap.add_argument("--port",       type=int, default=8888,        help="Port (default: 8888)")
    ap.add_argument("--host",       default="127.0.0.1",           help="Bind host (default: 127.0.0.1; use 0.0.0.0 in Docker)")
    ap.add_argument("--no-browser", action="store_true",           help="Do not open browser automatically")
    args = ap.parse_args()
    start(args.host, args.port, args.no_browser)
