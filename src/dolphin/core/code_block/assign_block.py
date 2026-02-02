import json
import ast

from dolphin.core.code_block.basic_code_block import BasicCodeBlock
from dolphin.core.logging.logger import console_block_start
from dolphin.core.common.enums import CategoryBlock, count_occurrences, TypeStage
from dolphin.core.context.context import Context
from dolphin.core.context.var_output import SourceType


class AssignBlock(BasicCodeBlock):
    def __init__(self, context: Context, debug_infos=None):
        super().__init__(context)
        self.debug_info = debug_infos

    def _try_parse_string_literal(self, expr: str):
        """Return the evaluated Python string literal if expr is a pure string literal."""
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return None

        if isinstance(tree.body, ast.Constant) and isinstance(tree.body.value, str):
            try:
                return ast.literal_eval(expr)
            except Exception:
                return None
        return None

    def _interpolate_plain_text(self, text: str) -> str:
        """Interpolate Dolphin variables in plain text without quoting."""
        variable_index_list = self.context.recognize_variable(text)
        if not variable_index_list:
            return text

        variable_index_list.sort(key=lambda x: x[1][0], reverse=True)
        for variable_name, (start, end) in variable_index_list:
            variable_value = self.context.get_variable_type(variable_name)
            text = text[:start] + str(variable_value) + text[end:]
        return text

    def _eval_assign_expression(self, expr: str):
        literal_value = self._try_parse_string_literal(expr)
        if literal_value is not None:
            return self._interpolate_plain_text(literal_value)

        var_before = self.context.recognize_variable(expr)
        local_variables = {"json": json}
        for i in range(len(var_before)):
            expr = expr.replace(var_before[i][0], "temp" + str(i))
            local_variables["temp" + str(i)] = self.context.get_variable_type(
                var_before[i][0]
            )

        try:
            return eval(expr, local_variables)
        except Exception as e:
            filtered_local_vars = {
                k: v for k, v in local_variables.items() if k.startswith("temp")
            }
            raise Exception(
                f"Failed to parse variable: var_before_str = {expr}; "
                f"local_variables = {filtered_local_vars}; error = {e}"
            )

    async def execute(
        self,
        content,
        category: CategoryBlock = CategoryBlock.ASSIGN,
        replace_variables=False,
    ):
        # Call the parent class's execute method
        async for _ in super().execute(content, category, replace_variables):
            pass
        num0 = count_occurrences(["->", ">>"], self.content)
        num1 = count_occurrences(
            ["/if/", "/prompt/", "/judge/", "/explore/"], self.content
        )
        if num0 > 1 or num1 > 0:
            raise Exception(f"Syntax Error({self.content})，check the '->' or '>>'")

        if self.assign_type == "->":
            var_before_str = self.content.split("->")[0].strip()
            if len(var_before_str) == 0 or len(self.output_var) == 0:
                raise Exception(f"Syntax Error({self.content})，check the variable")
            result = self._eval_assign_expression(var_before_str)
            console_block_start(
                "assign", self.output_var, str(result), verbose=self.context.verbose
            )
            self.recorder.update(
                item=result,
                stage=TypeStage.ASSIGN,
                is_completed=True,
                source_type=SourceType.ASSIGN,
            )
            yield result
        elif self.assign_type == ">>":
            var_before_str = self.content.split(">>")[0].strip()
            if len(var_before_str) == 0 or len(self.output_var) == 0:
                raise Exception(f"Syntax Error({self.content})，check the variable")
            result = self._eval_assign_expression(var_before_str)
            self.block_start_log("assign", result)
            self.recorder.update(
                item=result,
                stage=TypeStage.ASSIGN,
                is_completed=True,
                source_type=SourceType.ASSIGN,
            )
            yield result
