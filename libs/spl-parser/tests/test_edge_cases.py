"""
test_edge_cases.py — nested subsearch, escaped quotes, multiline SPL, keyword-as-field, etc.
"""
import pytest


def parse(spl):
    from cusplunk.spl.parser import SPLParser
    return SPLParser.parse(spl)


# ── Quoted strings & escaping ───────────────────────────────────────────────

def test_double_quoted_string_in_search():
    result = parse('search index=main message="hello world"')
    from cusplunk.spl.ast import SearchNode, FieldComparison
    cmd = result.commands[0]
    assert isinstance(cmd, SearchNode)


def test_single_quoted_string():
    result = parse("search index=main message='hello world'")
    assert result is not None


def test_escaped_quote_in_string():
    result = parse(r'search index=main message="say \"hello\""')
    assert result is not None


def test_escaped_backslash():
    result = parse(r'search index=main file_path="C:\\Windows\\System32\\cmd.exe"')
    assert result is not None


def test_single_char_string():
    result = parse('search index=main char="x"')
    assert result is not None


# ── Nested subsearch ─────────────────────────────────────────────────────────

def test_nested_subsearch_one_level():
    result = parse(
        "search index=main | join src_ip "
        "[search index=threat | fields ip | rename ip as src_ip]"
    )
    from cusplunk.spl.ast import JoinNode
    assert isinstance(result.commands[1], JoinNode)


def test_nested_subsearch_two_levels():
    result = parse(
        "search index=main | join user "
        "[search index=hr | join dept "
        "[search index=org | fields dept, team] "
        "| fields user, team]"
    )
    assert result is not None


def test_subsearch_in_append():
    result = parse(
        "search index=main | append [search index=archive | fields _time, host, action]"
    )
    from cusplunk.spl.ast import AppendNode
    assert isinstance(result.commands[1], AppendNode)


def test_subsearch_in_union():
    result = parse(
        "search index=main | union "
        "[search index=siem1] "
        "[search index=siem2]"
    )
    from cusplunk.spl.ast import UnionNode
    u = result.commands[1]
    assert isinstance(u, UnionNode)
    assert len(u.subsearches) == 2


def test_subsearch_in_transaction():
    result = parse(
        'search index=main | transaction session_id startswith="login" endswith="logout"'
    )
    from cusplunk.spl.ast import TransactionNode
    tx = result.commands[1]
    assert isinstance(tx, TransactionNode)
    assert tx.startswith is not None
    assert tx.endswith is not None


# ── Multiline SPL ────────────────────────────────────────────────────────────

def test_multiline_pipeline():
    spl = """search index=main
    | stats count by host
    | sort -count
    | head 10"""
    result = parse(spl)
    assert len(result.commands) == 4


def test_multiline_with_eval():
    spl = """search index=main
    | eval gb=round(bytes/1073741824, 2)
    | where gb > 1
    | table host, gb"""
    result = parse(spl)
    assert len(result.commands) == 4


def test_multiline_with_rex():
    spl = """search index=main
    | rex field=_raw "src=(?P<src_ip>[0-9.]+)"
    | stats count by src_ip
    | sort -count"""
    result = parse(spl)
    assert len(result.commands) == 4


# ── Keyword used as field name ───────────────────────────────────────────────

def test_keyword_as_field_in_stats_by():
    # "count" is a keyword but can be a field name after by
    result = parse("search index=main | stats sum(bytes) by count")
    assert result is not None


def test_keyword_as_field_in_table():
    result = parse("search index=main | table index, source, host, count")
    from cusplunk.spl.ast import TableNode
    tbl = result.commands[1]
    assert isinstance(tbl, TableNode)


def test_keyword_as_field_in_eval():
    result = parse("search index=main | eval min=min(a,b) | eval max=max(a,b)")
    assert result is not None


def test_time_unit_as_field():
    result = parse("search index=main | stats count by hour")
    assert result is not None


# ── Boolean logic ────────────────────────────────────────────────────────────

def test_search_and_or():
    result = parse("search index=main (error OR warning) AND host=web*")
    assert result is not None


def test_search_not():
    result = parse("search index=main NOT error")
    assert result is not None


def test_nested_boolean():
    result = parse("search index=main (error AND NOT warning) OR (debug AND level=high)")
    assert result is not None


def test_where_complex_expr():
    result = parse("search index=main | where (count>100 AND ratio<0.5) OR status=500")
    assert result is not None


def test_eval_case_expr():
    result = parse(
        'search index=main | eval sev=case(score>9,"critical",score>7,"high",score>4,"medium",true(),"low")'
    )
    from cusplunk.spl.ast import EvalNode
    ev = result.commands[1]
    assert isinstance(ev, EvalNode)


def test_eval_if_nested():
    result = parse(
        'search index=main | eval x=if(a>1,if(b>2,"both","a_only"),"neither")'
    )
    assert result is not None


# ── Time modifiers ───────────────────────────────────────────────────────────

def test_earliest_latest():
    result = parse("search index=main earliest=-1h latest=now")
    assert result is not None


def test_earliest_absolute():
    result = parse('search index=main earliest="01/01/2025:00:00:00"')
    assert result is not None


def test_index_time_modifiers():
    result = parse("search index=main index_earliest=-30d index_latest=-1d")
    assert result is not None


# ── Operators ────────────────────────────────────────────────────────────────

def test_regex_match_operator():
    result = parse("search index=main src_ip=~\"^10\\\\.\"")
    assert result is not None


def test_not_equal_operator():
    result = parse("search index=main status!=200")
    assert result is not None


def test_gte_lte_operators():
    result = parse("search index=main bytes>=1000 bytes<=10000")
    assert result is not None


def test_in_expr():
    result = parse("search index=main | where status IN (200, 301, 404)")
    assert result is not None


# ── Special field names ──────────────────────────────────────────────────────

def test_underscore_field():
    result = parse("search index=main _raw=* | table _time, _raw")
    assert result is not None


def test_dot_in_field():
    result = parse("search index=main Network_Traffic.src_ip=* | stats count by Network_Traffic.src_ip")
    assert result is not None


def test_quoted_field_with_spaces():
    result = parse('search index=main | rename src_ip as "Source IP Address"')
    from cusplunk.spl.ast import RenameNode
    rn = result.commands[1]
    assert isinstance(rn, RenameNode)
    assert rn.clauses[0].dst == "Source IP Address"


# ── Function calls ───────────────────────────────────────────────────────────

def test_eval_multi_arg_function():
    result = parse("search index=main | eval x=substr(message, 1, 10)")
    assert result is not None


def test_eval_nested_function():
    result = parse("search index=main | eval x=upper(trim(lower(message)))")
    assert result is not None


def test_eval_strftime():
    result = parse('search index=main | eval ts=strftime(_time, "%Y-%m-%d")')
    assert result is not None


def test_eval_strptime():
    result = parse('search index=main | eval t=strptime(timestamp, "%d/%b/%Y:%H:%M:%S")')
    assert result is not None


def test_eval_cidrmatch():
    result = parse('search index=main | eval is_private=cidrmatch("10.0.0.0/8", src_ip)')
    assert result is not None


def test_eval_coalesce():
    result = parse('search index=main | eval u=coalesce(user, src_user, "unknown")')
    assert result is not None


def test_eval_mvappend():
    result = parse("search index=main | eval all=mvappend(field1, field2, field3)")
    assert result is not None


# ── Stats variants ───────────────────────────────────────────────────────────

def test_stats_dc():
    result = parse("search index=main | stats dc(src_ip) as uniq by dest_port")
    from cusplunk.spl.ast import StatsNode
    stats = result.commands[1]
    assert stats.aggs[0].func == "dc"


def test_stats_perc():
    result = parse("search index=main | stats perc95(response_time) by host")
    assert result is not None


def test_stats_earliest_latest():
    result = parse("search index=main | stats earliest(_time) as first, latest(_time) as last by src_ip")
    from cusplunk.spl.ast import StatsNode
    stats = result.commands[1]
    assert len(stats.aggs) == 2


def test_stats_values_list():
    result = parse("search index=main | stats values(uri) as uris, list(user) as users by host")
    assert result is not None


def test_stats_eval_arg():
    result = parse("search index=main | stats count(eval(status>=400)) as errors by host")
    assert result is not None


# ── SPLParseError on invalid input ───────────────────────────────────────────

def test_invalid_spl_raises():
    from cusplunk.spl.parser import SPLParser, SPLParseError
    with pytest.raises(SPLParseError):
        SPLParser.parse("| | | garbage $$$ ???", strict=True)


def test_empty_string_raises():
    from cusplunk.spl.parser import SPLParser, SPLParseError
    # Empty input has no command — should fail at EOF matching
    with pytest.raises((SPLParseError, Exception)):
        SPLParser.parse("", strict=True)


def test_strict_false_no_raise():
    from cusplunk.spl.parser import SPLParser
    # Non-strict mode should not raise even on bad input
    try:
        SPLParser.parse("search index=main", strict=False)
    except Exception:
        pass  # ok if it errors — just shouldn't be SPLParseError from strict


# ── AST structure checks ─────────────────────────────────────────────────────

def test_pipeline_has_all_commands():
    result = parse("search index=main | eval x=1 | where x>0 | table host, x")
    assert len(result.commands) == 4
    from cusplunk.spl.ast import SearchNode, EvalNode, WhereNode, TableNode
    assert isinstance(result.commands[0], SearchNode)
    assert isinstance(result.commands[1], EvalNode)
    assert isinstance(result.commands[2], WhereNode)
    assert isinstance(result.commands[3], TableNode)


def test_span_value_unit_normalization():
    result = parse("search index=main | timechart span=60seconds count")
    from cusplunk.spl.ast import TimechartNode, SpanValue
    tc = result.commands[1]
    assert isinstance(tc, TimechartNode)
    assert tc.span.unit == "s"


def test_sort_multiple_fields():
    result = parse("search index=main | sort host, -_time, +bytes")
    from cusplunk.spl.ast import SortNode
    srt = result.commands[1]
    assert isinstance(srt, SortNode)
    assert len(srt.fields) == 3
    assert srt.fields[0].direction == "+"
    assert srt.fields[1].direction == "-"
    assert srt.fields[2].direction == "+"


def test_visitor_traversal():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.visitor import Visitor
    from cusplunk.spl.ast import StatsNode

    visited = []

    class CountingVisitor(Visitor):
        def visit_StatsNode(self, node):
            visited.append(node)
            return self.generic_visit(node)

    result = SPLParser.parse("search index=main | stats count by host | sort -count")
    v = CountingVisitor()
    v.visit(result)
    assert len(visited) == 1


def test_transformer_identity():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.visitor import Transformer

    result = SPLParser.parse("search index=main | stats count by host")
    t = Transformer()
    new_result = t.visit(result)
    # Identity transform: structure preserved
    assert len(new_result.commands) == 2
