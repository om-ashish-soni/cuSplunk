"""
sigma/evaluator.py — Evaluate CompiledRules against a DataFrame batch.

GPU path:  df is a cudf.DataFrame  → df[col].str.contains(pattern, regex=True)
CPU path:  df is a pandas.DataFrame → same API (used in unit tests, CI without GPU)

The DF_LIB shim at module load selects the right backend.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

# GPU / CPU shim — identical API surface
_CUDF_AVAILABLE = False
try:
    if os.environ.get("CUDF_PANDAS_FALLBACK_MODE") != "1":
        import cudf as _df_lib  # type: ignore
        _CUDF_AVAILABLE = True
    else:
        raise ImportError("fallback requested")
except ImportError:
    import pandas as _df_lib  # type: ignore

from cusplunk.sigma.compiler import CompiledRule, CompiledSelection, FieldPattern

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    rule_id: str
    rule_title: str
    level: str
    tags: list[str]
    matched_indices: list[int]    # row indices in the input DataFrame that matched


class SigmaEvaluator:
    """
    Batch-evaluate a list of CompiledRules against a DataFrame.

    Usage:
        evaluator = SigmaEvaluator()
        results = evaluator.evaluate(compiled_rules, df)
        # results: list[MatchResult]
    """

    def evaluate(
        self,
        rules: list[CompiledRule],
        df: "_df_lib.DataFrame",
    ) -> list[MatchResult]:
        """
        Evaluate all rules against df. Returns one MatchResult per rule that
        had at least one matching row.
        """
        if len(df) == 0:
            return []

        results: list[MatchResult] = []
        for rule in rules:
            try:
                match = self._evaluate_rule(rule, df)
                if match and match.matched_indices:
                    results.append(match)
            except Exception:
                logger.exception("Error evaluating rule %s ('%s')", rule.rule_id, rule.title)
        return results

    def _evaluate_rule(
        self,
        rule: CompiledRule,
        df: "_df_lib.DataFrame",
    ) -> MatchResult | None:
        # Step 1: evaluate each selection → boolean Series
        selection_masks: dict[str, "_df_lib.Series"] = {}
        for name, compiled_sel in rule.selections.items():
            selection_masks[name] = self._evaluate_selection(compiled_sel, df)

        # Step 2: evaluate keywords if present (always against _raw column)
        # Keywords are stored as a plain selection named "keywords" in the DF masks
        # (populated by the caller if rule.raw has keywords — handled via pipeline)

        # Step 3: apply condition_fn row-wise
        # Convert each selection mask to a dict of bool per row, apply condition
        # For performance: build a combined mask directly rather than row iteration
        combined_mask = self._apply_condition(rule, selection_masks, df)

        if combined_mask is None:
            return None

        # Step 4: collect matched row indices
        if _CUDF_AVAILABLE:
            matched = combined_mask[combined_mask].index.to_arrow().to_pylist()
        else:
            matched = list(combined_mask[combined_mask].index)

        return MatchResult(
            rule_id=rule.rule_id,
            rule_title=rule.title,
            level=rule.level,
            tags=rule.tags,
            matched_indices=matched,
        )

    def _evaluate_selection(
        self,
        sel: CompiledSelection,
        df: "_df_lib.DataFrame",
    ) -> "_df_lib.Series":
        """AND all field patterns in a selection. Returns a boolean Series."""
        mask = None
        for fp in sel.field_patterns:
            fp_mask = self._evaluate_field_pattern(fp, df)
            if mask is None:
                mask = fp_mask
            else:
                mask = mask & fp_mask

        if mask is None:
            # Empty selection — matches nothing
            return _df_lib.Series([False] * len(df))

        return mask

    def _evaluate_field_pattern(
        self,
        fp: FieldPattern,
        df: "_df_lib.DataFrame",
    ) -> "_df_lib.Series":
        col_name = fp.field_name

        # Keyword search → scan _raw column
        if col_name == "_keywords":
            col_name = "_raw"

        if col_name not in df.columns:
            # Column missing → no match (schema-on-read: field may not be extracted yet)
            return _df_lib.Series([False] * len(df))

        col = df[col_name].astype(str).fillna("")

        if fp.require_all:
            # All individual patterns must match (field|contains|all)
            # Split pattern on (?:...) boundaries and test each separately
            individual = self._split_alternation(fp.pattern)
            if not individual:
                return _df_lib.Series([False] * len(df))
            mask = col.str.contains(individual[0], regex=True, case=False, na=False)
            for pat in individual[1:]:
                mask = mask & col.str.contains(pat, regex=True, case=False, na=False)
            return mask
        else:
            if not fp.pattern:
                return _df_lib.Series([False] * len(df))
            return col.str.contains(fp.pattern, regex=True, case=False, na=False)

    def _apply_condition(
        self,
        rule: CompiledRule,
        selection_masks: dict[str, "_df_lib.Series"],
        df: "_df_lib.DataFrame",
    ) -> "_df_lib.Series | None":
        """
        Apply the condition function across all rows efficiently.

        Strategy: build a combined boolean Series by evaluating the condition
        over per-selection Series rather than row-by-row.

        For complex conditions, falls back to row iteration (correct, slower).
        """
        if not selection_masks:
            return None

        cond = rule.raw_condition.strip().lower()

        # Fast path: single selection reference
        sel_names = list(selection_masks.keys())
        if len(sel_names) == 1 and cond in (sel_names[0].lower(), "selection"):
            return selection_masks[sel_names[0]]

        # Fast path: "selection and not filter" (very common Sigma pattern)
        if len(sel_names) == 2:
            result = self._try_fast_two_selection(cond, selection_masks)
            if result is not None:
                return result

        # General path: row-by-row using condition_fn
        # Convert each Series to a list of bools for vectorised access
        bool_arrays: dict[str, list[bool]] = {}
        for name, mask in selection_masks.items():
            if _CUDF_AVAILABLE:
                bool_arrays[name] = mask.to_arrow().to_pylist()
            else:
                bool_arrays[name] = mask.tolist()

        n = len(df)
        result_list = []
        for i in range(n):
            row_map = {name: bool_arrays[name][i] for name in bool_arrays}
            try:
                result_list.append(rule.condition_fn(row_map))
            except Exception:
                result_list.append(False)

        return _df_lib.Series(result_list, index=df.index)

    def _try_fast_two_selection(
        self,
        cond: str,
        masks: dict[str, "_df_lib.Series"],
    ) -> "_df_lib.Series | None":
        """Optimised evaluation for 'A and not B' and 'A or B' patterns."""
        names = list(masks.keys())
        a_name, b_name = names[0], names[1]
        a, b = masks[a_name], masks[b_name]

        # "selection and not filter" pattern
        and_not = [
            f"{a_name} and not {b_name}",
            f"{a_name} and not filter",
            "selection and not filter",
        ]
        for pat in and_not:
            if cond == pat:
                return a & (~b)

        if cond in (f"{a_name} and {b_name}", "selection and filter"):
            return a & b
        if cond in (f"{a_name} or {b_name}", "selection or filter"):
            return a | b

        return None

    @staticmethod
    def _split_alternation(pattern: str) -> list[str]:
        """Split '(?:a)|(?:b)' into ['(?:a)', '(?:b)']."""
        import re
        parts = re.split(r"\|(?=\(\?:)", pattern)
        return [p for p in parts if p]
