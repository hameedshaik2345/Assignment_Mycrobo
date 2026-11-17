# AI Triage Microservice · Mycrobo Arena

[![Track: ai-triage](https://img.shields.io/badge/Track-ai--triage-00C853.svg)](https://arena.mycrobo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-3776AB.svg)](https://www.python.org/)

An automated, architecture-agnostic triage microservice designed for the **Mycrobo Arena Community Hackathon ("AntiSlop")**. It categorizes incoming customer communications, determines operational urgency, and provides calibrated confidence metrics with production-grade resilience.

---

## 1. Architectural Overview

The service is built following the **Anti-Slop** design principles: zero boilerplate, no redundant runtime dependencies, zero bloat, and predictable, deterministic behavior.

```
                    ┌─────────────────────────┐
                    │    HTTP Client / Grader │
                    └───────────┬─────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │  Threading HTTP Server  │
                    │  (Port 8000 / $PORT)    │
                    └───────────┬─────────────┘
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
       ┌──────────────────┐          ┌───────────────────┐
       │   GET /health    │          │  POST /classify   │
       │   200 {"ok":true}│          │  (JSON validation)│
       └──────────────────┘          └─────────┬─────────┘
                                               │
                                               ▼
                                     ┌───────────────────┐
                                     │ Triage Classifier │
                                     │ - Multi-Gram & KW │
                                     │ - Urgency Scorer  │
                                     │ - Confidence Calc │
                                     └───────────────────┘
```

### Key Technical Properties:
- **Zero External Dependencies**: Implemented using the Python 3 standard library (`http.server`, `json`, `re`, `signal`, `threading`). Starts in milliseconds and executes identically on any operating system or GitHub Actions runner.
- **Multi-threaded Concurrency**: Backed by `ThreadingHTTPServer` to process parallel triage requests without blocking.
- **Production Hardening**: Enforces payload size limits (16 KB), validates headers, enforces socket timeouts, and provides standard security headers (`nosniff`, `DENY`).

---

## 2. API Contract

### Health Check
- **Endpoint**: `GET /health`
- **Response**: `200 OK`
```json
{
  "ok": true
}
```

### Ticket & Message Triage
- **Endpoint**: `POST /classify`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
```json
{
  "text": "My payment failed and I was charged twice. Please refund immediately!"
}
```
- **Response**: `200 OK`
```json
{
  "category": "billing",
  "urgency": "high",
  "confidence": 0.95
}
```

### Error Responses
- **400 Bad Request (`text_required`)**: Request body is missing the `text` field or text is whitespace-only.
  ```json
  { "error": "text_required" }
  ```
- **400 Bad Request (`invalid_json`)**: Malformed JSON or non-object payload.
  ```json
  { "error": "invalid_json" }
  ```
- **400 Bad Request (`invalid_length`)**: Missing or non-numeric `Content-Length` header.
  ```json
  { "error": "invalid_length" }
  ```
- **413 Payload Too Large (`body_size`)**: Request body exceeds 16,384 bytes (16 KB).
  ```json
  { "error": "body_size" }
  ```
- **404 Not Found (`not_found`)**: Any unmapped route.
  ```json
  { "error": "not_found" }
  ```

---

## 3. Classification & Triage Taxonomy

The triage engine parses text into normalized tokens and multi-word phrases to calculate weighted category and urgency scores.

### Categories
1. **`billing`**: Invoices, credit card charges, refund requests, subscriptions, pricing, checkout failures, coupon codes.
2. **`technical`**: Server errors (500, 502, 503), crashes, bugs, database timeouts, latency issues, deployment failures, broken UI.
3. **`account`**: Authentication issues, password resets, 2FA/MFA verification, locked profiles, credential updates, onboarding.
4. **`general`**: Non-operational inquiries, product feedback, greetings, roadmap queries, or ambiguous messages.

### Urgency Determination
- **`high`**: Outages, production blockers (Sev-1 / P0), critical bugs, data loss risks, compromised credentials, or queries demanding immediate intervention.
- **`low`**: Standard inquiries, minor suggestions, cosmetic queries, and routine operational support.

### Confidence Calibration
Confidence values are strictly bounded between `0.0` and `1.0`:
- **Strong Intent ($\ge 0.85$)**: High keyword frequency and multi-word phrase matches with a clear separation from competing categories.
- **Moderate Intent ($0.70 - 0.84$)**: Single strong keyword or domain match.
- **Baseline Intent ($0.50 - 0.65$)**: Fallback or low-density classification.

---

## 4. Quick Start & Development

### Prerequisites
- Python 3.8 or higher. No third-party packages required.

### Installation
```bash
python -m pip install -r requirements.txt
```

### Running the Test Suite
```bash
python -m unittest discover -v
```
All unit tests and end-to-end HTTP integration tests run in under 1 second.

### Starting the Server
```bash
python app.py
```
The server will bind to `0.0.0.0:8000` (or the port specified by `$PORT`).

---

## 5. Grader Configuration (`arena.json`)

The repository root includes `arena.json` configured for Mycrobo Arena's automated testing pipeline:

```json
{
  "language": "python",
  "install": "python -m pip install -r requirements.txt",
  "test": "python -m unittest discover -v",
  "start": "python app.py",
  "port": 8000
}
```

