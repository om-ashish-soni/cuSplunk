"""
mock_store.py — CPU-only in-memory store mock for dev/CI.

Accepts Write requests (HTTP POST /write) and serves Scan requests
(HTTP POST /scan) returning fixture events from FIXTURES_PATH.

No GPU. No Arrow. No gRPC (stub: just HTTP for dev convenience).
"""

import json
import os
import time
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

FIXTURES_PATH = os.environ.get("FIXTURES_PATH", "/fixtures")

# In-memory event store: list of dicts, appended on Write
_events: list[dict] = []
_lock = threading.Lock()

# Preload fixture data so Scan has something to return immediately
def _load_fixtures() -> None:
    for fname in ["events/windows_event_log_1000.json", "events/firewall_sample.json"]:
        path = os.path.join(FIXTURES_PATH, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                data = json.load(f)
            events = data if isinstance(data, list) else data.get("events", [])
            with _lock:
                _events.extend(events)
            print(f"[mock-store] loaded {len(events)} events from {fname}")
        except Exception as e:
            print(f"[mock-store] warning: could not load {fname}: {e}")


class MockStoreHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default access log noise
        pass

    def _send_json(self, code: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            with _lock:
                count = len(_events)
            self._send_json(200, {"status": "ok", "event_count": count})
        elif path == "/stats":
            with _lock:
                count = len(_events)
            self._send_json(200, {
                "event_count": count,
                "indexes": list({e.get("index", "main") for e in _events}),
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"

        if path == "/write":
            try:
                req = json.loads(body)
                events = req.get("events", [])
                with _lock:
                    _events.extend(events)
                self._send_json(200, {"written": len(events)})
            except Exception as e:
                self._send_json(400, {"error": str(e)})

        elif path == "/scan":
            try:
                req = json.loads(body)
                index = req.get("index", "main")
                earliest = req.get("earliest", 0)
                latest = req.get("latest", int(time.time()))
                limit = req.get("limit", 1000)

                with _lock:
                    results = [
                        e for e in _events
                        if e.get("index", "main") == index
                        and earliest <= e.get("_time", 0) <= latest
                    ]

                results = results[:limit]
                self._send_json(200, {"events": results, "count": len(results)})
            except Exception as e:
                self._send_json(400, {"error": str(e)})

        elif path == "/reset":
            # Test helper: clear all in-memory events and reload fixtures
            with _lock:
                _events.clear()
            _load_fixtures()
            self._send_json(200, {"status": "reset"})

        else:
            self._send_json(404, {"error": "not found"})


def main():
    _load_fixtures()
    server = HTTPServer(("0.0.0.0", 8081), MockStoreHandler)
    print("[mock-store] listening on :8081 (HTTP)")
    server.serve_forever()


if __name__ == "__main__":
    main()
