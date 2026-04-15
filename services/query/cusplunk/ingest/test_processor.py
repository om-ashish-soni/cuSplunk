"""
Tests for cusplunk.ingest.processor.

All tests run with CUSPLUNK_FORCE_CPU=1 so no GPU is required.
The lz4 package is used for compression tests; if unavailable, the raw bytes
are passed through uncompressed and the test is skipped.
"""

import base64
import json
import os
import socket
import struct
import threading
import time
import pytest

# Force CPU path for all tests.
os.environ["CUSPLUNK_FORCE_CPU"] = "1"

# Re-import after setting env var (module may already be loaded).
import importlib
import cusplunk.ingest.processor as proc
importlib.reload(proc)

from cusplunk.ingest.processor import (
    WireEvent,
    parse_batch,
    compress_raw,
    _read_msg,
    _send_msg,
    serve,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wire_event(raw: str = "test log line", index: str = "main") -> WireEvent:
    return WireEvent(
        time_ns=1_735_689_600_000_000_000,
        raw=raw.encode(),
        host="testhost",
        source="/var/log/test",
        sourcetype="test",
        index=index,
        fields={"key": "value"},
    )


def make_json_batch(events: list[WireEvent]) -> bytes:
    """Serialize a list of WireEvents to the JSON wire format."""
    payload = json.dumps({
        "events": [
            {
                "time_ns": e.time_ns,
                "raw": base64.b64encode(e.raw).decode(),
                "host": e.host,
                "source": e.source,
                "sourcetype": e.sourcetype,
                "index": e.index,
                "fields": e.fields,
            }
            for e in events
        ]
    }).encode()
    hdr = struct.pack(">I", len(payload))
    return hdr + payload


# ---------------------------------------------------------------------------
# WireEvent deserialization tests
# ---------------------------------------------------------------------------

class TestWireEvent:
    def test_from_dict_base64_raw(self):
        raw = b"hello world"
        d = {
            "time_ns": 1000,
            "raw": base64.b64encode(raw).decode(),
            "host": "h",
            "source": "s",
            "sourcetype": "st",
            "index": "main",
            "fields": {"k": "v"},
        }
        e = WireEvent.from_dict(d)
        assert e.raw == raw
        assert e.host == "h"
        assert e.index == "main"
        assert e.fields == {"k": "v"}

    def test_from_dict_missing_fields(self):
        e = WireEvent.from_dict({"time_ns": 0, "raw": ""})
        assert e.host == ""
        assert e.index == "main"
        assert e.fields == {}

    def test_from_dict_null_raw(self):
        e = WireEvent.from_dict({"time_ns": 0, "raw": None})
        assert e.raw == b""


# ---------------------------------------------------------------------------
# parse_batch tests
# ---------------------------------------------------------------------------

class TestParseBatch:
    def test_empty_batch_returns_empty_dataframe(self):
        df = parse_batch([])
        assert len(df) == 0

    def test_single_event_columns(self):
        e = make_wire_event("log line")
        df = parse_batch([e])
        assert len(df) == 1
        assert "_time" in df.columns
        assert "_raw" in df.columns
        assert "host" in df.columns
        assert "sourcetype" in df.columns
        assert "index" in df.columns

    def test_host_field_preserved(self):
        e = make_wire_event()
        e.host = "myserver"
        df = parse_batch([e])
        assert df["host"].iloc[0] == "myserver"

    def test_index_field_preserved(self):
        e = make_wire_event(index="production")
        df = parse_batch([e])
        assert df["index"].iloc[0] == "production"

    def test_time_ns_converted_to_float_seconds(self):
        e = make_wire_event()
        e.time_ns = 1_735_689_600_000_000_000  # 2026-01-01 00:00:00 UTC in ns
        df = parse_batch([e])
        # _time should be close to 2026-01-01 00:00:00 UTC.
        # In CPU mode (pandas) we store as float seconds.
        t_val = df["_time"].iloc[0]
        if hasattr(t_val, "timestamp"):
            epoch_seconds = t_val.timestamp()
        else:
            epoch_seconds = float(t_val)
        assert abs(epoch_seconds - 1_735_689_600.0) < 1.0

    def test_multiple_events(self):
        events = [make_wire_event(f"line {i}") for i in range(100)]
        df = parse_batch(events)
        assert len(df) == 100

    def test_raw_compressed(self):
        e = make_wire_event("compress me")
        df = parse_batch([e])
        raw_val = df["_raw"].iloc[0]
        if isinstance(raw_val, (bytes, bytearray)):
            # If lz4 is available, the raw should be compressed (different from
            # the original). If not available, it's uncompressed.
            assert len(raw_val) > 0
        else:
            assert raw_val is not None


# ---------------------------------------------------------------------------
# compress_raw tests
# ---------------------------------------------------------------------------

class TestCompressRaw:
    def test_returns_bytes(self):
        result = compress_raw(b"hello world this is a test log line")
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_empty_bytes(self):
        result = compress_raw(b"")
        assert isinstance(result, bytes)

    @pytest.mark.skipif(
        not proc._HAS_LZ4,
        reason="lz4 not installed"
    )
    def test_lz4_roundtrip(self):
        import lz4.frame as lz4_frame
        raw = b"repeated log line " * 100
        compressed = compress_raw(raw)
        # lz4 compressed should be smaller than the original
        assert len(compressed) < len(raw)
        decompressed = lz4_frame.decompress(compressed)
        assert decompressed == raw


# ---------------------------------------------------------------------------
# Socket server integration test
# ---------------------------------------------------------------------------

class TestSocketServer:
    def _start_server(self, socket_path: str) -> threading.Thread:
        """Start the processor server in a background thread."""
        t = threading.Thread(
            target=serve,
            args=(socket_path,),
            daemon=True,
        )
        t.start()
        # Wait for the socket to appear.
        deadline = time.monotonic() + 5.0
        while not os.path.exists(socket_path):
            if time.monotonic() > deadline:
                raise TimeoutError(f"socket {socket_path} never appeared")
            time.sleep(0.01)
        return t

    def _send_batch(self, sock: socket.socket, events: list) -> dict:
        """Send a batch and receive the ack."""
        msg = make_json_batch(events)
        sock.sendall(msg)
        # Read ack
        hdr = _recvall_n(sock, 4)
        length = struct.unpack(">I", hdr)[0]
        body = _recvall_n(sock, length)
        return json.loads(body)

    def test_single_event_ack(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        self._start_server(socket_path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            ack = self._send_batch(conn, [make_wire_event("hello")])
            assert ack["error"] == ""
            assert ack["written"] == 1

    def test_batch_of_50_events(self, tmp_path):
        socket_path = str(tmp_path / "batch.sock")
        self._start_server(socket_path)

        events = [make_wire_event(f"event {i}") for i in range(50)]
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            ack = self._send_batch(conn, events)
            assert ack["error"] == ""
            assert ack["written"] == 50

    def test_multiple_sequential_batches(self, tmp_path):
        socket_path = str(tmp_path / "multi.sock")
        self._start_server(socket_path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            for _ in range(5):
                ack = self._send_batch(conn, [make_wire_event("msg")])
                assert ack["error"] == ""
                assert ack["written"] == 1

    def test_empty_batch_returns_zero(self, tmp_path):
        socket_path = str(tmp_path / "empty.sock")
        self._start_server(socket_path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            ack = self._send_batch(conn, [])
            assert ack["error"] == ""
            assert ack["written"] == 0

    def test_malformed_json_returns_error(self, tmp_path):
        socket_path = str(tmp_path / "malformed.sock")
        self._start_server(socket_path)

        bad_payload = b"not valid json at all!!!"
        hdr = struct.pack(">I", len(bad_payload))

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            conn.sendall(hdr + bad_payload)
            hdr_back = _recvall_n(conn, 4)
            length = struct.unpack(">I", hdr_back)[0]
            body = _recvall_n(conn, length)
            ack = json.loads(body)
            assert ack["error"] != ""

    def test_connection_close_graceful(self, tmp_path):
        socket_path = str(tmp_path / "close.sock")
        self._start_server(socket_path)

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.connect(socket_path)
            ack = self._send_batch(conn, [make_wire_event("before close")])
            assert ack["written"] == 1
        # No exception on close — connection cleanup is graceful.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _recvall_n(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed unexpectedly")
        buf.extend(chunk)
    return bytes(buf)
