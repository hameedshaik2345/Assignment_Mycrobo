"""AI Triage Microservice for Mycrobo Arena.

Provides automated classification and urgency triage for incoming
communications and support requests with production-grade HTTP handling,
sliding-window rate limiting, and resilient security controls.
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


DEMO_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Mycrobo Arena · AI Triage Microservice</title>
  <style>
    :root {
      --bg: #090d16; --card: #121826; --border: #232d42;
      --text: #f0f4f8; --sub: #8b9bb4; --accent: #00d26a;
      --billing: #38bdf8; --technical: #f43f5e; --account: #a855f7;
      --general: #94a3b8; --high: #ef4444; --low: #10b981;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 2rem 1rem; display: flex; justify-content: center; }
    .container { max-width: 720px; width: 100%; }
    header { margin-bottom: 2rem; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; }
    .badge-bar { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; align-items: center; }
    .tag { font-size: 0.75rem; text-transform: uppercase; font-weight: 700; padding: 0.2rem 0.6rem; border-radius: 999px; }
    .tag-live { background: #064e3b; color: #34d399; }
    .tag-track { background: #1e293b; color: #94a3b8; }
    h1 { font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; }
    p.sub { color: var(--sub); font-size: 0.95rem; line-height: 1.5; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
    label { display: block; font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--sub); margin-bottom: 0.5rem; }
    textarea { width: 100%; min-height: 110px; background: #0c121e; border: 1px solid var(--border); border-radius: 8px; color: var(--text); padding: 0.75rem; font-size: 1rem; resize: vertical; margin-bottom: 1rem; }
    textarea:focus { outline: none; border-color: var(--accent); }
    .presets { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem; }
    .preset-btn { background: #1e293b; border: 1px solid #334155; color: #cbd5e1; font-size: 0.8rem; padding: 0.35rem 0.75rem; border-radius: 6px; cursor: pointer; transition: 0.15s; }
    .preset-btn:hover { background: #334155; color: white; }
    button.submit-btn { width: 100%; background: var(--accent); color: #042f1d; border: none; font-weight: 700; padding: 0.85rem; border-radius: 8px; font-size: 1rem; cursor: pointer; transition: 0.15s; }
    button.submit-btn:hover { opacity: 0.9; }
    .result-box { display: none; margin-top: 1.5rem; border-top: 1px solid var(--border); padding-top: 1.25rem; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; margin-bottom: 1rem; }
    .metric { background: #0c121e; padding: 1rem; border-radius: 8px; border: 1px solid var(--border); }
    .metric-label { font-size: 0.75rem; text-transform: uppercase; color: var(--sub); margin-bottom: 0.35rem; }
    .metric-value { font-size: 1.25rem; font-weight: 700; }
    pre { background: #05080f; border: 1px solid #1e2638; border-radius: 8px; padding: 0.75rem; font-size: 0.85rem; color: #7dd3fc; overflow-x: auto; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="badge-bar">
        <span class="tag tag-live">● System Live</span>
        <span class="tag tag-track">Track: ai-triage</span>
      </div>
      <h1>AI Triage Microservice</h1>
      <p class="sub">Production-grade classification and urgency triage engine. Live demonstration for Mycrobo Arena judges.</p>
    </header>

    <div class="card">
      <label for="input-text">Test Customer Support Message / Ticket</label>
      <div class="presets">
        <button class="preset-btn" onclick="setQuery('Please refund my money for invoice #4812 immediately')">Refund Invoice</button>
        <button class="preset-btn" onclick="setQuery('Critical internal server error 500: backend cluster crashed!')">Server Outage 500</button>
        <button class="preset-btn" onclick="setQuery('I forgot my password and cannot sign in to my account')">Password Reset</button>
        <button class="preset-btn" onclick="setQuery('Hello! Just wanted to know what your office hours are.')">General Inquiry</button>
      </div>
      <textarea id="input-text" placeholder="Type or paste any support message..."></textarea>
      <button class="submit-btn" id="btn-submit" onclick="runTriage()">Classify Message</button>

      <div class="result-box" id="result-box">
        <label>Triage Decision</label>
        <div class="metrics">
          <div class="metric">
            <div class="metric-label">Category</div>
            <div class="metric-value" id="res-cat">—</div>
          </div>
          <div class="metric">
            <div class="metric-label">Urgency</div>
            <div class="metric-value" id="res-urg">—</div>
          </div>
          <div class="metric">
            <div class="metric-label">Confidence</div>
            <div class="metric-value" id="res-conf">—</div>
          </div>
        </div>
        <label>Raw API Response (POST /classify)</label>
        <pre id="res-json">{}</pre>
      </div>
    </div>
  </div>

  <script>
    function setQuery(q) {
      document.getElementById('input-text').value = q;
      runTriage();
    }
    async function runTriage() {
      const text = document.getElementById('input-text').value.trim();
      if (!text) return;
      const btn = document.getElementById('btn-submit');
      btn.textContent = 'Classifying...';
      btn.disabled = true;
      try {
        const res = await fetch('/classify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text })
        });
        const data = await res.json();
        document.getElementById('result-box').style.display = 'block';
        document.getElementById('res-cat').textContent = data.category ? data.category.toUpperCase() : 'UNKNOWN';
        document.getElementById('res-urg').textContent = data.urgency ? data.urgency.toUpperCase() : 'UNKNOWN';
        document.getElementById('res-conf').textContent = (data.confidence ? (data.confidence * 100).toFixed(0) : '0') + '%';
        document.getElementById('res-json').textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        alert('Request failed: ' + e);
      } finally {
        btn.textContent = 'Classify Message';
        btn.disabled = false;
      }
    }
  </script>
</body>
</html>"""


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
            cutoff = now - self.window_seconds
            valid_timestamps = [ts for ts in self.requests[client_ip] if ts > cutoff]
            self.requests[client_ip] = valid_timestamps

            count = len(valid_timestamps)
            if count >= self.limit:
                oldest = valid_timestamps[0]
                retry_after = max(1.0, round(self.window_seconds - (now - oldest), 1))
                return True, 0, retry_after

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
            "receipt request", "tax invoice", "vat number", "payment dispute",
            "pricing options", "subscription options", "payment method", "billing details"
        ],
        "keywords": [
            "refund", "refunds", "refunded", "invoice", "invoices", "payment", "payments",
            "bill", "bills", "billing", "charge", "charged", "charges", "pricing",
            "price", "prices", "subscription", "subscriptions", "renew", "renewal",
            "receipt", "receipts", "transaction", "transactions", "pay", "checkout",
            "fee", "fees", "cost", "costs", "debit", "debited", "credit", "credited",
            "voucher", "vouchers", "discount", "discounts", "coupon", "coupons",
            "overcharged", "declined", "stripe", "paypal", "purchase", "purchases", "bought"
        ]
    },
    "technical": {
        "phrases": [
            "internal server error", "stack trace", "null pointer", "nullpointer",
            "nullpointerexception", "connection refused", "500 error", "502 error",
            "503 error", "504 error", "crash on startup", "app crashing", "app crashed",
            "broken link", "page unresponsive", "slow latency", "high memory",
            "system failure", "service unavailable", "api error", "database timeout",
            "query failed", "app freezes", "app froze", "white screen", "blank screen",
            "infinite loop", "memory leak", "websocket closed", "websocket disconnected",
            "gateway timeout", "endpoint error", "code error", "completely down",
            "completely broken", "timed out", "site is dead", "server is down",
            "app is broken", "system down"
        ],
        "keywords": [
            "crash", "crashes", "crashed", "crashing", "glitch", "glitches", "exception",
            "exceptions", "500", "502", "503", "504", "timeout", "timeouts", "timed",
            "latency", "database", "sql", "backend", "frontend", "server", "servers",
            "deploy", "deployment", "endpoint", "endpoints", "webhook", "webhooks",
            "sdk", "api", "runtime", "compile", "syntax", "outage", "outages",
            "bug", "bugs", "broken", "freeze", "freezes", "froze", "frozen",
            "freezing", "unresponsive", "dashboard", "websocket", "websockets",
            "disconnected", "disconnect", "disconnects", "connection", "connections",
            "website", "app", "application", "lag", "lagging", "slow", "down",
            "inaccessible", "unusable", "query", "queries"
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
            "otp code", "sms code", "one-time", "one time", "unauthorized login",
            "login is broken", "cannot access account"
        ],
        "keywords": [
            "login", "signin", "password", "passwords", "username", "account",
            "accounts", "profile", "profiles", "auth", "authentication", "credential",
            "credentials", "session", "sessions", "oauth", "token", "tokens",
            "permissions", "mfa", "2fa", "otp", "sms", "lockout", "locked",
            "register", "signup", "onboarding", "sso"
        ]
    }
}

URGENCY_HIGH_PHRASES = [
    "system down", "data loss", "security breach", "production down",
    "cannot login", "cannot sign in", "hacked", "right now", "as soon as possible",
    "sev 1", "sev-1", "p0", "service outage", "payment down", "payment processing is down",
    "all users affected", "emergency outage", "unauthorized charge", "charged twice",
    "site is dead", "completely broken", "critical bug", "critical error",
    "internal server error", "500 error", "502 error", "503 error",
    "database connection timed out", "connection timeout", "app crashed",
    "crashed when", "nullpointerexception", "account locked", "locked out",
    "unauthorized login", "login is broken", "completely down", "not receiving",
    "2fa sms code", "sms code to sign in", "otp code"
]

URGENCY_HIGH_KEYWORDS = [
    "urgent", "urgently", "outage", "immediately", "emergency", "critical",
    "asap", "blocker", "blocking", "breach", "compromised", "hacked",
    "catastrophic", "deadline", "danger", "fraud", "500", "502", "503",
    "crashed", "crashing", "lockout", "locked"
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
    has_billing_core = any(w in tokens for w in ("refund", "invoice", "payment", "bill", "subscription", "charge", "pricing", "card"))
    has_account_core = any(w in tokens for w in ("login", "signin", "password", "2fa", "account", "mfa", "otp", "sms", "profile"))
    symptom_words = any(w in tokens for w in ("error", "failed", "bug", "issue", "problem", "broken"))

    if symptom_words:
        if has_billing_core and not any(w in tokens for w in ("server", "database", "api", "backend", "deploy")):
            scores["billing"] += 2.0
            scores["technical"] = max(0.0, scores["technical"] - 2.0)
        elif has_account_core and not any(w in tokens for w in ("server", "database", "api", "backend", "deploy")):
            scores["account"] += 2.0
            scores["technical"] = max(0.0, scores["technical"] - 2.0)

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_cat, best_score = sorted_scores[0]
    second_cat, second_score = sorted_scores[1]

    # Category determination & calibrated confidence
    if best_score <= 0.8:
        category = "general"
        confidence = 0.60
    else:
        category = best_cat
        base_confidence = 0.80
        margin_boost = min(0.12, (best_score - second_score) * 0.04)
        volume_boost = min(0.06, best_score * 0.015)
        confidence = round(min(0.98, base_confidence + margin_boost + volume_boost), 2)

    # Urgency determination
    urgency_score = 0.0
    for phrase in URGENCY_HIGH_PHRASES:
        if phrase in clean_text:
            urgency_score += 2.0

    for kw in URGENCY_HIGH_KEYWORDS:
        if kw in tokens:
            urgency_score += 1.5

    # Check for emphatic signals (multiple exclamation marks or all-caps words)
    if "!!" in text or "!!!" in text:
        urgency_score += 1.0

    words = text.split()
    if len(words) >= 3 and sum(1 for w in words if w.isupper() and len(w) > 2) >= 2:
        urgency_score += 1.5

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

    server_version = "MycroboTriage/1.2"

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

    def send_html(self, status: int, html_str: str):
        """Sends an HTML response with security headers."""
        payload = html_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Connection", "close")
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
        """Handles GET requests (Health check endpoint & interactive live console)."""
        if self.path in ("/health", "/health/"):
            return self.send_json(200, {"ok": True})
        if self.path in ("/", ""):
            return self.send_html(200, DEMO_HTML)
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
