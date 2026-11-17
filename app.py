"""AI Triage Microservice for Mycrobo Arena.

Provides automated classification and urgency triage for incoming
communications and support requests with production-grade HTTP handling,
rate limiting, and resilient security controls.
"""

import json
import os
import re
import signal
import sys
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_BODY_SIZE = 16384  # 16 KB payload ceiling


# ==============================================================================
# Rate Limiting (Production-Readiness Check #1)
# ==============================================================================
class RateLimiter:
    """Thread-safe sliding-window rate limiter per client IP address."""

    def __init__(self, limit: int = 120, window_seconds: float = 60.0):
        self.limit = limit
        self.window_seconds = window_seconds
        self.requests = defaultdict(list)
        self.lock = threading.Lock()

    def is_rate_limited(self, client_ip: str) -> tuple[bool, int, float]:
        """Checks if client exceeded rate limit.

        Returns (is_limited, remaining_requests, retry_after_seconds).
        """
        now = time.time()
        with self.lock:
            # Purge expired timestamps
            cutoff = now - self.window_seconds
            valid_timestamps = [ts for ts in self.requests[client_ip] if ts > cutoff]
            self.requests[client_ip] = valid_timestamps

            count = len(valid_timestamps)
            if count >= self.limit:
                oldest = valid_timestamps[0]
                retry_after = max(1.0, round(self.window_seconds - (now - oldest), 1))
                return True, 0, retry_after

            # Record this request
            self.requests[client_ip].append(now)
            remaining = self.limit - (count + 1)
            return False, remaining, 0.0

    def reset(self):
        """Clears all tracking data."""
        with self.lock:
            self.requests.clear()


# Global rate limiter instance (120 req/minute per IP)
global_rate_limiter = RateLimiter(limit=120, window_seconds=60.0)


# ==============================================================================
# Triage Taxonomy & Entity Disambiguation
# ==============================================================================
TAXONOMY = {
    "billing": {
        "phrases": [
            "credit card", "bank transfer", "debit card", "payment failed",
            "payment failure", "billing error", "charge error", "charged twice",
            "double charge", "billing issue", "invoice number", "subscription renewal",
            "cancel subscription", "refund request", "money back", "billing cycle",
            "overcharged me", "declined card", "card declined", "update payment",
            "pricing plan", "change plan", "upgrade plan", "downgrade plan",
            "receipt request", "tax invoice", "vat number", "payment dispute"
        ],
        "keywords": [
            "refund", "invoice", "payment", "bill", "billing", "charge",
            "charged", "pricing", "price", "subscription", "renew", "renewal",
            "receipt", "transaction", "pay", "checkout", "fee", "fees",
            "cost", "debit", "credited", "voucher", "discount", "coupon",
            "overcharged", "declined", "stripe", "paypal", "purchase", "bought"
        ]
    },
    "technical": {
        "phrases": [
            "internal server error", "stack trace", "null pointer", "nullpointer",
            "connection refused", "500 error", "502 error", "503 error", "504 error",
            "crash on startup", "app crashing", "broken link", "page unresponsive",
            "slow latency", "high memory", "system failure", "service unavailable",
            "api error", "database timeout", "query failed", "app freezes",
            "white screen", "blank screen", "infinite loop", "memory leak",
            "websocket closed", "gateway timeout", "endpoint error", "code error"
        ],
        "keywords": [
            "crash", "crashes", "crashing", "glitch", "glitches", "exception",
            "500", "502", "503", "504", "timeout", "latency", "database",
            "sql", "backend", "frontend", "server", "deploy", "deployment",
            "endpoint", "webhook", "sdk", "api", "runtime", "compile",
            "syntax", "outage", "bug", "bugs", "broken", "freeze", "freezes",
            "freezing", "unresponsive", "dashboard", "websocket", "disconnected",
            "disconnect", "connection"
        ]
    },
    "account": {
        "phrases": [
            "log in", "sign in", "forgot password", "reset password",
            "change password", "two factor", "2fa code", "mfa code",
            "verification code", "one time password", "account locked",
            "locked out", "access denied", "email verification", "verify email",
            "unauthorized access", "delete account", "change email", "update profile",
            "sso login", "single sign on", "suspicious login", "login failed",
            "cannot log in", "cannot sign in", "sign up", "sign out", "log out",
            "otp code", "sms code", "one-time", "one time"
        ],
        "keywords": [
            "login", "signin", "password", "passwords", "username", "account",
            "accounts", "profile", "auth", "authentication", "credential",
            "credentials", "session", "oauth", "token", "permissions", "mfa",
            "2fa", "otp", "sms", "lockout", "register", "signup", "onboarding", "sso"
        ]
    }
}

URGENCY_HIGH_PHRASES = [
    "system down", "data loss", "security breach", "production down",
    "cannot login", "hacked", "right now", "as soon as possible",
    "sev 1", "sev-1", "p0", "service outage", "payment down",
    "all users affected", "emergency outage", "unauthorized charge",
    "site is dead", "completely broken", "critical bug", "critical error"
]

URGENCY_HIGH_KEYWORDS = [
    "urgent", "urgently", "outage", "immediately", "emergency", "critical",
    "asap", "blocker", "blocking", "breach", "compromised", "down", "hacked",
    "unusable", "catastrophic", "deadline", "danger", "fraud"
]


def classify(text: str) -> dict:
    """Classifies input text into category, urgency, and calibrated confidence."""
    if not isinstance(text, str):
        return {"category": "general", "urgency": "low", "confidence": 0.50}

    clean_text = text.lower()
    tokens = set(re.findall(r"\b[a-z0-9_-]+\b", clean_text))

    scores = {"billing": 0.0, "technical": 0.0, "account": 0.0}

    for category, patterns in TAXONOMY.items():
        # Phrase matches carry primary weight (3.5 per hit)
        for phrase in patterns["phrases"]:
            if phrase in clean_text:
                scores[category] += 3.5

        # Keyword matches (1.2 per hit)
        for kw in patterns["keywords"]:
            if kw in tokens:
                scores[category] += 1.2

    # Contextual disambiguation:
    # If billing or account has core entities, symptoms like "error" or "failed"
    # belong to that domain rather than technical.
    has_billing_core = any(w in tokens for w in ("refund", "invoice", "payment", "bill", "subscription", "charge"))
    has_account_core = any(w in tokens for w in ("login", "signin", "password", "2fa", "account", "mfa", "otp", "sms"))
    symptom_words = any(w in tokens for w in ("error", "failed", "bug", "issue", "problem", "broken"))

    if symptom_words:
        if has_billing_core and not any(w in tokens for w in ("server", "database", "api", "backend", "deploy")):
            scores["billing"] += 1.5
            scores["technical"] = max(0.0, scores["technical"] - 1.5)
        elif has_account_core and not any(w in tokens for w in ("server", "database", "api", "backend", "deploy")):
            scores["account"] += 1.5
            scores["technical"] = max(0.0, scores["technical"] - 1.5)

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_cat, best_score = sorted_scores[0]
    second_cat, second_score = sorted_scores[1]

    # Category determination & calibrated confidence
    if best_score <= 0.8:
        category = "general"
        confidence = 0.60
    else:
        category = best_cat
        base_confidence = 0.78
        margin_boost = min(0.12, (best_score - second_score) * 0.04)
        volume_boost = min(0.08, best_score * 0.015)
        confidence = round(min(0.98, base_confidence + margin_boost + volume_boost), 2)

    # Urgency determination
    urgency_score = 0.0
    for phrase in URGENCY_HIGH_PHRASES:
        if phrase in clean_text:
            urgency_score += 2.5

    for kw in URGENCY_HIGH_KEYWORDS:
        if kw in tokens:
            urgency_score += 1.5

    # Check for emphatic signals (multiple exclamation marks or all-caps words)
    if "!!" in text or "!!!" in text:
        urgency_score += 1.0

    words = text.split()
    if len(words) >= 3 and sum(1 for w in words if w.isupper() and len(w) > 2) >= 2:
        urgency_score += 1.0

    urgency = "high" if urgency_score >= 1.5 else "low"

    return {
        "category": category,
        "urgency": urgency,
        "confidence": confidence
    }


# ==============================================================================
# HTTP Server Handler
# ==============================================================================
class TriageHandler(BaseHTTPRequestHandler):
    """HTTP Request Handler implementing the Mycrobo Arena Triage API contract."""

    server_version = "MycroboTriage/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10.0)

    @property
    def client_address_ip(self) -> str:
        """Extracts client IP safely."""
        return self.client_address[0] if self.client_address else "127.0.0.1"

    def send_json(self, status: int, data: dict, extra_headers: dict = None):
        """Sends a JSON response with strict security, CORS, and rate limit headers."""
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, str(v))

        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Handles preflight CORS requests cleanly."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        """Handles GET requests (Health check endpoint)."""
        if self.path in ("/health", "/health/"):
            return self.send_json(200, {"ok": True})
        return self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        """Handles POST requests (Classification endpoint with Rate Limiting)."""
        if self.path not in ("/classify", "/classify/"):
            return self.send_json(404, {"error": "not_found"})

        # Rate Limiting check (Check #1)
        is_limited, remaining, retry_after = global_rate_limiter.is_rate_limited(self.client_address_ip)
        rate_headers = {
            "X-RateLimit-Limit": global_rate_limiter.limit,
            "X-RateLimit-Remaining": remaining,
        }
        if is_limited:
            rate_headers["Retry-After"] = int(retry_after)
            return self.send_json(
                429,
                {"error": "rate_limit_exceeded", "message": "Too many requests. Please retry later."},
                extra_headers=rate_headers
            )

        # Validate Content-Length header
        length_header = self.headers.get("Content-Length")
        if not length_header:
            return self.send_json(400, {"error": "invalid_length"}, extra_headers=rate_headers)

        try:
            content_length = int(length_header)
        except (ValueError, TypeError):
            return self.send_json(400, {"error": "invalid_length"}, extra_headers=rate_headers)

        # Enforce maximum body size protection (413 Payload Too Large)
        if content_length <= 0:
            return self.send_json(400, {"error": "invalid_json"}, extra_headers=rate_headers)

        if content_length > MAX_BODY_SIZE:
            return self.send_json(413, {"error": "body_size"}, extra_headers=rate_headers)

        # Read request body with timeout safety
        try:
            raw_body = self.rfile.read(content_length)
        except (IOError, TimeoutError):
            return self.send_json(400, {"error": "read_error"}, extra_headers=rate_headers)

        # Parse JSON
        try:
            body = json.loads(raw_body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"error": "invalid_json"}, extra_headers=rate_headers)

        if not isinstance(body, dict):
            return self.send_json(400, {"error": "invalid_json"}, extra_headers=rate_headers)

        # Validate 'text' field
        text_val = body.get("text")
        if not isinstance(text_val, str) or not text_val.strip():
            return self.send_json(400, {"error": "text_required"}, extra_headers=rate_headers)

        # Perform classification
        result = classify(text_val)
        return self.send_json(200, result, extra_headers=rate_headers)

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
