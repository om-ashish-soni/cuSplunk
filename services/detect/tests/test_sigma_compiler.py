"""Unit tests for SigmaCompiler."""

import textwrap

import pytest

from cusplunk.sigma.compiler import SigmaCompiler, CompiledRule
from cusplunk.sigma.parser import SigmaParser

parser = SigmaParser()
compiler = SigmaCompiler()


def _compile(yaml_text: str) -> CompiledRule:
    rule = parser.parse(yaml_text)
    return compiler.compile(rule)


# ── Condition function correctness ────────────────────────────────

def test_condition_single_selection_true():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          selection:
            EventCode: 4625
          condition: selection
        level: medium
    """))
    assert cr.condition_fn({"selection": True}) is True
    assert cr.condition_fn({"selection": False}) is False


def test_condition_and_not():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          selection:
            EventCode: 4624
          filter:
            AccountName|endswith: "$"
          condition: selection and not filter
        level: medium
    """))
    assert cr.condition_fn({"selection": True, "filter": False}) is True
    assert cr.condition_fn({"selection": True, "filter": True}) is False
    assert cr.condition_fn({"selection": False, "filter": False}) is False


def test_condition_or():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel1:
            EventCode: 4624
          sel2:
            EventCode: 4625
          condition: sel1 or sel2
        level: medium
    """))
    assert cr.condition_fn({"sel1": True, "sel2": False}) is True
    assert cr.condition_fn({"sel1": False, "sel2": True}) is True
    assert cr.condition_fn({"sel1": False, "sel2": False}) is False


def test_condition_all_of():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel1:
            field1: val1
          sel2:
            field2: val2
          condition: all of sel*
        level: medium
    """))
    assert cr.condition_fn({"sel1": True, "sel2": True}) is True
    assert cr.condition_fn({"sel1": True, "sel2": False}) is False


def test_condition_1_of():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel1:
            field1: val1
          sel2:
            field2: val2
          condition: 1 of sel*
        level: medium
    """))
    assert cr.condition_fn({"sel1": False, "sel2": True}) is True
    assert cr.condition_fn({"sel1": False, "sel2": False}) is False


# ── Pattern compilation ───────────────────────────────────────────

def test_contains_pattern():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel:
            CommandLine|contains: mimikatz
          condition: sel
        level: high
    """))
    fp = cr.selections["sel"].field_patterns[0]
    assert "mimikatz" in fp.pattern
    assert not fp.require_all


def test_exact_match_anchored():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel:
            EventCode: 4625
          condition: sel
        level: medium
    """))
    fp = cr.selections["sel"].field_patterns[0]
    # Exact match: should be anchored
    assert "^" in fp.pattern
    assert "$" in fp.pattern


def test_endswith_pattern():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel:
            ProcessName|endswith: .exe
          condition: sel
        level: medium
    """))
    fp = cr.selections["sel"].field_patterns[0]
    assert fp.pattern.endswith("$") or "\\." in fp.pattern


def test_startswith_pattern():
    cr = _compile(textwrap.dedent("""
        title: T
        status: test
        logsource:
          product: windows
        detection:
          sel:
            ParentImage|startswith: C:\\\\Windows
          condition: sel
        level: medium
    """))
    fp = cr.selections["sel"].field_patterns[0]
    assert "^" in fp.pattern


def test_contains_all_sets_require_all():
    cr = _compile(textwrap.dedent("""
        title: T
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
    """))
    fp = cr.selections["sel"].field_patterns[0]
    assert fp.require_all is True


def test_multiple_values_alternation():
    cr = _compile(textwrap.dedent("""
        title: T
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
    """))
    fp = cr.selections["sel"].field_patterns[0]
    # All three values must appear in pattern
    assert "4624" in fp.pattern
    assert "4625" in fp.pattern
    assert "4634" in fp.pattern
