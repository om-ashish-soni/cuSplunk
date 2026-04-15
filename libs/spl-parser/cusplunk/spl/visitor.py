"""
Base visitor class for walking the SPL AST.

Usage:
    class MyVisitor(Visitor):
        def visit_StatsNode(self, node):
            ...
            self.visit_children(node)

All visit_* methods default to generic_visit which traverses children.
"""
from __future__ import annotations

from typing import Any
from dataclasses import fields as dataclass_fields


class Visitor:
    """Base visitor. Override visit_ClassName for specific node types."""

    def visit(self, node: Any) -> Any:
        if node is None:
            return None
        if isinstance(node, list):
            return [self.visit(item) for item in node]
        if hasattr(node, "accept"):
            return node.accept(self)
        return node

    def generic_visit(self, node: Any) -> Any:
        """Default: visit all child nodes."""
        self.visit_children(node)
        return node

    def visit_children(self, node: Any) -> None:
        if not hasattr(node, "__dataclass_fields__"):
            return
        for f in dataclass_fields(node):
            value = getattr(node, f.name)
            if isinstance(value, list):
                for item in value:
                    self.visit(item)
            elif hasattr(value, "accept"):
                self.visit(value)

    # ── Explicit visit methods (all no-ops by default, override as needed) ──

    def visit_Pipeline(self, node): return self.generic_visit(node)
    def visit_Subsearch(self, node): return self.generic_visit(node)
    def visit_MacroCall(self, node): return self.generic_visit(node)

    # Search
    def visit_SearchNode(self, node): return self.generic_visit(node)
    def visit_SearchOr(self, node): return self.generic_visit(node)
    def visit_SearchAnd(self, node): return self.generic_visit(node)
    def visit_SearchNot(self, node): return self.generic_visit(node)
    def visit_FieldComparison(self, node): return self.generic_visit(node)
    def visit_TimeModifier(self, node): return self.generic_visit(node)
    def visit_Term(self, node): return self.generic_visit(node)

    # Stats family
    def visit_StatsNode(self, node): return self.generic_visit(node)
    def visit_EventstatsNode(self, node): return self.generic_visit(node)
    def visit_StreamstatsNode(self, node): return self.generic_visit(node)
    def visit_AggCall(self, node): return self.generic_visit(node)
    def visit_EvalArg(self, node): return self.generic_visit(node)

    # Eval
    def visit_EvalNode(self, node): return self.generic_visit(node)
    def visit_EvalAssign(self, node): return self.generic_visit(node)

    # Rex
    def visit_RexNode(self, node): return self.generic_visit(node)

    # Join
    def visit_JoinNode(self, node): return self.generic_visit(node)

    # Timechart / Chart
    def visit_TimechartNode(self, node): return self.generic_visit(node)
    def visit_ChartNode(self, node): return self.generic_visit(node)

    # Tstats
    def visit_TstatsNode(self, node): return self.generic_visit(node)

    # Table / Fields / Where / Filter
    def visit_TableNode(self, node): return self.generic_visit(node)
    def visit_FieldsNode(self, node): return self.generic_visit(node)
    def visit_WhereNode(self, node): return self.generic_visit(node)
    def visit_DedupNode(self, node): return self.generic_visit(node)
    def visit_SortNode(self, node): return self.generic_visit(node)
    def visit_SortField(self, node): return self.generic_visit(node)
    def visit_SortSpec(self, node): return self.generic_visit(node)
    def visit_HeadNode(self, node): return self.generic_visit(node)
    def visit_TailNode(self, node): return self.generic_visit(node)

    # Rename
    def visit_RenameNode(self, node): return self.generic_visit(node)
    def visit_RenameClause(self, node): return self.generic_visit(node)

    # Lookup
    def visit_LookupNode(self, node): return self.generic_visit(node)
    def visit_LookupField(self, node): return self.generic_visit(node)
    def visit_InputlookupNode(self, node): return self.generic_visit(node)
    def visit_OutputlookupNode(self, node): return self.generic_visit(node)

    # Transaction
    def visit_TransactionNode(self, node): return self.generic_visit(node)

    # Bucket
    def visit_BucketNode(self, node): return self.generic_visit(node)

    # Set operations
    def visit_AppendNode(self, node): return self.generic_visit(node)
    def visit_AppendColsNode(self, node): return self.generic_visit(node)
    def visit_UnionNode(self, node): return self.generic_visit(node)

    # Top / Rare
    def visit_TopNode(self, node): return self.generic_visit(node)
    def visit_RareNode(self, node): return self.generic_visit(node)

    # Misc commands
    def visit_FillnullNode(self, node): return self.generic_visit(node)
    def visit_MakeresultsNode(self, node): return self.generic_visit(node)
    def visit_ExtractNode(self, node): return self.generic_visit(node)
    def visit_KvformNode(self, node): return self.generic_visit(node)
    def visit_MultikvNode(self, node): return self.generic_visit(node)
    def visit_GpuHintNode(self, node): return self.generic_visit(node)

    # Expressions
    def visit_OrExpr(self, node): return self.generic_visit(node)
    def visit_AndExpr(self, node): return self.generic_visit(node)
    def visit_NotExpr(self, node): return self.generic_visit(node)
    def visit_CompareExpr(self, node): return self.generic_visit(node)
    def visit_LikeExpr(self, node): return self.generic_visit(node)
    def visit_InExpr(self, node): return self.generic_visit(node)
    def visit_BinaryExpr(self, node): return self.generic_visit(node)
    def visit_UnaryExpr(self, node): return self.generic_visit(node)
    def visit_FunctionCall(self, node): return self.generic_visit(node)
    def visit_FieldRef(self, node): return self.generic_visit(node)
    def visit_StringLiteral(self, node): return self.generic_visit(node)
    def visit_NumberLiteral(self, node): return self.generic_visit(node)
    def visit_BoolLiteral(self, node): return self.generic_visit(node)
    def visit_NullLiteral(self, node): return self.generic_visit(node)
    def visit_SpanValue(self, node): return self.generic_visit(node)


class Transformer(Visitor):
    """Like Visitor but returns new nodes (bottom-up tree rewriting).

    Override visit_X to return a replacement node (or the same node).
    The base implementation recursively transforms children and returns
    the (possibly mutated) node.
    """

    def generic_visit(self, node: Any) -> Any:
        if not hasattr(node, "__dataclass_fields__"):
            return node
        updates = {}
        for f in dataclass_fields(node):
            value = getattr(node, f.name)
            if isinstance(value, list):
                new_list = [self.visit(item) for item in value]
                if new_list != value:
                    updates[f.name] = new_list
            elif hasattr(value, "accept"):
                new_val = self.visit(value)
                if new_val is not value:
                    updates[f.name] = new_val
        if updates:
            from dataclasses import replace
            return replace(node, **updates)
        return node
