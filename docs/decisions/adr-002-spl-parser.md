# ADR-002: ANTLR4 for SPL Grammar

**Status:** Accepted  
**Date:** 2026-04-15

## Context

SPL (Search Processing Language) is Splunk's proprietary query language. Full compatibility is a core product requirement. We need a parser that:
1. Handles 100% of real-world SPL (macros, subsearches, all commands)
2. Produces an AST we can optimize
3. Has good error messages (users will see parse errors)
4. Can be extended as we add cuSplunk-specific commands

## Decision

Use **ANTLR4** with a hand-written SPL grammar (`libs/spl-parser/SPL.g4`).

Python runtime (antlr4-python3-runtime) for integration with cuDF query executor.

## Grammar Strategy

Start from Splunk's official SPL documentation and reverse-engineer the grammar.
Test against a corpus of 10,000 real SPL queries from public Splunk community posts.

## Consequences

**Good:**
- Full control over grammar — can add `| gpu_hint` cuSplunk extensions
- ANTLR4 generates visitor/listener — easy AST walking for plan building
- Good error recovery — partial parses for autocomplete
- Well-known toolchain, team familiar with ANTLR

**Bad:**
- Maintenance burden: Splunk adds new SPL commands, we must update grammar
- Initial effort: complete SPL grammar is ~800 lines

## Alternatives Considered

| Approach | Rejected reason |
|---|---|
| Hand-written recursive descent | Maintenance nightmare for full SPL |
| Parse SPL → SQL, use existing SQL parser | SPL semantics don't map cleanly to SQL (pipeline model differs) |
| Use Splunk's own parser (internal) | Not accessible / not open source |
| PEG parser (lark, pyparsing) | Less tooling, harder to debug |
