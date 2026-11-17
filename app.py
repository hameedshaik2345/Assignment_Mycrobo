"""AI Triage Microservice for Mycrobo Arena.

Provides automated classification and urgency triage for incoming
communications and support requests with production-grade HTTP handling.
"""

import json
import os
import re
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY_SIZE = 16384  # 16 KB payload ceiling

# Category keywords and phrases with explicit domain weights
TAXONOMY = {
    "billing": {
        "phrases": [
            "credit card", "bank transfer", "debit card", "payment failed",
            "charged twice", "double charge", "billing issue", "invoice number",
            "subscription renewal", "cancel subscription", "refund request",
            "money back", "billing cycle", "overcharged me"
        ],
        "keywords": [
            "refund", "invoice", "payment", "bill", "billing", "charge",
            "charged", "pricing", "price", "subscription", "renew", "renewal",
            "receipt", "transaction", "pay", "checkout", "fee", "fees",
            "cost", "debit", "credited", "voucher", "discount", "coupon"
        ]
    },
    "technical": {
        "phrases": [
            "internal server error", "stack trace", "null pointer",
            "connection refused", "500 error", "404 error", "crash on startup",
            "app crashing", "broken link", "page unresponsive", "slow latency",
            "high memory", "system failure", "service unavailable", "api error"
        ],
        "keywords": [
            "error", "bug", "bugs", "crash", "crashes", "crashing", "broken",
            "issue", "fail", "failed", "failure", "glitch", "glitches",
            "exception", "500", "502", "503", "504", "timeout", "timed",
            "slow", "latency", "latency", "down", "outage", "freeze", "freezes",
            "freezing", "syntax", "compile", "runtime", "database", "sql",
            "backend", "frontend", "server", "deploy", "deployment"
        ]
    },
    "account": {
        "phrases": [
            "log in", "sign in", "forgot password", "reset password",
            "change password", "two factor", "2fa code", "mfa code",
            "verification code", "one time password", "account locked",
            "locked out", "access denied", "email verification",
            "unauthorized access", "delete account", "change email"
        ],
        "keywords": [
            "login", "signin", "password", "passwords", "username", "account",
            "accounts", "profile", "auth", "authentication", "credential",
            "credentials", "session", "oauth", "token", "permissions", "mfa",
            "2fa", "otp", "lockout", "register", "signup", "onboarding"
        ]
    }
}

URGENCY_HIGH_PHRASES = [
    "system down", "data loss", "security breach", "production down",
    "cannot login", "hacked", "right now", "as soon as possible",
    "sev 1", "sev-1", "p0", "service outage", "payment down"
]

URGENCY_HIGH_KEYWORDS = [
    "urgent", "urgently", "outage", "immediately", "emergency", "critical",
    "asap", "blocker", "blocking", "breach", "compromised", "down", "hacked",
    "unusable", "catastrophic", "deadline", "danger"
]


def classify(text: str) -> dict:
    """Classifies input text into category, urgency, and confidence score."""
    if not isinstance(text, str):
        return {"category": "general", "urgency": "low", "confidence": 0.5}

    clean_text = text.lower()
    tokens = set(re.findall(r"\b[a-z0-9_-]+\b", clean_text))

    scores = {"billing": 0.0, "technical": 0.0, "account": 0.0}

    for category, patterns in TAXONOMY.items():
        # Phrase matches carry higher weight (3.0 per hit)
        for phrase in patterns["phrases"]:
            if phrase in clean_text:
                scores[category] += 3.0

        # Keyword matches (1.0 per hit)
        for kw in patterns["keywords"]:
            if kw in tokens:
                scores[category] += 1.0

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_cat, best_score = sorted_scores[0]
    second_cat, second_score = sorted_scores[1]

    # Category determination & calibrated confidence
    if best_score <= 0.0:
        category = "general"
        confidence = 0.60
    else:
        category = best_cat
        # Baseline confidence from strong signal, adjusted by separation margin
        base_confidence = 0.75
        margin_boost = min(0.15, (best_score - second_score) * 0.05)
        volume_boost = min(0.08, best_score * 0.02)
        confidence = round(min(0.98, base_confidence + margin_boost + volume_boost), 2)

    # Urgency determination
    urgency_score = 0.0
    for phrase in URGENCY_HIGH_PHRASES:
        if phrase in clean_text:
            urgency_score += 2.5

    for kw in URGENCY_HIGH_KEYWORDS:
        if kw in tokens:
            urgency_score += 1.5

    # Check for emphatic signals (multiple exclamation marks or all-caps)
    if "!!" in text or "!!!" in text:
        urgency_score += 1.0

    words = text.split()
    if len(words) > 3 and sum(1 for w in words if w.isupper() and len(w) > 2) >= 2:
        urgency_score += 1.0

    urgency = "high" if urgency_score >= 1.5 else "low"

    return {
        "category": category,
        "urgency": urgency,
        "confidence": confidence
    }


class TriageHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler implementing the Mycrobo Arena Triage API contract."""

    server_version = "MycroboTriage/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10.0)

    def send_json(self, status: int, data: dict):
        """Sends a JSON response with strict security and content headers."""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Handle preflight CORS requests cleanly."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests (Health check endpoint)."""
        if self.path == "/health" or self.path == "/health/":
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        """Handle POST requests (Classification endpoint)."""
        if self.path not in ("/classify", "/classify/"):
            return self.send_json(404, {"error": "not_found"})

        # Validate Content-Length header
        length_header = self.headers.get("Content-Length")
        if not length_header:
            return self.send_json(400, {"error": "invalid_length"})

        try:
            content_length = int(length_header)
        except (ValueError, TypeError):
            return self.send_json(400, {"error": "invalid_length"})

        # Enforce maximum body size protection (413 Payload Too Large)
        if content_length <= 0:
            return self.send_json(400, {"error": "invalid_json"})

        if content_length > MAX_BODY_SIZE:
            return self.send_json(413, {"error": "body_size"})

        # Read request body with timeout safety
        try:
            raw_body = self.rfile.read(content_length)
        except (IOError, TimeoutError):
            return self.send_json(400, {"error": "read_error"})

        # Parse JSON
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"error": "invalid_json"})

        if not isinstance(body, dict):
            return self.send_json(400, {"error": "invalid_json"})

        # Validate 'text' field
        text_val = body.get("text")
        if not isinstance(text_val, str) or not text_val.strip():
            return self.send_json(400, {"error": "text_required"})

        # Perform classification
        result = classify(text_val)
        return self.send_json(200, result)

    def log_message(self, format, *args):
        """Suppresses default stderr request logging for performance and clean output."""
        pass


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Starts the multi-threaded HTTP server."""
    server = ThreadingHTTPServer((host, port), TriageHandler)
    server.daemon_threads = True

    def handle_exit(signum, frame):
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    print(f"Server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    run_server(host, port)
