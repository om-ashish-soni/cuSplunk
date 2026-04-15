# C3 — SPL Parser Checkpoint

**Status: R1 COMPLETE**
**Date: 2026-04-15**

## Test Results

```
594 passed in 5.24s
  - test_corpus.py:    532/532  (500 corpus queries + 32 unit tests)
  - test_edge_cases.py: 53/53
  - test_hypothesis.py:  9/9 (property-based: 600+ examples)
```

## Deliverables

| Artifact | Status |
|---|---|
| `SPL.g4` — ANTLR4 grammar | Complete |
| `generated/` — Python lexer/parser | Complete (auto-generated) |
| `cusplunk/spl/ast.py` — typed AST nodes | Complete |
| `cusplunk/spl/parser.py` — AST builder | Complete |
| `cusplunk/spl/visitor.py` — Visitor/Transformer | Complete |
| `corpus/basic.txt` — 500 test queries | Complete |
| `tests/test_corpus.py` | Complete |
| `tests/test_edge_cases.py` | Complete |
| `tests/test_hypothesis.py` | Complete |

## Grammar Coverage

Commands: search, stats, eval, rex, join, timechart, chart, tstats, table, fields, where,
dedup, sort, head, tail, rename, lookup, inputlookup, outputlookup, transaction, bucket/bin,
streamstats, eventstats, append, appendcols, union, top, rare, fillnull, makeresults,
extract, kvform, multikv, gpu_hint (cuSplunk extension), delta

Features:
- Boolean search expressions (AND/OR/NOT, precedence, parentheses)
- Wildcard terms (*, ?) with proper lexer disambiguation
- Field comparisons with all operators (=, !=, <, >, <=, >=, =~, IN, NOT IN)
- CIDR literals, IP literals, dotted field names
- Subsearch (nested [ ... ]) in join, append, union, transaction
- Eval: arithmetic (+, -, *, /, %), string concat (.), comparisons, boolean
- Eval functions: 40+ functions including null(), case(), if(), coalesce(), etc.
- Stats aggregations: count, sum, avg, min, max, dc, perc95, etc.
- Stats with computed by-fields and eval args in agg functions
- Timechart with multiple aggregations
- Streamstats with per-aggregation window= options
- Transaction with startswith/endswith
- Time modifiers: earliest=, latest=, relative (−1h@h) and absolute
- Macro calls (`macroname(args)`)
- GPU hint extension

## Key Design Decisions

1. **WILDCARD_TERM lexer rule**: Explicit 4-alternative rule preventing digit-only-prefix
   matching to avoid `1000*100` being lexed as a single WILDCARD_TERM.

2. **Token stream post-processor**: `_split_arithmetic_wildcards()` splits middle-wildcard
   tokens like `total*100` into [ID, STAR, INT] for arithmetic contexts.

3. **`%` operator**: Removed `%` from UNQUOTED_TERM/WILDCARD_TERM char class so that
   `random()%100` lexes as `PERCENT INT` rather than `UNQUOTED_TERM`.

4. **`null()` function**: `NULL_KW` added to `evalFuncName` so `null()` parses as a
   zero-argument function call.

5. **Function-call field names**: `renameClause`, `sortField`, `tableField` all accept
   `functionCall` alternatives to handle Splunk computed field names like `avg(response_time)`.

6. **`aggArg → expr`**: Allows `sum(if(...))` nested function calls as aggregation args.

7. **Streamstats**: `streamstatsAggItem` with optional `WINDOW EQ INT` prefix enables
   per-aggregation window specs like `window=5 avg(x) as ma5, window=20 avg(x) as ma20`.
