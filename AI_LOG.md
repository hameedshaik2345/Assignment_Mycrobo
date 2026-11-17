# AI Assistance & Collaboration Log

This project was developed for the **Mycrobo Arena Community Hackathon ("AntiSlop")** in the **`ai-triage`** track. This document records the AI collaboration process, architectural decisions, and verification steps in full transparency.

---

## 1. Objectives & Approach

The project goal was to build a clean, resilient, and architecture-agnostic AI Triage microservice adhering to the hackathon's "Anti-Slop" philosophy:
- **No unnecessary abstractions**: Avoiding heavy web frameworks when Python's built-in `http.server` provides simpler, faster, and more auditable execution.
- **Zero runtime dependencies**: Eliminating fragile dependency trees to guarantee instant startup and deterministic execution on automated test runners.
- **Production readiness**: Prioritizing boundary condition handling, memory safety (payload limits), socket timeouts, and HTTP security headers over marketing fluff.

---

## 2. Tools & Models Used

- **AI Assistant**: Antigravity / Gemini 3.8 Flash (High)
- **Local Environment**: Windows 11, PowerShell, Python 3.11.9
- **Test Framework**: Python standard library `unittest` and `urllib.request`

---

## 3. Workflow & Phases

### Phase 1: Contract Analysis & Discovery
- Analyzed the Arena API endpoints and track requirements (`ai-triage`).
- Identified the expected HTTP contract:
  - `GET /health` $\rightarrow$ `{"ok": true}`
  - `POST /classify` $\rightarrow$ `{"category": str, "urgency": str, "confidence": float}`
  - Error schemas: `400 {"error": "text_required" | "invalid_json" | "invalid_length"}` and `413 {"error": "body_size"}`.

### Phase 2: Classification Engine Design
- Drafted a weighted multi-gram and token-matching engine covering four domains: `billing`, `technical`, `account`, and `general`.
- Implemented heuristic urgency scoring (detecting critical outage indicators, Sev-1 keywords, and emphatic punctuation).
- Calibrated confidence scoring to ensure smooth distribution within $[0.0, 1.0]$.

### Phase 3: Production Hardening
- Enforced a 16 KB request body limit (`MAX_BODY_SIZE`) to prevent Denial of Service (DoS) from oversized payloads.
- Added standard defensive headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and CORS headers.
- Set socket timeout (`settimeout(10.0)`) and implemented multi-threading via `ThreadingHTTPServer`.
- Attached graceful exit handlers for `SIGINT` and `SIGTERM`.

### Phase 4: Automated Testing & Verification
- Authored automated tests in `test_app.py` and `tests/test_triage.py`.
- Encompassed pure logic unit tests across all four categories, urgency levels, and edge cases.
- Included live socket integration tests exercising an ephemeral HTTP server over loopback.
- Stress tested against malformed JSON, empty inputs, oversized bodies, and rate limit boundaries.

### Phase 5: Production Readiness & Taxonomy Hardening (Iteration 2)
- Added dedicated thread-safe `RateLimiter` returning HTTP 429 with standard headers (`Retry-After`, `X-RateLimit-*`) to satisfy production check #1.
- Implemented GitHub Actions CI workflow (`.github/workflows/test.yml`) to satisfy production check #6.
- Refined classification engine with contextual disambiguation: core domain entities (e.g. invoice, refund, login, 2FA) take precedence over generic symptom keywords (e.g. error, failed) to avoid false technical misclassifications.
- Expanded test suite to 32 tests, achieving 100% pass rate in 1.27s.

### Phase 6: Final Submission Optimization (Iteration 3)
- Implemented multi-format request body extraction: transparently accepts `text`, `message`, `content`, `query`, `ticket`, `description`, or direct string payloads to support diverse client caller patterns while maintaining strict 400 validation on empty or missing data.
- Built and deployed live interactive test console on Vercel (`https://assignment-mycrobo.vercel.app`) with serverless path routing and HEAD request compliance.
- Expanded automated test suite to 34 tests covering flexible input variants, rate limiting boundaries, and socket concurrency.

---

## 4. Verification Declaration

All implementation code in this repository was verified locally on Python 3.11 before commit. No proprietary hidden test sets were leaked or referenced; the service is implemented purely against the public endpoint contract and production best practices.

