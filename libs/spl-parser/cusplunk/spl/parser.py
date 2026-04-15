"""
SPLParser — public API for parsing SPL queries into an AST.

Usage:
    from cusplunk.spl.parser import SPLParser

    ast = SPLParser.parse("index=main | stats count by host")
    # -> Pipeline(commands=[SearchNode(...), StatsNode(...)])

Under the hood this drives the ANTLR4-generated lexer/parser and
converts the raw parse tree into typed AST nodes (see ast.py).
"""
from __future__ import annotations

import os
import sys
from typing import Any, List, Optional, Union

# ── Make generated/ importable ───────────────────────────────────
_HERE = os.path.dirname(__file__)
_GEN  = os.path.normpath(os.path.join(_HERE, "..", "..", "generated"))
if _GEN not in sys.path:
    sys.path.insert(0, _GEN)

import re as _re

from antlr4 import CommonTokenStream, InputStream, ParseTreeVisitor
from antlr4.error.ErrorListener import ErrorListener
from antlr4.ListTokenSource import ListTokenSource
from antlr4.Token import CommonToken

from SPLLexer  import SPLLexer
from SPLParser import SPLParser as _ANTLRParser

from .ast import (
    AggCall, AndExpr, AppendColsNode, AppendNode, BinaryExpr, BoolLiteral,
    BucketNode, ChartNode, CompareExpr, DedupNode, DeltaNode, EvalArg, EvalAssign,
    EvalNode, EventstatsNode, ExtractNode, FieldComparison, FieldRef,
    FieldsNode, FillnullNode, FunctionCall, GpuHintNode, HeadNode,
    InExpr, InputlookupNode, JoinNode, KvformNode, LikeExpr,
    LookupField, LookupNode, MacroCall, MakeresultsNode, MultikvNode,
    NotExpr, NullLiteral, NumberLiteral, OrExpr, OutputlookupNode,
    Pipeline, RareNode, RenameClause, RenameNode, RexNode, SearchAnd,
    SearchNode, SearchNot, SearchOr, SortField, SortNode, SortSpec,
    SpanValue, StatsNode, StreamstatsNode, StringLiteral, Subsearch,
    TableNode, TailNode, Term, TimechartNode, TimeModifier, TopNode,
    TransactionNode, TstatsNode, UnaryExpr, UnionNode, WhereNode,
)


# ─────────────────────────────────────────────────────────────────
#  ERROR HANDLING
# ─────────────────────────────────────────────────────────────────

class SPLParseError(Exception):
    """Raised when the SPL input cannot be parsed."""
    def __init__(self, msg: str, line: int = 0, col: int = 0):
        super().__init__(f"line {line}:{col} {msg}")
        self.line = line
        self.col  = col


class _RaisingErrorListener(ErrorListener):
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        raise SPLParseError(msg, line, column)


# ─────────────────────────────────────────────────────────────────
#  SPAN UNIT NORMALIZATION
# ─────────────────────────────────────────────────────────────────

_UNIT_MAP = {
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s",
    "m": "m", "min": "m", "mins": "m", "minute": "m", "minutes": "m",
    "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h",
    "d": "d", "day": "d", "days": "d",
    "w": "w", "week": "w", "weeks": "w",
    "mon": "mon", "month": "mon", "months": "mon",
    "q": "q", "qtr": "q", "qtrs": "q", "quarter": "q", "quarters": "q",
    "y": "y", "yr": "y", "yrs": "y", "year": "y", "years": "y",
}


def _norm_unit(u: str) -> str:
    return _UNIT_MAP.get(u.lower(), u.lower())


# ─────────────────────────────────────────────────────────────────
#  TOKEN STREAM UTILITIES
# ─────────────────────────────────────────────────────────────────

def _build_keyword_map():
    """Map lowercase keyword strings to their SPLLexer token types."""
    kmap = {}
    # Iterate all symbolic names in the lexer
    for name, val in vars(SPLLexer).items():
        if isinstance(val, int) and val > 0 and not name.startswith('_'):
            kmap[name.lower()] = val
    return kmap

_KEYWORD_NAMES: dict = _build_keyword_map()


def _split_arithmetic_wildcards(tokens: CommonTokenStream) -> CommonTokenStream:
    """
    Post-process the token stream to split WILDCARD_TERM tokens that have
    BOTH a non-empty prefix AND non-empty suffix (e.g. "total*100", "count*avg_rt").
    These are arithmetic multiplication expressions in eval context, not search globs.
    Wildcards with trailing * only (e.g. "web*") or leading * (e.g. "*error") are kept.
    """
    tokens.fill()
    new_list = []
    for tok in tokens.tokens:
        if tok.type == SPLLexer.WILDCARD_TERM:
            text = tok.text
            # Find first wildcard char position
            wc_pos = next((i for i, c in enumerate(text) if c in '*?'), -1)
            if wc_pos > 0 and wc_pos < len(text) - 1:
                # Middle wildcard: split into prefix * suffix
                prefix = text[:wc_pos]
                suffix = text[wc_pos + 1:]
                # Determine prefix token type
                if prefix in _KEYWORD_NAMES:
                    pre_type = _KEYWORD_NAMES[prefix.lower()]
                else:
                    pre_type = SPLLexer.UNQUOTED_TERM
                # Determine suffix token type
                suf_type = SPLLexer.INT if _re.fullmatch(r'[0-9]+', suffix) else SPLLexer.UNQUOTED_TERM
                # Build three synthetic tokens at the same position
                def _make_tok(ttype, ttext, line, col):
                    t = CommonToken(source=(None, None), type=ttype, channel=0)
                    t.text = ttext
                    t.line = line
                    t.column = col
                    t.start = -1
                    t.stop = -1
                    return t
                new_list.append(_make_tok(pre_type,       prefix, tok.line, tok.column))
                new_list.append(_make_tok(SPLLexer.STAR,  '*',    tok.line, tok.column + wc_pos))
                new_list.append(_make_tok(suf_type,       suffix, tok.line, tok.column + wc_pos + 1))
                continue
        new_list.append(tok)
    src = ListTokenSource(new_list)
    return CommonTokenStream(src)


# ─────────────────────────────────────────────────────────────────
#  AST BUILDER  (ANTLR4 parse-tree → typed AST)
# ─────────────────────────────────────────────────────────────────

class _ASTBuilder:
    """Walks the ANTLR4 concrete syntax tree and emits AST nodes."""

    # ── helpers ────────────────────────────────────────────────

    def _text(self, ctx) -> str:
        return ctx.getText()

    def _unescape(self, s: str) -> str:
        """Remove surrounding quotes and unescape escape sequences."""
        if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
            s = s[1:-1]
        return s.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")

    def _field_name(self, ctx) -> str:
        """Extract field name text, stripping quotes if quoted."""
        txt = self._text(ctx)
        if txt and txt[0] in ('"', "'"):
            return self._unescape(txt)
        return txt

    def _bool_val(self, ctx) -> bool:
        return self._text(ctx).lower() in ("true", "t", "1")

    def _int_opt(self, ctx, attr: str) -> Optional[int]:
        child = getattr(ctx, attr, lambda: None)()
        return int(child.getText()) if child else None

    # ── top level ──────────────────────────────────────────────

    def build_pipeline(self, ctx) -> Pipeline:
        commands = [self._build_command(c) for c in ctx.command()]
        return Pipeline(commands=commands)

    def _build_command(self, ctx):
        child = ctx.getChild(0)
        name  = type(child).__name__

        dispatch = {
            "SearchCmdContext":       self._search,
            "StatsCmdContext":        self._stats,
            "EvalCmdContext":         self._eval,
            "RexCmdContext":          self._rex,
            "JoinCmdContext":         self._join,
            "TimechartCmdContext":    self._timechart,
            "ChartCmdContext":        self._chart,
            "TstatsCmdContext":       self._tstats,
            "TableCmdContext":        self._table,
            "FieldsCmdContext":       self._fields,
            "WhereCmdContext":        self._where,
            "DedupCmdContext":        self._dedup,
            "SortCmdContext":         self._sort,
            "HeadCmdContext":         self._head,
            "TailCmdContext":         self._tail,
            "RenameCmdContext":       self._rename,
            "LookupCmdContext":       self._lookup,
            "InputlookupCmdContext":  self._inputlookup,
            "OutputlookupCmdContext": self._outputlookup,
            "TransactionCmdContext":  self._transaction,
            "BucketCmdContext":       self._bucket,
            "StreamstatsCmdContext":  self._streamstats,
            "EventstatsCmdContext":   self._eventstats,
            "AppendCmdContext":       self._append,
            "AppendColsCmdContext":   self._appendcols,
            "UnionCmdContext":        self._union,
            "TopCmdContext":          self._top,
            "RareCmdContext":         self._rare,
            "FillnullCmdContext":     self._fillnull,
            "MakeresultsCmdContext":  self._makeresults,
            "ExtractCmdContext":      self._extract,
            "KvformCmdContext":       self._kvform,
            "MultikvCmdContext":      self._multikv,
            "GpuHintCmdContext":      self._gpuhint,
            "DeltaCmdContext":        self._delta,
        }
        builder = dispatch.get(name)
        if builder is None:
            raise SPLParseError(f"Unhandled command context: {name}")
        return builder(child)

    # ── search ─────────────────────────────────────────────────

    def _search(self, ctx) -> SearchNode:
        if ctx.searchExpr():
            return SearchNode(expr=self._search_expr(ctx.searchExpr()))
        return SearchNode(expr=SearchAnd(terms=[]))  # bare "search" with no terms

    def _search_expr(self, ctx):
        return self._search_or(ctx.searchOrExpr())

    def _search_or(self, ctx):
        parts = [self._search_and(c) for c in ctx.searchAndExpr()]
        return parts[0] if len(parts) == 1 else SearchOr(terms=parts)

    def _search_and(self, ctx):
        parts = [self._search_not(c) for c in ctx.searchNotExpr()]
        return parts[0] if len(parts) == 1 else SearchAnd(terms=parts)

    def _search_not(self, ctx):
        if ctx.NOT():
            return SearchNot(term=self._search_not(ctx.searchNotExpr()))
        if ctx.LPAREN():
            return self._search_or(ctx.searchOrExpr())
        return self._search_atom(ctx.searchAtom())

    def _search_atom(self, ctx):
        if ctx.timeModifier():
            return self._time_modifier(ctx.timeModifier())
        if ctx.fieldComparison():
            return self._field_comparison(ctx.fieldComparison())
        if ctx.subsearch():
            return self._subsearch(ctx.subsearch())
        return Term(value=self._text(ctx.term()))

    def _time_modifier(self, ctx) -> TimeModifier:
        mod = ctx.getChild(0).getText().lower()
        return TimeModifier(modifier=mod, value=self._text(ctx.timeStr()))

    def _field_comparison(self, ctx) -> FieldComparison:
        field = self._field_name(ctx.fieldName())
        # IN / NOT IN form
        if ctx.fieldValList():
            vals = [self._text(fv) for fv in ctx.fieldValList().fieldVal()]
            # strip quotes
            vals = [self._unescape(v) if v and v[0] in ('"', "'") else v for v in vals]
            # determine operator
            op = "NOT IN" if ctx.NOT() else "IN"
            return FieldComparison(field=field, op=op, value=vals)
        op    = self._text(ctx.compOp())
        val   = self._text(ctx.fieldVal())
        # strip quotes from string values
        if val and val[0] in ('"', "'"):
            val = self._unescape(val)
        return FieldComparison(field=field, op=op, value=val)

    # ── stats ──────────────────────────────────────────────────

    def _stats_by_list(self, ctx) -> List[str]:
        """Extract field names from statsByList (supports computed by-fields like name=expr)."""
        result = []
        for sf in ctx.statsByField():
            # Each statsByField is either fieldName EQ expr or just fieldName
            result.append(self._field_name(sf.fieldName()))
        return result

    def _stats(self, ctx) -> StatsNode:
        aggs = self._agg_list(ctx.aggList())
        by   = self._stats_by_list(ctx.statsByList()) if ctx.statsByList() else []
        opts: dict = {}
        for o in ctx.statsOpt():
            k, v = self._stats_opt(o)
            opts[k] = v
        return StatsNode(aggs=aggs, by=by, options=opts)

    def _agg_list(self, ctx) -> List[AggCall]:
        return [self._agg_call(c) for c in ctx.aggCall()]

    def _agg_call(self, ctx) -> AggCall:
        func  = self._text(ctx.aggFunc()).lower()
        arg   = self._agg_arg(ctx.aggArg()) if ctx.aggArg() else None
        alias = self._field_name(ctx.fieldName()) if ctx.fieldName() else None
        return AggCall(func=func, arg=arg, alias=alias)

    def _agg_arg(self, ctx) -> Any:
        if ctx.STAR():
            return "*"
        exprs = ctx.expr()
        if ctx.EVAL():
            # EVAL LPAREN expr RPAREN  → exprs is a list with one element
            e = exprs[0] if isinstance(exprs, list) else exprs
            return EvalArg(expr=self._expr(e))
        # plain expr alternative
        if exprs:
            e = exprs[0] if isinstance(exprs, list) else exprs
            # If the expr is a simple fieldName (single atom → fieldName), return string
            try:
                or_e  = e.orExpr()
                and_e = or_e.andExpr(0)
                not_e = and_e.notExpr(0)
                comp_e = not_e.compExpr()
                add_e = comp_e.addExpr(0)
                if add_e and len(add_e.mulExpr()) == 1:
                    mul_e = add_e.mulExpr(0)
                    if len(mul_e.unaryExpr()) == 1:
                        un_e = mul_e.unaryExpr(0)
                        if un_e.atom() and un_e.atom().fieldName():
                            return self._field_name(un_e.atom().fieldName())
            except (AttributeError, TypeError, IndexError):
                pass
            return self._expr(e)
        return self._text(ctx)

    def _stats_opt(self, ctx):
        txt = ctx.getChild(0).getText().lower()
        val_ctx = ctx.getChild(2) if ctx.getChildCount() >= 3 else None
        val = self._text(val_ctx) if val_ctx else None
        if val and val.lower() in ("true", "false"):
            val = val.lower() == "true"
        elif val and val.isdigit():
            val = int(val)
        return txt, val

    def _eventstats(self, ctx) -> EventstatsNode:
        aggs = self._agg_list(ctx.aggList())
        by   = self._stats_by_list(ctx.statsByList()) if ctx.statsByList() else []
        allnum = False
        if ctx.ALLNUM():
            allnum = self._bool_val(ctx.boolLiteral())
        return EventstatsNode(aggs=aggs, by=by, allnum=allnum)

    def _streamstats(self, ctx) -> StreamstatsNode:
        aggs: List[AggCall] = []
        opts: dict = {}
        for o in ctx.streamstatsOpt():
            k = o.getChild(0).getText().lower()
            v_ctx = o.getChild(2)
            if v_ctx:
                v = self._text(v_ctx)
                if v.lower() in ("true", "false"):
                    v = v.lower() == "true"
                elif v.isdigit():
                    v = int(v)
            else:
                v = None
            opts[k] = v
        for item in ctx.streamstatsAggList().streamstatsAggItem():
            # optional per-item window
            if item.WINDOW():
                opts.setdefault("window", int(item.INT().getText()))
            aggs.append(self._agg_call(item.aggCall()))
        by = self._stats_by_list(ctx.statsByList()) if ctx.statsByList() else []
        return StreamstatsNode(aggs=aggs, by=by, options=opts)

    # ── eval ───────────────────────────────────────────────────

    def _eval(self, ctx) -> EvalNode:
        assigns = [self._eval_assign(a) for a in ctx.evalAssignList().evalAssign()]
        return EvalNode(assignments=assigns)

    def _eval_assign(self, ctx) -> EvalAssign:
        field = self._field_name(ctx.fieldName())
        expr  = self._expr(ctx.expr())
        return EvalAssign(field=field, expr=expr)

    # ── rex ────────────────────────────────────────────────────

    def _rex(self, ctx) -> RexNode:
        pattern = self._unescape(ctx.STRING_LITERAL().getText())
        field   = None
        mode    = None
        max_m   = 1
        offset  = None
        for o in ctx.rexOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            if k == "field":
                field = self._unescape(v) if v else None
            elif k == "mode":
                mode = self._unescape(v) if v else None
            elif k == "max_match":
                max_m = int(v) if v else 1
            elif k == "offset_field":
                offset = self._unescape(v) if v else None
        return RexNode(pattern=pattern, field=field, mode=mode,
                       max_match=max_m, offset_field=offset)

    # ── join ───────────────────────────────────────────────────

    def _join(self, ctx) -> JoinNode:
        jtype  = "inner"
        fields = [self._field_name(fn) for fn in ctx.fieldName()]
        opts: dict = {}
        for o in ctx.joinOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            if k == "type":
                jtype = (v or "inner").lower()
            elif v and v.lower() in ("true", "false"):
                opts[k] = v.lower() == "true"
            elif v and v.isdigit():
                opts[k] = int(v)
            else:
                opts[k] = v
        sub = self._subsearch(ctx.subsearch())
        return JoinNode(join_type=jtype, fields=fields, subsearch=sub, options=opts)

    # ── timechart ──────────────────────────────────────────────

    def _timechart(self, ctx) -> TimechartNode:
        aggs = self._agg_list(ctx.aggList()) if ctx.aggList() else []
        by   = self._field_name(ctx.fieldName()) if ctx.fieldName() else None
        span = None
        opts: dict = {}
        for o in ctx.timechartOpt():
            k = o.getChild(0).getText().lower()
            if k == "span":
                span = self._span_val(o.spanVal())
            else:
                v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
                opts[k] = v
        return TimechartNode(aggs=aggs, by=by, span=span, options=opts)

    # ── chart ──────────────────────────────────────────────────

    def _chart(self, ctx) -> ChartNode:
        aggs = self._agg_list(ctx.aggList())
        over = self._field_name(ctx.fieldName())
        by   = self._field_list(ctx.fieldList()) if ctx.fieldList() else []
        opts: dict = {}
        for o in ctx.chartOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            opts[k] = v
        return ChartNode(aggs=aggs, over=over, by=by, options=opts)

    # ── tstats ─────────────────────────────────────────────────

    def _tstats(self, ctx) -> TstatsNode:
        aggs = self._agg_list(ctx.aggList()) if ctx.aggList() else []
        dm   = None
        if ctx.DATAMODEL():
            dm_parts = [self._field_name(f) for f in ctx.fieldName()]
            dm = ".".join(dm_parts)
        # tstatsCmd has two (WHERE expr)? clauses — ctx.expr() returns a list
        expr_list = ctx.expr()
        if not isinstance(expr_list, list):
            expr_list = [expr_list] if expr_list else []
        where = self._expr(expr_list[0]) if expr_list else None
        by    = self._field_list(ctx.fieldList()) if ctx.fieldList() else []
        span  = self._span_val(ctx.spanVal()) if ctx.spanVal() else None
        opts: dict = {}
        for o in ctx.tstatsOpt():
            k = o.getChild(0).getText().lower()
            v_ctx = o.getChild(2)
            v = self._text(v_ctx).lower() if v_ctx else None
            opts[k] = v == "true" if v in ("true", "false") else v
        return TstatsNode(aggs=aggs, datamodel=dm, where=where,
                          by=by, span=span, options=opts)

    # ── table / fields / where / dedup / sort / head / tail ───

    def _table(self, ctx) -> TableNode:
        fields = []
        for tf in ctx.tableFieldList().tableField():
            if tf.functionCall():
                fields.append(self._text(tf.functionCall()))
            else:
                fields.append(self._field_name(tf.fieldName()))
        return TableNode(fields=fields)

    def _fields(self, ctx) -> FieldsNode:
        mode = "-" if ctx.MINUS() else "+"
        return FieldsNode(mode=mode, fields=self._field_list(ctx.fieldList()))

    def _where(self, ctx) -> WhereNode:
        return WhereNode(expr=self._expr(ctx.expr()))

    def _dedup(self, ctx) -> DedupNode:
        max_e = int(ctx.INT().getText()) if ctx.INT() else None
        fields = self._field_list(ctx.fieldList())
        ke = kp = con = False
        sort = None
        for i in range(ctx.getChildCount()):
            child = ctx.getChild(i)
            if hasattr(child, "getText"):
                t = child.getText().lower()
                if t == "keepevents" and i + 2 < ctx.getChildCount():
                    ke = self._text(ctx.getChild(i + 2)).lower() == "true"
                elif t == "keepempty" and i + 2 < ctx.getChildCount():
                    kp = self._text(ctx.getChild(i + 2)).lower() == "true"
                elif t == "consecutive" and i + 2 < ctx.getChildCount():
                    con = self._text(ctx.getChild(i + 2)).lower() == "true"
        if ctx.sortByClause():
            sort = self._sort_spec(ctx.sortByClause().sortFieldList())
        return DedupNode(max_events=max_e, fields=fields,
                         keepevents=ke, keepempty=kp, consecutive=con, sortby=sort)

    def _sort(self, ctx) -> SortNode:
        limit = None
        if ctx.LIMIT():
            # LIMIT EQ INT
            for i in range(ctx.getChildCount()):
                if hasattr(ctx.getChild(i), "getText") and \
                        ctx.getChild(i).getText().lower() == "limit":
                    limit = int(ctx.getChild(i + 2).getText())
                    break
        elif ctx.INT():
            limit = int(ctx.INT().getText())
        fields = self._sort_fields(ctx.sortFieldList())
        return SortNode(fields=fields, limit=limit)

    def _sort_fields(self, ctx) -> List[SortField]:
        return [self._sort_field(f) for f in ctx.sortField()]

    def _sort_spec(self, ctx) -> SortSpec:
        return SortSpec(fields=self._sort_fields(ctx))

    def _sort_field(self, ctx) -> SortField:
        direction = "+"
        type_hint = None
        field_ctx = None
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText()
            if t == "-":
                direction = "-"
            elif t == "+":
                direction = "+"
            elif t.lower() in ("auto", "ip", "num", "str"):
                type_hint = t.lower()
            elif hasattr(ch, "fieldName"):
                field_ctx = ch.fieldName()
            elif type(ch).__name__ == "FieldNameContext":
                field_ctx = ch
        # functionCall as sort key (e.g. sort -avg(response_time))
        if ctx.functionCall():
            field = self._text(ctx.functionCall())
            return SortField(field=field, direction=direction, type_hint=type_hint)
        if field_ctx is None:
            field_ctx = ctx.fieldName()
        field = self._field_name(field_ctx) if field_ctx else self._text(ctx)
        return SortField(field=field, direction=direction, type_hint=type_hint)

    def _head(self, ctx) -> HeadNode:
        count: Any = None
        ints = ctx.INT()
        if ints:
            first = ints[0] if isinstance(ints, list) else ints
            count = int(first.getText())
        elif ctx.expr():
            count = self._expr(ctx.expr())
        return HeadNode(count=count)

    def _tail(self, ctx) -> TailNode:
        ints = ctx.INT()
        if ints:
            first = ints[0] if isinstance(ints, list) else ints
            n = int(first.getText())
        else:
            n = 10
        return TailNode(count=n)

    # ── rename ─────────────────────────────────────────────────

    def _rename(self, ctx) -> RenameNode:
        clauses = [self._rename_clause(c) for c in ctx.renameClause()]
        return RenameNode(clauses=clauses)

    def _rename_clause(self, ctx) -> RenameClause:
        names = ctx.fieldName()
        if ctx.functionCall():
            # e.g. rename avg(response_time) as avg_rt
            src = self._text(ctx.functionCall())
            dst = self._field_name(names[0])
        else:
            src = self._field_name(names[0])
            dst = self._field_name(names[1])
        return RenameClause(src=src, dst=dst)

    # ── lookup ─────────────────────────────────────────────────

    def _lookup(self, ctx) -> LookupNode:
        name = self._text(ctx.lookupName())
        input_fields: List[LookupField] = []
        output_mode  = None
        output_fields: List[LookupField] = []

        lookup_field_ctxs = ctx.lookupFields()
        if lookup_field_ctxs:
            # first lookupFields = input
            input_fields = self._lookup_fields(lookup_field_ctxs[0])
            if len(lookup_field_ctxs) > 1:
                output_fields = self._lookup_fields(lookup_field_ctxs[1])
        if ctx.OUTPUT():
            output_mode = "OUTPUT"
        elif ctx.OUTPUTNEW():
            output_mode = "OUTPUTNEW"
        return LookupNode(name=name, input_fields=input_fields,
                          output_mode=output_mode, output_fields=output_fields)

    def _lookup_fields(self, ctx) -> List[LookupField]:
        return [self._lookup_field(f) for f in ctx.lookupField()]

    def _lookup_field(self, ctx) -> LookupField:
        names = ctx.fieldName()
        alias = self._field_name(names[1]) if len(names) > 1 else None
        return LookupField(src=self._field_name(names[0]), alias=alias)

    def _inputlookup(self, ctx) -> InputlookupNode:
        name    = self._text(ctx.lookupName())
        where   = self._expr(ctx.expr()) if ctx.expr() else None
        append  = False
        start   = 0
        max_val = None
        # walk options
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText().lower() if hasattr(ch, "getText") else ""
            if t == "append" and i + 2 < ctx.getChildCount():
                append = ctx.getChild(i + 2).getText().lower() == "true"
            elif t == "start" and i + 2 < ctx.getChildCount():
                start = int(ctx.getChild(i + 2).getText())
            elif t == "max" and i + 2 < ctx.getChildCount():
                max_val = int(ctx.getChild(i + 2).getText())
        return InputlookupNode(name=name, where=where,
                               append=append, start=start, max=max_val)

    def _outputlookup(self, ctx) -> OutputlookupNode:
        name = self._text(ctx.lookupName())
        return OutputlookupNode(name=name)

    # ── transaction ────────────────────────────────────────────

    def _transaction(self, ctx) -> TransactionNode:
        # fieldList was replaced by fieldName* (space-separated, no commas)
        fields = [self._field_name(fn) for fn in ctx.fieldName()]
        maxspan  = None
        maxpause = None
        maxevents = None
        startswith = None
        endswith   = None
        keeporphans = False
        mvlist      = False
        for o in ctx.transactionOpt():
            k = o.getChild(0).getText().lower()
            if k == "maxspan":
                maxspan = self._span_val(o.spanVal())
            elif k == "maxpause":
                maxpause = self._span_val(o.spanVal())
            elif k == "maxevents":
                maxevents = int(o.getChild(2).getText())
            elif k == "keeporphans":
                keeporphans = o.getChild(2).getText().lower() == "true"
            elif k == "mvlist":
                mvlist = o.getChild(2).getText().lower() == "true"
            elif k == "startswith":
                startswith = self._text(o.getChild(2))
            elif k == "endswith":
                endswith = self._text(o.getChild(2))
        return TransactionNode(fields=fields, maxspan=maxspan, maxpause=maxpause,
                               maxevents=maxevents, startswith=startswith,
                               endswith=endswith, keeporphans=keeporphans,
                               mvlist=mvlist)

    # ── bucket ─────────────────────────────────────────────────

    def _bucket(self, ctx) -> BucketNode:
        fn = ctx.fieldName()
        field = self._field_name(fn[0])
        alias = self._field_name(fn[1]) if len(fn) > 1 else None
        span  = None
        bins  = None
        opts: dict = {}
        for o in ctx.bucketOpt():
            k = o.getChild(0).getText().lower()
            if k == "span":
                span = self._span_val(o.spanVal())
            elif k == "bins":
                bins = int(o.getChild(2).getText())
            else:
                opts[k] = self._text(o.getChild(2))
        return BucketNode(field=field, alias=alias, span=span, bins=bins, options=opts)

    # ── append / appendcols / union ───────────────────────────

    def _append(self, ctx) -> AppendNode:
        return AppendNode(subsearch=self._subsearch(ctx.subsearch()))

    def _appendcols(self, ctx) -> AppendColsNode:
        return AppendColsNode(subsearch=self._subsearch(ctx.subsearch()))

    def _union(self, ctx) -> UnionNode:
        subs = [self._subsearch(s) for s in ctx.subsearch()]
        max_val = None
        if ctx.MAX():
            for i in range(ctx.getChildCount()):
                if ctx.getChild(i).getText().lower() == "max":
                    max_val = int(ctx.getChild(i + 2).getText())
                    break
        return UnionNode(subsearches=subs, max=max_val)

    # ── top / rare ─────────────────────────────────────────────

    def _top(self, ctx) -> TopNode:
        fields = self._field_list(ctx.fieldList()[0])
        by     = self._field_list(ctx.fieldList()[1]) if len(ctx.fieldList()) > 1 else []
        # Limit: either inline INT (top 5 host) or LIMIT=N option
        ints = ctx.INT()
        limit = int((ints[0] if isinstance(ints, list) else ints).getText()) if ints else 10
        opts: dict = {}
        for o in ctx.topRareOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            if k == "limit" and v:
                limit = int(v)
            else:
                opts[k] = v
        return TopNode(fields=fields, by=by, limit=limit, options=opts)

    def _rare(self, ctx) -> RareNode:
        fields = self._field_list(ctx.fieldList()[0])
        by     = self._field_list(ctx.fieldList()[1]) if len(ctx.fieldList()) > 1 else []
        ints = ctx.INT()
        limit = int((ints[0] if isinstance(ints, list) else ints).getText()) if ints else 10
        opts: dict = {}
        for o in ctx.topRareOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            if k == "limit" and v:
                limit = int(v)
            else:
                opts[k] = v
        return RareNode(fields=fields, by=by, limit=limit, options=opts)

    # ── misc commands ──────────────────────────────────────────

    def _fillnull(self, ctx) -> FillnullNode:
        value  = "0"
        fields: List[str] = []
        if ctx.STRING_LITERAL():
            value = self._unescape(ctx.STRING_LITERAL().getText())
        if ctx.fieldList():
            fields = self._field_list(ctx.fieldList())
        return FillnullNode(value=value, fields=fields)

    def _makeresults(self, ctx) -> MakeresultsNode:
        count = 1
        annotate = False
        server   = None
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText().lower() if hasattr(ch, "getText") else ""
            if t == "count" and i + 2 < ctx.getChildCount():
                count = int(ctx.getChild(i + 2).getText())
            elif t == "annotate" and i + 2 < ctx.getChildCount():
                annotate = ctx.getChild(i + 2).getText().lower() == "true"
            elif t == "splunk_server" and i + 2 < ctx.getChildCount():
                server = self._unescape(ctx.getChild(i + 2).getText())
        return MakeresultsNode(count=count, annotate=annotate, splunk_server=server)

    def _extract(self, ctx) -> ExtractNode:
        opts: dict = {}
        for o in ctx.extractOpt():
            k = o.getChild(0).getText().lower()
            v = self._text(o.getChild(2)) if o.getChildCount() >= 3 else None
            opts[k] = v
        return ExtractNode(options=opts)

    def _kvform(self, ctx) -> KvformNode:
        field  = None
        output = None
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText().lower() if hasattr(ch, "getText") else ""
            if t == "field" and i + 2 < ctx.getChildCount():
                field = self._field_name(ctx.getChild(i + 2))
            elif t == "output" and i + 2 < ctx.getChildCount():
                output = self._field_name(ctx.getChild(i + 2))
        return KvformNode(field=field, output=output)

    def _multikv(self, ctx) -> MultikvNode:
        fields: List[str] = []
        rmorig = False
        if ctx.fieldList():
            fields = self._field_list(ctx.fieldList())
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText().lower() if hasattr(ch, "getText") else ""
            if t == "rmorig" and i + 2 < ctx.getChildCount():
                rmorig = ctx.getChild(i + 2).getText().lower() == "true"
        return MultikvNode(fields=fields, rmorig=rmorig)

    def _gpuhint(self, ctx) -> GpuHintNode:
        memory = None
        stream = False
        for i in range(ctx.getChildCount()):
            ch = ctx.getChild(i)
            t  = ch.getText().lower() if hasattr(ch, "getText") else ""
            if t == "memory" and i + 2 < ctx.getChildCount():
                memory = int(ctx.getChild(i + 2).getText())
            elif t == "stream" and i + 2 < ctx.getChildCount():
                stream = ctx.getChild(i + 2).getText().lower() == "true"
        return GpuHintNode(memory=memory, stream=stream)

    def _delta(self, ctx) -> DeltaNode:
        names = ctx.fieldName()
        field = self._field_name(names[0])
        alias = self._field_name(names[1]) if len(names) > 1 else None
        return DeltaNode(field=field, alias=alias)

    # ── subsearch ──────────────────────────────────────────────

    def _subsearch(self, ctx) -> Subsearch:
        return Subsearch(pipeline=self.build_pipeline(ctx.pipeline()))

    # ── expressions ────────────────────────────────────────────

    def _expr(self, ctx):
        return self._or_expr(ctx.orExpr())

    def _or_expr(self, ctx):
        parts = [self._and_expr(c) for c in ctx.andExpr()]
        return parts[0] if len(parts) == 1 else OrExpr(terms=parts)

    def _and_expr(self, ctx):
        parts = [self._not_expr(c) for c in ctx.notExpr()]
        return parts[0] if len(parts) == 1 else AndExpr(terms=parts)

    def _not_expr(self, ctx):
        if ctx.NOT():
            return NotExpr(expr=self._not_expr(ctx.notExpr()))
        return self._comp_expr(ctx.compExpr())

    def _comp_expr(self, ctx):
        left = self._add_expr(ctx.addExpr(0))
        if ctx.compOp():
            op    = self._text(ctx.compOp())
            right = self._add_expr(ctx.addExpr(1))
            return CompareExpr(left=left, op=op, right=right)
        if ctx.LIKE():
            pat = self._unescape(ctx.STRING_LITERAL().getText())
            return LikeExpr(expr=left, pattern=pat)
        if ctx.IN():
            vals = self._value_list(ctx.valueList())
            negated = ctx.NOT() is not None
            return InExpr(expr=left, values=vals, negated=negated)
        return left

    def _value_list(self, ctx):
        return [self._literal(lit) for lit in ctx.literal()]

    def _add_expr(self, ctx):
        result = self._mul_expr(ctx.mulExpr(0))
        for i in range(1, len(ctx.mulExpr())):
            op  = ctx.getChild(2 * i - 1).getText()
            rhs = self._mul_expr(ctx.mulExpr(i))
            result = BinaryExpr(left=result, op=op, right=rhs)
        return result

    def _mul_expr(self, ctx):
        result = self._unary_expr(ctx.unaryExpr(0))
        for i in range(1, len(ctx.unaryExpr())):
            op  = ctx.getChild(2 * i - 1).getText()
            rhs = self._unary_expr(ctx.unaryExpr(i))
            result = BinaryExpr(left=result, op=op, right=rhs)
        return result

    def _unary_expr(self, ctx):
        if ctx.MINUS():
            return UnaryExpr(op="-", expr=self._unary_expr(ctx.unaryExpr()))
        if ctx.PLUS():
            return UnaryExpr(op="+", expr=self._unary_expr(ctx.unaryExpr()))
        return self._atom(ctx.atom())

    def _atom(self, ctx):
        if ctx.LPAREN():
            return self._expr(ctx.expr())
        if ctx.functionCall():
            return self._function_call(ctx.functionCall())
        if ctx.macroCall():
            return self._macro_call(ctx.macroCall())
        if ctx.subsearch():
            return self._subsearch(ctx.subsearch())
        if ctx.literal():
            return self._literal(ctx.literal())
        if ctx.fieldName():
            return FieldRef(name=self._field_name(ctx.fieldName()))
        return FieldRef(name=self._text(ctx))

    def _function_call(self, ctx) -> FunctionCall:
        name = self._text(ctx.funcName()).lower()
        args = []
        if ctx.funcArgList():
            args = [self._expr(e) for e in ctx.funcArgList().expr()]
        return FunctionCall(name=name, args=args)

    def _macro_call(self, ctx) -> MacroCall:
        name = self._text(ctx.fieldName())
        args = []
        if ctx.macroArgs():
            for a in ctx.macroArgs().macroArg():
                txt = self._text(a)
                if txt.startswith(('"', "'")):
                    args.append(self._unescape(txt))
                elif txt.replace(".", "").isdigit():
                    args.append(float(txt) if "." in txt else int(txt))
                else:
                    args.append(txt)
        return MacroCall(name=name, args=args)

    def _literal(self, ctx):
        if ctx.STRING_LITERAL():
            return StringLiteral(value=self._unescape(ctx.STRING_LITERAL().getText()))
        if ctx.number():
            return self._number(ctx.number())
        if ctx.boolLiteral():
            return BoolLiteral(value=self._bool_val(ctx.boolLiteral()))
        if ctx.NULL_KW():
            return NullLiteral()
        return StringLiteral(value=self._text(ctx))

    def _number(self, ctx) -> NumberLiteral:
        txt = self._text(ctx)
        if "." in txt:
            return NumberLiteral(value=float(txt))
        if txt.lower().startswith("0x"):
            return NumberLiteral(value=int(txt, 16))
        return NumberLiteral(value=int(txt))

    # ── shared helpers ─────────────────────────────────────────

    def _field_list(self, ctx) -> List[str]:
        return [self._field_name(f) for f in ctx.fieldName()]

    def _span_val(self, ctx) -> SpanValue:
        import re as _re
        if ctx.RELATIVE_TIME_LITERAL():
            # e.g. "1h", "30m", "-1d@d"  — split into numeric part + unit
            txt = ctx.RELATIVE_TIME_LITERAL().getText().lstrip("+-")
            txt = txt.split("@")[0]  # strip snap portion
            m = _re.match(r'^(\d+(?:\.\d*)?)(\w+)$', txt)
            if m:
                raw_n = m.group(1)
                n = float(raw_n) if "." in raw_n else int(raw_n)
                return SpanValue(value=n, unit=_norm_unit(m.group(2)))
            # pure unit like "-d" → value 1
            unit_part = _re.sub(r'^\d+', '', txt)
            return SpanValue(value=1, unit=_norm_unit(unit_part or txt))
        if ctx.UNQUOTED_TERM():
            # e.g. "1mb", "1kb", "1gb" — parse as number+unit from raw text
            raw = ctx.UNQUOTED_TERM().getText()
            m = _re.match(r'^(\d+(?:\.\d*)?)(\w+)$', raw)
            if m:
                raw_n = m.group(1)
                n = float(raw_n) if "." in raw_n else int(raw_n)
                return SpanValue(value=n, unit=m.group(2).lower())
            return SpanValue(value=0, unit=raw)
        n    = self._number(ctx.number()).value
        if ctx.timeUnit():
            unit = _norm_unit(self._text(ctx.timeUnit()))
        else:
            unit = ""   # bare number span (e.g. span=1000000 for byte buckets)
        return SpanValue(value=n, unit=unit)


# ─────────────────────────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────────────────────────

class SPLParser:
    """Parse SPL queries into a typed AST."""

    @staticmethod
    def parse(spl: str, strict: bool = True) -> Pipeline:
        """
        Parse an SPL query string and return a Pipeline AST.

        Args:
            spl:    The SPL query string (may contain newlines).
            strict: If True (default), raise SPLParseError on any
                    syntax error. If False, ANTLR4's default error
                    recovery is used (partial trees).

        Returns:
            Pipeline node.

        Raises:
            SPLParseError: on syntax error when strict=True.
        """
        stream = InputStream(spl)
        lexer  = SPLLexer(stream)
        if strict:
            lexer.removeErrorListeners()
            lexer.addErrorListener(_RaisingErrorListener())
        raw_tokens = CommonTokenStream(lexer)
        tokens = _split_arithmetic_wildcards(raw_tokens)
        parser = _ANTLRParser(tokens)

        if strict:
            parser.removeErrorListeners()
            parser.addErrorListener(_RaisingErrorListener())

        tree = parser.spl()
        return _ASTBuilder().build_pipeline(tree.pipeline())

    @staticmethod
    def parse_expr(expr: str, strict: bool = True):
        """Parse a standalone eval/where expression."""
        stream = InputStream(expr)
        lexer  = SPLLexer(stream)
        if strict:
            lexer.removeErrorListeners()
            lexer.addErrorListener(_RaisingErrorListener())
        raw_tokens = CommonTokenStream(lexer)
        tokens = _split_arithmetic_wildcards(raw_tokens)
        parser = _ANTLRParser(tokens)

        if strict:
            parser.removeErrorListeners()
            parser.addErrorListener(_RaisingErrorListener())

        tree = parser.expr()
        return _ASTBuilder()._expr(tree)
