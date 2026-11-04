"""Vercel entrypoint. Re-exports the Handler from scripts.serve_dashboard
as `handler` — the name Vercel's Python runtime looks for on BaseHTTPRequestHandler subclasses."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.serve_dashboard import Handler as handler  # noqa: E402, F401
