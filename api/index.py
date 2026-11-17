"""Vercel serverless function entrypoint."""

import os
import sys

# Ensure project root is in sys.path for serverless execution
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import TriageHandler


class handler(TriageHandler):
    """Vercel Python runtime handler."""
    pass
