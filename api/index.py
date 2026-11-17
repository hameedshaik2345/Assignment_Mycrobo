"""Vercel serverless function entrypoint with path normalization."""

import os
import sys
from urllib.parse import parse_qs, urlparse

# Ensure project root is in sys.path for serverless execution
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import TriageHandler


class handler(TriageHandler):
    """Vercel Python runtime handler with intelligent serverless path mapping."""

    def _normalize_path(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        custom_path = params.get("path", [""])[0].strip("/")

        if custom_path == "health":
            self.path = "/health"
        elif custom_path == "classify":
            self.path = "/classify"
        elif custom_path == "":
            self.path = "/"
        else:
            self.path = f"/{custom_path}"

    def do_GET(self):
        self._normalize_path()
        return super().do_GET()

    def do_POST(self):
        self._normalize_path()
        return super().do_POST()

    def do_OPTIONS(self):
        self._normalize_path()
        return super().do_OPTIONS()
