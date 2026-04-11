# Generated from C:\Users\pmora\OneDrive\Documents\Git\GitHub\GraphvizPy\gvpy\grammar\RecordParser.g4 by ANTLR 4.13.0
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
        4,1,7,55,2,0,7,0,2,1,7,1,2,2,7,2,2,3,7,3,2,4,7,4,2,5,7,5,1,0,1,0,
        1,0,1,0,1,0,3,0,18,8,0,1,1,1,1,1,1,5,1,23,8,1,10,1,12,1,26,9,1,1,
        2,1,2,1,2,1,2,1,2,3,2,33,8,2,1,2,5,2,36,8,2,10,2,12,2,39,9,2,3,2,
        41,8,2,1,3,1,3,1,3,1,3,1,4,5,4,48,8,4,10,4,12,4,51,9,4,1,5,1,5,1,
        5,0,0,6,0,2,4,6,8,10,0,1,1,0,6,7,54,0,17,1,0,0,0,2,19,1,0,0,0,4,
        40,1,0,0,0,6,42,1,0,0,0,8,49,1,0,0,0,10,52,1,0,0,0,12,13,5,1,0,0,
        13,14,3,2,1,0,14,15,5,2,0,0,15,18,1,0,0,0,16,18,3,2,1,0,17,12,1,
        0,0,0,17,16,1,0,0,0,18,1,1,0,0,0,19,24,3,4,2,0,20,21,5,3,0,0,21,
        23,3,4,2,0,22,20,1,0,0,0,23,26,1,0,0,0,24,22,1,0,0,0,24,25,1,0,0,
        0,25,3,1,0,0,0,26,24,1,0,0,0,27,28,5,1,0,0,28,29,3,2,1,0,29,30,5,
        2,0,0,30,41,1,0,0,0,31,33,3,6,3,0,32,31,1,0,0,0,32,33,1,0,0,0,33,
        37,1,0,0,0,34,36,3,10,5,0,35,34,1,0,0,0,36,39,1,0,0,0,37,35,1,0,
        0,0,37,38,1,0,0,0,38,41,1,0,0,0,39,37,1,0,0,0,40,27,1,0,0,0,40,32,
        1,0,0,0,41,5,1,0,0,0,42,43,5,4,0,0,43,44,3,8,4,0,44,45,5,5,0,0,45,
        7,1,0,0,0,46,48,7,0,0,0,47,46,1,0,0,0,48,51,1,0,0,0,49,47,1,0,0,
        0,49,50,1,0,0,0,50,9,1,0,0,0,51,49,1,0,0,0,52,53,7,0,0,0,53,11,1,
        0,0,0,6,17,24,32,37,40,49
    ]

class RecordParser ( Parser ):

    grammarFileName = "RecordParser.g4"

    atn = ATNDeserializer().deserialize(serializedATN())

    decisionsToDFA = [ DFA(ds, i) for i, ds in enumerate(atn.decisionToState) ]

    sharedContextCache = PredictionContextCache()

    literalNames = [ "<INVALID>", "'{'", "'}'", "'|'", "'<'", "'>'" ]

    symbolicNames = [ "<INVALID>", "LBRACE", "RBRACE", "PIPE", "PORT_OPEN", 
                      "PORT_CLOSE", "ESCAPE", "TEXT" ]

    RULE_recordLabel = 0
    RULE_fieldList = 1
    RULE_field = 2
    RULE_port = 3
    RULE_portName = 4
    RULE_textContent = 5

    ruleNames =  [ "recordLabel", "fieldList", "field", "port", "portName", 
                   "textContent" ]

    EOF = Token.EOF
    LBRACE=1
    RBRACE=2
    PIPE=3
    PORT_OPEN=4
    PORT_CLOSE=5
    ESCAPE=6
    TEXT=7

    def __init__(self, input:TokenStream, output:TextIO = sys.stdout):
        super().__init__(input, output)
        self.checkVersion("4.13.0")
        self._interp = ParserATNSimulator(self, self.atn, self.decisionsToDFA, self.sharedContextCache)
        self._predicates = None




    class RecordLabelContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def LBRACE(self):
            return self.getToken(RecordParser.LBRACE, 0)

        def fieldList(self):
            return self.getTypedRuleContext(RecordParser.FieldListContext,0)


        def RBRACE(self):
            return self.getToken(RecordParser.RBRACE, 0)

        def getRuleIndex(self):
            return RecordParser.RULE_recordLabel

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitRecordLabel" ):
                return visitor.visitRecordLabel(self)
            else:
                return visitor.visitChildren(self)




    def recordLabel(self):

        localctx = RecordParser.RecordLabelContext(self, self._ctx, self.state)
        self.enterRule(localctx, 0, self.RULE_recordLabel)
        try:
            self.state = 17
            self._errHandler.sync(self)
            la_ = self._interp.adaptivePredict(self._input,0,self._ctx)
            if la_ == 1:
                self.enterOuterAlt(localctx, 1)
                self.state = 12
                self.match(RecordParser.LBRACE)
                self.state = 13
                self.fieldList()
                self.state = 14
                self.match(RecordParser.RBRACE)
                pass

            elif la_ == 2:
                self.enterOuterAlt(localctx, 2)
                self.state = 16
                self.fieldList()
                pass


        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class FieldListContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def field(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(RecordParser.FieldContext)
            else:
                return self.getTypedRuleContext(RecordParser.FieldContext,i)


        def PIPE(self, i:int=None):
            if i is None:
                return self.getTokens(RecordParser.PIPE)
            else:
                return self.getToken(RecordParser.PIPE, i)

        def getRuleIndex(self):
            return RecordParser.RULE_fieldList

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitFieldList" ):
                return visitor.visitFieldList(self)
            else:
                return visitor.visitChildren(self)




    def fieldList(self):

        localctx = RecordParser.FieldListContext(self, self._ctx, self.state)
        self.enterRule(localctx, 2, self.RULE_fieldList)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 19
            self.field()
            self.state = 24
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==3:
                self.state = 20
                self.match(RecordParser.PIPE)
                self.state = 21
                self.field()
                self.state = 26
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class FieldContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def LBRACE(self):
            return self.getToken(RecordParser.LBRACE, 0)

        def fieldList(self):
            return self.getTypedRuleContext(RecordParser.FieldListContext,0)


        def RBRACE(self):
            return self.getToken(RecordParser.RBRACE, 0)

        def port(self):
            return self.getTypedRuleContext(RecordParser.PortContext,0)


        def textContent(self, i:int=None):
            if i is None:
                return self.getTypedRuleContexts(RecordParser.TextContentContext)
            else:
                return self.getTypedRuleContext(RecordParser.TextContentContext,i)


        def getRuleIndex(self):
            return RecordParser.RULE_field

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitField" ):
                return visitor.visitField(self)
            else:
                return visitor.visitChildren(self)




    def field(self):

        localctx = RecordParser.FieldContext(self, self._ctx, self.state)
        self.enterRule(localctx, 4, self.RULE_field)
        self._la = 0 # Token type
        try:
            self.state = 40
            self._errHandler.sync(self)
            token = self._input.LA(1)
            if token in [1]:
                self.enterOuterAlt(localctx, 1)
                self.state = 27
                self.match(RecordParser.LBRACE)
                self.state = 28
                self.fieldList()
                self.state = 29
                self.match(RecordParser.RBRACE)
                pass
            elif token in [-1, 2, 3, 4, 6, 7]:
                self.enterOuterAlt(localctx, 2)
                self.state = 32
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                if _la==4:
                    self.state = 31
                    self.port()


                self.state = 37
                self._errHandler.sync(self)
                _la = self._input.LA(1)
                while _la==6 or _la==7:
                    self.state = 34
                    self.textContent()
                    self.state = 39
                    self._errHandler.sync(self)
                    _la = self._input.LA(1)

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


    class PortContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def PORT_OPEN(self):
            return self.getToken(RecordParser.PORT_OPEN, 0)

        def portName(self):
            return self.getTypedRuleContext(RecordParser.PortNameContext,0)


        def PORT_CLOSE(self):
            return self.getToken(RecordParser.PORT_CLOSE, 0)

        def getRuleIndex(self):
            return RecordParser.RULE_port

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitPort" ):
                return visitor.visitPort(self)
            else:
                return visitor.visitChildren(self)




    def port(self):

        localctx = RecordParser.PortContext(self, self._ctx, self.state)
        self.enterRule(localctx, 6, self.RULE_port)
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 42
            self.match(RecordParser.PORT_OPEN)
            self.state = 43
            self.portName()
            self.state = 44
            self.match(RecordParser.PORT_CLOSE)
        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class PortNameContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def TEXT(self, i:int=None):
            if i is None:
                return self.getTokens(RecordParser.TEXT)
            else:
                return self.getToken(RecordParser.TEXT, i)

        def ESCAPE(self, i:int=None):
            if i is None:
                return self.getTokens(RecordParser.ESCAPE)
            else:
                return self.getToken(RecordParser.ESCAPE, i)

        def getRuleIndex(self):
            return RecordParser.RULE_portName

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitPortName" ):
                return visitor.visitPortName(self)
            else:
                return visitor.visitChildren(self)




    def portName(self):

        localctx = RecordParser.PortNameContext(self, self._ctx, self.state)
        self.enterRule(localctx, 8, self.RULE_portName)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 49
            self._errHandler.sync(self)
            _la = self._input.LA(1)
            while _la==6 or _la==7:
                self.state = 46
                _la = self._input.LA(1)
                if not(_la==6 or _la==7):
                    self._errHandler.recoverInline(self)
                else:
                    self._errHandler.reportMatch(self)
                    self.consume()
                self.state = 51
                self._errHandler.sync(self)
                _la = self._input.LA(1)

        except RecognitionException as re:
            localctx.exception = re
            self._errHandler.reportError(self, re)
            self._errHandler.recover(self, re)
        finally:
            self.exitRule()
        return localctx


    class TextContentContext(ParserRuleContext):
        __slots__ = 'parser'

        def __init__(self, parser, parent:ParserRuleContext=None, invokingState:int=-1):
            super().__init__(parent, invokingState)
            self.parser = parser

        def TEXT(self):
            return self.getToken(RecordParser.TEXT, 0)

        def ESCAPE(self):
            return self.getToken(RecordParser.ESCAPE, 0)

        def getRuleIndex(self):
            return RecordParser.RULE_textContent

        def accept(self, visitor:ParseTreeVisitor):
            if hasattr( visitor, "visitTextContent" ):
                return visitor.visitTextContent(self)
            else:
                return visitor.visitChildren(self)




    def textContent(self):

        localctx = RecordParser.TextContentContext(self, self._ctx, self.state)
        self.enterRule(localctx, 10, self.RULE_textContent)
        self._la = 0 # Token type
        try:
            self.enterOuterAlt(localctx, 1)
            self.state = 52
            _la = self._input.LA(1)
            if not(_la==6 or _la==7):
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





