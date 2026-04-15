/**
 * SPL.g4 — Splunk Search Processing Language grammar for cuSplunk
 *
 * Covers all major SPL commands, subsearch, macros, eval functions,
 * boolean expressions, time modifiers, and field references.
 *
 * ANTLR4 4.13.2 — target: Python3
 *
 * Design notes:
 *  - Keywords can be field names: handled via the `kw` catch-all rule
 *  - Search boolean and eval boolean are separate rule trees (no mutual recursion)
 *  - Aggregate function tokens are also used as option names: defined once,
 *    referenced in both contexts
 */
grammar SPL;

// ─────────────────────────────────────────────
//  TOP LEVEL
// ─────────────────────────────────────────────

spl
    : pipeline EOF
    ;

pipeline
    : PIPE? command (PIPE command)*
    ;

// ─────────────────────────────────────────────
//  COMMANDS
// ─────────────────────────────────────────────

command
    : searchCmd
    | statsCmd
    | evalCmd
    | rexCmd
    | joinCmd
    | timechartCmd
    | chartCmd
    | tstatsCmd
    | tableCmd
    | fieldsCmd
    | whereCmd
    | dedupCmd
    | sortCmd
    | headCmd
    | tailCmd
    | renameCmd
    | lookupCmd
    | inputlookupCmd
    | outputlookupCmd
    | transactionCmd
    | bucketCmd
    | streamstatsCmd
    | eventstatsCmd
    | appendCmd
    | appendColsCmd
    | unionCmd
    | topCmd
    | rareCmd
    | fillnullCmd
    | makeresultsCmd
    | extractCmd
    | kvformCmd
    | multikvCmd
    | gpuHintCmd
    | deltaCmd
    ;

// ─────────────────────────────────────────────
//  SEARCH
// ─────────────────────────────────────────────

searchCmd
    : SEARCH searchExpr?
    ;

searchExpr
    : searchOrExpr
    ;

searchOrExpr
    : searchAndExpr (OR searchAndExpr)*
    ;

searchAndExpr
    : searchNotExpr (AND? searchNotExpr)*    // AND is optional (SPL implicit AND)
    ;

searchNotExpr
    : NOT searchNotExpr
    | LPAREN searchOrExpr RPAREN
    | searchAtom
    ;

searchAtom
    : timeModifier
    | fieldComparison
    | subsearch
    | term
    ;

term
    : STRING_LITERAL
    | CIDR_LITERAL
    | IP_LITERAL
    | DOTTED_FIELD
    | UNQUOTED_TERM
    | WILDCARD_TERM
    | STAR
    | number
    | ID
    | kw
    ;

fieldComparison
    : fieldName compOp fieldVal
    | fieldName IN LPAREN fieldValList RPAREN
    | fieldName NOT IN LPAREN fieldValList RPAREN
    ;

fieldValList
    : fieldVal (COMMA fieldVal)*
    ;

compOp
    : EQ | NEQ | LT | GT | LTE | GTE | MATCH_REGEX
    ;

fieldVal
    : STRING_LITERAL
    | CIDR_LITERAL
    | IP_LITERAL
    | DOTTED_FIELD
    | UNQUOTED_TERM
    | WILDCARD_TERM
    | STAR
    | number
    | boolLiteral
    | ID
    | kw
    ;

timeModifier
    : (EARLIEST | LATEST | INDEX_EARLIEST | INDEX_LATEST) EQ timeStr
    ;

timeStr
    : RELATIVE_TIME_LITERAL
    | STRING_LITERAL
    | INT
    ;

// ─────────────────────────────────────────────
//  STATS / EVENTSTATS / STREAMSTATS
// ─────────────────────────────────────────────

statsCmd
    : STATS (statsOpt)* aggList (BY statsByList (SPAN EQ spanVal)?)?
    ;

statsOpt
    : PARTITIONS EQ INT
    | ALLNUM EQ boolLiteral
    | DELIM EQ STRING_LITERAL
    | DEDUP_SPLITVALS EQ boolLiteral
    ;

eventstatsCmd
    : EVENTSTATS (ALLNUM EQ boolLiteral)? aggList (BY statsByList)?
    ;

streamstatsCmd
    : STREAMSTATS (streamstatsOpt)* streamstatsAggList (BY statsByList)?
    ;

streamstatsAggList
    : streamstatsAggItem (COMMA streamstatsAggItem)*
    ;

streamstatsAggItem
    : (WINDOW EQ INT)? aggCall
    ;

streamstatsOpt
    : CURRENT EQ boolLiteral
    | WINDOW EQ INT
    | GLOBAL EQ boolLiteral
    | RESET_ON_CHANGE EQ boolLiteral
    | RESET_BEFORE LPAREN expr RPAREN
    | RESET_AFTER  LPAREN expr RPAREN
    | TIME_WINDOW EQ spanVal
    ;

aggList
    : aggCall (COMMA aggCall)*
    ;

aggCall
    : aggFunc LPAREN aggArg? RPAREN (AS fieldName)?   // count(field), sum(bytes)
    | aggFunc (AS fieldName)?                          // bare count (no parens)
    ;

aggFunc
    : COUNT | SUM | AVG | MIN | MAX | RANGE | STDEV | STDEVP
    | VAR | VARP | MEDIAN | MODE | FIRST | LAST | EARLIEST | LATEST
    | LIST | VALUES | DC | ESTDC | ESTDC_ERROR | PERC | PERCN | UPPERPERC | UPPERPERCN
    | PER_SECOND | EARLIEST_TIME | LATEST_TIME | RATE | RATE_SUM | RATE_AVG
    ;

aggArg
    : STAR
    | EVAL LPAREN expr RPAREN
    | expr
    ;

// ─────────────────────────────────────────────
//  EVAL
// ─────────────────────────────────────────────

evalCmd
    : EVAL evalAssignList
    ;

evalAssignList
    : evalAssign (COMMA evalAssign)*
    ;

evalAssign
    : fieldName EQ expr
    ;

// ─────────────────────────────────────────────
//  REX
// ─────────────────────────────────────────────

rexCmd
    : REX (rexOpt)* STRING_LITERAL (rexOpt)*
    ;

rexOpt
    : FIELD EQ fieldName
    | MODE EQ STRING_LITERAL
    | MAX_MATCH EQ INT
    | OFFSET_FIELD EQ fieldName
    ;

// ─────────────────────────────────────────────
//  JOIN
// ─────────────────────────────────────────────

joinCmd
    : JOIN (joinOpt)* fieldName* subsearch
    ;

joinOpt
    : TYPE EQ joinType
    | USETIME EQ boolLiteral
    | EARLIER EQ boolLiteral
    | OVERWRITE EQ boolLiteral
    | MAX EQ INT
    ;

joinType
    : INNER | LEFT | OUTER
    ;

// ─────────────────────────────────────────────
//  TIMECHART / CHART
// ─────────────────────────────────────────────

timechartCmd
    : TIMECHART (timechartOpt)* aggList? (BY fieldName)? (LIMIT EQ INT)? (timechartOpt)*
    ;

timechartOpt
    : SPAN EQ spanVal
    | BINS EQ INT
    | MINSPAN EQ spanVal
    | PARTIAL EQ boolLiteral
    | CONT EQ boolLiteral
    | USENULL EQ boolLiteral
    | USEOTHER EQ boolLiteral
    | NULLSTR EQ STRING_LITERAL
    | OTHERSTR EQ STRING_LITERAL
    | FIX_EMPTY EQ boolLiteral
    | ALIGNTIME EQ timeStr
    | LIMIT EQ INT
    ;

chartCmd
    : CHART (chartOpt)* aggList OVER fieldName (BY fieldList)? (LIMIT EQ INT)?
    ;

chartOpt
    : SPAN EQ spanVal
    | BINS EQ INT
    | CONT EQ boolLiteral
    | USENULL EQ boolLiteral
    | USEOTHER EQ boolLiteral
    | NULLSTR EQ STRING_LITERAL
    | OTHERSTR EQ STRING_LITERAL
    | LIMIT EQ INT
    ;

// ─────────────────────────────────────────────
//  TSTATS
// ─────────────────────────────────────────────

tstatsCmd
    : TSTATS (tstatsOpt)* aggList?
      (FROM (DATAMODEL EQ? fieldName (DOT fieldName)*))?
      (WHERE expr)?
      (FROM (DATAMODEL EQ? fieldName (DOT fieldName)*))?
      (BY fieldList (SPAN EQ spanVal)?)?
      (FROM (DATAMODEL EQ? fieldName (DOT fieldName)*))?
      (WHERE expr)?
    ;

tstatsOpt
    : SUMMARIESONLY EQ boolLiteral
    | ALLOW_OLD_SUMMARIES EQ boolLiteral
    | APPEND EQ boolLiteral
    | PRESTATS EQ boolLiteral
    | LOCAL EQ boolLiteral
    ;

// ─────────────────────────────────────────────
//  TABLE / FIELDS / WHERE / DEDUP / SORT / HEAD / TAIL
// ─────────────────────────────────────────────

tableCmd
    : TABLE tableFieldList
    ;

tableFieldList
    : tableField (COMMA tableField)*
    ;

tableField
    : functionCall
    | fieldName
    ;

fieldsCmd
    : FIELDS (PLUS | MINUS)? fieldList
    ;

whereCmd
    : WHERE expr
    ;

dedupCmd
    : DEDUP (INT)? fieldList
      (KEEPEVENTS EQ boolLiteral)?
      (KEEPEMPTY EQ boolLiteral)?
      (CONSECUTIVE EQ boolLiteral)?
      sortByClause?
    ;

sortCmd
    : SORT (MINUS INT | LIMIT EQ INT)? sortFieldList
    ;

sortFieldList
    : sortField (COMMA sortField)*
    ;

sortField
    : (PLUS | MINUS)? (AUTO | IP | NUM | STR | aggFunc) LPAREN fieldName RPAREN
    | (PLUS | MINUS)? functionCall
    | (PLUS | MINUS)? fieldName
    ;

sortByClause
    : SORTBY sortFieldList
    ;

headCmd
    : HEAD (INT | expr)? (LIMIT EQ INT)? (KEEPLAST EQ boolLiteral)? (NULL_KW EQ boolLiteral)?
    ;

tailCmd
    : TAIL INT?
    ;

// ─────────────────────────────────────────────
//  RENAME
// ─────────────────────────────────────────────

renameCmd
    : RENAME renameClause (COMMA renameClause)*
    ;

renameClause
    : (functionCall | fieldName) AS fieldName
    ;

// ─────────────────────────────────────────────
//  LOOKUP / INPUTLOOKUP / OUTPUTLOOKUP
// ─────────────────────────────────────────────

lookupCmd
    : LOOKUP lookupName lookupFields ((OUTPUT | OUTPUTNEW) lookupFields)?
    ;

inputlookupCmd
    : INPUTLOOKUP (APPEND EQ boolLiteral)? (START EQ INT)? (MAX EQ INT)?
      lookupName (WHERE expr)?
    ;

outputlookupCmd
    : OUTPUTLOOKUP (APPEND EQ boolLiteral)? (CREATE_EMPTY EQ boolLiteral)?
      (MAX EQ INT)? (KEY_FIELD EQ fieldName)?
      lookupName
    ;

lookupName
    : fieldName
    ;

lookupFields
    : lookupField (COMMA lookupField)*
    ;

lookupField
    : fieldName (AS fieldName)?
    ;

// ─────────────────────────────────────────────
//  TRANSACTION
// ─────────────────────────────────────────────

transactionCmd
    : TRANSACTION fieldName* (transactionOpt)*
    ;

transactionOpt
    : MAXSPAN EQ spanVal
    | MAXPAUSE EQ spanVal
    | MAXEVENTS EQ INT
    | KEEPORPHANS EQ boolLiteral
    | MVLIST EQ boolLiteral
    | NULLSTR EQ STRING_LITERAL
    | STARTSWITH EQ evalOrSearch
    | ENDSWITH EQ evalOrSearch
    ;

evalOrSearch
    : EVAL LPAREN expr RPAREN
    | SEARCH LPAREN searchExpr RPAREN
    | STRING_LITERAL
    ;

// ─────────────────────────────────────────────
//  BUCKET / BIN
// ─────────────────────────────────────────────

bucketCmd
    : (BUCKET | BIN) (bucketOpt)* fieldName (bucketOpt)* (AS fieldName)?
    ;

bucketOpt
    : SPAN EQ spanVal
    | BINS EQ INT
    | MINSPAN EQ spanVal
    | START EQ number
    | END EQ number
    | ALIGNTIME EQ timeStr
    ;

// ─────────────────────────────────────────────
//  APPEND / APPENDCOLS / UNION
// ─────────────────────────────────────────────

appendCmd
    : APPEND subsearch
    ;

appendColsCmd
    : APPENDCOLS subsearch
    ;

unionCmd
    : UNION (MAX EQ INT)? subsearch+
    ;

// ─────────────────────────────────────────────
//  TOP / RARE
// ─────────────────────────────────────────────

topCmd
    : TOP INT? (topRareOpt)* fieldList (BY fieldList)? (topRareOpt)*
    ;

rareCmd
    : RARE INT? (topRareOpt)* fieldList (BY fieldList)? (topRareOpt)*
    ;

topRareOpt
    : LIMIT EQ INT
    | COUNTFIELD EQ fieldName
    | PERCENTFIELD EQ fieldName
    | SHOWPERC EQ boolLiteral
    | USEOTHER EQ boolLiteral
    | OTHERSTR EQ STRING_LITERAL
    ;

// ─────────────────────────────────────────────
//  FILLNULL / MAKERESULTS
// ─────────────────────────────────────────────

fillnullCmd
    : FILLNULL (VALUE EQ (STRING_LITERAL | number | UNQUOTED_TERM))? fieldList?
    ;

makeresultsCmd
    : MAKERESULTS (COUNT EQ INT)? (ANNOTATE EQ boolLiteral)? (SPLUNK_SERVER EQ STRING_LITERAL)?
    ;

// ─────────────────────────────────────────────
//  EXTRACT / KVFORM / MULTIKV
// ─────────────────────────────────────────────

extractCmd
    : EXTRACT (extractOpt)*
    ;

extractOpt
    : CLEAN_KEYS EQ boolLiteral
    | KVDELIM EQ STRING_LITERAL
    | LIMIT EQ INT
    | MAXCHARS EQ INT
    | PAIRDELIM EQ STRING_LITERAL
    | AUTO EQ boolLiteral
    ;

kvformCmd
    : KVFORM (FIELD EQ fieldName)? (OUTPUT EQ fieldName)?
    ;

multikvCmd
    : MULTIKV (FIELDS fieldList)? (RMORIG EQ boolLiteral)?
    ;

// ─────────────────────────────────────────────
//  cuSplunk EXTENSION
// ─────────────────────────────────────────────

gpuHintCmd
    : GPU_HINT (MEMORY EQ INT)? (STREAM EQ boolLiteral)?
    ;

// ─────────────────────────────────────────────
//  DELTA
// ─────────────────────────────────────────────

deltaCmd
    : DELTA fieldName (AS fieldName)?
    ;

// ─────────────────────────────────────────────
//  SUBSEARCH / MACRO
// ─────────────────────────────────────────────

subsearch
    : LBRACKET pipeline RBRACKET
    ;

macroCall
    : BACKTICK fieldName (LPAREN macroArgs RPAREN)? BACKTICK
    ;

macroArgs
    : macroArg (COMMA macroArg)*
    ;

macroArg
    : STRING_LITERAL
    | number
    | fieldName
    ;

// ─────────────────────────────────────────────
//  EXPRESSIONS  (eval / where)
// ─────────────────────────────────────────────

expr
    : orExpr
    ;

orExpr
    : andExpr (OR andExpr)*
    ;

andExpr
    : notExpr (AND notExpr)*
    ;

notExpr
    : NOT notExpr
    | compExpr
    ;

compExpr
    : addExpr (compOp addExpr)?
    | addExpr LIKE STRING_LITERAL
    | addExpr IN LPAREN valueList RPAREN
    | addExpr NOT IN LPAREN valueList RPAREN
    ;

addExpr
    : mulExpr ((PLUS | MINUS | DOT) mulExpr)*
    ;

mulExpr
    : unaryExpr ((STAR | SLASH | PERCENT) unaryExpr)*
    ;

unaryExpr
    : MINUS unaryExpr
    | PLUS  unaryExpr
    | atom
    ;

atom
    : LPAREN expr RPAREN
    | functionCall
    | macroCall
    | subsearch
    | fieldName
    | literal
    | WILDCARD_TERM
    | CIDR_LITERAL
    | IP_LITERAL
    | STAR
    ;

literal
    : STRING_LITERAL
    | number
    | boolLiteral
    | NULL_KW
    ;

valueList
    : literal (COMMA literal)*
    ;

functionCall
    : funcName LPAREN funcArgList? RPAREN
    ;

funcName
    : evalFuncName
    | fieldName
    ;

funcArgList
    : expr (COMMA expr)*
    ;

// ─────────────────────────────────────────────
//  EVAL FUNCTION NAMES  (keyword tokens re-used as func names)
// ─────────────────────────────────────────────

evalFuncName
    : ABS | CEILING | EXACT | EXP | FLOOR | LN | LOG | PI | ROUND | SIGFIG | SQRT | TONUMBER
    | LEN | LOWER | LTRIM | REPLACE | RTRIM | SPLIT | STRCAT | SUBSTR | TRIM | UPPER | URLDECODE
    | ISNULL | ISNOTNULL | ISNUM | ISSTR | ISINT | ISNAN | ISBOOL | COALESCE | CASE | IF
    | NULLIF | VALIDATE | TYPEOF
    | COMMANDS | MVAPPEND | MVCOUNT | MVDEDUP | MVFIND | MVINDEX | MVJOIN | MVRANGE | MVSORT | MVZIP
    | NOW | RELATIVE_TIME_FN | STRFTIME | STRPTIME | TIME_FN
    | TOSTRING | PRINTF
    | MD5 | SHA1 | SHA256 | SHA512
    | CIDRMATCH | MATCH_FN | SEARCHMATCH
    | TRUE | FALSE | NULL_KW
    ;

// ─────────────────────────────────────────────
//  SHARED FRAGMENTS
// ─────────────────────────────────────────────

spanVal
    : number timeUnit               // e.g. 1 h, 30 min
    | RELATIVE_TIME_LITERAL         // e.g. 1h, 30m (lexed as single token)
    | number                        // bare number: e.g. span=1000000 (byte buckets)
    | UNQUOTED_TERM                 // size units: 1mb, 1kb, 1gb, or non-standard units
    ;

timeUnit
    : S | SEC | SECS | SECOND | SECONDS
    | M | MIN | MINS | MINUTE | MINUTES
    | H | HR | HRS | HOUR | HOURS
    | D | DAY | DAYS
    | W | WEEK | WEEKS
    | MON | MONTH | MONTHS
    | Q | QTR | QTRS | QUARTER | QUARTERS
    | Y | YR | YRS | YEAR | YEARS
    ;

boolLiteral
    : TRUE | FALSE
    ;

fieldList
    : fieldName (COMMA fieldName)*
    ;

// statsByList allows "name=expr" computed fields as well as plain field names
statsByList
    : statsByField (COMMA statsByField)*
    ;

statsByField
    : fieldName EQ expr   # computedByField
    | fieldName           # plainByField
    ;

fieldName
    : ID
    | STRING_LITERAL
    | DOTTED_FIELD
    | UNQUOTED_TERM
    | kw
    ;

// Allow any keyword to appear as a field name (SPL is context-sensitive)
kw
    : SEARCH | STATS | EVAL | REX | JOIN | TIMECHART | CHART | TSTATS
    | TABLE | FIELDS | WHERE | DEDUP | SORT | HEAD | TAIL | RENAME
    | LOOKUP | INPUTLOOKUP | OUTPUTLOOKUP | TRANSACTION | BUCKET | BIN
    | STREAMSTATS | EVENTSTATS | APPEND | APPENDCOLS | UNION | TOP | RARE
    | FILLNULL | MAKERESULTS | EXTRACT | KVFORM | MULTIKV | GPU_HINT
    | COUNT | SUM | AVG | MIN | MAX | RANGE | STDEV | STDEVP | VAR | VARP
    | MEDIAN | MODE | FIRST | LAST | EARLIEST | LATEST | LIST | VALUES
    | DC | ESTDC | PERC | RATE | AS | BY | OVER | FROM | OUTPUT | OUTPUTNEW
    | DATAMODEL | IN | NOT | AND | OR | LIKE | SPAN | BINS | LIMIT
    | TYPE | FIELD | INNER | LEFT | OUTER | CURRENT | WINDOW | GLOBAL
    | INDEX | SOURCE | SOURCETYPE | HOST | AUTO | LOCAL | PARTIAL
    | START | END | MAX_MATCH | OFFSET_FIELD | KEEPEVENTS | KEEPEMPTY
    | CONSECUTIVE | MAXSPAN | MAXPAUSE | MAXEVENTS | KEEPORPHANS | MVLIST
    | STARTSWITH | ENDSWITH | SUMMARIESONLY | PRESTATS | APPEND | VALUE
    | ANNOTATE | RMORIG | CLEAN_KEYS | COUNTFIELD | PERCENTFIELD | SHOWPERC
    | USEOTHER | USENULL | CONT | SORTBY | ALLNUM | DELIM | OVERWRITE
    | USETIME | EARLIER | SORTBY | KEEPLAST | ABS | CEILING | EXACT | EXP
    | FLOOR | LN | LOG | PI | ROUND | SIGFIG | SQRT | TONUMBER | LEN
    | LOWER | LTRIM | REPLACE | RTRIM | SPLIT | STRCAT | SUBSTR | TRIM
    | UPPER | URLDECODE | ISNULL | ISNOTNULL | ISNUM | ISSTR | ISINT
    | ISNAN | ISBOOL | COALESCE | CASE | IF | NULLIF | VALIDATE | TYPEOF
    | MVAPPEND | MVCOUNT | MVDEDUP | MVFIND | MVINDEX | MVJOIN | MVRANGE
    | MVSORT | MVZIP | NOW | TOSTRING | PRINTF | MD5 | SHA1 | SHA256 | SHA512
    | CIDRMATCH | MATCH_FN | SEARCHMATCH | MEMORY | STREAM | IP | NUM | STR
    | S | SEC | SECS | SECOND | SECONDS | M | MIN | MINS | MINUTE | MINUTES
    | H | HR | HRS | HOUR | HOURS | D | DAY | DAYS | W | WEEK | WEEKS
    | MON | MONTH | MONTHS | Q | QTR | QTRS | QUARTER | QUARTERS
    | Y | YR | YRS | YEAR | YEARS | CREATE_EMPTY | KEY_FIELD | TIME_WINDOW
    | RESET_ON_CHANGE | DEDUP_SPLITVALS | ALLOW_OLD_SUMMARIES | PARTITIONS
    | ALIGNTIME | MINSPAN | NULLSTR | OTHERSTR | FIX_EMPTY | SPLUNK_SERVER
    | KVDELIM | MAXCHARS | PAIRDELIM | SEGMENT | RESET_BEFORE | RESET_AFTER
    | DELTA | NULL_KW
    ;

number
    : INT
    | FLOAT
    | HEX_INT
    ;

// ─────────────────────────────────────────────
//  LEXER — KEYWORDS
// ─────────────────────────────────────────────

// Commands
SEARCH        : [Ss][Ee][Aa][Rr][Cc][Hh] ;
STATS         : [Ss][Tt][Aa][Tt][Ss] ;
EVAL          : [Ee][Vv][Aa][Ll] ;
REX           : [Rr][Ee][Xx] ;
JOIN          : [Jj][Oo][Ii][Nn] ;
TIMECHART     : [Tt][Ii][Mm][Ee][Cc][Hh][Aa][Rr][Tt] ;
CHART         : [Cc][Hh][Aa][Rr][Tt] ;
TSTATS        : [Tt][Ss][Tt][Aa][Tt][Ss] ;
TABLE         : [Tt][Aa][Bb][Ll][Ee] ;
FIELDS        : [Ff][Ii][Ee][Ll][Dd][Ss] ;
WHERE         : [Ww][Hh][Ee][Rr][Ee] ;
DEDUP         : [Dd][Ee][Dd][Uu][Pp] ;
SORT          : [Ss][Oo][Rr][Tt] ;
HEAD          : [Hh][Ee][Aa][Dd] ;
TAIL          : [Tt][Aa][Ii][Ll] ;
RENAME        : [Rr][Ee][Nn][Aa][Mm][Ee] ;
LOOKUP        : [Ll][Oo][Oo][Kk][Uu][Pp] ;
INPUTLOOKUP   : [Ii][Nn][Pp][Uu][Tt][Ll][Oo][Oo][Kk][Uu][Pp] ;
OUTPUTLOOKUP  : [Oo][Uu][Tt][Pp][Uu][Tt][Ll][Oo][Oo][Kk][Uu][Pp] ;
TRANSACTION   : [Tt][Rr][Aa][Nn][Ss][Aa][Cc][Tt][Ii][Oo][Nn] ;
BUCKET        : [Bb][Uu][Cc][Kk][Ee][Tt] ;
BIN           : [Bb][Ii][Nn] ;
STREAMSTATS   : [Ss][Tt][Rr][Ee][Aa][Mm][Ss][Tt][Aa][Tt][Ss] ;
EVENTSTATS    : [Ee][Vv][Ee][Nn][Tt][Ss][Tt][Aa][Tt][Ss] ;
APPEND        : [Aa][Pp][Pp][Ee][Nn][Dd] ;
APPENDCOLS    : [Aa][Pp][Pp][Ee][Nn][Dd][Cc][Oo][Ll][Ss] ;
UNION         : [Uu][Nn][Ii][Oo][Nn] ;
TOP           : [Tt][Oo][Pp] ;
RARE          : [Rr][Aa][Rr][Ee] ;
FILLNULL      : [Ff][Ii][Ll][Ll][Nn][Uu][Ll][Ll] ;
MAKERESULTS   : [Mm][Aa][Kk][Ee][Rr][Ee][Ss][Uu][Ll][Tt][Ss] ;
EXTRACT       : [Ee][Xx][Tt][Rr][Aa][Cc][Tt] ;
KVFORM        : [Kk][Vv][Ff][Oo][Rr][Mm] ;
MULTIKV       : [Mm][Uu][Ll][Tt][Ii][Kk][Vv] ;
GPU_HINT      : [Gg][Pp][Uu][_][Hh][Ii][Nn][Tt] ;
DELTA         : [Dd][Ee][Ll][Tt][Aa] ;

// Aggregate functions
COUNT         : [Cc][Oo][Uu][Nn][Tt] ;
SUM           : [Ss][Uu][Mm] ;
AVG           : [Aa][Vv][Gg] ;
MIN           : [Mm][Ii][Nn] ;
MAX           : [Mm][Aa][Xx] ;
RANGE         : [Rr][Aa][Nn][Gg][Ee] ;
STDEV         : [Ss][Tt][Dd][Ee][Vv] ;
STDEVP        : [Ss][Tt][Dd][Ee][Vv][Pp] ;
VAR           : [Vv][Aa][Rr] ;
VARP          : [Vv][Aa][Rr][Pp] ;
MEDIAN        : [Mm][Ee][Dd][Ii][Aa][Nn] ;
MODE          : [Mm][Oo][Dd][Ee] ;
FIRST         : [Ff][Ii][Rr][Ss][Tt] ;
LAST          : [Ll][Aa][Ss][Tt] ;
EARLIEST      : [Ee][Aa][Rr][Ll][Ii][Ee][Ss][Tt] ;
LATEST        : [Ll][Aa][Tt][Ee][Ss][Tt] ;
LIST          : [Ll][Ii][Ss][Tt] ;
VALUES        : [Vv][Aa][Ll][Uu][Ee][Ss] ;
DC            : [Dd][Cc] ;
ESTDC         : [Ee][Ss][Tt][Dd][Cc] ;
ESTDC_ERROR   : [Ee][Ss][Tt][Dd][Cc][_][Ee][Rr][Rr][Oo][Rr] ;
PERCN         : [Pp][Ee][Rr][Cc][0-9]+ ;
UPPERPERCN    : [Uu][Pp][Pp][Ee][Rr][Pp][Ee][Rr][Cc][0-9]+ ;
PERC          : [Pp][Ee][Rr][Cc] ;
UPPERPERC     : [Uu][Pp][Pp][Ee][Rr][Pp][Ee][Rr][Cc] ;
PER_SECOND    : [Pp][Ee][Rr][_][Ss][Ee][Cc][Oo][Nn][Dd] ;
EARLIEST_TIME : [Ee][Aa][Rr][Ll][Ii][Ee][Ss][Tt][_][Tt][Ii][Mm][Ee] ;
LATEST_TIME   : [Ll][Aa][Tt][Ee][Ss][Tt][_][Tt][Ii][Mm][Ee] ;
RATE          : [Rr][Aa][Tt][Ee] ;
RATE_SUM      : [Rr][Aa][Tt][Ee][_][Ss][Uu][Mm] ;
RATE_AVG      : [Rr][Aa][Tt][Ee][_][Aa][Vv][Gg] ;

// Eval function keywords
ABS           : [Aa][Bb][Ss] ;
CEILING       : [Cc][Ee][Ii][Ll][Ii][Nn][Gg] ;
EXACT         : [Ee][Xx][Aa][Cc][Tt] ;
EXP           : [Ee][Xx][Pp] ;
FLOOR         : [Ff][Ll][Oo][Oo][Rr] ;
LN            : [Ll][Nn] ;
LOG           : [Ll][Oo][Gg] ;
PI            : [Pp][Ii] ;
ROUND         : [Rr][Oo][Uu][Nn][Dd] ;
SIGFIG        : [Ss][Ii][Gg][Ff][Ii][Gg] ;
SQRT          : [Ss][Qq][Rr][Tt] ;
TONUMBER      : [Tt][Oo][Nn][Uu][Mm][Bb][Ee][Rr] ;
LEN           : [Ll][Ee][Nn] ;
LOWER         : [Ll][Oo][Ww][Ee][Rr] ;
LTRIM         : [Ll][Tt][Rr][Ii][Mm] ;
REPLACE       : [Rr][Ee][Pp][Ll][Aa][Cc][Ee] ;
RTRIM         : [Rr][Tt][Rr][Ii][Mm] ;
SPLIT         : [Ss][Pp][Ll][Ii][Tt] ;
STRCAT        : [Ss][Tt][Rr][Cc][Aa][Tt] ;
SUBSTR        : [Ss][Uu][Bb][Ss][Tt][Rr] ;
TRIM          : [Tt][Rr][Ii][Mm] ;
UPPER         : [Uu][Pp][Pp][Ee][Rr] ;
URLDECODE     : [Uu][Rr][Ll][Dd][Ee][Cc][Oo][Dd][Ee] ;
ISNULL        : [Ii][Ss][Nn][Uu][Ll][Ll] ;
ISNOTNULL     : [Ii][Ss][Nn][Oo][Tt][Nn][Uu][Ll][Ll] ;
ISNUM         : [Ii][Ss][Nn][Uu][Mm] ;
ISSTR         : [Ii][Ss][Ss][Tt][Rr] ;
ISINT         : [Ii][Ss][Ii][Nn][Tt] ;
ISNAN         : [Ii][Ss][Nn][Aa][Nn] ;
ISBOOL        : [Ii][Ss][Bb][Oo][Oo][Ll] ;
COALESCE      : [Cc][Oo][Aa][Ll][Ee][Ss][Cc][Ee] ;
CASE          : [Cc][Aa][Ss][Ee] ;
IF            : [Ii][Ff] ;
NULLIF        : [Nn][Uu][Ll][Ll][Ii][Ff] ;
VALIDATE      : [Vv][Aa][Ll][Ii][Dd][Aa][Tt][Ee] ;
TYPEOF        : [Tt][Yy][Pp][Ee][Oo][Ff] ;
COMMANDS      : [Cc][Oo][Mm][Mm][Aa][Nn][Dd][Ss] ;
MVAPPEND      : [Mm][Vv][Aa][Pp][Pp][Ee][Nn][Dd] ;
MVCOUNT       : [Mm][Vv][Cc][Oo][Uu][Nn][Tt] ;
MVDEDUP       : [Mm][Vv][Dd][Ee][Dd][Uu][Pp] ;
MVFIND        : [Mm][Vv][Ff][Ii][Nn][Dd] ;
MVINDEX       : [Mm][Vv][Ii][Nn][Dd][Ee][Xx] ;
MVJOIN        : [Mm][Vv][Jj][Oo][Ii][Nn] ;
MVRANGE       : [Mm][Vv][Rr][Aa][Nn][Gg][Ee] ;
MVSORT        : [Mm][Vv][Ss][Oo][Rr][Tt] ;
MVZIP         : [Mm][Vv][Zz][Ii][Pp] ;
NOW           : [Nn][Oo][Ww] ;
RELATIVE_TIME_FN : [Rr][Ee][Ll][Aa][Tt][Ii][Vv][Ee][_][Tt][Ii][Mm][Ee] ;
STRFTIME      : [Ss][Tt][Rr][Ff][Tt][Ii][Mm][Ee] ;
STRPTIME      : [Ss][Tt][Rr][Pp][Tt][Ii][Mm][Ee] ;
TIME_FN       : [Tt][Ii][Mm][Ee] ;
TOSTRING      : [Tt][Oo][Ss][Tt][Rr][Ii][Nn][Gg] ;
PRINTF        : [Pp][Rr][Ii][Nn][Tt][Ff] ;
MD5           : [Mm][Dd] '5' ;
SHA1          : [Ss][Hh][Aa] '1' ;
SHA256        : [Ss][Hh][Aa] '256' ;
SHA512        : [Ss][Hh][Aa] '512' ;
CIDRMATCH     : [Cc][Ii][Dd][Rr][Mm][Aa][Tt][Cc][Hh] ;
MATCH_FN      : [Mm][Aa][Tt][Cc][Hh] ;
SEARCHMATCH   : [Ss][Ee][Aa][Rr][Cc][Hh][Mm][Aa][Tt][Cc][Hh] ;

// Clause keywords
AS            : [Aa][Ss] ;
BY            : [Bb][Yy] ;
OVER          : [Oo][Vv][Ee][Rr] ;
FROM          : [Ff][Rr][Oo][Mm] ;
OUTPUT        : [Oo][Uu][Tt][Pp][Uu][Tt] ;
OUTPUTNEW     : [Oo][Uu][Tt][Pp][Uu][Tt][Nn][Ee][Ww] ;
DATAMODEL     : [Dd][Aa][Tt][Aa][Mm][Oo][Dd][Ee][Ll] ;
IN            : [Ii][Nn] ;
NOT           : [Nn][Oo][Tt] ;
AND           : [Aa][Nn][Dd] ;
OR            : [Oo][Rr] ;
LIKE          : [Ll][Ii][Kk][Ee] ;

// Option names
SPAN          : [Ss][Pp][Aa][Nn] ;
BINS          : [Bb][Ii][Nn][Ss] ;
MINSPAN       : [Mm][Ii][Nn][Ss][Pp][Aa][Nn] ;
START         : [Ss][Tt][Aa][Rr][Tt] ;
END           : [Ee][Nn][Dd] ;
ALIGNTIME     : [Aa][Ll][Ii][Gg][Nn][Tt][Ii][Mm][Ee] ;
LIMIT         : [Ll][Ii][Mm][Ii][Tt] ;
CONT          : [Cc][Oo][Nn][Tt] ;
USENULL       : [Uu][Ss][Ee][Nn][Uu][Ll][Ll] ;
USEOTHER      : [Uu][Ss][Ee][Oo][Tt][Hh][Ee][Rr] ;
NULLSTR       : [Nn][Uu][Ll][Ll][Ss][Tt][Rr] ;
OTHERSTR      : [Oo][Tt][Hh][Ee][Rr][Ss][Tt][Rr] ;
KEEPEVENTS    : [Kk][Ee][Ee][Pp][Ee][Vv][Ee][Nn][Tt][Ss] ;
KEEPEMPTY     : [Kk][Ee][Ee][Pp][Ee][Mm][Pp][Tt][Yy] ;
CONSECUTIVE   : [Cc][Oo][Nn][Ss][Ee][Cc][Uu][Tt][Ii][Vv][Ee] ;
SORTBY        : [Ss][Oo][Rr][Tt][Bb][Yy] ;
ALLNUM        : [Aa][Ll][Ll][Nn][Uu][Mm] ;
DELIM         : [Dd][Ee][Ll][Ii][Mm] ;
DEDUP_SPLITVALS : [Dd][Ee][Dd][Uu][Pp][_][Ss][Pp][Ll][Ii][Tt][Vv][Aa][Ll][Ss] ;
PARTITIONS    : [Pp][Aa][Rr][Tt][Ii][Tt][Ii][Oo][Nn][Ss] ;
TYPE          : [Tt][Yy][Pp][Ee] ;
USETIME       : [Uu][Ss][Ee][Tt][Ii][Mm][Ee] ;
EARLIER       : [Ee][Aa][Rr][Ll][Ii][Ee][Rr] ;
OVERWRITE     : [Oo][Vv][Ee][Rr][Ww][Rr][Ii][Tt][Ee] ;
INNER         : [Ii][Nn][Nn][Ee][Rr] ;
LEFT          : [Ll][Ee][Ff][Tt] ;
OUTER         : [Oo][Uu][Tt][Ee][Rr] ;
FIELD         : [Ff][Ii][Ee][Ll][Dd] ;
MAX_MATCH     : [Mm][Aa][Xx][_][Mm][Aa][Tt][Cc][Hh] ;
OFFSET_FIELD  : [Oo][Ff][Ff][Ss][Ee][Tt][_][Ff][Ii][Ee][Ll][Dd] ;
CURRENT       : [Cc][Uu][Rr][Rr][Ee][Nn][Tt] ;
WINDOW        : [Ww][Ii][Nn][Dd][Oo][Ww] ;
GLOBAL        : [Gg][Ll][Oo][Bb][Aa][Ll] ;
RESET_ON_CHANGE : [Rr][Ee][Ss][Ee][Tt][_][Oo][Nn][_][Cc][Hh][Aa][Nn][Gg][Ee] ;
RESET_BEFORE  : [Rr][Ee][Ss][Ee][Tt][_][Bb][Ee][Ff][Oo][Rr][Ee] ;
RESET_AFTER   : [Rr][Ee][Ss][Ee][Tt][_][Aa][Ff][Tt][Ee][Rr] ;
TIME_WINDOW   : [Tt][Ii][Mm][Ee][_][Ww][Ii][Nn][Dd][Oo][Ww] ;
PARTIAL       : [Pp][Aa][Rr][Tt][Ii][Aa][Ll] ;
FIX_EMPTY     : [Ff][Ii][Xx][_][Ee][Mm][Pp][Tt][Yy] ;
MAXSPAN       : [Mm][Aa][Xx][Ss][Pp][Aa][Nn] ;
MAXPAUSE      : [Mm][Aa][Xx][Pp][Aa][Uu][Ss][Ee] ;
MAXEVENTS     : [Mm][Aa][Xx][Ee][Vv][Ee][Nn][Tt][Ss] ;
KEEPORPHANS   : [Kk][Ee][Ee][Pp][Oo][Rr][Pp][Hh][Aa][Nn][Ss] ;
MVLIST        : [Mm][Vv][Ll][Ii][Ss][Tt] ;
STARTSWITH    : [Ss][Tt][Aa][Rr][Tt][Ss][Ww][Ii][Tt][Hh] ;
ENDSWITH      : [Ee][Nn][Dd][Ss][Ww][Ii][Tt][Hh] ;
SUMMARIESONLY : [Ss][Uu][Mm][Mm][Aa][Rr][Ii][Ee][Ss][Oo][Nn][Ll][Yy] ;
ALLOW_OLD_SUMMARIES : [Aa][Ll][Ll][Oo][Ww][_][Oo][Ll][Dd][_][Ss][Uu][Mm][Mm][Aa][Rr][Ii][Ee][Ss] ;
PRESTATS      : [Pp][Rr][Ee][Ss][Tt][Aa][Tt][Ss] ;
LOCAL         : [Ll][Oo][Cc][Aa][Ll] ;
ANNOTATE      : [Aa][Nn][Nn][Oo][Tt][Aa][Tt][Ee] ;
SPLUNK_SERVER : [Ss][Pp][Ll][Uu][Nn][Kk][_][Ss][Ee][Rr][Vv][Ee][Rr] ;
RMORIG        : [Rr][Mm][Oo][Rr][Ii][Gg] ;
CLEAN_KEYS    : [Cc][Ll][Ee][Aa][Nn][_][Kk][Ee][Yy][Ss] ;
KVDELIM       : [Kk][Vv][Dd][Ee][Ll][Ii][Mm] ;
MAXCHARS      : [Mm][Aa][Xx][Cc][Hh][Aa][Rr][Ss] ;
PAIRDELIM     : [Pp][Aa][Ii][Rr][Dd][Ee][Ll][Ii][Mm] ;
SEGMENT       : [Ss][Ee][Gg][Mm][Ee][Nn][Tt] ;
AUTO          : [Aa][Uu][Tt][Oo] ;
CREATE_EMPTY  : [Cc][Rr][Ee][Aa][Tt][Ee][_][Ee][Mm][Pp][Tt][Yy] ;
KEY_FIELD     : [Kk][Ee][Yy][_][Ff][Ii][Ee][Ll][Dd] ;
COUNTFIELD    : [Cc][Oo][Uu][Nn][Tt][Ff][Ii][Ee][Ll][Dd] ;
PERCENTFIELD  : [Pp][Ee][Rr][Cc][Ee][Nn][Tt][Ff][Ii][Ee][Ll][Dd] ;
SHOWPERC      : [Ss][Hh][Oo][Ww][Pp][Ee][Rr][Cc] ;
VALUE         : [Vv][Aa][Ll][Uu][Ee] ;
MEMORY        : [Mm][Ee][Mm][Oo][Rr][Yy] ;
STREAM        : [Ss][Tt][Rr][Ee][Aa][Mm] ;
KEEPLAST      : [Kk][Ee][Ee][Pp][Ll][Aa][Ss][Tt] ;
NULL_KW       : [Nn][Uu][Ll][Ll] ;

// Sort type hints
IP            : [Ii][Pp] ;
NUM           : [Nn][Uu][Mm] ;
STR           : [Ss][Tt][Rr] ;

// Index / search default fields
INDEX         : [Ii][Nn][Dd][Ee][Xx] ;
SOURCE        : [Ss][Oo][Uu][Rr][Cc][Ee] ;
SOURCETYPE    : [Ss][Oo][Uu][Rr][Cc][Ee][Tt][Yy][Pp][Ee] ;
HOST          : [Hh][Oo][Ss][Tt] ;

// Time modifier field names
// EARLIEST and LATEST are already defined above as agg tokens
INDEX_EARLIEST : [Ii][Nn][Dd][Ee][Xx][_][Ee][Aa][Rr][Ll][Ii][Ee][Ss][Tt] ;
INDEX_LATEST   : [Ii][Nn][Dd][Ee][Xx][_][Ll][Aa][Tt][Ee][Ss][Tt] ;

// Boolean
TRUE          : [Tt][Rr][Uu][Ee] ;
FALSE         : [Ff][Aa][Ll][Ss][Ee] ;

// Time units (single char — must come after longer tokens)
S             : 's' ;
M             : 'm' ;
H             : 'h' ;
D             : 'd' ;
W             : 'w' ;
Q             : 'q' ;
Y             : 'y' ;
SEC           : 'sec' ;
SECS          : 'secs' ;
SECOND        : 'second' ;
SECONDS       : 'seconds' ;
// MIN already defined above as agg token — reused here for time unit
MINS          : 'mins' ;
MINUTE        : 'minute' ;
MINUTES       : 'minutes' ;
HR            : 'hr' ;
HRS           : 'hrs' ;
HOUR          : 'hour' ;
HOURS         : 'hours' ;
DAY           : 'day' ;
DAYS          : 'days' ;
WEEK          : 'week' ;
WEEKS         : 'weeks' ;
MON           : 'mon' ;
MONTH         : 'month' ;
MONTHS        : 'months' ;
QTR           : 'qtr' ;
QTRS          : 'qtrs' ;
QUARTER       : 'quarter' ;
QUARTERS      : 'quarters' ;
YR            : 'yr' ;
YRS           : 'yrs' ;
YEAR          : 'year' ;
YEARS         : 'years' ;

// ─────────────────────────────────────────────
//  OPERATORS
// ─────────────────────────────────────────────

EQ            : '=' ;
NEQ           : '!=' ;
LT            : '<' ;
GT            : '>' ;
LTE           : '<=' ;
GTE           : '>=' ;
MATCH_REGEX   : '=~' ;
PLUS          : '+' ;
MINUS         : '-' ;
STAR          : '*' ;
SLASH         : '/' ;
PERCENT       : '%' ;
DOT           : '.' ;
COMMA         : ',' ;
PIPE          : '|' ;
LPAREN        : '(' ;
RPAREN        : ')' ;
LBRACKET      : '[' ;
RBRACKET      : ']' ;
BACKTICK      : '`' ;

// ─────────────────────────────────────────────
//  LITERALS
// ─────────────────────────────────────────────

// CIDR notation: 192.168.0.0/16, 10.0.0.0/8
// Must come before SLASH and IP_LITERAL to capture IP/prefix as one token
CIDR_LITERAL
    : [0-9]+ ('.' [0-9]+)+ '/' [0-9]+
    ;

// Bare IPv4 address: 192.168.0.0, 10.0.0.1 (no CIDR mask)
// Requires exactly 4 octets (3 dots) to avoid consuming floats like 3.14
IP_LITERAL
    : [0-9]+ '.' [0-9]+ '.' [0-9]+ '.' [0-9]+
    ;

// Dotted field names: Network_Traffic.src_ip, field.subfield
// Must come before UNQUOTED_TERM (dots removed) and before DOT operator
DOTTED_FIELD
    : [a-zA-Z_] [a-zA-Z0-9_]* ('.' [a-zA-Z_] [a-zA-Z0-9_]*)+
    ;

STRING_LITERAL
    : '"' ( '\\' . | ~[\\"] )* '"'
    | '\'' ( '\\' . | ~[\\'] )* '\''
    ;

RELATIVE_TIME_LITERAL
    : [-+] [0-9]* TIMEUNIT_FRAG ('@' TIMEUNIT_FRAG)? {(lambda c: not (c >= 0 and (chr(c).isalnum() or chr(c) == '_')))(self._input.LA(1))}?   // -1h, +30m, -d, -1d@d
    | [0-9]+ TIMEUNIT_FRAG ('@' TIMEUNIT_FRAG)? {(lambda c: not (c >= 0 and (chr(c).isalnum() or chr(c) == '_')))(self._input.LA(1))}?         // 1h, 30m (no sign)
    | '@' TIMEUNIT_FRAG                                  // @h, @d snap
    | 'now'
    ;

fragment TIMEUNIT_FRAG
    : 'seconds' | 'second' | 'secs' | 'sec' | 's'
    | 'minutes' | 'minute' | 'mins' | 'min'
    | 'hours'   | 'hour'   | 'hrs'  | 'hr'  | 'h'
    | 'days'    | 'day'    | 'd'
    | 'weeks'   | 'week'   | 'w'
    | 'months'  | 'month'  | 'mon'
    | 'quarters'| 'quarter'| 'qtrs' | 'qtr' | 'q'
    | 'years'   | 'year'   | 'yrs'  | 'yr'  | 'y'
    | 'm'
    ;

INT
    : [0-9]+
    ;

FLOAT
    : [0-9]+ '.' [0-9]*
    | '.' [0-9]+
    ;

HEX_INT
    : '0' [xX] [0-9a-fA-F]+
    ;

// Unquoted terms for search expressions (no spaces, may contain wildcards)
// Note: '-' removed from character classes to allow MINUS to tokenize separately
// WILDCARD_TERM: a term containing at least one * or ? wildcard.
// Require at least one non-digit character in the prefix before the first wildcard
// (prevents "1000*100" being greedily matched instead of INT*INT).
// Three forms:
//   (a) prefix with at least one non-digit char: e.g. host*, web*, 10.0.*, _raw*
//   (b) starts with a wildcard directly: e.g. *error, *.log
//   (c) pure-digit prefix only if followed by non-digit chars: e.g. 10.* but not 1000*100
WILDCARD_TERM
    : [a-zA-Z_:@#$^&!~\\] [a-zA-Z0-9_:@#$^&!~\\]* ('*' | '?') [a-zA-Z0-9_:@#$^&!~\\*?]*
    | [0-9]+ [.:@#$^&!~\\] [a-zA-Z0-9_.:@#$^&!~\\]* ('*' | '?') [a-zA-Z0-9_.:@#$^&!~\\*?]*
    | ('*' | '?') [a-zA-Z_:@#$^&!~\\] [a-zA-Z0-9_:@#$^&!~\\*?]*
    | [a-zA-Z0-9_:@#$^&!~\\]* '.' [a-zA-Z0-9_.:@#$^&!~\\]* ('*' | '?') [a-zA-Z0-9_.:@#$^&!~\\*?]*
    ;

UNQUOTED_TERM
    : [a-zA-Z0-9_:@#$^&!~\\]+
    ;

ID
    : [a-zA-Z_] [a-zA-Z0-9_]*
    ;

// ─────────────────────────────────────────────
//  WHITESPACE / COMMENTS
// ─────────────────────────────────────────────

BLOCK_COMMENT : '/*' .*? '*/'      -> skip ;
WS            : [ \t\r\n]+         -> skip ;
