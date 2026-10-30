#!/usr/bin/env python3
"""Cron Rhythm Studio Standalone Production Server on Port 5174.

Provides real REST API endpoints:
  - /health & /api/health
  - /api/diagnostics
  - /api/parse
  - /api/humanize
  - /api/next
  - /api/transpile
  - /api/rhythm
  - /api/presets
  - /api/fleet
  - /api/dst-audit
  - /api/tz-board
  - /api/mcp/config
  - /api/export-bundle
and serves the standalone Cron Rhythm Studio from public/.
"""

import sys
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
PUBLIC_DIR = ROOT_DIR / "public"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cron_rhythm_studio.cli import cmd_serve

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cron Rhythm Studio Standalone Workstation")
    parser.add_argument("--port", type=int, default=5174, help="Port to listen on (default: 5174)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    args = parser.parse_args()

    print(f"Starting Cron Rhythm Studio Server on {args.host}:{args.port}...")
    sys.exit(cmd_serve(args))
