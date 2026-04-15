"""
test_cybert_windows_event_log.py — Integration test: cyBERT-style normalisation
of fixture Windows Event Log data.

Tests the CPU regex path (CUDF_PANDAS_FALLBACK_MODE=1).
GPU/Triton path is tested in integration tests (requires GPU runner).

F1 target: >0.99 on event_id extraction from fixture data.
"""

import json
import os
from pathlib import Path

import pandas as pd
import pytest

os.environ.setdefault("CUDF_PANDAS_FALLBACK_MODE", "1")

from cusplunk.normalize.normalizer import LogNormalizer, LogFormat

FIXTURES = Path(__file__).parent.parent.parent.parent / "tests/fixtures/events"


@pytest.fixture(scope="module")
def windows_events():
    path = FIXTURES / "windows_event_log_1000.json"
    if not path.exists():
        pytest.skip("Fixture not generated — run: make fixtures")
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def normalizer():
    return LogNormalizer()  # CPU path — no triton_url


def test_format_detection_windows(windows_events, normalizer):
    """At least 95% of fixture events should be detected as WINDOWS_EVENT."""
    total = len(windows_events)
    detected = sum(
        1 for e in windows_events
        if normalizer.detect_format(e.get("_raw", "")) == LogFormat.WINDOWS_EVENT
    )
    rate = detected / total
    assert rate >= 0.95, f"Format detection rate {rate:.1%} < 95% (detected {detected}/{total})"


def test_event_id_extraction_f1(windows_events, normalizer):
    """
    F1 score for event_id extraction must be >= 0.99.

    Ground truth: 'EventCode' field in fixture data.
    Prediction: event.event_id from LogNormalizer.normalize().
    """
    true_positive = 0
    false_negative = 0
    false_positive = 0

    for raw_event in windows_events:
        raw = raw_event.get("_raw", "")
        gt_code = raw_event.get("EventCode")
        if not gt_code:
            continue

        event = normalizer.normalize(raw)

        if event.event_id is not None:
            if str(event.event_id) == str(gt_code):
                true_positive += 1
            else:
                false_positive += 1
        else:
            false_negative += 1

    total = true_positive + false_negative + false_positive
    if total == 0:
        pytest.skip("No ground-truth event codes in fixture")

    precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) > 0 else 0
    recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    assert f1 >= 0.99, (
        f"event_id F1={f1:.3f} < 0.99 "
        f"(TP={true_positive} FP={false_positive} FN={false_negative})"
    )


def test_host_extraction_rate(windows_events, normalizer):
    """At least 90% of events should have host extracted."""
    total = len(windows_events)
    extracted = sum(
        1 for e in windows_events
        if normalizer.normalize(e.get("_raw", "")).host is not None
    )
    rate = extracted / total
    assert rate >= 0.90, f"Host extraction rate {rate:.1%} < 90%"


def test_user_extraction_rate(windows_events, normalizer):
    """At least 90% of events should have user/target_user extracted."""
    total = len(windows_events)
    extracted = sum(
        1 for e in windows_events
        if normalizer.normalize(e.get("_raw", "")).user is not None
    )
    rate = extracted / total
    assert rate >= 0.90, f"User extraction rate {rate:.1%} < 90%"


def test_batch_normalize_returns_dataframe(windows_events, normalizer):
    """normalize_batch should return a DataFrame with extracted columns."""
    sample = windows_events[:50]
    df = pd.DataFrame([{"_raw": e["_raw"]} for e in sample])
    result_df = normalizer.normalize_batch(df)

    assert "_raw" in result_df.columns
    assert len(result_df) == 50
    # At least some enrichment columns should be added
    new_cols = set(result_df.columns) - {"_raw"}
    assert len(new_cols) > 0, "normalize_batch added no new columns"


def test_normalize_no_crash_on_all_fixtures(windows_events, normalizer):
    """None of the 1,000 fixture events should raise an exception."""
    errors = []
    for i, raw_event in enumerate(windows_events):
        raw = raw_event.get("_raw", "")
        try:
            event = normalizer.normalize(raw)
            assert event._raw == raw
        except Exception as e:
            errors.append(f"row {i}: {e}")

    assert not errors, f"{len(errors)} normalisation errors:\n" + "\n".join(errors[:3])
