// DOTParser.g4 — ANTLR4 parser grammar for the Graphviz DOT language.
// Based on https://graphviz.org/doc/info/lang.html and the original
// Graphviz grammar.y.

parser grammar DOTParser;

options { tokenVocab = DOTLexer; }

// ── Entry point ──────────────────────────────────
graph
    : KW_STRICT? graphType id_? LBRACE stmtList RBRACE EOF
    ;

graphType
    : KW_GRAPH
    | KW_DIGRAPH
    ;

stmtList
    : ( stmt SEMI? )*
    ;

stmt
    : attrStmt
    | edgeStmt
    | nodeStmt
    | subgraph
    | id_ EQUALS id_       // graph-level attribute: rankdir=LR
    ;

// ── Attribute statements ─────────────────────────
attrStmt
    : ( KW_GRAPH | KW_NODE | KW_EDGE ) attrList
    ;

attrList
    : ( LBRACK aList? RBRACK )+
    ;

aList
    : ( id_ EQUALS id_ ( SEMI | COMMA )? )+
    ;

// ── Edge statement ───────────────────────────────
edgeStmt
    : ( nodeId | subgraph ) edgeRhs+ attrList?
    ;

edgeRhs
    : edgeOp ( nodeId | subgraph )
    ;

edgeOp
    : DIRECTED_EDGE
    | UNDIRECTED_EDGE
    ;

// ── Node statement ───────────────────────────────
nodeStmt
    : nodeId attrList?
    ;

nodeId
    : id_ port?
    ;

port
    : COLON id_ ( COLON id_ )?
    ;

// ── Subgraph ─────────────────────────────────────
subgraph
    : ( KW_SUBGRAPH id_? )? LBRACE stmtList RBRACE
    ;

// ── Identifier (all four DOT ID forms) ───────────
id_
    : ID
    | NUMBER
    | QUOTED_STRING
    | htmlString
    ;

// HTML string reconstructed from mode tokens
htmlString
    : HTML_OPEN htmlContent* HTML_CLOSE
    ;

htmlContent
    : HTML_TEXT
    | HTML_OPEN htmlContent* HTML_CLOSE
    ;
