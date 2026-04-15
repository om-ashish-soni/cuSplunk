"""
normalize/normalizer.py — Log normalizer dispatcher.

In production (GPU path): delegates to cyBERT (RAPIDS CLX) via Triton.
In CPU/test path: uses regex-based parsers per log format.

The GPU cyBERT path is enabled when:
  - CUDF_PANDAS_FALLBACK_MODE != "1"  AND
  - triton_url is provided  AND
  - cudf is importable

Otherwise falls back to regex normalizers (deterministic, no GPU needed).
"""

from __future__ import annotations

import enum
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class LogFormat(str, enum.Enum):
    WINDOWS_EVENT = "windows_event"
    SYSLOG_RFC3164 = "syslog_rfc3164"
    SYSLOG_RFC5424 = "syslog_rfc5424"
    CEF = "cef"
    JSON = "json"
    UNKNOWN = "unknown"


@dataclass
class NormalizedEvent:
    """ECS-compatible normalised field set extracted from a raw log string."""
    _raw: str
    _time: float | None = None
    host: str | None = None
    source: str | None = None
    sourcetype: str | None = None
    index: str = "main"

    # Common fields
    src_ip: str | None = None
    dst_ip: str | None = None
    src_port: int | None = None
    dst_port: int | None = None
    user: str | None = None
    domain: str | None = None
    process: str | None = None
    pid: int | None = None
    action: str | None = None
    status: str | None = None
    severity: str | None = None
    message: str | None = None

    # Windows-specific
    event_id: int | None = None
    logon_type: int | None = None
    subject_user: str | None = None
    target_user: str | None = None
    computer_name: str | None = None
    workstation_name: str | None = None

    # Syslog-specific
    facility: int | None = None
    priority: int | None = None
    app_name: str | None = None
    proc_id: str | None = None
    msg_id: str | None = None

    # CEF-specific
    device_vendor: str | None = None
    device_product: str | None = None
    device_version: str | None = None
    signature_id: str | None = None
    name: str | None = None

    # Extra extracted fields (overflow)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to flat dict, omitting None values."""
        d = {}
        for k, v in self.__dict__.items():
            if v is None:
                continue
            if k == "extra":
                d.update(v)
            else:
                d[k] = v
        return d


class LogNormalizer:
    """
    Normalise raw log strings to NormalizedEvent.

    CPU path: regex-based parsers (deterministic, used in tests + CI).
    GPU path: cyBERT via Triton (enabled when GPU available + triton_url set).

    Usage:
        normalizer = LogNormalizer()
        event = normalizer.normalize(raw_log)

        # Batch (CPU: pandas, GPU: cudf)
        df_out = normalizer.normalize_batch(df)
    """

    def __init__(self, triton_url: str | None = None) -> None:
        self._use_gpu = self._should_use_gpu(triton_url)
        self._triton_url = triton_url
        self._triton_client = None

        if self._use_gpu:
            self._init_triton()

        # Lazy-import regex parsers
        from cusplunk.normalize.windows import WindowsEventParser
        from cusplunk.normalize.syslog import SyslogParser
        from cusplunk.normalize.cef import CEFParser

        self._windows_parser = WindowsEventParser()
        self._syslog_parser = SyslogParser()
        self._cef_parser = CEFParser()

    # ── Public API ────────────────────────────────────────────────

    def detect_format(self, raw: str) -> LogFormat:
        """Heuristic format detection from raw log string."""
        stripped = raw.strip()
        if stripped.startswith("CEF:"):
            return LogFormat.CEF
        if stripped.startswith("{") and stripped.endswith("}"):
            return LogFormat.JSON
        if "EventCode=" in stripped or "EventID=" in stripped or "Security" in stripped:
            return LogFormat.WINDOWS_EVENT
        if stripped.startswith("<") and ">" in stripped:
            # Syslog PRI field
            content = stripped[stripped.index(">") + 1:]
            # RFC5424: version digit after PRI
            if content and content[0].isdigit():
                return LogFormat.SYSLOG_RFC5424
            return LogFormat.SYSLOG_RFC3164
        return LogFormat.UNKNOWN

    def normalize(self, raw: str) -> NormalizedEvent:
        """Normalise a single raw log string."""
        if self._use_gpu:
            return self._normalize_gpu(raw)
        return self._normalize_cpu(raw)

    def normalize_batch(self, df: "object") -> "object":
        """
        Normalise all rows in a DataFrame.

        Expects df to have a '_raw' column.
        Returns df with extracted fields added as new columns.

        GPU path: cudf DataFrame + Triton cyBERT inference.
        CPU path: pandas apply (used in unit tests).
        """
        if self._use_gpu:
            return self._normalize_batch_gpu(df)
        return self._normalize_batch_cpu(df)

    # ── CPU path (regex) ──────────────────────────────────────────

    def _normalize_cpu(self, raw: str) -> NormalizedEvent:
        fmt = self.detect_format(raw)
        try:
            if fmt == LogFormat.WINDOWS_EVENT:
                return self._windows_parser.parse(raw)
            if fmt in (LogFormat.SYSLOG_RFC3164, LogFormat.SYSLOG_RFC5424):
                return self._syslog_parser.parse(raw)
            if fmt == LogFormat.CEF:
                return self._cef_parser.parse(raw)
            if fmt == LogFormat.JSON:
                return self._parse_json(raw)
        except Exception as e:
            logger.debug("normalize_cpu fallback for format %s: %s", fmt, e)

        return NormalizedEvent(_raw=raw)

    def _normalize_batch_cpu(self, df: "object") -> "object":
        import pandas as pd
        if "_raw" not in df.columns:
            return df
        events = df["_raw"].apply(lambda r: self._normalize_cpu(str(r)).to_dict())
        extracted = pd.DataFrame(events.tolist(), index=df.index)
        # Only add columns that aren't already in df to avoid overwrite
        new_cols = [c for c in extracted.columns if c not in df.columns]
        for col in new_cols:
            df = df.copy()
            df[col] = extracted[col]
        return df

    @staticmethod
    def _parse_json(raw: str) -> NormalizedEvent:
        import json
        try:
            d = json.loads(raw)
            event = NormalizedEvent(_raw=raw)
            event._time = d.get("_time") or d.get("time") or d.get("timestamp")
            event.host = d.get("host") or d.get("hostname")
            event.message = d.get("message") or d.get("msg")
            event.src_ip = d.get("src_ip") or d.get("sourceIp")
            event.dst_ip = d.get("dst_ip") or d.get("destIp")
            event.user = d.get("user") or d.get("username")
            event.extra = {k: v for k, v in d.items() if not hasattr(event, k)}
            return event
        except Exception:
            return NormalizedEvent(_raw=raw)

    # ── GPU path (cyBERT / Triton) ────────────────────────────────

    def _init_triton(self) -> None:
        try:
            import tritonclient.grpc as grpcclient  # type: ignore
            self._triton_client = grpcclient.InferenceServerClient(url=self._triton_url)
            logger.info("LogNormalizer: Triton client connected to %s", self._triton_url)
        except Exception as e:
            logger.warning("LogNormalizer: Triton init failed (%s) — falling back to CPU", e)
            self._use_gpu = False

    def _normalize_gpu(self, raw: str) -> NormalizedEvent:
        # Single-event GPU inference: batch it for efficiency
        import pandas as pd
        df = pd.DataFrame({"_raw": [raw]})
        result_df = self._normalize_batch_gpu(df)
        row = result_df.iloc[0].to_dict()
        event = NormalizedEvent(_raw=raw)
        for k, v in row.items():
            if hasattr(event, k) and v is not None:
                setattr(event, k, v)
        return event

    def _normalize_batch_gpu(self, df: "object") -> "object":
        """
        GPU cyBERT inference via Triton.

        Sends batches of raw log strings to the cyBERT model endpoint and
        merges extracted fields back into the DataFrame.
        """
        if self._triton_client is None:
            return self._normalize_batch_cpu(df)

        try:
            import numpy as np  # type: ignore
            import tritonclient.grpc as grpcclient  # type: ignore

            raws = df["_raw"].astype(str).tolist()
            # Encode as byte strings for Triton
            inputs = np.array([[r.encode("utf-8", errors="replace")] for r in raws], dtype=object)

            infer_input = grpcclient.InferInput("input_ids", inputs.shape, "BYTES")
            infer_input.set_data_from_numpy(inputs)

            response = self._triton_client.infer(
                model_name="cybert",
                inputs=[infer_input],
                outputs=[grpcclient.InferRequestedOutput("extracted_fields")],
            )

            import json
            extracted_raw = response.as_numpy("extracted_fields")
            rows = [json.loads(b.decode("utf-8")) for b in extracted_raw.flatten()]

            import pandas as pd
            extracted_df = pd.DataFrame(rows, index=df.index)
            for col in extracted_df.columns:
                if col not in df.columns:
                    df[col] = extracted_df[col]
            return df

        except Exception as e:
            logger.warning("LogNormalizer: Triton inference failed (%s) — falling back to CPU", e)
            return self._normalize_batch_cpu(df)

    @staticmethod
    def _should_use_gpu(triton_url: str | None) -> bool:
        if os.environ.get("CUDF_PANDAS_FALLBACK_MODE") == "1":
            return False
        if not triton_url:
            return False
        try:
            import cudf  # type: ignore  # noqa: F401
            return True
        except ImportError:
            return False
