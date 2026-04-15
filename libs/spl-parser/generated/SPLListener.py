# Generated from SPL.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .SPLParser import SPLParser
else:
    from SPLParser import SPLParser

# This class defines a complete listener for a parse tree produced by SPLParser.
class SPLListener(ParseTreeListener):

    # Enter a parse tree produced by SPLParser#spl.
    def enterSpl(self, ctx:SPLParser.SplContext):
        pass

    # Exit a parse tree produced by SPLParser#spl.
    def exitSpl(self, ctx:SPLParser.SplContext):
        pass


    # Enter a parse tree produced by SPLParser#pipeline.
    def enterPipeline(self, ctx:SPLParser.PipelineContext):
        pass

    # Exit a parse tree produced by SPLParser#pipeline.
    def exitPipeline(self, ctx:SPLParser.PipelineContext):
        pass


    # Enter a parse tree produced by SPLParser#command.
    def enterCommand(self, ctx:SPLParser.CommandContext):
        pass

    # Exit a parse tree produced by SPLParser#command.
    def exitCommand(self, ctx:SPLParser.CommandContext):
        pass


    # Enter a parse tree produced by SPLParser#searchCmd.
    def enterSearchCmd(self, ctx:SPLParser.SearchCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#searchCmd.
    def exitSearchCmd(self, ctx:SPLParser.SearchCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#searchExpr.
    def enterSearchExpr(self, ctx:SPLParser.SearchExprContext):
        pass

    # Exit a parse tree produced by SPLParser#searchExpr.
    def exitSearchExpr(self, ctx:SPLParser.SearchExprContext):
        pass


    # Enter a parse tree produced by SPLParser#searchOrExpr.
    def enterSearchOrExpr(self, ctx:SPLParser.SearchOrExprContext):
        pass

    # Exit a parse tree produced by SPLParser#searchOrExpr.
    def exitSearchOrExpr(self, ctx:SPLParser.SearchOrExprContext):
        pass


    # Enter a parse tree produced by SPLParser#searchAndExpr.
    def enterSearchAndExpr(self, ctx:SPLParser.SearchAndExprContext):
        pass

    # Exit a parse tree produced by SPLParser#searchAndExpr.
    def exitSearchAndExpr(self, ctx:SPLParser.SearchAndExprContext):
        pass


    # Enter a parse tree produced by SPLParser#searchNotExpr.
    def enterSearchNotExpr(self, ctx:SPLParser.SearchNotExprContext):
        pass

    # Exit a parse tree produced by SPLParser#searchNotExpr.
    def exitSearchNotExpr(self, ctx:SPLParser.SearchNotExprContext):
        pass


    # Enter a parse tree produced by SPLParser#searchAtom.
    def enterSearchAtom(self, ctx:SPLParser.SearchAtomContext):
        pass

    # Exit a parse tree produced by SPLParser#searchAtom.
    def exitSearchAtom(self, ctx:SPLParser.SearchAtomContext):
        pass


    # Enter a parse tree produced by SPLParser#term.
    def enterTerm(self, ctx:SPLParser.TermContext):
        pass

    # Exit a parse tree produced by SPLParser#term.
    def exitTerm(self, ctx:SPLParser.TermContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldComparison.
    def enterFieldComparison(self, ctx:SPLParser.FieldComparisonContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldComparison.
    def exitFieldComparison(self, ctx:SPLParser.FieldComparisonContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldValList.
    def enterFieldValList(self, ctx:SPLParser.FieldValListContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldValList.
    def exitFieldValList(self, ctx:SPLParser.FieldValListContext):
        pass


    # Enter a parse tree produced by SPLParser#compOp.
    def enterCompOp(self, ctx:SPLParser.CompOpContext):
        pass

    # Exit a parse tree produced by SPLParser#compOp.
    def exitCompOp(self, ctx:SPLParser.CompOpContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldVal.
    def enterFieldVal(self, ctx:SPLParser.FieldValContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldVal.
    def exitFieldVal(self, ctx:SPLParser.FieldValContext):
        pass


    # Enter a parse tree produced by SPLParser#timeModifier.
    def enterTimeModifier(self, ctx:SPLParser.TimeModifierContext):
        pass

    # Exit a parse tree produced by SPLParser#timeModifier.
    def exitTimeModifier(self, ctx:SPLParser.TimeModifierContext):
        pass


    # Enter a parse tree produced by SPLParser#timeStr.
    def enterTimeStr(self, ctx:SPLParser.TimeStrContext):
        pass

    # Exit a parse tree produced by SPLParser#timeStr.
    def exitTimeStr(self, ctx:SPLParser.TimeStrContext):
        pass


    # Enter a parse tree produced by SPLParser#statsCmd.
    def enterStatsCmd(self, ctx:SPLParser.StatsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#statsCmd.
    def exitStatsCmd(self, ctx:SPLParser.StatsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#statsOpt.
    def enterStatsOpt(self, ctx:SPLParser.StatsOptContext):
        pass

    # Exit a parse tree produced by SPLParser#statsOpt.
    def exitStatsOpt(self, ctx:SPLParser.StatsOptContext):
        pass


    # Enter a parse tree produced by SPLParser#eventstatsCmd.
    def enterEventstatsCmd(self, ctx:SPLParser.EventstatsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#eventstatsCmd.
    def exitEventstatsCmd(self, ctx:SPLParser.EventstatsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#streamstatsCmd.
    def enterStreamstatsCmd(self, ctx:SPLParser.StreamstatsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#streamstatsCmd.
    def exitStreamstatsCmd(self, ctx:SPLParser.StreamstatsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#streamstatsAggList.
    def enterStreamstatsAggList(self, ctx:SPLParser.StreamstatsAggListContext):
        pass

    # Exit a parse tree produced by SPLParser#streamstatsAggList.
    def exitStreamstatsAggList(self, ctx:SPLParser.StreamstatsAggListContext):
        pass


    # Enter a parse tree produced by SPLParser#streamstatsAggItem.
    def enterStreamstatsAggItem(self, ctx:SPLParser.StreamstatsAggItemContext):
        pass

    # Exit a parse tree produced by SPLParser#streamstatsAggItem.
    def exitStreamstatsAggItem(self, ctx:SPLParser.StreamstatsAggItemContext):
        pass


    # Enter a parse tree produced by SPLParser#streamstatsOpt.
    def enterStreamstatsOpt(self, ctx:SPLParser.StreamstatsOptContext):
        pass

    # Exit a parse tree produced by SPLParser#streamstatsOpt.
    def exitStreamstatsOpt(self, ctx:SPLParser.StreamstatsOptContext):
        pass


    # Enter a parse tree produced by SPLParser#aggList.
    def enterAggList(self, ctx:SPLParser.AggListContext):
        pass

    # Exit a parse tree produced by SPLParser#aggList.
    def exitAggList(self, ctx:SPLParser.AggListContext):
        pass


    # Enter a parse tree produced by SPLParser#aggCall.
    def enterAggCall(self, ctx:SPLParser.AggCallContext):
        pass

    # Exit a parse tree produced by SPLParser#aggCall.
    def exitAggCall(self, ctx:SPLParser.AggCallContext):
        pass


    # Enter a parse tree produced by SPLParser#aggFunc.
    def enterAggFunc(self, ctx:SPLParser.AggFuncContext):
        pass

    # Exit a parse tree produced by SPLParser#aggFunc.
    def exitAggFunc(self, ctx:SPLParser.AggFuncContext):
        pass


    # Enter a parse tree produced by SPLParser#aggArg.
    def enterAggArg(self, ctx:SPLParser.AggArgContext):
        pass

    # Exit a parse tree produced by SPLParser#aggArg.
    def exitAggArg(self, ctx:SPLParser.AggArgContext):
        pass


    # Enter a parse tree produced by SPLParser#evalCmd.
    def enterEvalCmd(self, ctx:SPLParser.EvalCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#evalCmd.
    def exitEvalCmd(self, ctx:SPLParser.EvalCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#evalAssignList.
    def enterEvalAssignList(self, ctx:SPLParser.EvalAssignListContext):
        pass

    # Exit a parse tree produced by SPLParser#evalAssignList.
    def exitEvalAssignList(self, ctx:SPLParser.EvalAssignListContext):
        pass


    # Enter a parse tree produced by SPLParser#evalAssign.
    def enterEvalAssign(self, ctx:SPLParser.EvalAssignContext):
        pass

    # Exit a parse tree produced by SPLParser#evalAssign.
    def exitEvalAssign(self, ctx:SPLParser.EvalAssignContext):
        pass


    # Enter a parse tree produced by SPLParser#rexCmd.
    def enterRexCmd(self, ctx:SPLParser.RexCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#rexCmd.
    def exitRexCmd(self, ctx:SPLParser.RexCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#rexOpt.
    def enterRexOpt(self, ctx:SPLParser.RexOptContext):
        pass

    # Exit a parse tree produced by SPLParser#rexOpt.
    def exitRexOpt(self, ctx:SPLParser.RexOptContext):
        pass


    # Enter a parse tree produced by SPLParser#joinCmd.
    def enterJoinCmd(self, ctx:SPLParser.JoinCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#joinCmd.
    def exitJoinCmd(self, ctx:SPLParser.JoinCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#joinOpt.
    def enterJoinOpt(self, ctx:SPLParser.JoinOptContext):
        pass

    # Exit a parse tree produced by SPLParser#joinOpt.
    def exitJoinOpt(self, ctx:SPLParser.JoinOptContext):
        pass


    # Enter a parse tree produced by SPLParser#joinType.
    def enterJoinType(self, ctx:SPLParser.JoinTypeContext):
        pass

    # Exit a parse tree produced by SPLParser#joinType.
    def exitJoinType(self, ctx:SPLParser.JoinTypeContext):
        pass


    # Enter a parse tree produced by SPLParser#timechartCmd.
    def enterTimechartCmd(self, ctx:SPLParser.TimechartCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#timechartCmd.
    def exitTimechartCmd(self, ctx:SPLParser.TimechartCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#timechartOpt.
    def enterTimechartOpt(self, ctx:SPLParser.TimechartOptContext):
        pass

    # Exit a parse tree produced by SPLParser#timechartOpt.
    def exitTimechartOpt(self, ctx:SPLParser.TimechartOptContext):
        pass


    # Enter a parse tree produced by SPLParser#chartCmd.
    def enterChartCmd(self, ctx:SPLParser.ChartCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#chartCmd.
    def exitChartCmd(self, ctx:SPLParser.ChartCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#chartOpt.
    def enterChartOpt(self, ctx:SPLParser.ChartOptContext):
        pass

    # Exit a parse tree produced by SPLParser#chartOpt.
    def exitChartOpt(self, ctx:SPLParser.ChartOptContext):
        pass


    # Enter a parse tree produced by SPLParser#tstatsCmd.
    def enterTstatsCmd(self, ctx:SPLParser.TstatsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#tstatsCmd.
    def exitTstatsCmd(self, ctx:SPLParser.TstatsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#tstatsOpt.
    def enterTstatsOpt(self, ctx:SPLParser.TstatsOptContext):
        pass

    # Exit a parse tree produced by SPLParser#tstatsOpt.
    def exitTstatsOpt(self, ctx:SPLParser.TstatsOptContext):
        pass


    # Enter a parse tree produced by SPLParser#tableCmd.
    def enterTableCmd(self, ctx:SPLParser.TableCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#tableCmd.
    def exitTableCmd(self, ctx:SPLParser.TableCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#tableFieldList.
    def enterTableFieldList(self, ctx:SPLParser.TableFieldListContext):
        pass

    # Exit a parse tree produced by SPLParser#tableFieldList.
    def exitTableFieldList(self, ctx:SPLParser.TableFieldListContext):
        pass


    # Enter a parse tree produced by SPLParser#tableField.
    def enterTableField(self, ctx:SPLParser.TableFieldContext):
        pass

    # Exit a parse tree produced by SPLParser#tableField.
    def exitTableField(self, ctx:SPLParser.TableFieldContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldsCmd.
    def enterFieldsCmd(self, ctx:SPLParser.FieldsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldsCmd.
    def exitFieldsCmd(self, ctx:SPLParser.FieldsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#whereCmd.
    def enterWhereCmd(self, ctx:SPLParser.WhereCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#whereCmd.
    def exitWhereCmd(self, ctx:SPLParser.WhereCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#dedupCmd.
    def enterDedupCmd(self, ctx:SPLParser.DedupCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#dedupCmd.
    def exitDedupCmd(self, ctx:SPLParser.DedupCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#sortCmd.
    def enterSortCmd(self, ctx:SPLParser.SortCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#sortCmd.
    def exitSortCmd(self, ctx:SPLParser.SortCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#sortFieldList.
    def enterSortFieldList(self, ctx:SPLParser.SortFieldListContext):
        pass

    # Exit a parse tree produced by SPLParser#sortFieldList.
    def exitSortFieldList(self, ctx:SPLParser.SortFieldListContext):
        pass


    # Enter a parse tree produced by SPLParser#sortField.
    def enterSortField(self, ctx:SPLParser.SortFieldContext):
        pass

    # Exit a parse tree produced by SPLParser#sortField.
    def exitSortField(self, ctx:SPLParser.SortFieldContext):
        pass


    # Enter a parse tree produced by SPLParser#sortByClause.
    def enterSortByClause(self, ctx:SPLParser.SortByClauseContext):
        pass

    # Exit a parse tree produced by SPLParser#sortByClause.
    def exitSortByClause(self, ctx:SPLParser.SortByClauseContext):
        pass


    # Enter a parse tree produced by SPLParser#headCmd.
    def enterHeadCmd(self, ctx:SPLParser.HeadCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#headCmd.
    def exitHeadCmd(self, ctx:SPLParser.HeadCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#tailCmd.
    def enterTailCmd(self, ctx:SPLParser.TailCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#tailCmd.
    def exitTailCmd(self, ctx:SPLParser.TailCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#renameCmd.
    def enterRenameCmd(self, ctx:SPLParser.RenameCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#renameCmd.
    def exitRenameCmd(self, ctx:SPLParser.RenameCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#renameClause.
    def enterRenameClause(self, ctx:SPLParser.RenameClauseContext):
        pass

    # Exit a parse tree produced by SPLParser#renameClause.
    def exitRenameClause(self, ctx:SPLParser.RenameClauseContext):
        pass


    # Enter a parse tree produced by SPLParser#lookupCmd.
    def enterLookupCmd(self, ctx:SPLParser.LookupCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#lookupCmd.
    def exitLookupCmd(self, ctx:SPLParser.LookupCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#inputlookupCmd.
    def enterInputlookupCmd(self, ctx:SPLParser.InputlookupCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#inputlookupCmd.
    def exitInputlookupCmd(self, ctx:SPLParser.InputlookupCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#outputlookupCmd.
    def enterOutputlookupCmd(self, ctx:SPLParser.OutputlookupCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#outputlookupCmd.
    def exitOutputlookupCmd(self, ctx:SPLParser.OutputlookupCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#lookupName.
    def enterLookupName(self, ctx:SPLParser.LookupNameContext):
        pass

    # Exit a parse tree produced by SPLParser#lookupName.
    def exitLookupName(self, ctx:SPLParser.LookupNameContext):
        pass


    # Enter a parse tree produced by SPLParser#lookupFields.
    def enterLookupFields(self, ctx:SPLParser.LookupFieldsContext):
        pass

    # Exit a parse tree produced by SPLParser#lookupFields.
    def exitLookupFields(self, ctx:SPLParser.LookupFieldsContext):
        pass


    # Enter a parse tree produced by SPLParser#lookupField.
    def enterLookupField(self, ctx:SPLParser.LookupFieldContext):
        pass

    # Exit a parse tree produced by SPLParser#lookupField.
    def exitLookupField(self, ctx:SPLParser.LookupFieldContext):
        pass


    # Enter a parse tree produced by SPLParser#transactionCmd.
    def enterTransactionCmd(self, ctx:SPLParser.TransactionCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#transactionCmd.
    def exitTransactionCmd(self, ctx:SPLParser.TransactionCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#transactionOpt.
    def enterTransactionOpt(self, ctx:SPLParser.TransactionOptContext):
        pass

    # Exit a parse tree produced by SPLParser#transactionOpt.
    def exitTransactionOpt(self, ctx:SPLParser.TransactionOptContext):
        pass


    # Enter a parse tree produced by SPLParser#evalOrSearch.
    def enterEvalOrSearch(self, ctx:SPLParser.EvalOrSearchContext):
        pass

    # Exit a parse tree produced by SPLParser#evalOrSearch.
    def exitEvalOrSearch(self, ctx:SPLParser.EvalOrSearchContext):
        pass


    # Enter a parse tree produced by SPLParser#bucketCmd.
    def enterBucketCmd(self, ctx:SPLParser.BucketCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#bucketCmd.
    def exitBucketCmd(self, ctx:SPLParser.BucketCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#bucketOpt.
    def enterBucketOpt(self, ctx:SPLParser.BucketOptContext):
        pass

    # Exit a parse tree produced by SPLParser#bucketOpt.
    def exitBucketOpt(self, ctx:SPLParser.BucketOptContext):
        pass


    # Enter a parse tree produced by SPLParser#appendCmd.
    def enterAppendCmd(self, ctx:SPLParser.AppendCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#appendCmd.
    def exitAppendCmd(self, ctx:SPLParser.AppendCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#appendColsCmd.
    def enterAppendColsCmd(self, ctx:SPLParser.AppendColsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#appendColsCmd.
    def exitAppendColsCmd(self, ctx:SPLParser.AppendColsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#unionCmd.
    def enterUnionCmd(self, ctx:SPLParser.UnionCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#unionCmd.
    def exitUnionCmd(self, ctx:SPLParser.UnionCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#topCmd.
    def enterTopCmd(self, ctx:SPLParser.TopCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#topCmd.
    def exitTopCmd(self, ctx:SPLParser.TopCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#rareCmd.
    def enterRareCmd(self, ctx:SPLParser.RareCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#rareCmd.
    def exitRareCmd(self, ctx:SPLParser.RareCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#topRareOpt.
    def enterTopRareOpt(self, ctx:SPLParser.TopRareOptContext):
        pass

    # Exit a parse tree produced by SPLParser#topRareOpt.
    def exitTopRareOpt(self, ctx:SPLParser.TopRareOptContext):
        pass


    # Enter a parse tree produced by SPLParser#fillnullCmd.
    def enterFillnullCmd(self, ctx:SPLParser.FillnullCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#fillnullCmd.
    def exitFillnullCmd(self, ctx:SPLParser.FillnullCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#makeresultsCmd.
    def enterMakeresultsCmd(self, ctx:SPLParser.MakeresultsCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#makeresultsCmd.
    def exitMakeresultsCmd(self, ctx:SPLParser.MakeresultsCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#extractCmd.
    def enterExtractCmd(self, ctx:SPLParser.ExtractCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#extractCmd.
    def exitExtractCmd(self, ctx:SPLParser.ExtractCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#extractOpt.
    def enterExtractOpt(self, ctx:SPLParser.ExtractOptContext):
        pass

    # Exit a parse tree produced by SPLParser#extractOpt.
    def exitExtractOpt(self, ctx:SPLParser.ExtractOptContext):
        pass


    # Enter a parse tree produced by SPLParser#kvformCmd.
    def enterKvformCmd(self, ctx:SPLParser.KvformCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#kvformCmd.
    def exitKvformCmd(self, ctx:SPLParser.KvformCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#multikvCmd.
    def enterMultikvCmd(self, ctx:SPLParser.MultikvCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#multikvCmd.
    def exitMultikvCmd(self, ctx:SPLParser.MultikvCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#gpuHintCmd.
    def enterGpuHintCmd(self, ctx:SPLParser.GpuHintCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#gpuHintCmd.
    def exitGpuHintCmd(self, ctx:SPLParser.GpuHintCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#deltaCmd.
    def enterDeltaCmd(self, ctx:SPLParser.DeltaCmdContext):
        pass

    # Exit a parse tree produced by SPLParser#deltaCmd.
    def exitDeltaCmd(self, ctx:SPLParser.DeltaCmdContext):
        pass


    # Enter a parse tree produced by SPLParser#subsearch.
    def enterSubsearch(self, ctx:SPLParser.SubsearchContext):
        pass

    # Exit a parse tree produced by SPLParser#subsearch.
    def exitSubsearch(self, ctx:SPLParser.SubsearchContext):
        pass


    # Enter a parse tree produced by SPLParser#macroCall.
    def enterMacroCall(self, ctx:SPLParser.MacroCallContext):
        pass

    # Exit a parse tree produced by SPLParser#macroCall.
    def exitMacroCall(self, ctx:SPLParser.MacroCallContext):
        pass


    # Enter a parse tree produced by SPLParser#macroArgs.
    def enterMacroArgs(self, ctx:SPLParser.MacroArgsContext):
        pass

    # Exit a parse tree produced by SPLParser#macroArgs.
    def exitMacroArgs(self, ctx:SPLParser.MacroArgsContext):
        pass


    # Enter a parse tree produced by SPLParser#macroArg.
    def enterMacroArg(self, ctx:SPLParser.MacroArgContext):
        pass

    # Exit a parse tree produced by SPLParser#macroArg.
    def exitMacroArg(self, ctx:SPLParser.MacroArgContext):
        pass


    # Enter a parse tree produced by SPLParser#expr.
    def enterExpr(self, ctx:SPLParser.ExprContext):
        pass

    # Exit a parse tree produced by SPLParser#expr.
    def exitExpr(self, ctx:SPLParser.ExprContext):
        pass


    # Enter a parse tree produced by SPLParser#orExpr.
    def enterOrExpr(self, ctx:SPLParser.OrExprContext):
        pass

    # Exit a parse tree produced by SPLParser#orExpr.
    def exitOrExpr(self, ctx:SPLParser.OrExprContext):
        pass


    # Enter a parse tree produced by SPLParser#andExpr.
    def enterAndExpr(self, ctx:SPLParser.AndExprContext):
        pass

    # Exit a parse tree produced by SPLParser#andExpr.
    def exitAndExpr(self, ctx:SPLParser.AndExprContext):
        pass


    # Enter a parse tree produced by SPLParser#notExpr.
    def enterNotExpr(self, ctx:SPLParser.NotExprContext):
        pass

    # Exit a parse tree produced by SPLParser#notExpr.
    def exitNotExpr(self, ctx:SPLParser.NotExprContext):
        pass


    # Enter a parse tree produced by SPLParser#compExpr.
    def enterCompExpr(self, ctx:SPLParser.CompExprContext):
        pass

    # Exit a parse tree produced by SPLParser#compExpr.
    def exitCompExpr(self, ctx:SPLParser.CompExprContext):
        pass


    # Enter a parse tree produced by SPLParser#addExpr.
    def enterAddExpr(self, ctx:SPLParser.AddExprContext):
        pass

    # Exit a parse tree produced by SPLParser#addExpr.
    def exitAddExpr(self, ctx:SPLParser.AddExprContext):
        pass


    # Enter a parse tree produced by SPLParser#mulExpr.
    def enterMulExpr(self, ctx:SPLParser.MulExprContext):
        pass

    # Exit a parse tree produced by SPLParser#mulExpr.
    def exitMulExpr(self, ctx:SPLParser.MulExprContext):
        pass


    # Enter a parse tree produced by SPLParser#unaryExpr.
    def enterUnaryExpr(self, ctx:SPLParser.UnaryExprContext):
        pass

    # Exit a parse tree produced by SPLParser#unaryExpr.
    def exitUnaryExpr(self, ctx:SPLParser.UnaryExprContext):
        pass


    # Enter a parse tree produced by SPLParser#atom.
    def enterAtom(self, ctx:SPLParser.AtomContext):
        pass

    # Exit a parse tree produced by SPLParser#atom.
    def exitAtom(self, ctx:SPLParser.AtomContext):
        pass


    # Enter a parse tree produced by SPLParser#literal.
    def enterLiteral(self, ctx:SPLParser.LiteralContext):
        pass

    # Exit a parse tree produced by SPLParser#literal.
    def exitLiteral(self, ctx:SPLParser.LiteralContext):
        pass


    # Enter a parse tree produced by SPLParser#valueList.
    def enterValueList(self, ctx:SPLParser.ValueListContext):
        pass

    # Exit a parse tree produced by SPLParser#valueList.
    def exitValueList(self, ctx:SPLParser.ValueListContext):
        pass


    # Enter a parse tree produced by SPLParser#functionCall.
    def enterFunctionCall(self, ctx:SPLParser.FunctionCallContext):
        pass

    # Exit a parse tree produced by SPLParser#functionCall.
    def exitFunctionCall(self, ctx:SPLParser.FunctionCallContext):
        pass


    # Enter a parse tree produced by SPLParser#funcName.
    def enterFuncName(self, ctx:SPLParser.FuncNameContext):
        pass

    # Exit a parse tree produced by SPLParser#funcName.
    def exitFuncName(self, ctx:SPLParser.FuncNameContext):
        pass


    # Enter a parse tree produced by SPLParser#funcArgList.
    def enterFuncArgList(self, ctx:SPLParser.FuncArgListContext):
        pass

    # Exit a parse tree produced by SPLParser#funcArgList.
    def exitFuncArgList(self, ctx:SPLParser.FuncArgListContext):
        pass


    # Enter a parse tree produced by SPLParser#evalFuncName.
    def enterEvalFuncName(self, ctx:SPLParser.EvalFuncNameContext):
        pass

    # Exit a parse tree produced by SPLParser#evalFuncName.
    def exitEvalFuncName(self, ctx:SPLParser.EvalFuncNameContext):
        pass


    # Enter a parse tree produced by SPLParser#spanVal.
    def enterSpanVal(self, ctx:SPLParser.SpanValContext):
        pass

    # Exit a parse tree produced by SPLParser#spanVal.
    def exitSpanVal(self, ctx:SPLParser.SpanValContext):
        pass


    # Enter a parse tree produced by SPLParser#timeUnit.
    def enterTimeUnit(self, ctx:SPLParser.TimeUnitContext):
        pass

    # Exit a parse tree produced by SPLParser#timeUnit.
    def exitTimeUnit(self, ctx:SPLParser.TimeUnitContext):
        pass


    # Enter a parse tree produced by SPLParser#boolLiteral.
    def enterBoolLiteral(self, ctx:SPLParser.BoolLiteralContext):
        pass

    # Exit a parse tree produced by SPLParser#boolLiteral.
    def exitBoolLiteral(self, ctx:SPLParser.BoolLiteralContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldList.
    def enterFieldList(self, ctx:SPLParser.FieldListContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldList.
    def exitFieldList(self, ctx:SPLParser.FieldListContext):
        pass


    # Enter a parse tree produced by SPLParser#statsByList.
    def enterStatsByList(self, ctx:SPLParser.StatsByListContext):
        pass

    # Exit a parse tree produced by SPLParser#statsByList.
    def exitStatsByList(self, ctx:SPLParser.StatsByListContext):
        pass


    # Enter a parse tree produced by SPLParser#computedByField.
    def enterComputedByField(self, ctx:SPLParser.ComputedByFieldContext):
        pass

    # Exit a parse tree produced by SPLParser#computedByField.
    def exitComputedByField(self, ctx:SPLParser.ComputedByFieldContext):
        pass


    # Enter a parse tree produced by SPLParser#plainByField.
    def enterPlainByField(self, ctx:SPLParser.PlainByFieldContext):
        pass

    # Exit a parse tree produced by SPLParser#plainByField.
    def exitPlainByField(self, ctx:SPLParser.PlainByFieldContext):
        pass


    # Enter a parse tree produced by SPLParser#fieldName.
    def enterFieldName(self, ctx:SPLParser.FieldNameContext):
        pass

    # Exit a parse tree produced by SPLParser#fieldName.
    def exitFieldName(self, ctx:SPLParser.FieldNameContext):
        pass


    # Enter a parse tree produced by SPLParser#kw.
    def enterKw(self, ctx:SPLParser.KwContext):
        pass

    # Exit a parse tree produced by SPLParser#kw.
    def exitKw(self, ctx:SPLParser.KwContext):
        pass


    # Enter a parse tree produced by SPLParser#number.
    def enterNumber(self, ctx:SPLParser.NumberContext):
        pass

    # Exit a parse tree produced by SPLParser#number.
    def exitNumber(self, ctx:SPLParser.NumberContext):
        pass



del SPLParser