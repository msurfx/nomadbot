"""Vercel entrypoint. Imports the Handler from the local serve_dashboard module."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.serve_dashboard import Handler  # noqa: E402, F401
