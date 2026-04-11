# Generated from C:\Users\pmora\OneDrive\Documents\Git\GitHub\GraphvizPy\gvpy\grammar\RecordLexer.g4 by ANTLR 4.13.0
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
    from typing import TextIO
else:
    from typing.io import TextIO


def serializedATN():
    return [
        4,0,7,33,6,-1,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,
        6,7,6,1,0,1,0,1,1,1,1,1,2,1,2,1,3,1,3,1,4,1,4,1,5,1,5,1,5,1,6,4,
        6,30,8,6,11,6,12,6,31,0,0,7,1,1,3,2,5,3,7,4,9,5,11,6,13,7,1,0,2,
        5,0,92,92,108,108,110,110,114,114,123,125,4,0,60,60,62,62,92,92,
        123,125,33,0,1,1,0,0,0,0,3,1,0,0,0,0,5,1,0,0,0,0,7,1,0,0,0,0,9,1,
        0,0,0,0,11,1,0,0,0,0,13,1,0,0,0,1,15,1,0,0,0,3,17,1,0,0,0,5,19,1,
        0,0,0,7,21,1,0,0,0,9,23,1,0,0,0,11,25,1,0,0,0,13,29,1,0,0,0,15,16,
        5,123,0,0,16,2,1,0,0,0,17,18,5,125,0,0,18,4,1,0,0,0,19,20,5,124,
        0,0,20,6,1,0,0,0,21,22,5,60,0,0,22,8,1,0,0,0,23,24,5,62,0,0,24,10,
        1,0,0,0,25,26,5,92,0,0,26,27,7,0,0,0,27,12,1,0,0,0,28,30,8,1,0,0,
        29,28,1,0,0,0,30,31,1,0,0,0,31,29,1,0,0,0,31,32,1,0,0,0,32,14,1,
        0,0,0,2,0,31,0
    ]

class RecordLexer(Lexer):

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    LBRACE = 1
    RBRACE = 2
    PIPE = 3
    PORT_OPEN = 4
    PORT_CLOSE = 5
    ESCAPE = 6
    TEXT = 7

    channelNames = [ u"DEFAULT_TOKEN_CHANNEL", u"HIDDEN" ]

    modeNames = [ "DEFAULT_MODE" ]

    literalNames = [ "<INVALID>",
            "'{'", "'}'", "'|'", "'<'", "'>'" ]

    symbolicNames = [ "<INVALID>",
            "LBRACE", "RBRACE", "PIPE", "PORT_OPEN", "PORT_CLOSE", "ESCAPE", 
            "TEXT" ]

    ruleNames = [ "LBRACE", "RBRACE", "PIPE", "PORT_OPEN", "PORT_CLOSE", 
                  "ESCAPE", "TEXT" ]

    grammarFileName = "RecordLexer.g4"

    def __init__(self, input=None, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.0")
        self._interp = LexerATNSimulator(self, self.atn, self.decisionsToDFA, PredictionContextCache())
        self._actions = None
        self._predicates = None


