"""Vercel catch-all serverless function for every /api/* request.

Vercel's dynamic routing sends anything matching /api/<something>[/<more>]
here with the original URL preserved (no rewrite), so self.path inside the
handler is exactly what the browser requested. We then delegate to our
BaseHTTPRequestHandler from scripts/serve_dashboard.py.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.serve_dashboard import Handler as _BaseHandler  # noqa: E402


class handler(_BaseHandler):  # noqa: N801  (Vercel requires lowercase)
    """BaseHTTPRequestHandler subclass that Vercel wraps for each request."""
    pass
