"""
sigma/compiler.py — Compile SigmaRule into GPU-ready patterns.

Each SigmaRule is compiled into a CompiledRule that holds:
  - Per-selection regex patterns for GPU multi-pattern matching
  - A condition evaluator callable (Python AST → lambda)

On GPU (cuDF): patterns applied with df[col].str.contains(pattern, regex=True)
On CPU (pandas): same API, same semantics — used in unit tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from cusplunk.sigma.parser import (
    AggregationCondition,
    Detection,
    FieldMatcher,
    SelectionGroup,
    SigmaRule,
)


@dataclass
class FieldPattern:
    """One compiled field → pattern, ready to evaluate against a DataFrame column."""
    field_name: str          # DataFrame column name; "_keywords" → scan _raw
    pattern: str             # Python regex
    is_regex: bool           # if False, was a plain value list → converted to alternation
    negate: bool             # field|not modifier (future)
    require_all: bool        # field|contains|all → all patterns must match


@dataclass
class CompiledSelection:
    """All field patterns for one named selection (AND'd together)."""
    name: str
    field_patterns: list[FieldPattern]   # each must match (AND)


@dataclass
class CompiledRule:
    """GPU-ready compiled representation of a SigmaRule."""
    rule_id: str
    title: str
    level: str
    tags: list[str]
    selections: dict[str, CompiledSelection]   # name → compiled selection
    condition_fn: Callable[[dict[str, bool]], bool]
    aggregation: AggregationCondition | None
    raw_condition: str


class SigmaCompileError(Exception):
    pass


class SigmaCompiler:
    """
    Compile a SigmaRule into a CompiledRule.

    Usage:
        compiler = SigmaCompiler()
        compiled = compiler.compile(rule)
    """

    def compile(self, rule: SigmaRule) -> CompiledRule:
        compiled_selections: dict[str, CompiledSelection] = {}
        for name, sel_group in rule.detection.selections.items():
            compiled_selections[name] = self._compile_selection(sel_group)

        condition_fn = self._compile_condition(
            rule.detection.condition,
            set(compiled_selections.keys()),
            has_keywords=rule.detection.keywords is not None,
        )

        return CompiledRule(
            rule_id=rule.id,
            title=rule.title,
            level=rule.level,
            tags=rule.tags,
            selections=compiled_selections,
            condition_fn=condition_fn,
            aggregation=rule.detection.aggregation,
            raw_condition=rule.detection.condition,
        )

    # ── Selection compilation ──────────────────────────────────────

    def _compile_selection(self, sel: SelectionGroup) -> CompiledSelection:
        field_patterns = [self._compile_matcher(m) for m in sel.matchers]
        return CompiledSelection(name=sel.name, field_patterns=field_patterns)

    def _compile_matcher(self, matcher: FieldMatcher) -> FieldPattern:
        modifiers = set(matcher.modifiers)
        is_regex = "re" in modifiers
        require_all = "all" in modifiers

        if is_regex:
            # Values are already regex patterns — join with alternation if multiple
            if require_all:
                # All patterns must independently match — we'll handle in evaluator
                combined = "|".join(
                    f"(?:{v})" for v in matcher.values if v is not None
                )
            else:
                combined = "|".join(
                    f"(?:{v})" for v in matcher.values if v is not None
                )
            return FieldPattern(
                field_name=matcher.field_name,
                pattern=combined,
                is_regex=True,
                negate=False,
                require_all=require_all,
            )

        # Plain value matching — build regex from modifier chain
        parts: list[str] = []
        for value in matcher.values:
            if value is None:
                continue
            escaped = re.escape(str(value))
            if "contains" in modifiers:
                part = escaped
            elif "startswith" in modifiers:
                part = f"^{escaped}"
            elif "endswith" in modifiers:
                part = f"{escaped}$"
            else:
                # Exact match
                part = f"^{escaped}$"

            if "windash" in modifiers:
                # Replace - with [\\-/] for Windows CLI option variants
                part = part.replace(r"\-", r"[\-/]")

            parts.append(f"(?:{part})")

        pattern = "|".join(parts) if parts else "(?!)"  # (?!) never matches if empty

        return FieldPattern(
            field_name=matcher.field_name,
            pattern=pattern,
            is_regex=False,
            negate=False,
            require_all=require_all,
        )

    # ── Condition compilation ──────────────────────────────────────

    def _compile_condition(
        self,
        condition: str,
        selection_names: set[str],
        has_keywords: bool,
    ) -> Callable[[dict[str, bool]], bool]:
        """
        Compile a Sigma condition string into a Python callable.

        The callable receives a dict of {selection_name: bool} match results
        and returns True if the overall condition is satisfied.

        Supported:
          selection                         → simple reference
          selection1 and selection2
          selection1 or selection2
          not selection
          all of selection*                 → all names matching glob
          1 of selection*                   → any name matching glob
          N of selection*                   → at least N names
          keywords                          → bare keyword check
          count(...) by field > N           → aggregation (handled separately)
        """
        # Strip aggregation suffix before parsing boolean logic
        cond = self._strip_aggregation(condition).strip()

        # Build a safe evaluator
        try:
            fn = self._parse_condition_expr(cond, selection_names, has_keywords)
        except Exception as e:
            raise SigmaCompileError(
                f"Cannot compile condition '{condition}': {e}"
            ) from e
        return fn

    @staticmethod
    def _strip_aggregation(condition: str) -> str:
        """Remove aggregation suffix: 'selection | count() by x > 5' → 'selection'"""
        pipe_idx = condition.find("|")
        if pipe_idx != -1:
            return condition[:pipe_idx].strip()
        return condition

    def _parse_condition_expr(
        self,
        expr: str,
        names: set[str],
        has_keywords: bool,
    ) -> Callable[[dict[str, bool]], bool]:
        tokens = self._tokenize(expr)
        fn, remaining = self._parse_or(tokens, names, has_keywords)
        if remaining:
            raise SigmaCompileError(f"Unexpected tokens after condition: {remaining}")
        return fn

    # ── Recursive descent parser for condition expressions ─────────

    def _tokenize(self, expr: str) -> list[str]:
        # Split on whitespace, preserve parentheses as separate tokens
        raw = re.sub(r"([()])", r" \1 ", expr)
        return raw.split()

    def _parse_or(
        self,
        tokens: list[str],
        names: set[str],
        has_keywords: bool,
    ) -> tuple[Callable, list[str]]:
        left, tokens = self._parse_and(tokens, names, has_keywords)
        while tokens and tokens[0].lower() == "or":
            tokens = tokens[1:]
            right, tokens = self._parse_and(tokens, names, has_keywords)
            _left, _right = left, right
            left = lambda m, l=_left, r=_right: l(m) or r(m)
        return left, tokens

    def _parse_and(
        self,
        tokens: list[str],
        names: set[str],
        has_keywords: bool,
    ) -> tuple[Callable, list[str]]:
        left, tokens = self._parse_not(tokens, names, has_keywords)
        while tokens and tokens[0].lower() == "and":
            tokens = tokens[1:]
            right, tokens = self._parse_not(tokens, names, has_keywords)
            _left, _right = left, right
            left = lambda m, l=_left, r=_right: l(m) and r(m)
        return left, tokens

    def _parse_not(
        self,
        tokens: list[str],
        names: set[str],
        has_keywords: bool,
    ) -> tuple[Callable, list[str]]:
        if tokens and tokens[0].lower() == "not":
            tokens = tokens[1:]
            inner, tokens = self._parse_atom(tokens, names, has_keywords)
            return lambda m, f=inner: not f(m), tokens
        return self._parse_atom(tokens, names, has_keywords)

    def _parse_atom(
        self,
        tokens: list[str],
        names: set[str],
        has_keywords: bool,
    ) -> tuple[Callable, list[str]]:
        if not tokens:
            raise SigmaCompileError("Unexpected end of condition")

        tok = tokens[0]

        # Parenthesised group
        if tok == "(":
            tokens = tokens[1:]
            fn, tokens = self._parse_or(tokens, names, has_keywords)
            if not tokens or tokens[0] != ")":
                raise SigmaCompileError("Missing closing ')'")
            return fn, tokens[1:]

        # Quantifier: "N of selection*" or "all of selection*" or "1 of them"
        if tok.lower() in ("all", "1") or tok.isdigit():
            return self._parse_quantifier(tokens, names, has_keywords)

        # Keywords reference
        if tok.lower() == "keywords" and has_keywords:
            return lambda m: m.get("keywords", False), tokens[1:]

        # Named selection reference
        if tok in names:
            _tok = tok
            return lambda m, k=_tok: m.get(k, False), tokens[1:]

        # Unknown token — be lenient (future-proof for new Sigma features)
        import logging
        logging.debug("SigmaCompiler: unknown token '%s', treating as False", tok)
        return lambda m: False, tokens[1:]

    def _parse_quantifier(
        self,
        tokens: list[str],
        names: set[str],
        has_keywords: bool,
    ) -> tuple[Callable, list[str]]:
        """Parse: all of X* | 1 of X* | N of X*"""
        quantifier = tokens[0].lower()
        if len(tokens) < 3 or tokens[1].lower() != "of":
            raise SigmaCompileError(f"Expected 'N of <glob>' near '{tokens[:3]}'")
        glob_pat = tokens[2]
        remaining = tokens[3:]

        # Resolve glob to matching selection names
        matched = self._resolve_glob(glob_pat, names, has_keywords)

        if quantifier == "all":
            def fn(m: dict[str, bool], keys: list[str] = matched) -> bool:
                return all(m.get(k, False) for k in keys)
        elif quantifier == "1" or quantifier == "them":
            def fn(m: dict[str, bool], keys: list[str] = matched) -> bool:
                return any(m.get(k, False) for k in keys)
        else:
            n = int(quantifier)
            def fn(m: dict[str, bool], keys: list[str] = matched, threshold: int = n) -> bool:
                return sum(1 for k in keys if m.get(k, False)) >= threshold

        return fn, remaining

    def _resolve_glob(
        self,
        pattern: str,
        names: set[str],
        has_keywords: bool,
    ) -> list[str]:
        """Resolve 'selection*' or 'them' to matching selection names."""
        import fnmatch
        if pattern == "them":
            result = list(names)
            if has_keywords:
                result.append("keywords")
            return result
        return [n for n in names if fnmatch.fnmatch(n, pattern)]
