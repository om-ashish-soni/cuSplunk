"""Unit tests for SigmaParser."""

import textwrap
from pathlib import Path

import pytest

from cusplunk.sigma.parser import (
    AggregationCondition,
    LogSource,
    SigmaParser,
    SigmaParseError,
    SigmaRule,
)


FIXTURES = Path(__file__).parent.parent.parent.parent / "tests/fixtures/sigma/test_rules"

parser = SigmaParser()


# ── Basic parsing ──────────────────────────────────────────────────

def test_parse_minimal_rule():
    yaml_text = textwrap.dedent("""
        title: Test Rule
        id: aaaaaaaa-0000-4000-8000-000000000001
        status: test
        description: A minimal test rule.
        author: test
        date: 2024-01-01
        logsource:
          product: windows
          service: security
        detection:
          selection:
            EventCode: 4625
          condition: selection
        level: medium
    """)
    rule = parser.parse(yaml_text)
    assert rule.title == "Test Rule"
    assert rule.id == "aaaaaaaa-0000-4000-8000-000000000001"
    assert rule.status == "test"
    assert rule.level == "medium"
    assert rule.logsource.product == "windows"
    assert rule.logsource.service == "security"
    assert rule.detection.condition == "selection"
    assert "selection" in rule.detection.selections
    assert rule.detection.aggregation is None


def test_parse_field_modifiers():
    yaml_text = textwrap.dedent("""
        title: Modifier Test
        status: test
        logsource:
          product: windows
        detection:
          sel:
            CommandLine|contains: mimikatz
            ProcessName|endswith: .exe
            ParentImage|startswith: C:\\\\Windows
          condition: sel
        level: high
    """)
    rule = parser.parse(yaml_text)
    sel = rule.detection.selections["sel"]
    assert len(sel.matchers) == 3

    matcher_map = {m.field_name: m for m in sel.matchers}
    assert "contains" in matcher_map["CommandLine"].modifiers
    assert "endswith" in matcher_map["ProcessName"].modifiers
    assert "startswith" in matcher_map["ParentImage"].modifiers


def test_parse_field_contains_all():
    yaml_text = textwrap.dedent("""
        title: Contains All Test
        status: test
        logsource:
          product: windows
        detection:
          sel:
            CommandLine|contains|all:
              - /c
              - whoami
          condition: sel
        level: high
    """)
    rule = parser.parse(yaml_text)
    matcher = rule.detection.selections["sel"].matchers[0]
    assert "contains" in matcher.modifiers
    assert "all" in matcher.modifiers
    assert "/c" in matcher.values
    assert "whoami" in matcher.values


def test_parse_regex_modifier():
    yaml_text = textwrap.dedent("""
        title: Regex Test
        status: test
        logsource:
          category: process_creation
        detection:
          sel:
            CommandLine|re: '^.*\\\\cmd\\.exe.*$'
          condition: sel
        level: medium
    """)
    rule = parser.parse(yaml_text)
    matcher = rule.detection.selections["sel"].matchers[0]
    assert "re" in matcher.modifiers


def test_parse_field_list_values():
    yaml_text = textwrap.dedent("""
        title: List Values Test
        status: test
        logsource:
          product: windows
        detection:
          sel:
            EventCode:
              - 4624
              - 4625
              - 4634
          condition: sel
        level: low
    """)
    rule = parser.parse(yaml_text)
    matcher = rule.detection.selections["sel"].matchers[0]
    assert len(matcher.values) == 3
    assert "4624" in str(matcher.values)


def test_parse_and_condition():
    yaml_text = textwrap.dedent("""
        title: AND Condition
        status: test
        logsource:
          category: firewall
        detection:
          selection:
            action: deny
          filter:
            src_ip: 10.0.0.1
          condition: selection and not filter
        level: medium
    """)
    rule = parser.parse(yaml_text)
    assert rule.detection.condition == "selection and not filter"
    assert "selection" in rule.detection.selections
    assert "filter" in rule.detection.selections


def test_parse_aggregation_condition():
    yaml_text = textwrap.dedent("""
        title: Aggregation Test
        status: test
        logsource:
          category: firewall
        detection:
          selection:
            action: deny
            dst_port: 22
          condition: selection | count() by src_ip > 5
        level: medium
    """)
    rule = parser.parse(yaml_text)
    agg = rule.detection.aggregation
    assert agg is not None
    assert agg.function == "count"
    assert agg.group_by == "src_ip"
    assert agg.op == ">"
    assert agg.threshold == 5


def test_parse_tags():
    yaml_text = textwrap.dedent("""
        title: Tags Test
        status: test
        logsource:
          product: windows
        detection:
          selection:
            EventCode: 4625
          condition: selection
        tags:
          - attack.credential_access
          - attack.t1110
        level: high
    """)
    rule = parser.parse(yaml_text)
    assert "attack.credential_access" in rule.tags
    assert "attack.t1110" in rule.tags


def test_parse_missing_condition_raises():
    yaml_text = textwrap.dedent("""
        title: Bad Rule
        status: test
        logsource:
          product: windows
        detection:
          selection:
            EventCode: 4625
        level: medium
    """)
    with pytest.raises(SigmaParseError, match="condition"):
        parser.parse(yaml_text)


def test_parse_invalid_yaml_raises():
    with pytest.raises(SigmaParseError):
        parser.parse("{{invalid: yaml: }: }")


def test_parse_logsource_fields():
    yaml_text = textwrap.dedent("""
        title: LogSource Test
        status: test
        logsource:
          category: network_connection
          product: windows
          service: sysmon
        detection:
          selection:
            dst_port: 4444
          condition: selection
        level: high
    """)
    rule = parser.parse(yaml_text)
    ls = rule.logsource
    assert ls.category == "network_connection"
    assert ls.product == "windows"
    assert ls.service == "sysmon"


# ── Fixture rules parsing ──────────────────────────────────────────

@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
def test_parse_all_fixture_sigma_rules():
    """All 10 fixture Sigma rules must parse without error."""
    rules = parser.parse_directory(FIXTURES)
    assert len(rules) == 10, f"Expected 10 rules, got {len(rules)}"


@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
@pytest.mark.parametrize("filename", [
    "brute_force_ssh.yml",
    "windows_failed_logon.yml",
    "rdp_scan.yml",
    "privilege_escalation_token.yml",
    "data_exfil_large_upload.yml",
    "new_user_created.yml",
    "port_scan_horizontal.yml",
    "kerberos_ticket_request_unusual.yml",
    "firewall_policy_bypass.yml",
    "lateral_movement_pass_the_hash.yml",
])
def test_parse_specific_fixture_rule(filename):
    rule = parser.parse_file(FIXTURES / filename)
    assert rule.title
    assert rule.detection.condition
    assert rule.level in ("low", "medium", "high", "critical", "informational")


@pytest.mark.skipif(not FIXTURES.exists(), reason="fixtures not generated")
def test_fixture_rules_have_mitre_tags():
    """All fixture rules should have at least one ATT&CK tag."""
    rules = parser.parse_directory(FIXTURES)
    for rule in rules:
        assert any("attack." in t for t in rule.tags), (
            f"Rule '{rule.title}' has no ATT&CK tags"
        )
