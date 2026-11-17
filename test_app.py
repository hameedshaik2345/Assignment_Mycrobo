"""Unit and integration test suite for Mycrobo Arena AI Triage service."""

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from app import TriageHandler, classify


class TestClassificationLogic(unittest.TestCase):
    """Tests the intent, category, urgency, and confidence scoring."""

    def test_billing_classification(self):
        cases = [
            "Please refund this invoice immediately",
            "I was charged twice on my credit card this month",
            "Where can I find my latest payment receipt?",
            "I would like to cancel my subscription renewal",
            "Can you apply a discount coupon to my billing cycle?"
        ]
        for query in cases:
            res = classify(query)
            self.assertEqual(res["category"], "billing", f"Failed for: {query}")
            self.assertGreaterEqual(res["confidence"], 0.70)

    def test_technical_classification(self):
        cases = [
            "The app is broken and crashes on startup",
            "Getting internal server error 500 when calling the API",
            "Database connection timeout and high latency observed",
            "Found a critical bug in the deployment pipeline",
            "The dashboard is freezing up and completely unresponsive"
        ]
        for query in cases:
            res = classify(query)
            self.assertEqual(res["category"], "technical", f"Failed for: {query}")
            self.assertGreaterEqual(res["confidence"], 0.70)

    def test_account_classification(self):
        cases = [
            "I forgot my password and cannot sign in",
            "Need to reset my two factor 2fa verification code",
            "My account is locked out after multiple attempts",
            "How do I update my username and email address?",
            "Unable to log in with my authentication credentials"
        ]
        for query in cases:
            res = classify(query)
            self.assertEqual(res["category"], "account", f"Failed for: {query}")
            self.assertGreaterEqual(res["confidence"], 0.70)

    def test_general_classification(self):
        cases = [
            "Hello there, what are your opening hours?",
            "Nice product, thanks for the hard work!",
            "Where is your company headquarters located?",
            "Do you have a public roadmap for future features?"
        ]
        for query in cases:
            res = classify(query)
            self.assertEqual(res["category"], "general", f"Failed for: {query}")
            self.assertGreaterEqual(res["confidence"], 0.50)

    def test_urgency_detection(self):
        high_cases = [
            "CRITICAL: Production server is down right now!",
            "Emergency outage affecting all active users immediately",
            "URGENT data loss detected in database!!",
            "Sev 1 incident: payments are failing for all customers"
        ]
        for query in high_cases:
            res = classify(query)
            self.assertEqual(res["urgency"], "high", f"Failed urgency for: {query}")

        low_cases = [
            "Just a quick question about your color scheme",
            "Whenever you have time, can you check this typo?",
            "Curious about how your team approaches onboarding"
        ]
        for query in low_cases:
            res = classify(query)
            self.assertEqual(res["urgency"], "low", f"Failed urgency for: {query}")

    def test_confidence_constraints(self):
        queries = ["Refund please", "Error 500", "Hello", "Sign in issue", ""]
        for q in queries:
            res = classify(q)
            self.assertIsInstance(res["confidence"], float)
            self.assertGreaterEqual(res["confidence"], 0.0)
            self.assertLessEqual(res["confidence"], 1.0)


class TestHttpServerIntegration(unittest.TestCase):
    """End-to-end integration tests over real HTTP requests."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), TriageHandler)
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, method="GET", body=None, headers=None, raw_body=None):
        url = f"{self.base_url}{path}"
        req_headers = headers or {}
        data = None

        if raw_body is not None:
            data = raw_body
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read().decode("utf-8")
                return resp.status, resp.headers, json.loads(resp_body) if resp_body else {}
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8")
            try:
                parsed = json.loads(err_body)
            except Exception:
                parsed = {"raw": err_body}
            return err.code, err.headers, parsed

    def test_health_endpoint(self):
        status, headers, body = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})
        self.assertIn("application/json", headers.get("Content-Type", ""))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_classify_valid_request(self):
        payload = {"text": "I need an urgent refund for my invoice #1234"}
        status, headers, body = self.request("/classify", method="POST", body=payload)
        self.assertEqual(status, 200)
        self.assertEqual(body["category"], "billing")
        self.assertEqual(body["urgency"], "high")
        self.assertGreater(body["confidence"], 0.7)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def test_classify_missing_text_field(self):
        status, _, body = self.request("/classify", method="POST", body={"other": 123})
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "text_required")

    def test_classify_empty_text_field(self):
        status, _, body = self.request("/classify", method="POST", body={"text": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "text_required")

    def test_classify_invalid_json(self):
        raw = b"{ malformed: json ]"
        status, _, body = self.request(
            "/classify",
            method="POST",
            raw_body=raw,
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)
        self.assertEqual(body.get("error"), "invalid_json")

    def test_classify_oversized_payload(self):
        large_text = "error " * 4000  # > 16 KB
        payload = {"text": large_text}
        status, _, body = self.request("/classify", method="POST", body=payload)
        self.assertEqual(status, 413)
        self.assertEqual(body.get("error"), "body_size")

    def test_not_found_endpoint(self):
        status, _, body = self.request("/non-existent")
        self.assertEqual(status, 404)
        self.assertEqual(body.get("error"), "not_found")


if __name__ == "__main__":
    unittest.main()
