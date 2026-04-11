// RecordParser.g4 — ANTLR4 parser grammar for Graphviz record node labels.
// Based on C lib/common/shapes.c parse_reclbl().
//
// Record labels have the form:
//   {name|{<In0>|<In1>}|fmap|{<Out0>}}
//
// Grammar:
//   label      ::= '{' fieldList '}'     // top-level record
//                 | fieldList             // bare field list
//   fieldList  ::= field ('|' field)*
//   field      ::= '{' fieldList '}'     // nested sub-record
//                 | port? textContent*    // leaf field with optional port
//   port       ::= '<' portName '>'
//   portName   ::= TEXT | ESCAPE         // port identifier text
//   textContent::= TEXT | ESCAPE         // display text

parser grammar RecordParser;

options { tokenVocab = RecordLexer; }

// ── Entry point ─────────────────────────────────
// A record label may be wrapped in outer braces or bare.
recordLabel
    : LBRACE fieldList RBRACE       // {field|field|...}
    | fieldList                      // field|field|...
    ;

// ── Field list (separated by |) ─────────────────
fieldList
    : field ( PIPE field )*
    ;

// ── Single field ────────────────────────────────
// A field is either:
//   - A nested sub-record: { fieldList }
//   - A leaf field: optional <portName> followed by text
field
    : LBRACE fieldList RBRACE       // nested sub-record
    | port? textContent*            // leaf field (port + text)
    ;

// ── Port identifier ─────────────────────────────
// <portName> — angle-bracket delimited port name
port
    : PORT_OPEN portName PORT_CLOSE
    ;

portName
    : ( TEXT | ESCAPE )*
    ;

// ── Text content ────────────────────────────────
textContent
    : TEXT
    | ESCAPE
    ;
