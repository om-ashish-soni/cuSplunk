"""
sigma/parser.py — Parse Sigma YAML rules into SigmaRule dataclasses.

Handles all Sigma condition types:
  - field: value           (exact match)
  - field|contains: value  (substring)
  - field|startswith: ...  (prefix)
  - field|endswith: ...    (suffix)
  - field|re: pattern      (regex)
  - field|contains|all:    (all of a list)
  - keywords: [...]        (bare keyword search in _raw)
  - condition aggregations: count() by field > N

References: https://sigmahq.io/docs/basics/rules.html
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── Data model ────────────────────────────────────────────────────

@dataclass
class LogSource:
    category: str | None = None
    product: str | None = None
    service: str | None = None
    definition: str | None = None


@dataclass
class FieldMatcher:
    """Single field → value(s) matcher with optional modifier chain."""
    field_name: str                  # None → keyword search on _raw
    modifiers: list[str]             # e.g. ["contains", "all"]
    values: list[str | int | None]   # matched values

    @property
    def is_keyword(self) -> bool:
        return self.field_name == "_keywords"

    @property
    def is_null_check(self) -> bool:
        return any(v is None for v in self.values)


@dataclass
class SelectionGroup:
    """A named detection selection: one or more FieldMatchers (AND'd together)."""
    name: str
    matchers: list[FieldMatcher]   # list items are AND'd; list values within each OR'd


@dataclass
class AggregationCondition:
    """count()/near aggregation condition: e.g. count() by src_ip > 5"""
    function: str          # "count" | "near"
    field: str | None      # field argument to count(field)
    group_by: str | None   # BY clause field
    op: str                # ">", ">=", "<", "<=", "=="
    threshold: int


@dataclass
class Detection:
    selections: dict[str, SelectionGroup]    # name → SelectionGroup
    keywords: list[str] | None               # bare keywords (no field)
    condition: str                           # raw condition expression
    aggregation: AggregationCondition | None
    timeframe: str | None                    # e.g. "5m", "1h"


@dataclass
class SigmaRule:
    id: str
    title: str
    status: str                    # stable | test | experimental | deprecated
    description: str
    author: str
    date: str
    modified: str | None
    references: list[str]
    tags: list[str]                # ATT&CK tags: attack.t1234 etc.
    logsource: LogSource
    detection: Detection
    fields: list[str]
    falsepositives: list[str]
    level: str                     # informational | low | medium | high | critical
    raw: dict[str, Any]            # original parsed YAML for debugging


# ── Parser ────────────────────────────────────────────────────────

class SigmaParseError(Exception):
    pass


class SigmaParser:
    """
    Parse Sigma YAML into SigmaRule objects.

    Usage:
        parser = SigmaParser()
        rule = parser.parse(yaml_text)
        rules = parser.parse_file(path)
    """

    # Valid modifiers per Sigma spec
    _VALID_MODIFIERS = frozenset([
        "contains", "startswith", "endswith", "re", "all",
        "base64", "base64offset", "wide", "windash",
        "cidr", "lt", "lte", "gt", "gte",
    ])

    # Aggregation functions
    _AGG_RE = re.compile(
        r"(?P<fn>count|sum|min|max|avg)"
        r"\((?P<arg>[^)]*)\)"
        r"(?:\s+by\s+(?P<by>\S+))?"
        r"\s*(?P<op>[><=!]+)\s*(?P<threshold>\d+)",
        re.IGNORECASE,
    )

    def parse(self, yaml_text: str) -> SigmaRule:
        try:
            doc = yaml.safe_load(yaml_text)
        except yaml.YAMLError as e:
            raise SigmaParseError(f"YAML parse error: {e}") from e

        if not isinstance(doc, dict):
            raise SigmaParseError("Sigma rule must be a YAML mapping")

        return self._parse_doc(doc)

    def parse_file(self, path: Path | str) -> SigmaRule:
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise SigmaParseError(f"Cannot read {path}: {e}") from e
        try:
            rule = self.parse(text)
        except SigmaParseError as e:
            raise SigmaParseError(f"{path}: {e}") from e
        return rule

    def parse_directory(self, directory: Path | str) -> list[SigmaRule]:
        """Parse all *.yml files in a directory (non-recursive)."""
        directory = Path(directory)
        rules = []
        errors = []
        for yml_file in sorted(directory.glob("*.yml")):
            try:
                rules.append(self.parse_file(yml_file))
            except SigmaParseError as e:
                errors.append(str(e))
        if errors:
            # Log but don't abort — return successfully parsed rules
            import logging
            for err in errors:
                logging.warning("SigmaParser: %s", err)
        return rules

    # ── Internal ──────────────────────────────────────────────────

    def _parse_doc(self, doc: dict) -> SigmaRule:
        # Required fields
        title = self._require_str(doc, "title")
        detection_raw = doc.get("detection")
        if not detection_raw:
            raise SigmaParseError(f"Rule '{title}': missing 'detection'")
        if not isinstance(detection_raw, dict):
            raise SigmaParseError(f"Rule '{title}': 'detection' must be a mapping")

        logsource_raw = doc.get("logsource", {})

        return SigmaRule(
            id=str(doc.get("id", "")),
            title=title,
            status=str(doc.get("status", "experimental")),
            description=str(doc.get("description", "")),
            author=str(doc.get("author", "")),
            date=str(doc.get("date", "")),
            modified=str(doc["modified"]) if "modified" in doc else None,
            references=self._to_str_list(doc.get("references", [])),
            tags=self._to_str_list(doc.get("tags", [])),
            logsource=self._parse_logsource(logsource_raw),
            detection=self._parse_detection(title, detection_raw),
            fields=self._to_str_list(doc.get("fields", [])),
            falsepositives=self._to_str_list(doc.get("falsepositives", [])),
            level=str(doc.get("level", "medium")),
            raw=doc,
        )

    def _parse_logsource(self, ls: dict) -> LogSource:
        return LogSource(
            category=ls.get("category"),
            product=ls.get("product"),
            service=ls.get("service"),
            definition=ls.get("definition"),
        )

    def _parse_detection(self, title: str, detection: dict) -> Detection:
        condition_raw = detection.get("condition")
        if not condition_raw:
            raise SigmaParseError(f"Rule '{title}': detection missing 'condition'")
        condition = str(condition_raw).strip()

        timeframe = detection.get("timeframe")

        # Keywords (bare search, no field)
        keywords_raw = detection.get("keywords")
        keywords: list[str] | None = None
        if keywords_raw is not None:
            keywords = self._to_str_list(keywords_raw)

        # Selections: everything in detection except 'condition', 'timeframe', 'keywords'
        selections: dict[str, SelectionGroup] = {}
        for key, value in detection.items():
            if key in ("condition", "timeframe", "keywords"):
                continue
            matchers = self._parse_selection_value(key, value)
            selections[key] = SelectionGroup(name=key, matchers=matchers)

        # Aggregation condition
        aggregation = self._parse_aggregation(condition)

        return Detection(
            selections=selections,
            keywords=keywords,
            condition=condition,
            aggregation=aggregation,
            timeframe=str(timeframe) if timeframe else None,
        )

    def _parse_selection_value(self, key: str, value: Any) -> list[FieldMatcher]:
        """
        Convert a detection selection value into FieldMatcher list.

        Formats:
          field: value
          field: [v1, v2]
          field|contains: value
          field|contains|all: [v1, v2]
          - field: value   (list of mappings → AND of multiple field conditions)
        """
        if isinstance(value, list):
            # List of mappings → each mapping is AND'd
            if all(isinstance(item, dict) for item in value):
                matchers = []
                for mapping in value:
                    matchers.extend(self._parse_mapping(mapping))
                return matchers
            # List of bare values → keyword-style match on _raw
            return [FieldMatcher(
                field_name="_keywords",
                modifiers=["contains"],
                values=[str(v) for v in value],
            )]

        if isinstance(value, dict):
            return self._parse_mapping(value)

        # Scalar → treat as keyword
        return [FieldMatcher(
            field_name="_keywords",
            modifiers=["contains"],
            values=[str(value)],
        )]

    def _parse_mapping(self, mapping: dict) -> list[FieldMatcher]:
        matchers = []
        for field_spec, raw_values in mapping.items():
            field_name, modifiers = self._parse_field_spec(field_spec)
            values = self._normalise_values(raw_values)
            matchers.append(FieldMatcher(
                field_name=field_name,
                modifiers=modifiers,
                values=values,
            ))
        return matchers

    def _parse_field_spec(self, spec: str) -> tuple[str, list[str]]:
        """'EventCode|contains|all' → ('EventCode', ['contains', 'all'])"""
        parts = spec.split("|")
        field_name = parts[0]
        modifiers = [m.lower() for m in parts[1:]]
        unknown = set(modifiers) - self._VALID_MODIFIERS
        if unknown:
            import logging
            logging.debug("SigmaParser: unknown modifiers %s in field '%s'", unknown, spec)
        return field_name, modifiers

    def _normalise_values(self, raw: Any) -> list[str | int | None]:
        if raw is None:
            return [None]
        if isinstance(raw, list):
            return [self._normalise_scalar(v) for v in raw]
        return [self._normalise_scalar(raw)]

    @staticmethod
    def _normalise_scalar(v: Any) -> str | int | None:
        if v is None:
            return None
        if isinstance(v, bool):
            return str(v).lower()
        if isinstance(v, int):
            return v
        return str(v)

    def _parse_aggregation(self, condition: str) -> AggregationCondition | None:
        m = self._AGG_RE.search(condition)
        if not m:
            return None
        fn = m.group("fn").lower()
        arg = m.group("arg").strip() or None
        by = m.group("by")
        op = m.group("op")
        threshold = int(m.group("threshold"))
        return AggregationCondition(
            function=fn,
            field=arg if arg else None,
            group_by=by,
            op=op,
            threshold=threshold,
        )

    @staticmethod
    def _require_str(doc: dict, key: str) -> str:
        val = doc.get(key)
        if not val:
            raise SigmaParseError(f"Missing required field '{key}'")
        return str(val)

    @staticmethod
    def _to_str_list(val: Any) -> list[str]:
        if val is None:
            return []
        if isinstance(val, str):
            return [val]
        if isinstance(val, list):
            return [str(v) for v in val]
        return [str(val)]
