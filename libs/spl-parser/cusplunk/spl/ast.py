"""
AST node types for the cuSplunk SPL parser.

All nodes are dataclasses. The tree mirrors the SPL pipeline:
    Pipeline([command, command, ...])

Each command corresponds to an SPL pipe stage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Union


# ─────────────────────────────────────────────────────────────────
#  BASE
# ─────────────────────────────────────────────────────────────────

@dataclass
class Node:
    """Base class for all AST nodes."""
    def accept(self, visitor: "Visitor") -> Any:
        method = f"visit_{type(self).__name__}"
        return getattr(visitor, method, visitor.generic_visit)(self)


# ─────────────────────────────────────────────────────────────────
#  TOP LEVEL
# ─────────────────────────────────────────────────────────────────

@dataclass
class Pipeline(Node):
    commands: List[Node]


@dataclass
class Subsearch(Node):
    pipeline: Pipeline


@dataclass
class MacroCall(Node):
    name: str
    args: List[Any]


# ─────────────────────────────────────────────────────────────────
#  SEARCH
# ─────────────────────────────────────────────────────────────────

@dataclass
class SearchNode(Node):
    expr: "SearchExpr"


@dataclass
class SearchOr(Node):
    terms: List[Node]


@dataclass
class SearchAnd(Node):
    terms: List[Node]


@dataclass
class SearchNot(Node):
    term: Node


@dataclass
class FieldComparison(Node):
    field: str
    op: str                  # =, !=, <, >, <=, >=, =~
    value: Any


@dataclass
class TimeModifier(Node):
    modifier: str            # earliest, latest, index_earliest, index_latest
    value: str


@dataclass
class Term(Node):
    value: str


SearchExpr = Union[SearchOr, SearchAnd, SearchNot, FieldComparison, TimeModifier, Term, Subsearch]


# ─────────────────────────────────────────────────────────────────
#  STATS / EVENTSTATS / STREAMSTATS
# ─────────────────────────────────────────────────────────────────

@dataclass
class AggCall(Node):
    func: str
    arg: Optional[Any]       # field name string, "*", or EvalArg node
    alias: Optional[str]


@dataclass
class EvalArg(Node):
    expr: "Expr"


@dataclass
class StatsNode(Node):
    aggs: List[AggCall]
    by: List[str]
    options: dict = field(default_factory=dict)


@dataclass
class EventstatsNode(Node):
    aggs: List[AggCall]
    by: List[str]
    allnum: bool = False


@dataclass
class StreamstatsNode(Node):
    aggs: List[AggCall]
    by: List[str]
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  EVAL
# ─────────────────────────────────────────────────────────────────

@dataclass
class EvalNode(Node):
    assignments: List["EvalAssign"]


@dataclass
class EvalAssign(Node):
    field: str
    expr: "Expr"


# ─────────────────────────────────────────────────────────────────
#  REX
# ─────────────────────────────────────────────────────────────────

@dataclass
class RexNode(Node):
    pattern: str
    field: Optional[str]
    mode: Optional[str]
    max_match: int = 1
    offset_field: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
#  JOIN
# ─────────────────────────────────────────────────────────────────

@dataclass
class JoinNode(Node):
    join_type: str           # inner, left, outer
    fields: List[str]
    subsearch: Subsearch
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  TIMECHART / CHART
# ─────────────────────────────────────────────────────────────────

@dataclass
class TimechartNode(Node):
    aggs: List[AggCall]
    by: Optional[str]
    span: Optional["SpanValue"]
    options: dict = field(default_factory=dict)


@dataclass
class ChartNode(Node):
    aggs: List[AggCall]
    over: str
    by: List[str]
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  TSTATS
# ─────────────────────────────────────────────────────────────────

@dataclass
class TstatsNode(Node):
    aggs: List[AggCall]
    datamodel: Optional[str]
    where: Optional["Expr"]
    by: List[str]
    span: Optional["SpanValue"]
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  TABLE / FIELDS / WHERE / DEDUP / SORT / HEAD / TAIL
# ─────────────────────────────────────────────────────────────────

@dataclass
class TableNode(Node):
    fields: List[str]


@dataclass
class FieldsNode(Node):
    mode: str                # "+" or "-"
    fields: List[str]


@dataclass
class WhereNode(Node):
    expr: "Expr"


@dataclass
class DedupNode(Node):
    max_events: Optional[int]
    fields: List[str]
    keepevents: bool = False
    keepempty: bool = False
    consecutive: bool = False
    sortby: Optional["SortSpec"] = None


@dataclass
class SortSpec(Node):
    fields: List["SortField"]


@dataclass
class SortField(Node):
    field: str
    direction: str           # "+" or "-"
    type_hint: Optional[str] = None   # auto, ip, num, str


@dataclass
class SortNode(Node):
    fields: List[SortField]
    limit: Optional[int] = None


@dataclass
class HeadNode(Node):
    count: Optional[Any]     # int or expr
    limit: Optional[int] = None
    keeplast: bool = False
    null_option: bool = False


@dataclass
class TailNode(Node):
    count: int = 10


# ─────────────────────────────────────────────────────────────────
#  RENAME
# ─────────────────────────────────────────────────────────────────

@dataclass
class RenameNode(Node):
    clauses: List["RenameClause"]


@dataclass
class RenameClause(Node):
    src: str
    dst: str


# ─────────────────────────────────────────────────────────────────
#  LOOKUP / INPUTLOOKUP / OUTPUTLOOKUP
# ─────────────────────────────────────────────────────────────────

@dataclass
class LookupNode(Node):
    name: str
    input_fields: List["LookupField"]
    output_mode: Optional[str]       # OUTPUT or OUTPUTNEW
    output_fields: List["LookupField"]


@dataclass
class LookupField(Node):
    src: str
    alias: Optional[str]


@dataclass
class InputlookupNode(Node):
    name: str
    where: Optional["Expr"]
    append: bool = False
    start: int = 0
    max: Optional[int] = None


@dataclass
class OutputlookupNode(Node):
    name: str
    append: bool = False
    create_empty: bool = True
    max: Optional[int] = None
    key_field: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
#  TRANSACTION
# ─────────────────────────────────────────────────────────────────

@dataclass
class TransactionNode(Node):
    fields: List[str]
    maxspan: Optional["SpanValue"]
    maxpause: Optional["SpanValue"]
    maxevents: Optional[int]
    startswith: Optional[Any]
    endswith: Optional[Any]
    keeporphans: bool = False
    mvlist: bool = False


# ─────────────────────────────────────────────────────────────────
#  BUCKET / BIN
# ─────────────────────────────────────────────────────────────────

@dataclass
class BucketNode(Node):
    field: str
    alias: Optional[str]
    span: Optional["SpanValue"]
    bins: Optional[int]
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  APPEND / APPENDCOLS / UNION
# ─────────────────────────────────────────────────────────────────

@dataclass
class AppendNode(Node):
    subsearch: Subsearch


@dataclass
class AppendColsNode(Node):
    subsearch: Subsearch


@dataclass
class UnionNode(Node):
    subsearches: List[Subsearch]
    max: Optional[int] = None


# ─────────────────────────────────────────────────────────────────
#  TOP / RARE
# ─────────────────────────────────────────────────────────────────

@dataclass
class TopNode(Node):
    fields: List[str]
    by: List[str]
    limit: int = 10
    options: dict = field(default_factory=dict)


@dataclass
class RareNode(Node):
    fields: List[str]
    by: List[str]
    limit: int = 10
    options: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────
#  FILLNULL / MAKERESULTS
# ─────────────────────────────────────────────────────────────────

@dataclass
class FillnullNode(Node):
    value: str = "0"
    fields: List[str] = field(default_factory=list)


@dataclass
class MakeresultsNode(Node):
    count: int = 1
    annotate: bool = False
    splunk_server: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
#  EXTRACT / KVFORM / MULTIKV
# ─────────────────────────────────────────────────────────────────

@dataclass
class ExtractNode(Node):
    options: dict = field(default_factory=dict)


@dataclass
class KvformNode(Node):
    field: Optional[str] = None
    output: Optional[str] = None


@dataclass
class MultikvNode(Node):
    fields: List[str] = field(default_factory=list)
    rmorig: bool = False


# ─────────────────────────────────────────────────────────────────
#  cuSplunk EXTENSION
# ─────────────────────────────────────────────────────────────────

@dataclass
class GpuHintNode(Node):
    memory: Optional[int] = None
    stream: bool = False


@dataclass
class DeltaNode(Node):
    field: str
    alias: Optional[str] = None


# ─────────────────────────────────────────────────────────────────
#  EXPRESSIONS
# ─────────────────────────────────────────────────────────────────

@dataclass
class OrExpr(Node):
    terms: List["Expr"]


@dataclass
class AndExpr(Node):
    terms: List["Expr"]


@dataclass
class NotExpr(Node):
    expr: "Expr"


@dataclass
class CompareExpr(Node):
    left: "Expr"
    op: str
    right: "Expr"


@dataclass
class LikeExpr(Node):
    expr: "Expr"
    pattern: str


@dataclass
class InExpr(Node):
    expr: "Expr"
    values: List[Any]
    negated: bool = False


@dataclass
class BinaryExpr(Node):
    left: "Expr"
    op: str          # +, -, *, /, %
    right: "Expr"


@dataclass
class UnaryExpr(Node):
    op: str          # -, +
    expr: "Expr"


@dataclass
class FunctionCall(Node):
    name: str
    args: List["Expr"]


@dataclass
class FieldRef(Node):
    name: str


@dataclass
class StringLiteral(Node):
    value: str


@dataclass
class NumberLiteral(Node):
    value: Union[int, float]


@dataclass
class BoolLiteral(Node):
    value: bool


@dataclass
class NullLiteral(Node):
    pass


Expr = Union[
    OrExpr, AndExpr, NotExpr, CompareExpr, LikeExpr, InExpr,
    BinaryExpr, UnaryExpr, FunctionCall, FieldRef,
    StringLiteral, NumberLiteral, BoolLiteral, NullLiteral,
    Subsearch, MacroCall,
]


# ─────────────────────────────────────────────────────────────────
#  SHARED VALUE TYPES
# ─────────────────────────────────────────────────────────────────

@dataclass
class SpanValue(Node):
    value: Union[int, float]
    unit: str                # s, m, h, d, w, mon, q, y (canonical)
