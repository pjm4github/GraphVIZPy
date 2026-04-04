# Generated from DOTParser.g4 by ANTLR 4.13.0
from antlr4 import *
if "." in __name__:
    from .DOTParser import DOTParser
else:
    from DOTParser import DOTParser

# This class defines a complete generic visitor for a parse tree produced by DOTParser.

class DOTParserVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by DOTParser#graph.
    def visitGraph(self, ctx:DOTParser.GraphContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#graphType.
    def visitGraphType(self, ctx:DOTParser.GraphTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#stmtList.
    def visitStmtList(self, ctx:DOTParser.StmtListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#stmt.
    def visitStmt(self, ctx:DOTParser.StmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#attrStmt.
    def visitAttrStmt(self, ctx:DOTParser.AttrStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#attrList.
    def visitAttrList(self, ctx:DOTParser.AttrListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#aList.
    def visitAList(self, ctx:DOTParser.AListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#edgeStmt.
    def visitEdgeStmt(self, ctx:DOTParser.EdgeStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#edgeRhs.
    def visitEdgeRhs(self, ctx:DOTParser.EdgeRhsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#edgeOp.
    def visitEdgeOp(self, ctx:DOTParser.EdgeOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#nodeStmt.
    def visitNodeStmt(self, ctx:DOTParser.NodeStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#nodeId.
    def visitNodeId(self, ctx:DOTParser.NodeIdContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#port.
    def visitPort(self, ctx:DOTParser.PortContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#subgraph.
    def visitSubgraph(self, ctx:DOTParser.SubgraphContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#id_.
    def visitId_(self, ctx:DOTParser.Id_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#htmlString.
    def visitHtmlString(self, ctx:DOTParser.HtmlStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by DOTParser#htmlContent.
    def visitHtmlContent(self, ctx:DOTParser.HtmlContentContext):
        return self.visitChildren(ctx)



del DOTParser