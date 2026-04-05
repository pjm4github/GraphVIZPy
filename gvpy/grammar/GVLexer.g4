// GVLexer.g4 — ANTLR4 lexer grammar for the Graphviz DOT language.
// Based on https://graphviz.org/doc/info/lang.html and the original
// Graphviz scan.l lexer.
//
// Renamed from DOTLexer.g4 to GVLexer.g4 as part of the GraphvizPy
// (gvpy) package restructuring.

lexer grammar GVLexer;

// ── Case-insensitive keyword fragments ───────────
fragment A: [aA]; fragment B: [bB]; fragment C: [cC]; fragment D: [dD];
fragment E: [eE]; fragment F: [fF]; fragment G: [gG]; fragment H: [hH];
fragment I: [iI]; fragment K: [kK]; fragment L: [lL]; fragment N: [nN];
fragment O: [oO]; fragment P: [pP]; fragment R: [rR]; fragment S: [sS];
fragment T: [tT]; fragment U: [uU]; fragment X: [xX]; fragment Y: [yY];
fragment W: [wW];

// ── Keywords (case-insensitive) ──────────────────
KW_STRICT   : S T R I C T ;
KW_GRAPH    : G R A P H ;
KW_DIGRAPH  : D I G R A P H ;
KW_NODE     : N O D E ;
KW_EDGE     : E D G E ;
KW_SUBGRAPH : S U B G R A P H ;

// ── Edge operators (must precede single-char rules) ──
DIRECTED_EDGE   : '->' ;
UNDIRECTED_EDGE : '--' ;

// ── Punctuation ──────────────────────────────────
LBRACE   : '{' ;
RBRACE   : '}' ;
LBRACK   : '[' ;
RBRACK   : ']' ;
SEMI     : ';' ;
COMMA    : ',' ;
COLON    : ':' ;
EQUALS   : '=' ;

// ── String literals ──────────────────────────────
QUOTED_STRING : '"' ( '\\' . | ~[\\"] )* '"' ;

// HTML strings use a mode to track nesting
HTML_OPEN_OUTER : '<' -> pushMode(HTML_MODE), type(HTML_OPEN) ;

// ── Numeric literal (before ID so -1.5 is not minus+ID) ──
NUMBER : '-'? ( '.' [0-9]+ | [0-9]+ ( '.' [0-9]* )? ) ;

// ── Bare identifier ──────────────────────────────
ID : [a-zA-Z_\u0080-\u00FF] [a-zA-Z0-9_\u0080-\u00FF]* ;

// ── Comments → hidden channel ────────────────────
LINE_COMMENT  : '//' ~[\r\n]* -> channel(HIDDEN) ;
BLOCK_COMMENT : '/*' .*? '*/' -> channel(HIDDEN) ;
PREPROC_LINE  : '#' ~[\r\n]*  -> channel(HIDDEN) ;

// ── Whitespace → skip ────────────────────────────
WS : [ \t\r\n]+ -> skip ;

// ═══════════════════════════════════════════════════
// HTML_MODE: accumulates text inside <...> with nesting
// ═══════════════════════════════════════════════════
mode HTML_MODE;
HTML_OPEN  : '<'  -> pushMode(HTML_MODE) ;
HTML_CLOSE : '>'  -> popMode ;
HTML_TEXT  : ~[<>]+ ;
