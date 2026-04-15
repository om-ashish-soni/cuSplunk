"""
pipeline.py — Morpheus detection pipeline skeleton.

Production (GPU + Morpheus):
  Source (cuStreamz) → cyBERT normalization → Sigma eval → alert queue

CPU/test path:
  Source (pandas batch iterator) → regex normalization → Sigma eval → alert queue

The pipeline is wire-compatible: same Alert output shape regardless of path.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_USE_MORPHEUS = False
try:
    if os.environ.get("CUDF_PANDAS_FALLBACK_MODE") != "1":
        import morpheus  # type: ignore  # noqa: F401
        _USE_MORPHEUS = True
except ImportError:
    pass


@dataclass
class Alert:
    """Output of the detection pipeline — one alert per rule match."""
    rule_id: str
    rule_title: str
    level: str                       # informational|low|medium|high|critical
    tags: list[str]
    event_count: int
    first_event_raw: str
    matched_indices: list[int]
    ts: float = field(default_factory=time.time)
    mitre_techniques: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Extract MITRE technique IDs from tags (e.g. "attack.t1110" → "T1110")
        self.mitre_techniques = [
            t.split(".")[-1].upper()
            for t in self.tags
            if t.lower().startswith("attack.t")
        ]


class DetectionPipeline:
    """
    Detection pipeline: ingests event batches, runs Sigma + cyBERT, emits alerts.

    Usage:
        pipeline = DetectionPipeline(
            rules_dir="/etc/cusplunk/sigma/",
            alert_queue=my_queue,
        )
        pipeline.start()
        pipeline.ingest(df)   # push a batch DataFrame
        pipeline.stop()
    """

    def __init__(
        self,
        rules_dir: str = "",
        alert_queue: queue.Queue | None = None,
        triton_url: str | None = None,
        batch_size: int = 1000,
    ) -> None:
        self._rules_dir = rules_dir
        self._alert_queue: queue.Queue = alert_queue or queue.Queue(maxsize=10_000)
        self._triton_url = triton_url
        self._batch_size = batch_size
        self._running = False
        self._input_queue: queue.Queue = queue.Queue(maxsize=100)
        self._worker: threading.Thread | None = None

        # Lazy-init on start()
        self._loader = None
        self._evaluator = None
        self._normalizer = None

    # ── Public API ────────────────────────────────────────────────

    def start(self) -> None:
        """Load rules, initialise normalizer, start processing thread."""
        self._init_components()
        self._running = True
        self._worker = threading.Thread(
            target=self._process_loop,
            name="detect-pipeline",
            daemon=True,
        )
        self._worker.start()
        logger.info(
            "DetectionPipeline: started (%s path, %d rules loaded)",
            "GPU/Morpheus" if _USE_MORPHEUS else "CPU",
            self._loader.rule_count() if self._loader else 0,
        )

    def stop(self) -> None:
        self._running = False
        self._input_queue.put(None)  # sentinel
        if self._worker:
            self._worker.join(timeout=10)
        if self._loader:
            self._loader.stop()
        logger.info("DetectionPipeline: stopped")

    def ingest(self, df: "object", block: bool = False, timeout: float = 1.0) -> bool:
        """
        Push a DataFrame batch into the pipeline.

        Returns True if accepted, False if the input queue was full.
        df must have a '_raw' column.
        """
        try:
            self._input_queue.put(df, block=block, timeout=timeout)
            return True
        except queue.Full:
            logger.warning("DetectionPipeline: input queue full — dropping batch")
            return False

    def get_alert(self, timeout: float = 0.1) -> Alert | None:
        """Poll for the next alert (non-blocking by default)."""
        try:
            return self._alert_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def alert_queue_depth(self) -> int:
        return self._alert_queue.qsize()

    # ── Internal ──────────────────────────────────────────────────

    def _init_components(self) -> None:
        from cusplunk.sigma.loader import SigmaLoader
        from cusplunk.sigma.evaluator import SigmaEvaluator
        from cusplunk.normalize.normalizer import LogNormalizer

        self._normalizer = LogNormalizer(triton_url=self._triton_url)
        self._evaluator = SigmaEvaluator()

        if self._rules_dir:
            self._loader = SigmaLoader(self._rules_dir)
            self._loader.start()
        else:
            self._loader = None

    def _process_loop(self) -> None:
        """Worker thread: pull batches, normalise, evaluate, emit alerts."""
        while self._running:
            try:
                batch = self._input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if batch is None:  # sentinel
                break

            try:
                self._process_batch(batch)
            except Exception:
                logger.exception("DetectionPipeline: error processing batch")

    def _process_batch(self, df: "object") -> None:
        if self._normalizer is None or self._evaluator is None:
            return

        # Stage 1: cyBERT normalization
        df = self._normalizer.normalize_batch(df)

        # Stage 2: Sigma evaluation
        rules = self._loader.get_compiled_rules() if self._loader else []
        if not rules:
            return

        matches = self._evaluator.evaluate(rules, df)

        # Stage 3: emit alerts
        for match in matches:
            first_raw = ""
            if match.matched_indices:
                try:
                    first_raw = str(df["_raw"].iloc[match.matched_indices[0]])
                except Exception:
                    pass

            alert = Alert(
                rule_id=match.rule_id,
                rule_title=match.rule_title,
                level=match.level,
                tags=match.tags,
                event_count=len(match.matched_indices),
                first_event_raw=first_raw,
                matched_indices=match.matched_indices,
            )
            try:
                self._alert_queue.put_nowait(alert)
            except queue.Full:
                logger.warning(
                    "DetectionPipeline: alert queue full, dropping alert for rule %s",
                    match.rule_id,
                )
