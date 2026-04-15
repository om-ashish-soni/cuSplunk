"""
test_corpus.py — parse all 500 queries in corpus/basic.txt.

Acceptance criterion from S3.1:
    Zero SPLParseError on the entire corpus.
    Each query must return a Pipeline with at least one command.
"""
import os
import pytest

_CORPUS = os.path.join(os.path.dirname(__file__), "..", "corpus", "basic.txt")


def _load_corpus():
    queries = []
    with open(_CORPUS, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading "search " so the pipeline rule matches
            queries.append(line)
    return queries


CORPUS_QUERIES = _load_corpus()


@pytest.mark.parametrize("spl", CORPUS_QUERIES, ids=lambda q: q[:60])
def test_corpus_no_parse_error(spl):
    """Every corpus query must parse without error."""
    from cusplunk.spl.parser import SPLParser
    result = SPLParser.parse(spl, strict=True)
    assert result is not None
    assert len(result.commands) >= 1, f"Expected at least 1 command, got 0 for: {spl!r}"


def test_corpus_count():
    """Exactly 500 queries must be in the corpus."""
    assert len(CORPUS_QUERIES) == 500, (
        f"Expected 500 corpus queries, found {len(CORPUS_QUERIES)}"
    )


def test_corpus_file_exists():
    assert os.path.isfile(_CORPUS), f"Corpus file not found: {_CORPUS}"


def test_basic_search_parses():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import SearchNode
    result = SPLParser.parse("search index=main")
    assert len(result.commands) == 1
    assert isinstance(result.commands[0], SearchNode)


def test_stats_pipeline_parses():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import SearchNode, StatsNode
    result = SPLParser.parse("search index=main | stats count by host")
    assert len(result.commands) == 2
    assert isinstance(result.commands[0], SearchNode)
    assert isinstance(result.commands[1], StatsNode)


def test_stats_by_fields():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import StatsNode
    result = SPLParser.parse("search index=main | stats count by host, sourcetype")
    stats = result.commands[1]
    assert isinstance(stats, StatsNode)
    assert stats.by == ["host", "sourcetype"]


def test_stats_agg_with_alias():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import StatsNode
    result = SPLParser.parse("search index=main | stats sum(bytes) as total by host")
    stats = result.commands[1]
    assert isinstance(stats, StatsNode)
    assert len(stats.aggs) == 1
    agg = stats.aggs[0]
    assert agg.func == "sum"
    assert agg.arg == "bytes"
    assert agg.alias == "total"


def test_eval_assignment():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import EvalNode, EvalAssign
    result = SPLParser.parse("search index=main | eval gb=bytes/1073741824")
    ev = result.commands[1]
    assert isinstance(ev, EvalNode)
    assert len(ev.assignments) == 1
    assert ev.assignments[0].field == "gb"


def test_rex_basic():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import RexNode
    result = SPLParser.parse('search index=main | rex "(?P<ip>\\\\d+\\\\.\\\\d+)"')
    rex = result.commands[1]
    assert isinstance(rex, RexNode)
    assert "ip" in rex.pattern


def test_table_fields():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TableNode
    result = SPLParser.parse("search index=main | table _time, host, user")
    tbl = result.commands[1]
    assert isinstance(tbl, TableNode)
    assert tbl.fields == ["_time", "host", "user"]


def test_sort_direction():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import SortNode
    result = SPLParser.parse("search index=main | sort -count")
    srt = result.commands[1]
    assert isinstance(srt, SortNode)
    assert srt.fields[0].direction == "-"
    assert srt.fields[0].field == "count"


def test_head_count():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import HeadNode
    result = SPLParser.parse("search index=main | head 20")
    hd = result.commands[1]
    assert isinstance(hd, HeadNode)
    assert hd.count == 20


def test_tail_count():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TailNode
    result = SPLParser.parse("search index=main | tail 5")
    tl = result.commands[1]
    assert isinstance(tl, TailNode)
    assert tl.count == 5


def test_rename_clause():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import RenameNode
    result = SPLParser.parse('search index=main | rename src_ip as "Source IP"')
    rn = result.commands[1]
    assert isinstance(rn, RenameNode)
    assert len(rn.clauses) == 1
    assert rn.clauses[0].src == "src_ip"
    assert rn.clauses[0].dst == "Source IP"


def test_dedup_basic():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import DedupNode
    result = SPLParser.parse("search index=main | dedup host")
    dd = result.commands[1]
    assert isinstance(dd, DedupNode)
    assert dd.fields == ["host"]


def test_timechart_span():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TimechartNode, SpanValue
    result = SPLParser.parse("search index=main | timechart span=1h count")
    tc = result.commands[1]
    assert isinstance(tc, TimechartNode)
    assert isinstance(tc.span, SpanValue)
    assert tc.span.unit == "h"
    assert tc.span.value == 1


def test_where_expr():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import WhereNode
    result = SPLParser.parse("search index=main | where count>100")
    wh = result.commands[1]
    assert isinstance(wh, WhereNode)


def test_fields_include():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import FieldsNode
    result = SPLParser.parse("search index=main | fields host, user, action")
    fld = result.commands[1]
    assert isinstance(fld, FieldsNode)
    assert fld.mode == "+"


def test_fields_exclude():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import FieldsNode
    result = SPLParser.parse("search index=main | fields - _raw, punct")
    fld = result.commands[1]
    assert isinstance(fld, FieldsNode)
    assert fld.mode == "-"


def test_lookup_basic():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import LookupNode
    result = SPLParser.parse("search index=main | lookup geo_lookup src_ip OUTPUT country, city")
    lk = result.commands[1]
    assert isinstance(lk, LookupNode)
    assert lk.name == "geo_lookup"
    assert lk.output_mode == "OUTPUT"


def test_inputlookup():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import InputlookupNode
    result = SPLParser.parse("search index=main | inputlookup user_list.csv")
    il = result.commands[1]
    assert isinstance(il, InputlookupNode)
    assert il.name == "user_list.csv"


def test_transaction_maxspan():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TransactionNode
    result = SPLParser.parse("search index=main | transaction session_id maxspan=30m")
    tx = result.commands[1]
    assert isinstance(tx, TransactionNode)
    assert "session_id" in tx.fields
    assert tx.maxspan is not None
    assert tx.maxspan.unit == "m"
    assert tx.maxspan.value == 30


def test_bucket_span():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import BucketNode
    result = SPLParser.parse("search index=main | bucket _time span=1h")
    bk = result.commands[1]
    assert isinstance(bk, BucketNode)
    assert bk.field == "_time"
    assert bk.span.unit == "h"


def test_fillnull_default():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import FillnullNode
    result = SPLParser.parse("search index=main | fillnull")
    fn = result.commands[1]
    assert isinstance(fn, FillnullNode)


def test_top_command():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import TopNode
    result = SPLParser.parse("search index=main | top 5 host")
    tp = result.commands[1]
    assert isinstance(tp, TopNode)
    assert tp.limit == 5
    assert "host" in tp.fields


def test_rare_command():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import RareNode
    result = SPLParser.parse("search index=main | rare dest_port")
    rr = result.commands[1]
    assert isinstance(rr, RareNode)


def test_eventstats():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import EventstatsNode
    result = SPLParser.parse("search index=main | eventstats count as total_count")
    es = result.commands[1]
    assert isinstance(es, EventstatsNode)


def test_streamstats():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import StreamstatsNode
    result = SPLParser.parse("search index=main | streamstats count by host")
    ss = result.commands[1]
    assert isinstance(ss, StreamstatsNode)


def test_makeresults():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import MakeresultsNode
    result = SPLParser.parse("search | makeresults count=10")
    mr = result.commands[1]
    assert isinstance(mr, MakeresultsNode)
    assert mr.count == 10


def test_gpu_hint_extension():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import GpuHintNode
    result = SPLParser.parse("search index=main | gpu_hint memory=8192 stream=true | stats count by host")
    assert len(result.commands) == 3
    gh = result.commands[1]
    assert isinstance(gh, GpuHintNode)
    assert gh.memory == 8192
    assert gh.stream is True


def test_subsearch_in_join():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import JoinNode, Subsearch
    result = SPLParser.parse(
        "search index=main | join src_ip [search index=threat | fields ip, score | rename ip as src_ip]"
    )
    jn = result.commands[1]
    assert isinstance(jn, JoinNode)
    assert isinstance(jn.subsearch, Subsearch)


def test_long_pipeline():
    from cusplunk.spl.parser import SPLParser
    spl = (
        "search index=main sourcetype=access_combined status=404 "
        "| rex field=uri \"(?P<path>[^?]+)\" "
        "| stats count by path "
        "| sort -count "
        "| head 20 "
        "| lookup url_category_lookup path OUTPUT category "
        "| fillnull value=\"uncategorized\" category "
        "| table path, category, count"
    )
    result = SPLParser.parse(spl)
    assert len(result.commands) == 8


def test_multiple_stats_aggs():
    from cusplunk.spl.parser import SPLParser
    from cusplunk.spl.ast import StatsNode
    result = SPLParser.parse(
        "search index=main | stats count, sum(bytes) as total_bytes, avg(bytes) as avg_bytes by host"
    )
    stats = result.commands[1]
    assert isinstance(stats, StatsNode)
    assert len(stats.aggs) == 3
    funcs = [a.func for a in stats.aggs]
    assert "count" in funcs
    assert "sum" in funcs
    assert "avg" in funcs
