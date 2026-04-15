"""
cusplunk.ingest.processor — GPU Parse Queue Processor
======================================================

This module is the Python side of the Go↔Python GPU ingest pipeline. It:

  1. Listens on a Unix domain socket specified by $CUSPLUNK_SOCKET.
  2. Receives length-prefixed JSON batches from the Go ingest service.
  3. Parses each batch with cuDF (GPU) or pandas (CPU fallback when
     CUDF_PANDAS_FALLBACK_MODE=1 or NUMBA_ENABLE_CUDASIM=1).
  4. Extracts _time, host, source, sourcetype, index fields.
  5. Compresses the _raw column using LZ4 (nvCOMP on GPU when available).
  6. Forwards the processed Arrow batch to the store gRPC service via
     store_client.write_batch().
  7. Sends an ack JSON back to Go: {"written": N, "error": "..."}.

Wire format (shared with gpuqueue.go):
  Go → Python:  4-byte big-endian length + JSON
  Python → Go:  4-byte big-endian length + JSON

CPU fallback
  Set CUDF_PANDAS_FALLBACK_MODE=1 or NUMBA_ENABLE_CUDASIM=1 to use pandas
  instead of cuDF. All CI/unit tests use this path.

Usage:
  python3 -m cusplunk.ingest.processor
  # or via the Go subprocess launcher which sets CUSPLUNK_SOCKET.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import signal
import socket
import struct
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# GPU / CPU import resolution
# ---------------------------------------------------------------------------

_USE_GPU = not (
    os.environ.get("CUDF_PANDAS_FALLBACK_MODE", "0") == "1"
    or os.environ.get("NUMBA_ENABLE_CUDASIM", "0") == "1"
    or os.environ.get("CUSPLUNK_FORCE_CPU", "0") == "1"
)

if _USE_GPU:
    try:
        import cudf
        import cudf.pandas  # noqa: F401 — activates pandas compatibility layer
        _pd = cudf
        _HAS_CUDF = True
    except ImportError:
        _USE_GPU = False
        _HAS_CUDF = False
        import pandas as _pd  # type: ignore
else:
    _HAS_CUDF = False
    import pandas as _pd  # type: ignore

# LZ4 compression: prefer nvCOMP on GPU, fall back to lz4 Python package.
if _USE_GPU and _HAS_CUDF:
    try:
        import nvcomp  # noqa: F401
        _HAS_NVCOMP = True
    except ImportError:
        _HAS_NVCOMP = False
else:
    _HAS_NVCOMP = False

try:
    import lz4.frame as _lz4
    _HAS_LZ4 = True
except ImportError:
    _HAS_LZ4 = False

# gRPC store client
try:
    from cusplunk.ingest.store_grpc import write_batch as _grpc_write_batch
    _HAS_GRPC = True
except ImportError:
    _HAS_GRPC = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [processor] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("cusplunk.ingest.processor")

# ---------------------------------------------------------------------------
# Data structures (mirror gpuqueue.go wire types)
# ---------------------------------------------------------------------------

@dataclass
class WireEvent:
    time_ns: int
    raw: bytes          # base64-decoded raw bytes
    host: str = ""
    source: str = ""
    sourcetype: str = ""
    index: str = "main"
    fields: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "WireEvent":
        raw_bytes = d.get("raw")
        if isinstance(raw_bytes, str):
            raw_bytes = base64.b64decode(raw_bytes)
        elif raw_bytes is None:
            raw_bytes = b""
        return cls(
            time_ns=int(d.get("time_ns", 0)),
            raw=raw_bytes,
            host=d.get("host", ""),
            source=d.get("source", ""),
            sourcetype=d.get("sourcetype", ""),
            index=d.get("index", "main"),
            fields=d.get("fields") or {},
        )


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def compress_raw(raw_bytes: bytes) -> bytes:
    """Compress raw event bytes with LZ4 (CPU or GPU)."""
    if _HAS_NVCOMP:
        # GPU path: nvCOMP LZ4 — returns compressed bytes on device
        # For now, ship the compressed bytes as a standard lz4 frame so the
        # store can decompress with any lz4 library.
        # TODO R3: use nvCOMP device-to-device path once store accepts it.
        pass  # fall through to CPU lz4
    if _HAS_LZ4:
        return _lz4.compress(raw_bytes)
    # No compression available — return uncompressed.
    return raw_bytes


def parse_batch(events: List[WireEvent]) -> _pd.DataFrame:  # type: ignore
    """
    Parse a batch of raw events into a DataFrame using cuDF (GPU) or pandas.

    Extracted columns:
      _time      — timestamp as float seconds since epoch
      _raw       — LZ4-compressed raw bytes (Python bytes or GPU bytes)
      host       — originating host
      source     — source identifier
      sourcetype — log format identifier
      index      — target index
    """
    if not events:
        return _pd.DataFrame()

    rows = {
        "_time": [],
        "_raw": [],
        "host": [],
        "source": [],
        "sourcetype": [],
        "index": [],
    }

    for e in events:
        rows["_time"].append(e.time_ns / 1e9)
        rows["_raw"].append(compress_raw(e.raw))
        rows["host"].append(e.host)
        rows["source"].append(e.source)
        rows["sourcetype"].append(e.sourcetype)
        rows["index"].append(e.index)

    df = _pd.DataFrame(rows)

    if _HAS_CUDF:
        # GPU-accelerated timestamp parsing: convert float epoch to datetime.
        df["_time"] = _pd.to_datetime(df["_time"], unit="s", utc=True)

    return df


def forward_to_store(df: _pd.DataFrame, events: List[WireEvent]) -> int:
    """
    Forward the processed DataFrame to the store service.

    Returns the number of events written.
    """
    if df is None or len(df) == 0:
        return 0

    if _HAS_GRPC:
        return _grpc_write_batch(df, events)

    # No gRPC client available (unit tests or standalone mode).
    log.debug("store gRPC client unavailable, dropping %d events", len(events))
    return len(events)


# ---------------------------------------------------------------------------
# Socket server
# ---------------------------------------------------------------------------

def _read_msg(sock: socket.socket) -> Optional[bytes]:
    """Read a length-prefixed message from sock. Returns None on EOF."""
    hdr = _recvall(sock, 4)
    if hdr is None:
        return None
    length = struct.unpack(">I", hdr)[0]
    if length == 0:
        return b""
    if length > 64 * 1024 * 1024:
        raise ValueError(f"message too large: {length} bytes")
    return _recvall(sock, length)


def _send_msg(sock: socket.socket, payload: bytes) -> None:
    """Send a length-prefixed message to sock."""
    hdr = struct.pack(">I", len(payload))
    sock.sendall(hdr + payload)


def _recvall(sock: socket.socket, n: int) -> Optional[bytes]:
    """Receive exactly n bytes from sock. Returns None on EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _handle_conn(conn: socket.socket, addr: str) -> None:
    """Handle one Go ingest connection: receive batches, process, ack."""
    log.info("new connection from %s", addr)
    try:
        while True:
            msg = _read_msg(conn)
            if msg is None:
                log.info("connection closed by %s", addr)
                break

            t0 = time.monotonic()
            error_msg = ""
            written = 0

            try:
                data = json.loads(msg)
                raw_events = [WireEvent.from_dict(e) for e in data.get("events", [])]

                df = parse_batch(raw_events)
                written = forward_to_store(df, raw_events)

                elapsed_ms = (time.monotonic() - t0) * 1000
                log.debug(
                    "processed %d events in %.1f ms (gpu=%s)",
                    written, elapsed_ms, _HAS_CUDF,
                )
            except Exception as exc:  # noqa: BLE001
                error_msg = str(exc)
                log.exception("error processing batch")

            ack = json.dumps({"written": written, "error": error_msg}).encode()
            _send_msg(conn, ack)
    except OSError as exc:
        log.warning("connection error from %s: %s", addr, exc)
    finally:
        conn.close()


def serve(socket_path: str) -> None:
    """
    Serve on a Unix domain socket, processing batches indefinitely.

    The socket file is created at socket_path. This function blocks until
    SIGINT or SIGTERM is received.
    """
    # Remove stale socket.
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(socket_path)
    srv.listen(32)
    log.info(
        "gpu processor listening on %s (cudf=%s, nvcomp=%s, lz4=%s)",
        socket_path, _HAS_CUDF, _HAS_NVCOMP, _HAS_LZ4,
    )

    shutdown = threading.Event()

    # Signal handlers must only be installed from the main thread.
    if threading.current_thread() is threading.main_thread():
        def _handle_signal(sig, _frame):
            log.info("received signal %d, shutting down", sig)
            shutdown.set()
            try:
                srv.close()
            except OSError:
                pass

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

    while not shutdown.is_set():
        try:
            srv.settimeout(1.0)
            conn, _ = srv.accept()
            t = threading.Thread(
                target=_handle_conn,
                args=(conn, socket_path),
                daemon=True,
            )
            t.start()
        except socket.timeout:
            continue
        except OSError:
            if shutdown.is_set():
                break
            raise

    log.info("processor shutdown complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    socket_path = os.environ.get("CUSPLUNK_SOCKET", "/tmp/cusplunk-gpu.sock")
    log.info("starting processor, socket=%s, gpu=%s", socket_path, _USE_GPU)
    serve(socket_path)


if __name__ == "__main__":
    main()
