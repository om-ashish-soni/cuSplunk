"""
cusplunk.ingest.store_grpc — gRPC client for the store service.

Imports store_pb2 and store_pb2_grpc (generated from libs/proto/store.proto).
Falls back to a no-op if the generated stubs are unavailable.

Generate stubs:
  python -m grpc_tools.protoc \
      -I ../../../../libs/proto \
      --python_out=. \
      --grpc_python_out=. \
      ../../../../libs/proto/store.proto
"""

from __future__ import annotations

import logging
import os
import time
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports in type hints

log = logging.getLogger("cusplunk.ingest.store_grpc")

# ---------------------------------------------------------------------------
# Attempt to import generated stubs
# ---------------------------------------------------------------------------

try:
    import grpc
    from cusplunk.ingest import store_pb2, store_pb2_grpc
    _GRPC_AVAILABLE = True
except ImportError:
    _GRPC_AVAILABLE = False
    grpc = None  # type: ignore

# ---------------------------------------------------------------------------
# gRPC channel (lazy, singleton per process)
# ---------------------------------------------------------------------------

_channel = None
_stub = None
_channel_lock = __import__("threading").Lock()

_STORE_ADDRESS = os.environ.get("CUSPLUNK_STORE_ADDR", "localhost:50051")


def _get_stub():
    global _channel, _stub
    if _stub is not None:
        return _stub
    with _channel_lock:
        if _stub is not None:
            return _stub
        _channel = grpc.insecure_channel(_STORE_ADDRESS)
        _stub = store_pb2_grpc.StoreStub(_channel)
        log.info("connected to store at %s", _STORE_ADDRESS)
    return _stub


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_batch(df, events: List) -> int:  # noqa: ANN001
    """
    Write a processed batch to the store service.

    Parameters
    ----------
    df:
        A cuDF or pandas DataFrame with columns: _time, _raw, host, source,
        sourcetype, index. _raw values are LZ4-compressed bytes.
    events:
        The original WireEvent list (for metadata not in the DataFrame).

    Returns
    -------
    int
        Number of events written.
    """
    if not _GRPC_AVAILABLE:
        log.debug("gRPC stubs unavailable, dropping %d events", len(events))
        return len(events)

    stub = _get_stub()
    index = df["index"].iloc[0] if len(df) > 0 else "main"

    proto_events = []
    for i, e in enumerate(events):
        row = df.iloc[i]
        # _time is a pandas/cudf Timestamp; convert to nanoseconds.
        t_val = row["_time"]
        if hasattr(t_val, "value"):
            time_ns = int(t_val.value)  # nanoseconds since epoch
        else:
            time_ns = int(float(t_val) * 1_000_000_000)

        raw_bytes = row["_raw"]
        if isinstance(raw_bytes, memoryview):
            raw_bytes = bytes(raw_bytes)
        elif not isinstance(raw_bytes, (bytes, bytearray)):
            raw_bytes = str(raw_bytes).encode()

        pe = store_pb2.Event(
            time_ns=time_ns,
            raw=raw_bytes,
            host=e.host,
            source=e.source,
            sourcetype=e.sourcetype,
            index=e.index,
            fields=e.fields or {},
        )
        proto_events.append(pe)

    req = store_pb2.WriteRequest(index=index, events=proto_events)

    try:
        resp = stub.Write(req, timeout=30)
        log.debug("store.Write: %d events written, bucket=%s",
                  resp.events_written, resp.bucket_id)
        return int(resp.events_written)
    except grpc.RpcError as exc:
        log.error("store.Write failed: %s", exc)
        raise
