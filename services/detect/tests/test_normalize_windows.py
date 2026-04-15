"""Unit tests for Windows Event Log normalizer."""

import json
from pathlib import Path

import pytest

from cusplunk.normalize.windows import WindowsEventParser

FIXTURES = Path(__file__).parent.parent.parent.parent / "tests/fixtures/events"

parser = WindowsEventParser()


def test_parse_event_4624():
    raw = (
        "EventCode=4624 ComputerName=WORKSTATION-001 "
        "AccountName=jsmith AccountDomain=CORP "
        "LogonType=3 IpAddress=10.0.1.50 IpPort=50432"
    )
    event = parser.parse(raw)
    assert event.event_id == 4624
    assert event.computer_name == "WORKSTATION-001"
    assert event.target_user == "jsmith"
    assert event.domain == "CORP"
    assert event.logon_type == 3
    assert event.src_ip == "10.0.1.50"
    assert event.src_port == 50432
    assert event.sourcetype == "WinEventLog:Security"


def test_parse_event_4625():
    raw = (
        "EventCode=4625 ComputerName=WS-002 "
        "AccountName=administrator AccountDomain=ACME "
        "LogonType=3 IpAddress=192.168.1.100"
    )
    event = parser.parse(raw)
    assert event.event_id == 4625
    assert event.severity == "medium"
    assert event.target_user == "administrator"


def test_parse_event_4688():
    raw = (
        "EventCode=4688 ComputerName=DC-01 "
        "AccountName=SYSTEM NewProcessName=C:\\Windows\\System32\\cmd.exe "
        "ProcessId=0x1a4"
    )
    event = parser.parse(raw)
    assert event.event_id == 4688
    assert event.process == "C:\\Windows\\System32\\cmd.exe"
    assert event.pid == 0x1a4


def test_parse_localhost_ip_stripped():
    """127.0.0.1 and - should be stripped from src_ip."""
    raw = "EventCode=4624 AccountName=test IpAddress=127.0.0.1"
    event = parser.parse(raw)
    assert event.src_ip is None

    raw2 = "EventCode=4624 AccountName=test IpAddress=-"
    event2 = parser.parse(raw2)
    assert event2.src_ip is None


def test_parse_unknown_event_id():
    raw = "EventCode=9999 ComputerName=WS AccountName=user"
    event = parser.parse(raw)
    assert event.event_id == 9999
    assert event.severity == "low"  # default for unknown


def test_parse_missing_fields_no_crash():
    raw = "EventCode=4624"
    event = parser.parse(raw)
    assert event.event_id == 4624
    assert event.computer_name is None
    assert event.target_user is None


def test_raw_preserved():
    raw = "EventCode=4625 AccountName=baduser IpAddress=1.2.3.4"
    event = parser.parse(raw)
    assert event._raw == raw


def test_index_is_windows():
    raw = "EventCode=4624 AccountName=user"
    event = parser.parse(raw)
    assert event.index == "windows"


def test_to_dict_no_none_values():
    raw = "EventCode=4624 AccountName=user"
    event = parser.parse(raw)
    d = event.to_dict()
    assert None not in d.values()
    assert "event_id" in d
    assert "target_user" in d


@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
def test_parse_fixture_windows_events():
    """Parse all 1,000 fixture Windows events — none should raise."""
    path = FIXTURES / "windows_event_log_1000.json"
    events_raw = json.loads(path.read_text())
    errors = []
    for raw_event in events_raw:
        raw = raw_event.get("_raw", "")
        if not raw:
            continue
        try:
            parsed = parser.parse(raw)
            assert parsed._raw == raw
            assert parsed.event_id is not None
        except Exception as e:
            errors.append(f"{raw[:60]}: {e}")
    assert not errors, f"{len(errors)} parse errors:\n" + "\n".join(errors[:5])


@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
def test_fixture_windows_events_field_extraction_rate():
    """At least 95% of fixture events should have event_id extracted."""
    path = FIXTURES / "windows_event_log_1000.json"
    events_raw = json.loads(path.read_text())
    total = len(events_raw)
    extracted = sum(
        1 for e in events_raw
        if parser.parse(e.get("_raw", "")).event_id is not None
    )
    rate = extracted / total
    assert rate >= 0.95, f"Field extraction rate {rate:.1%} < 95%"
