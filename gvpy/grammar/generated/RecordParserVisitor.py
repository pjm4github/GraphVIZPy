# Generated from C:\Users\pmora\OneDrive\Documents\Git\GitHub\GraphvizPy\gvpy\grammar\RecordParser.g4 by ANTLR 4.13.0
from antlr4 import *
if "." in __name__:
    from .RecordParser import RecordParser
else:
    from RecordParser import RecordParser

# This class defines a complete generic visitor for a parse tree produced by RecordParser.

class RecordParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by RecordParser#recordLabel.
    def visitRecordLabel(self, ctx:RecordParser.RecordLabelContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by RecordParser#fieldList.
    def visitFieldList(self, ctx:RecordParser.FieldListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by RecordParser#field.
    def visitField(self, ctx:RecordParser.FieldContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by RecordParser#port.
    def visitPort(self, ctx:RecordParser.PortContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by RecordParser#portName.
    def visitPortName(self, ctx:RecordParser.PortNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by RecordParser#textContent.
    def visitTextContent(self, ctx:RecordParser.TextContentContext):
        return self.visitChildren(ctx)



del RecordParser