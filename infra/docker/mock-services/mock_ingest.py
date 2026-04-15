"""
mock_ingest.py — CPU-only ingest mock for dev/CI.

Listens for HEC events on :8088 and writes them to OUTPUT_FILE.
Also exposes a minimal S2S TCP listener on :9997 that accepts
connections and ACKs without actually parsing the binary protocol.

No GPU. No cuDF. Pure stdlib.
"""

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "/tmp/ingest.log")
MOCK_STORE_URL = os.environ.get("MOCK_STORE_URL", "http://mock-store:8081")

_file_lock = threading.Lock()


def _append_events(events: list[dict]) -> None:
    with _file_lock:
        with open(OUTPUT_FILE, "a") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")


def _forward_to_store(events: list[dict]) -> None:
    """Best-effort forward to mock-store. Swallow errors — dev mock only."""
    try:
        import urllib.request
        payload = json.dumps({"events": events}).encode()
        req = urllib.request.Request(
            f"{MOCK_STORE_URL}/write",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass


class HECHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
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
        if path in ("/services/collector/health", "/services/collector/health/1.0"):
            self._send_json(200, {"text": "HEC is healthy", "code": 17})
        else:
            self._send_json(404, {"text": "Not found", "code": 9})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        # Validate HEC token (accept anything in dev)
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Splunk ") and not auth.startswith("Bearer "):
            self._send_json(403, {"text": "Invalid token", "code": 4})
            return

        if path in ("/services/collector/event", "/services/collector/event/1.0"):
            try:
                # HEC allows multiple JSON objects concatenated (no array wrapper)
                events = []
                decoder = json.JSONDecoder()
                raw = body.decode("utf-8", errors="replace").strip()
                idx = 0
                while idx < len(raw):
                    obj, end = decoder.raw_decode(raw, idx)
                    event = obj.get("event", obj)
                    if isinstance(event, str):
                        event = {"_raw": event}
                    event.setdefault("_time", obj.get("time", time.time()))
                    event.setdefault("host", obj.get("host", "unknown"))
                    event.setdefault("source", obj.get("source", "hec"))
                    event.setdefault("sourcetype", obj.get("sourcetype", "_json"))
                    event.setdefault("index", obj.get("index", "main"))
                    events.append(event)
                    idx = end
                    # Skip whitespace between objects
                    while idx < len(raw) and raw[idx] in " \t\n\r":
                        idx += 1

                _append_events(events)
                _forward_to_store(events)
                self._send_json(200, {"text": "Success", "code": 0})
            except Exception as e:
                self._send_json(400, {"text": str(e), "code": 6})

        elif path in ("/services/collector/raw", "/services/collector/raw/1.0"):
            try:
                raw_text = body.decode("utf-8", errors="replace")
                events = []
                for line in raw_text.splitlines():
                    line = line.strip()
                    if line:
                        events.append({
                            "_raw": line,
                            "_time": time.time(),
                            "host": self.headers.get("X-Splunk-Request-Channel", "unknown"),
                            "source": "hec-raw",
                            "sourcetype": "generic_single_line",
                            "index": "main",
                        })
                _append_events(events)
                _forward_to_store(events)
                self._send_json(200, {"text": "Success", "code": 0})
            except Exception as e:
                self._send_json(400, {"text": str(e), "code": 6})

        else:
            self._send_json(404, {"text": "Not found", "code": 9})


def _s2s_listener():
    """Stub S2S listener: accepts connections, sends a minimal ACK, discards data."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", 9997))
    srv.listen(128)
    print("[mock-ingest] S2S stub listening on :9997")
    while True:
        try:
            conn, addr = srv.accept()
            threading.Thread(target=_s2s_handle, args=(conn, addr), daemon=True).start()
        except Exception:
            pass


def _s2s_handle(conn: socket.socket, addr):
    try:
        # Consume whatever the forwarder sends and reply with a minimal ACK frame.
        # Real S2S protocol parsing is implemented in services/ingest (Go).
        conn.recv(4096)
        # Minimal S2S ACK: length-prefixed empty payload
        conn.sendall(b"\x00\x00\x00\x04\x00\x00\x00\x00")
    except Exception:
        pass
    finally:
        conn.close()


def main():
    # S2S stub in background thread
    t = threading.Thread(target=_s2s_listener, daemon=True)
    t.start()

    # HEC HTTP server (foreground)
    server = HTTPServer(("0.0.0.0", 8088), HECHandler)
    print(f"[mock-ingest] HEC listening on :8088, writing to {OUTPUT_FILE}")
    server.serve_forever()


if __name__ == "__main__":
    main()
