"""
test_hypothesis.py — property-based tests.

Invariant: the parser must NEVER panic/crash on any string input.
Valid SPL strings built from grammar should always parse successfully.
"""
import string

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st


# ── Strategy: build valid-ish SPL strings ───────────────────────────────────

COMMANDS = [
    "stats count",
    "stats count by host",
    "stats sum(bytes) by host",
    "stats avg(response_time) by host",
    "stats dc(user) by host",
    "eval x=1",
    "eval x=bytes/1024",
    "table host, user",
    "fields host, user",
    "sort -count",
    "sort host",
    "head 10",
    "head 100",
    "tail 10",
    "dedup host",
    "dedup user, host",
    "where count>0",
    "where bytes>1000",
    "rename host as server",
    "timechart span=1h count",
    "timechart span=5m count by host",
    "bucket _time span=1h",
    "top 10 host",
    "rare dest_port",
    "fillnull value=\"0\"",
]

SEARCH_PREFIXES = [
    "search index=main",
    "search index=main error",
    "search index=main sourcetype=syslog",
    "search index=main host=web*",
    "search index=main status=200",
    "search index=main src_ip=10.0.0.1",
    "search index=main bytes>1000",
    "search index=main NOT error",
    "search index=main (error OR warning)",
]

spl_command = st.sampled_from(COMMANDS)
spl_prefix  = st.sampled_from(SEARCH_PREFIXES)


@st.composite
def valid_spl_pipeline(draw):
    """Generate a syntactically valid SPL pipeline string."""
    prefix   = draw(spl_prefix)
    n_stages = draw(st.integers(min_value=0, max_value=4))
    stages   = draw(st.lists(spl_command, min_size=n_stages, max_size=n_stages))
    parts    = [prefix] + stages
    return " | ".join(parts)


@given(spl=valid_spl_pipeline())
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=5000,
)
def test_valid_spl_never_panics(spl):
    """Any string built from valid grammar fragments must parse without exception."""
    from cusplunk.spl.parser import SPLParser
    result = SPLParser.parse(spl, strict=True)
    assert result is not None
    assert len(result.commands) >= 1


@given(spl=valid_spl_pipeline())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=5000,
)
def test_parse_result_is_pipeline(spl):
    """Parse result is always a Pipeline with at least 1 command."""
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import Pipeline
    result = SPLParser.parse(spl)
    assert isinstance(result, Pipeline)


@given(spl=valid_spl_pipeline())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=5000,
)
def test_visitor_on_any_valid_pipeline(spl):
    """Visitor traversal must complete without error on any valid pipeline."""
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.visitor import Visitor

    result = SPLParser.parse(spl)
    v = Visitor()
    v.visit(result)   # must not raise


@given(spl=valid_spl_pipeline())
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
    deadline=5000,
)
def test_transformer_identity_on_any_valid(spl):
    """Identity transformer must preserve command count."""
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.visitor import Transformer

    original = SPLParser.parse(spl)
    t = Transformer()
    transformed = t.visit(original)
    assert len(transformed.commands) == len(original.commands)


# ── Arbitrary strings must never crash the parser ───────────────────────────

@given(garbage=st.text(
    alphabet=string.printable,
    min_size=1,
    max_size=200,
))
@settings(
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    deadline=5000,
)
def test_arbitrary_string_never_crashes(garbage):
    """Parser must never hard-crash on arbitrary string — raise or return, never segfault."""
    from cusplunk.spl.parser import SPLParser, SPLParseError
    try:
        SPLParser.parse(garbage, strict=True)
    except SPLParseError:
        pass   # expected for invalid input
    except Exception as e:
        # Some ANTLR internal errors are OK; hard crashes are not
        allowed = (
            "RecognitionException",
            "NoViableAltException",
            "InputMismatchException",
            "ParseCancellationException",
            "LexerNoViableAltException",
        )
        if not any(t in type(e).__name__ for t in allowed):
            raise AssertionError(f"Unexpected exception type {type(e).__name__}: {e}") from e


# ── Stats agg round-trip ─────────────────────────────────────────────────────

AGG_FUNCS = ["count", "sum", "avg", "min", "max", "dc", "median", "stdev", "range", "first", "last"]
FIELDS     = ["bytes", "duration", "response_time", "score", "value"]

@given(
    func=st.sampled_from(AGG_FUNCS),
    field=st.sampled_from(FIELDS),
    by_field=st.sampled_from(["host", "user", "src_ip", "dest_port", "action"]),
)
@settings(max_examples=50, deadline=3000)
def test_stats_agg_roundtrip(func, field, by_field):
    """stats <func>(<field>) by <field> always parses and returns correct func name."""
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import StatsNode
    spl = f"search index=main | stats {func}({field}) by {by_field}"
    result = SPLParser.parse(spl)
    stats = result.commands[1]
    assert isinstance(stats, StatsNode)
    assert stats.aggs[0].func == func
    assert stats.by == [by_field]


# ── Timechart span units ─────────────────────────────────────────────────────

SPAN_UNITS = ["s", "m", "h", "d", "w"]

@given(
    n=st.integers(min_value=1, max_value=100),
    unit=st.sampled_from(SPAN_UNITS),
)
@settings(max_examples=50, deadline=3000)
def test_timechart_span_units(n, unit):
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TimechartNode, SpanValue
    spl = f"search index=main | timechart span={n}{unit} count"
    result = SPLParser.parse(spl)
    tc = result.commands[1]
    assert isinstance(tc, TimechartNode)
    assert isinstance(tc.span, SpanValue)
    assert tc.span.value == n


# ── Eval arithmetic ──────────────────────────────────────────────────────────

@given(
    a=st.integers(min_value=1, max_value=1000),
    b=st.integers(min_value=1, max_value=1000),
    op=st.sampled_from(["+", "-", "*", "/"]),
)
@settings(max_examples=50, deadline=3000)
def test_eval_arithmetic(a, b, op):
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import EvalNode, BinaryExpr
    spl = f"search index=main | eval result={a}{op}{b}"
    result = SPLParser.parse(spl)
    ev = result.commands[1]
    assert isinstance(ev, EvalNode)
    assert len(ev.assignments) == 1
    assert isinstance(ev.assignments[0].expr, BinaryExpr)


# ── Head count ───────────────────────────────────────────────────────────────

@given(n=st.integers(min_value=1, max_value=100000))
@settings(max_examples=50, deadline=3000)
def test_head_count_roundtrip(n):
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import HeadNode
    result = SPLParser.parse(f"search index=main | head {n}")
    hd = result.commands[1]
    assert isinstance(hd, HeadNode)
    assert hd.count == n
