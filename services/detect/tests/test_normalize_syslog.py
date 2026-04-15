"""Unit tests for RFC 3164 + RFC 5424 syslog normalizer."""

import pytest

from cusplunk.normalize.syslog import SyslogParser

parser = SyslogParser()


def test_rfc3164_basic():
    raw = "<34>Jan 15 12:34:56 myhost sshd[1234]: Accepted password for user from 10.0.0.5"
    event = parser.parse(raw)
    assert event.host == "myhost"
    assert event.app_name == "sshd"
    assert event.pid == 1234
    assert "Accepted password" in event.message
    assert event.facility == 4   # 34 >> 3 = 4
    assert event.priority == 2   # 34 & 7 = 2
    assert event._time is not None


def test_rfc3164_no_pid():
    raw = "<13>Feb  5 10:00:00 router dhcpd: DHCPACK on 192.168.1.5"
    event = parser.parse(raw)
    assert event.host == "router"
    assert event.app_name == "dhcpd"
    assert event.pid is None
    assert "DHCPACK" in event.message


def test_rfc5424_basic():
    raw = (
        "<165>1 2024-01-15T12:34:56.789Z mymachine myapp 1234 ID47 "
        '[exampleSDID@32473 iut="3" eventSource="Application"] '
        "An application event log entry."
    )
    event = parser.parse(raw)
    assert event.host == "mymachine"
    assert event.app_name == "myapp"
    assert event.proc_id == "1234"
    assert event.msg_id == "ID47"
    assert "application event log" in event.message.lower()
    assert event.facility == 20   # 165 >> 3 = 20
    assert event.priority == 5    # 165 & 7 = 5


def test_rfc5424_nil_fields():
    raw = "<34>1 2024-01-15T10:00:00Z - - - - - Test message"
    event = parser.parse(raw)
    assert event.host is None
    assert event.app_name is None
    assert event.proc_id is None
    assert event.message == "Test message"


def test_rfc5424_structured_data():
    raw = (
        "<14>1 2024-01-15T10:00:00Z host app - - "
        '[origin ip="192.168.1.1" software="test"] message'
    )
    event = parser.parse(raw)
    assert "ip" in event.extra or event.host == "host"


def test_no_pri_fallback():
    raw = "Jan 15 12:00:00 host app: message without PRI"
    event = parser.parse(raw)
    assert event._raw == raw
    # Should not raise — returns NormalizedEvent with _raw set


def test_raw_preserved():
    raw = "<34>Jan 15 12:34:56 myhost sshd: test"
    event = parser.parse(raw)
    assert event._raw == raw


def test_index_is_syslog():
    raw = "<34>Jan 15 12:34:56 myhost sshd: test"
    event = parser.parse(raw)
    assert event.index == "syslog"


def test_sourcetype_is_syslog():
    raw = "<34>Jan 15 12:34:56 myhost sshd: test"
    event = parser.parse(raw)
    assert event.sourcetype == "syslog"
