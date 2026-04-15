"""Unit tests for CEF normalizer."""

import pytest

from cusplunk.normalize.cef import CEFParser

parser = CEFParser()


def test_parse_basic_cef():
    raw = (
        "CEF:0|Palo Alto Networks|PAN-OS|10.0|threat|Generic Threat|7|"
        "src=1.2.3.4 dst=5.6.7.8 spt=55123 dpt=443 act=alert"
    )
    event = parser.parse(raw)
    assert event.device_vendor == "Palo Alto Networks"
    assert event.device_product == "PAN-OS"
    assert event.device_version == "10.0"
    assert event.signature_id == "threat"
    assert event.name == "Generic Threat"
    assert event.src_ip == "1.2.3.4"
    assert event.dst_ip == "5.6.7.8"
    assert event.src_port == 55123
    assert event.dst_port == 443
    assert event.action == "alert"


def test_parse_severity_numeric():
    # CEF 0-3=low, 4-6=medium, 7-8=high, 9-10=critical
    assert parser.parse("CEF:0|V|P|1|id|n|9|").severity == "critical"
    assert parser.parse("CEF:0|V|P|1|id|n|10|").severity == "critical"
    assert parser.parse("CEF:0|V|P|1|id|n|8|").severity == "high"
    assert parser.parse("CEF:0|V|P|1|id|n|7|").severity == "high"
    assert parser.parse("CEF:0|V|P|1|id|n|5|").severity == "medium"
    assert parser.parse("CEF:0|V|P|1|id|n|2|").severity == "low"
    assert parser.parse("CEF:0|V|P|1|id|n|0|").severity == "low"


def test_parse_severity_label():
    raw = "CEF:0|V|P|1|id|name|High|"
    event = parser.parse(raw)
    assert event.severity == "high"


def test_parse_user_fields():
    raw = "CEF:0|V|P|1|id|name|5|suser=jsmith duser=admin"
    event = parser.parse(raw)
    assert event.user == "jsmith"
    assert event.target_user == "admin"


def test_parse_message_field():
    raw = "CEF:0|V|P|1|id|name|5|msg=Login failed for user admin"
    event = parser.parse(raw)
    assert event.message == "Login failed for user admin"


def test_parse_time_epoch_ms():
    raw = "CEF:0|V|P|1|id|name|5|rt=1700000000000"
    event = parser.parse(raw)
    # rt is epoch ms → _time in seconds
    assert abs(event._time - 1_700_000_000.0) < 1


def test_parse_extra_fields():
    raw = "CEF:0|V|P|1|id|name|5|customKey=customValue"
    event = parser.parse(raw)
    assert event.extra.get("customKey") == "customValue"


def test_raw_preserved():
    raw = "CEF:0|V|P|1|id|name|5|src=1.2.3.4"
    event = parser.parse(raw)
    assert event._raw == raw


def test_invalid_cef_no_crash():
    raw = "not a cef message at all"
    event = parser.parse(raw)
    assert event._raw == raw
    assert event.device_vendor is None


def test_index_is_cef():
    raw = "CEF:0|V|P|1|id|name|5|src=1.2.3.4"
    event = parser.parse(raw)
    assert event.index == "cef"
