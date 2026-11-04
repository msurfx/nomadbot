"""Vercel entrypoint. Vercel's Python runtime does static analysis for a
top-level `handler` name, so we declare a real class definition rather than an
import alias."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.serve_dashboard import Handler as _BaseHandler  # noqa: E402


class handler(_BaseHandler):  # noqa: N801  (Vercel requires lowercase)
    """BaseHTTPRequestHandler subclass that Vercel wraps for each request."""
    pass
