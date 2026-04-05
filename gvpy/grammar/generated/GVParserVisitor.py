# Generated from GVParser.g4 by ANTLR 4.13.0
from antlr4 import *
if "." in __name__:
    from .GVParser import GVParser
else:
    from GVParser import GVParser

# This class defines a complete generic visitor for a parse tree produced by GVParser.

class GVParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by GVParser#graph.
    def visitGraph(self, ctx:GVParser.GraphContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#graphType.
    def visitGraphType(self, ctx:GVParser.GraphTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#stmtList.
    def visitStmtList(self, ctx:GVParser.StmtListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#stmt.
    def visitStmt(self, ctx:GVParser.StmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#attrStmt.
    def visitAttrStmt(self, ctx:GVParser.AttrStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#attrList.
    def visitAttrList(self, ctx:GVParser.AttrListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#aList.
    def visitAList(self, ctx:GVParser.AListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#edgeStmt.
    def visitEdgeStmt(self, ctx:GVParser.EdgeStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#edgeRhs.
    def visitEdgeRhs(self, ctx:GVParser.EdgeRhsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#edgeOp.
    def visitEdgeOp(self, ctx:GVParser.EdgeOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#nodeStmt.
    def visitNodeStmt(self, ctx:GVParser.NodeStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#nodeId.
    def visitNodeId(self, ctx:GVParser.NodeIdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#port.
    def visitPort(self, ctx:GVParser.PortContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#subgraph.
    def visitSubgraph(self, ctx:GVParser.SubgraphContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#id_.
    def visitId_(self, ctx:GVParser.Id_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#htmlString.
    def visitHtmlString(self, ctx:GVParser.HtmlStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by GVParser#htmlContent.
    def visitHtmlContent(self, ctx:GVParser.HtmlContentContext):
        return self.visitChildren(ctx)



del GVParser