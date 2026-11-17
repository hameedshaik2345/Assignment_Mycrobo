"""Vercel serverless function entrypoint with path normalization."""

import os
import sys

# Ensure project root is in sys.path for serverless execution
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import TriageHandler


class handler(TriageHandler):
    """Vercel Python runtime handler with intelligent serverless path mapping."""

    def _normalize_path(self):
        # Vercel serverless provides the original client path via headers or path
        raw = (
            self.headers.get("x-matched-path")
            or self.headers.get("x-invoke-path")
            or self.headers.get("x-forwarded-uri")
            or self.path
        )
        clean = raw.split("?")[0].rstrip("/")

        if clean.endswith("/health") or clean == "/health":
            self.path = "/health"
        elif clean.endswith("/classify") or clean == "/classify":
            self.path = "/classify"
        elif clean in ("", "/", "/api", "/api/index", "/api/index.py"):
            self.path = "/"
        else:
            self.path = clean

    def do_GET(self):
        self._normalize_path()
        return super().do_GET()

    def do_POST(self):
        self._normalize_path()
        return super().do_POST()

    def do_OPTIONS(self):
        self._normalize_path()
        return super().do_OPTIONS()
