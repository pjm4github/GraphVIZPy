# Generated from GVParser.g4 by ANTLR 4.13.0
# encoding: utf-8
from antlr4 import *
from io import StringIO
import sys
if sys.version_info[1] > 5:
	from typing import TextIO
else:
	from typing.io import TextIO

def serializedATN():
    return [
        4,1,26,159,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,2,6,7,
        6,2,7,7,7,2,8,7,8,2,9,7,9,2,10,7,10,2,11,7,11,2,12,7,12,2,13,7,13,
        2,14,7,14,2,15,7,15,2,16,7,16,1,0,3,0,36,8,0,1,0,1,0,3,0,40,8,0,
        1,0,1,0,1,0,1,0,1,0,1,1,1,1,1,2,1,2,3,2,51,8,2,5,2,53,8,2,10,2,12,
        2,56,9,2,1,3,1,3,1,3,1,3,1,3,1,3,1,3,1,3,3,3,66,8,3,1,4,1,4,1,4,
        1,5,1,5,3,5,73,8,5,1,5,4,5,76,8,5,11,5,12,5,77,1,6,1,6,1,6,1,6,3,
        6,84,8,6,4,6,86,8,6,11,6,12,6,87,1,7,1,7,3,7,92,8,7,1,7,4,7,95,8,
        7,11,7,12,7,96,1,7,3,7,100,8,7,1,8,1,8,1,8,3,8,105,8,8,1,9,1,9,1,
        10,1,10,3,10,111,8,10,1,11,1,11,3,11,115,8,11,1,12,1,12,1,12,1,12,
        3,12,121,8,12,1,13,1,13,3,13,125,8,13,3,13,127,8,13,1,13,1,13,1,
        13,1,13,1,14,1,14,1,14,1,14,3,14,137,8,14,1,15,1,15,5,15,141,8,15,
        10,15,12,15,144,9,15,1,15,1,15,1,16,1,16,1,16,5,16,151,8,16,10,16,
        12,16,154,9,16,1,16,3,16,157,8,16,1,16,0,0,17,0,2,4,6,8,10,12,14,
        16,18,20,22,24,26,28,30,32,0,4,1,0,2,3,2,0,2,2,4,5,1,0,13,14,1,0,
        7,8,168,0,35,1,0,0,0,2,46,1,0,0,0,4,54,1,0,0,0,6,65,1,0,0,0,8,67,
        1,0,0,0,10,75,1,0,0,0,12,85,1,0,0,0,14,91,1,0,0,0,16,101,1,0,0,0,
        18,106,1,0,0,0,20,108,1,0,0,0,22,112,1,0,0,0,24,116,1,0,0,0,26,126,
        1,0,0,0,28,136,1,0,0,0,30,138,1,0,0,0,32,156,1,0,0,0,34,36,5,1,0,
        0,35,34,1,0,0,0,35,36,1,0,0,0,36,37,1,0,0,0,37,39,3,2,1,0,38,40,
        3,28,14,0,39,38,1,0,0,0,39,40,1,0,0,0,40,41,1,0,0,0,41,42,5,9,0,
        0,42,43,3,4,2,0,43,44,5,10,0,0,44,45,5,0,0,1,45,1,1,0,0,0,46,47,
        7,0,0,0,47,3,1,0,0,0,48,50,3,6,3,0,49,51,5,13,0,0,50,49,1,0,0,0,
        50,51,1,0,0,0,51,53,1,0,0,0,52,48,1,0,0,0,53,56,1,0,0,0,54,52,1,
        0,0,0,54,55,1,0,0,0,55,5,1,0,0,0,56,54,1,0,0,0,57,66,3,8,4,0,58,
        66,3,14,7,0,59,66,3,20,10,0,60,66,3,26,13,0,61,62,3,28,14,0,62,63,
        5,16,0,0,63,64,3,28,14,0,64,66,1,0,0,0,65,57,1,0,0,0,65,58,1,0,0,
        0,65,59,1,0,0,0,65,60,1,0,0,0,65,61,1,0,0,0,66,7,1,0,0,0,67,68,7,
        1,0,0,68,69,3,10,5,0,69,9,1,0,0,0,70,72,5,11,0,0,71,73,3,12,6,0,
        72,71,1,0,0,0,72,73,1,0,0,0,73,74,1,0,0,0,74,76,5,12,0,0,75,70,1,
        0,0,0,76,77,1,0,0,0,77,75,1,0,0,0,77,78,1,0,0,0,78,11,1,0,0,0,79,
        80,3,28,14,0,80,81,5,16,0,0,81,83,3,28,14,0,82,84,7,2,0,0,83,82,
        1,0,0,0,83,84,1,0,0,0,84,86,1,0,0,0,85,79,1,0,0,0,86,87,1,0,0,0,
        87,85,1,0,0,0,87,88,1,0,0,0,88,13,1,0,0,0,89,92,3,22,11,0,90,92,
        3,26,13,0,91,89,1,0,0,0,91,90,1,0,0,0,92,94,1,0,0,0,93,95,3,16,8,
        0,94,93,1,0,0,0,95,96,1,0,0,0,96,94,1,0,0,0,96,97,1,0,0,0,97,99,
        1,0,0,0,98,100,3,10,5,0,99,98,1,0,0,0,99,100,1,0,0,0,100,15,1,0,
        0,0,101,104,3,18,9,0,102,105,3,22,11,0,103,105,3,26,13,0,104,102,
        1,0,0,0,104,103,1,0,0,0,105,17,1,0,0,0,106,107,7,3,0,0,107,19,1,
        0,0,0,108,110,3,22,11,0,109,111,3,10,5,0,110,109,1,0,0,0,110,111,
        1,0,0,0,111,21,1,0,0,0,112,114,3,28,14,0,113,115,3,24,12,0,114,113,
        1,0,0,0,114,115,1,0,0,0,115,23,1,0,0,0,116,117,5,15,0,0,117,120,
        3,28,14,0,118,119,5,15,0,0,119,121,3,28,14,0,120,118,1,0,0,0,120,
        121,1,0,0,0,121,25,1,0,0,0,122,124,5,6,0,0,123,125,3,28,14,0,124,
        123,1,0,0,0,124,125,1,0,0,0,125,127,1,0,0,0,126,122,1,0,0,0,126,
        127,1,0,0,0,127,128,1,0,0,0,128,129,5,9,0,0,129,130,3,4,2,0,130,
        131,5,10,0,0,131,27,1,0,0,0,132,137,5,19,0,0,133,137,5,18,0,0,134,
        137,5,17,0,0,135,137,3,30,15,0,136,132,1,0,0,0,136,133,1,0,0,0,136,
        134,1,0,0,0,136,135,1,0,0,0,137,29,1,0,0,0,138,142,5,24,0,0,139,
        141,3,32,16,0,140,139,1,0,0,0,141,144,1,0,0,0,142,140,1,0,0,0,142,
        143,1,0,0,0,143,145,1,0,0,0,144,142,1,0,0,0,145,146,5,25,0,0,146,
        31,1,0,0,0,147,157,5,26,0,0,148,152,5,24,0,0,149,151,3,32,16,0,150,
        149,1,0,0,0,151,154,1,0,0,0,152,150,1,0,0,0,152,153,1,0,0,0,153,
        155,1,0,0,0,154,152,1,0,0,0,155,157,5,25,0,0,156,147,1,0,0,0,156,
        148,1,0,0,0,157,33,1,0,0,0,22,35,39,50,54,65,72,77,83,87,91,96,99,
        104,110,114,120,124,126,136,142,152,156
    ]

class GVParser ( Parser ):

    grammarFileName = "GVParser.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                     "<INVALID>", "<INVALID>", "<INVALID>", "'->'", "'--'", 
                     "'{'", "'}'", "'['", "']'", "';'", "','", "':'", "'='", 
                     "<INVALID>", "<INVALID>", "<INVALID>", "<INVALID>", 
                     "<INVALID>", "<INVALID>", "<INVALID>", "'<'", "'>'" ]

    symbolicNames = [ "<INVALID>", "KW_STRICT", "KW_GRAPH", "KW_DIGRAPH", 
                      "KW_NODE", "KW_EDGE", "KW_SUBGRAPH", "DIRECTED_EDGE", 
                      "UNDIRECTED_EDGE", "LBRACE", "RBRACE", "LBRACK", "RBRACK", 
                      "SEMI", "COMMA", "COLON", "EQUALS", "QUOTED_STRING", 
                      "NUMBER", "ID", "LINE_COMMENT", "BLOCK_COMMENT", "PREPROC_LINE", 
                      "WS", "HTML_OPEN", "HTML_CLOSE", "HTML_TEXT" ]

    RULE_graph = 0
    RULE_graphType = 1
    RULE_stmtList = 2
    RULE_stmt = 3
    RULE_attrStmt = 4
    RULE_attrList = 5
    RULE_aList = 6
    RULE_edgeStmt = 7
    RULE_edgeRhs = 8
    RULE_edgeOp = 9
    RULE_nodeStmt = 10
    RULE_nodeId = 11
    RULE_port = 12
    RULE_subgraph = 13
    RULE_id_ = 14
    RULE_htmlString = 15
    RULE_htmlContent = 16

    ruleNames =  [ "graph", "graphType", "stmtList", "stmt", "attrStmt", 
                   "attrList", "aList", "edgeStmt", "edgeRhs", "edgeOp", 
                   "nodeStmt", "nodeId", "port", "subgraph", "id_", "htmlString", 
                   "htmlContent" ]

    EOF = Token.EOF
    KW_STRICT=1
    KW_GRAPH=2
    KW_DIGRAPH=3
    KW_NODE=4
    KW_EDGE=5
    KW_SUBGRAPH=6
    DIRECTED_EDGE=7
    UNDIRECTED_EDGE=8
    LBRACE=9
    RBRACE=10
    LBRACK=11
    RBRACK=12
    SEMI=13
    COMMA=14
    COLON=15
    EQUALS=16
    QUOTED_STRING=17
    NUMBER=18
    ID=19
    LINE_COMMENT=20
    BLOCK_COMMENT=21
    PREPROC_LINE=22
    WS=23
    HTML_OPEN=24
    HTML_CLOSE=25
    HTML_TEXT=26

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.0")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class GraphContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def graphType(self):
            return self.getTypedRuleContext(GVParser.GraphTypeContext,0)


        def LBRACE(self):
            return self.getToken(GVParser.LBRACE, 0)

        def stmtList(self):
            return self.getTypedRuleContext(GVParser.StmtListContext,0)


        def RBRACE(self):
            return self.getToken(GVParser.RBRACE, 0)

        def EOF(self):
            return self.getToken(GVParser.EOF, 0)

        def KW_STRICT(self):
            return self.getToken(GVParser.KW_STRICT, 0)

        def id_(self):
            return self.getTypedRuleContext(GVParser.Id_Context,0)


        def getRuleIndex(self):
            return GVParser.RULE_graph

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitGraph" ):
                return visitor.visitGraph(self)
            else:
                return visitor.visitChildren(self)




    def graph(self):

        localctx = GVParser.GraphContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_graph)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 35
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==1:
                self.state = 34
                self.match(GVParser.KW_STRICT)


            self.state = 37
            self.graphType()
            self.state = 39
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if (((_la) & ~0x3f) == 0 and ((1 << _la) & 17694720) != 0):
                self.state = 38
                self.id_()


            self.state = 41
            self.match(GVParser.LBRACE)
            self.state = 42
            self.stmtList()
            self.state = 43
            self.match(GVParser.RBRACE)
            self.state = 44
            self.match(GVParser.EOF)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class GraphTypeContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def KW_GRAPH(self):
            return self.getToken(GVParser.KW_GRAPH, 0)

        def KW_DIGRAPH(self):
            return self.getToken(GVParser.KW_DIGRAPH, 0)

        def getRuleIndex(self):
            return GVParser.RULE_graphType

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitGraphType" ):
                return visitor.visitGraphType(self)
            else:
                return visitor.visitChildren(self)




    def graphType(self):

        localctx = GVParser.GraphTypeContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_graphType)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 46
            _la = self._input.LA(1)
            if not(_la==2 or _la==3):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class StmtListContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def stmt(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.StmtContext)
            else:
                return self.getTypedRuleContext(GVParser.StmtContext,i)


        def SEMI(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.SEMI)
            else:
                return self.getToken(GVParser.SEMI, i)

        def getRuleIndex(self):
            return GVParser.RULE_stmtList

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitStmtList" ):
                return visitor.visitStmtList(self)
            else:
                return visitor.visitChildren(self)




    def stmtList(self):

        localctx = GVParser.StmtListContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_stmtList)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 54
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while (((_la) & ~0x3f) == 0 and ((1 << _la) & 17695348) != 0):
                self.state = 48
                self.stmt()
                self.state = 50
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if _la==13:
                    self.state = 49
                    self.match(GVParser.SEMI)


                self.state = 56
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class StmtContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def attrStmt(self):
            return self.getTypedRuleContext(GVParser.AttrStmtContext,0)


        def edgeStmt(self):
            return self.getTypedRuleContext(GVParser.EdgeStmtContext,0)


        def nodeStmt(self):
            return self.getTypedRuleContext(GVParser.NodeStmtContext,0)


        def subgraph(self):
            return self.getTypedRuleContext(GVParser.SubgraphContext,0)


        def id_(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.Id_Context)
            else:
                return self.getTypedRuleContext(GVParser.Id_Context,i)


        def EQUALS(self):
            return self.getToken(GVParser.EQUALS, 0)

        def getRuleIndex(self):
            return GVParser.RULE_stmt

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitStmt" ):
                return visitor.visitStmt(self)
            else:
                return visitor.visitChildren(self)




    def stmt(self):

        localctx = GVParser.StmtContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_stmt)
        try:
            self.state = 65
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,4,self._ctx)
            if la_ == 1:
                self.enterOuterAlt(localctx, 1)
                self.state = 57
                self.attrStmt()
                pass

            elif la_ == 2:
                self.enterOuterAlt(localctx, 2)
                self.state = 58
                self.edgeStmt()
                pass

            elif la_ == 3:
                self.enterOuterAlt(localctx, 3)
                self.state = 59
                self.nodeStmt()
                pass

            elif la_ == 4:
                self.enterOuterAlt(localctx, 4)
                self.state = 60
                self.subgraph()
                pass

            elif la_ == 5:
                self.enterOuterAlt(localctx, 5)
                self.state = 61
                self.id_()
                self.state = 62
                self.match(GVParser.EQUALS)
                self.state = 63
                self.id_()
                pass


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class AttrStmtContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def attrList(self):
            return self.getTypedRuleContext(GVParser.AttrListContext,0)


        def KW_GRAPH(self):
            return self.getToken(GVParser.KW_GRAPH, 0)

        def KW_NODE(self):
            return self.getToken(GVParser.KW_NODE, 0)

        def KW_EDGE(self):
            return self.getToken(GVParser.KW_EDGE, 0)

        def getRuleIndex(self):
            return GVParser.RULE_attrStmt

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitAttrStmt" ):
                return visitor.visitAttrStmt(self)
            else:
                return visitor.visitChildren(self)




    def attrStmt(self):

        localctx = GVParser.AttrStmtContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_attrStmt)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 67
            _la = self._input.LA(1)
            if not((((_la) & ~0x3f) == 0 and ((1 << _la) & 52) != 0)):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
            self.state = 68
            self.attrList()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class AttrListContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def LBRACK(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.LBRACK)
            else:
                return self.getToken(GVParser.LBRACK, i)

        def RBRACK(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.RBRACK)
            else:
                return self.getToken(GVParser.RBRACK, i)

        def aList(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.AListContext)
            else:
                return self.getTypedRuleContext(GVParser.AListContext,i)


        def getRuleIndex(self):
            return GVParser.RULE_attrList

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitAttrList" ):
                return visitor.visitAttrList(self)
            else:
                return visitor.visitChildren(self)




    def attrList(self):

        localctx = GVParser.AttrListContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_attrList)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 75 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 70
                self.match(GVParser.LBRACK)
                self.state = 72
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if (((_la) & ~0x3f) == 0 and ((1 << _la) & 17694720) != 0):
                    self.state = 71
                    self.aList()


                self.state = 74
                self.match(GVParser.RBRACK)
                self.state = 77 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not (_la==11):
                    break

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class AListContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def id_(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.Id_Context)
            else:
                return self.getTypedRuleContext(GVParser.Id_Context,i)


        def EQUALS(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.EQUALS)
            else:
                return self.getToken(GVParser.EQUALS, i)

        def SEMI(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.SEMI)
            else:
                return self.getToken(GVParser.SEMI, i)

        def COMMA(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.COMMA)
            else:
                return self.getToken(GVParser.COMMA, i)

        def getRuleIndex(self):
            return GVParser.RULE_aList

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitAList" ):
                return visitor.visitAList(self)
            else:
                return visitor.visitChildren(self)




    def aList(self):

        localctx = GVParser.AListContext(self, self._ctx, self.state)
        self.enterRule(localctx, 12, self.RULE_aList)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 85 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 79
                self.id_()
                self.state = 80
                self.match(GVParser.EQUALS)
                self.state = 81
                self.id_()
                self.state = 83
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if _la==13 or _la==14:
                    self.state = 82
                    _la = self._input.LA(1)
                    if not(_la==13 or _la==14):
                        self._errHandler.recoverInline(self)
                    else:
                        self._errHandler.reportMatch(self)
                        self.consume()


                self.state = 87 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not ((((_la) & ~0x3f) == 0 and ((1 << _la) & 17694720) != 0)):
                    break

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class EdgeStmtContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def nodeId(self):
            return self.getTypedRuleContext(GVParser.NodeIdContext,0)


        def subgraph(self):
            return self.getTypedRuleContext(GVParser.SubgraphContext,0)


        def edgeRhs(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.EdgeRhsContext)
            else:
                return self.getTypedRuleContext(GVParser.EdgeRhsContext,i)


        def attrList(self):
            return self.getTypedRuleContext(GVParser.AttrListContext,0)


        def getRuleIndex(self):
            return GVParser.RULE_edgeStmt

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitEdgeStmt" ):
                return visitor.visitEdgeStmt(self)
            else:
                return visitor.visitChildren(self)




    def edgeStmt(self):

        localctx = GVParser.EdgeStmtContext(self, self._ctx, self.state)
        self.enterRule(localctx, 14, self.RULE_edgeStmt)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 91
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [17, 18, 19, 24]:
                self.state = 89
                self.nodeId()
                pass
            elif token in [6, 9]:
                self.state = 90
                self.subgraph()
                pass
            else:
                raise NoViableAltException(self)

            self.state = 94 
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while True:
                self.state = 93
                self.edgeRhs()
                self.state = 96 
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if not (_la==7 or _la==8):
                    break

            self.state = 99
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==11:
                self.state = 98
                self.attrList()


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class EdgeRhsContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def edgeOp(self):
            return self.getTypedRuleContext(GVParser.EdgeOpContext,0)


        def nodeId(self):
            return self.getTypedRuleContext(GVParser.NodeIdContext,0)


        def subgraph(self):
            return self.getTypedRuleContext(GVParser.SubgraphContext,0)


        def getRuleIndex(self):
            return GVParser.RULE_edgeRhs

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitEdgeRhs" ):
                return visitor.visitEdgeRhs(self)
            else:
                return visitor.visitChildren(self)




    def edgeRhs(self):

        localctx = GVParser.EdgeRhsContext(self, self._ctx, self.state)
        self.enterRule(localctx, 16, self.RULE_edgeRhs)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 101
            self.edgeOp()
            self.state = 104
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [17, 18, 19, 24]:
                self.state = 102
                self.nodeId()
                pass
            elif token in [6, 9]:
                self.state = 103
                self.subgraph()
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class EdgeOpContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def DIRECTED_EDGE(self):
            return self.getToken(GVParser.DIRECTED_EDGE, 0)

        def UNDIRECTED_EDGE(self):
            return self.getToken(GVParser.UNDIRECTED_EDGE, 0)

        def getRuleIndex(self):
            return GVParser.RULE_edgeOp

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitEdgeOp" ):
                return visitor.visitEdgeOp(self)
            else:
                return visitor.visitChildren(self)




    def edgeOp(self):

        localctx = GVParser.EdgeOpContext(self, self._ctx, self.state)
        self.enterRule(localctx, 18, self.RULE_edgeOp)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 106
            _la = self._input.LA(1)
            if not(_la==7 or _la==8):
                self._errHandler.recoverInline(self)
            else:
                self._errHandler.reportMatch(self)
                self.consume()
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class NodeStmtContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def nodeId(self):
            return self.getTypedRuleContext(GVParser.NodeIdContext,0)


        def attrList(self):
            return self.getTypedRuleContext(GVParser.AttrListContext,0)


        def getRuleIndex(self):
            return GVParser.RULE_nodeStmt

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitNodeStmt" ):
                return visitor.visitNodeStmt(self)
            else:
                return visitor.visitChildren(self)




    def nodeStmt(self):

        localctx = GVParser.NodeStmtContext(self, self._ctx, self.state)
        self.enterRule(localctx, 20, self.RULE_nodeStmt)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 108
            self.nodeId()
            self.state = 110
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==11:
                self.state = 109
                self.attrList()


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class NodeIdContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def id_(self):
            return self.getTypedRuleContext(GVParser.Id_Context,0)


        def port(self):
            return self.getTypedRuleContext(GVParser.PortContext,0)


        def getRuleIndex(self):
            return GVParser.RULE_nodeId

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitNodeId" ):
                return visitor.visitNodeId(self)
            else:
                return visitor.visitChildren(self)




    def nodeId(self):

        localctx = GVParser.NodeIdContext(self, self._ctx, self.state)
        self.enterRule(localctx, 22, self.RULE_nodeId)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 112
            self.id_()
            self.state = 114
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==15:
                self.state = 113
                self.port()


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class PortContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def COLON(self, i:int=None):
            if i is None:
                return self.getTokens(GVParser.COLON)
            else:
                return self.getToken(GVParser.COLON, i)

        def id_(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.Id_Context)
            else:
                return self.getTypedRuleContext(GVParser.Id_Context,i)


        def getRuleIndex(self):
            return GVParser.RULE_port

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitPort" ):
                return visitor.visitPort(self)
            else:
                return visitor.visitChildren(self)




    def port(self):

        localctx = GVParser.PortContext(self, self._ctx, self.state)
        self.enterRule(localctx, 24, self.RULE_port)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 116
            self.match(GVParser.COLON)
            self.state = 117
            self.id_()
            self.state = 120
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==15:
                self.state = 118
                self.match(GVParser.COLON)
                self.state = 119
                self.id_()


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class SubgraphContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def LBRACE(self):
            return self.getToken(GVParser.LBRACE, 0)

        def stmtList(self):
            return self.getTypedRuleContext(GVParser.StmtListContext,0)


        def RBRACE(self):
            return self.getToken(GVParser.RBRACE, 0)

        def KW_SUBGRAPH(self):
            return self.getToken(GVParser.KW_SUBGRAPH, 0)

        def id_(self):
            return self.getTypedRuleContext(GVParser.Id_Context,0)


        def getRuleIndex(self):
            return GVParser.RULE_subgraph

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitSubgraph" ):
                return visitor.visitSubgraph(self)
            else:
                return visitor.visitChildren(self)




    def subgraph(self):

        localctx = GVParser.SubgraphContext(self, self._ctx, self.state)
        self.enterRule(localctx, 26, self.RULE_subgraph)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 126
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            if _la==6:
                self.state = 122
                self.match(GVParser.KW_SUBGRAPH)
                self.state = 124
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if (((_la) & ~0x3f) == 0 and ((1 << _la) & 17694720) != 0):
                    self.state = 123
                    self.id_()




            self.state = 128
            self.match(GVParser.LBRACE)
            self.state = 129
            self.stmtList()
            self.state = 130
            self.match(GVParser.RBRACE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class Id_Context(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def ID(self):
            return self.getToken(GVParser.ID, 0)

        def NUMBER(self):
            return self.getToken(GVParser.NUMBER, 0)

        def QUOTED_STRING(self):
            return self.getToken(GVParser.QUOTED_STRING, 0)

        def htmlString(self):
            return self.getTypedRuleContext(GVParser.HtmlStringContext,0)


        def getRuleIndex(self):
            return GVParser.RULE_id_

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitId_" ):
                return visitor.visitId_(self)
            else:
                return visitor.visitChildren(self)




    def id_(self):

        localctx = GVParser.Id_Context(self, self._ctx, self.state)
        self.enterRule(localctx, 28, self.RULE_id_)
        try:
            self.state = 136
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [19]:
                self.enterOuterAlt(localctx, 1)
                self.state = 132
                self.match(GVParser.ID)
                pass
            elif token in [18]:
                self.enterOuterAlt(localctx, 2)
                self.state = 133
                self.match(GVParser.NUMBER)
                pass
            elif token in [17]:
                self.enterOuterAlt(localctx, 3)
                self.state = 134
                self.match(GVParser.QUOTED_STRING)
                pass
            elif token in [24]:
                self.enterOuterAlt(localctx, 4)
                self.state = 135
                self.htmlString()
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class HtmlStringContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def HTML_OPEN(self):
            return self.getToken(GVParser.HTML_OPEN, 0)

        def HTML_CLOSE(self):
            return self.getToken(GVParser.HTML_CLOSE, 0)

        def htmlContent(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.HtmlContentContext)
            else:
                return self.getTypedRuleContext(GVParser.HtmlContentContext,i)


        def getRuleIndex(self):
            return GVParser.RULE_htmlString

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitHtmlString" ):
                return visitor.visitHtmlString(self)
            else:
                return visitor.visitChildren(self)




    def htmlString(self):

        localctx = GVParser.HtmlStringContext(self, self._ctx, self.state)
        self.enterRule(localctx, 30, self.RULE_htmlString)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 138
            self.match(GVParser.HTML_OPEN)
            self.state = 142
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==24 or _la==26:
                self.state = 139
                self.htmlContent()
                self.state = 144
                self._errHandler.sync(self)
                _la = self._input.LA(1)

            self.state = 145
            self.match(GVParser.HTML_CLOSE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class HtmlContentContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def HTML_TEXT(self):
            return self.getToken(GVParser.HTML_TEXT, 0)

        def HTML_OPEN(self):
            return self.getToken(GVParser.HTML_OPEN, 0)

        def HTML_CLOSE(self):
            return self.getToken(GVParser.HTML_CLOSE, 0)

        def htmlContent(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(GVParser.HtmlContentContext)
            else:
                return self.getTypedRuleContext(GVParser.HtmlContentContext,i)


        def getRuleIndex(self):
            return GVParser.RULE_htmlContent

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitHtmlContent" ):
                return visitor.visitHtmlContent(self)
            else:
                return visitor.visitChildren(self)




    def htmlContent(self):

        localctx = GVParser.HtmlContentContext(self, self._ctx, self.state)
        self.enterRule(localctx, 32, self.RULE_htmlContent)
        self._la = 0 # Token type
        try:
            self.state = 156
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [26]:
                self.enterOuterAlt(localctx, 1)
                self.state = 147
                self.match(GVParser.HTML_TEXT)
                pass
            elif token in [24]:
                self.enterOuterAlt(localctx, 2)
                self.state = 148
                self.match(GVParser.HTML_OPEN)
                self.state = 152
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                while _la==24 or _la==26:
                    self.state = 149
                    self.htmlContent()
                    self.state = 154
                    self._errHandler.sync(self)
                    _la = self._input.LA(1)

                self.state = 155
                self.match(GVParser.HTML_CLOSE)
                pass
            else:
                raise NoViableAltException(self)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx





