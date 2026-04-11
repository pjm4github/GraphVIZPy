// RecordLexer.g4 — ANTLR4 lexer grammar for Graphviz record node labels.
// Parses labels like: {name|In|{<Out0>|<Out1>}}
//
// Based on C lib/common/shapes.c parse_reclbl() which processes record
// labels character by character with modes for ports, text, and nesting.

lexer grammar RecordLexer;

// ── Structural tokens ───────────────────────────
LBRACE    : '{' ;
RBRACE    : '}' ;
PIPE      : '|' ;
PORT_OPEN : '<' ;
PORT_CLOSE: '>' ;

// ── Escaped characters (must precede TEXT) ──────
// C parse_reclbl: \{  \}  \|  \\ are literal escapes
// \n \l \r are line break directives
ESCAPE    : '\\' [{}|\\nlr] ;

// ── Text content (anything not structural) ──────
// Matches one or more characters that aren't structural tokens.
// Includes spaces and printable characters.
TEXT      : ~[{}|<>\\]+ ;
