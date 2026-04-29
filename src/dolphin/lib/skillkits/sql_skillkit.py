from typing import List, Optional
import re
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit

from dolphin.lib.ontology.ontology_context import OntologyContext


class SQLSkillkit(Skillkit):
    def __init__(self, ontologyContext: Optional[OntologyContext] = None):
        super().__init__()
        self.ontologyContext = ontologyContext

    def getName(self) -> str:
        return "sql_skillkit"

    def setGlobalConfig(self, globalConfig):
        super().setGlobalConfig(globalConfig)
        if (
            self.ontologyContext is None
            and self.globalConfig.ontology_config is not None
        ):
            self.ontologyContext = OntologyContext.loadOntologyContext(
                self.globalConfig.ontology_config
            )

    def executeSQL(
        self, datasource: str, sql: str, dialect: str = "mysql", **kwargs
    ) -> str:
        """Execute an SQL statement in the specified data source and return the result.

        Args:
            datasource (str): Name or concept name of the data source
            sql (str): A valid SQL statement starting with SELECT
            dialect (str): SQL dialect, default is 'mysql', supports 'oracle', 'mysql', 'postgres', etc.
            **kwargs: Other parameters
        """
        # Extract valid SQL from input string using regex
        cleanedSQL = self._extractSQL(sql)
        if not cleanedSQL:
            return "无法从输入中提取有效的SQL语句"

        # Apply dialect-specific preprocessing
        processedSQL = self._preprocessSQL(cleanedSQL, dialect)

        if self.ontologyContext is None:
            return "Ontology context is not initialized"

        ontology = self.ontologyContext.getOntology()
        if ontology is None:
            return "Ontology is not available"

        theDataSource = ontology.getDataSource(datasource)
        if theDataSource is None:
            return f"数据源或概念 {datasource} 不存在"

        try:
            result = theDataSource.executeQuery(processedSQL)
            return str(result)
        except Exception as e:
            # Enhanced error handling with dialect-specific suggestions
            return self._handleSQLError(e, processedSQL, dialect)

    def _extractSQL(self, inputStr: str) -> str:
        if not inputStr:
            return ""

        content = inputStr.strip()

        if content.startswith("```") and content.endswith("```"):
            content = content[3:-3].strip()
            if content.lower().startswith("sql"):
                content = content[3:].strip()

        while True:
            if (
                (content.startswith('"') and content.endswith('"'))
                or (content.startswith("'") and content.endswith("'"))
                or (content.startswith("`") and content.endswith("`"))
            ):
                content = content[1:-1].strip()
            else:
                break

        lines = content.split("\n")
        sql_lines = []
        in_sql_block = False
        sql_keywords = [
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
            "CREATE",
            "DROP",
            "ALTER",
            "WITH",
        ]

        for line in lines:
            stripped_line = line.strip()

            if not in_sql_block:
                for keyword in sql_keywords:
                    if stripped_line.upper().startswith(keyword):
                        in_sql_block = True
                        break

            if in_sql_block:
                if not stripped_line:
                    break
                sql_lines.append(line)
                if stripped_line.endswith(";"):
                    break

        if sql_lines:
            return "\n".join(sql_lines).strip()

        return content.strip()

    def _extractSQLFromMixedContent(self, text: str) -> str:
        return self._extractSQL(text)  # Just reuse the main logic

    def _normalizeWhitespace(self, sql: str) -> str:
        return sql.strip()

    def _validateSQLCompleteness(self, sql: str) -> bool:
        if not sql:
            return False

        text = sql

        # Remove string literals and comments to avoid interfering with structural validation
        def _strip_literals_and_comments(s: str) -> str:
            # Remove -- line comments
            s = re.sub(r"--.*?$", "", s, flags=re.MULTILINE)
            # Remove /* ... */ block comments
            s = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)
            # Remove the content within single and double quotation marks (preserve structure outside quotes)
            s = re.sub(r"'(?:''|[^'])*'", "''", s)
            s = re.sub(r'"(?:""|[^"])*"', '""', s)
            return s

        cleaned = _strip_literals_and_comments(text)

        # Bracket Matching
        open_parens = cleaned.count("(")
        close_parens = cleaned.count(")")
        if open_parens != close_parens:
            return False

        sql_upper = cleaned.upper().strip()

        # Basic Structure Judgment
        if sql_upper.startswith("SELECT"):
            # Allow FROM across newlines/indentation by using word-boundary match
            if not re.search(r"\bFROM\b", sql_upper):
                return False
            # Avoid false positives like identifiers ending with these keywords (e.g., SORT_ORDER)
            if re.search(
                r"\b(AND|OR|WHERE|FROM|JOIN|ON|GROUP|ORDER|HAVING|UNION|INTERSECT|EXCEPT)\s*$",
                sql_upper,
            ):
                return False
        elif sql_upper.startswith("WITH"):
            if "SELECT" not in sql_upper:
                return False

        if text.strip().endswith(","):
            return False

        # CASE/END Pairing (matched by word boundaries to avoid miscounting)
        case_count = len(re.findall(r"\bCASE\b", cleaned, flags=re.IGNORECASE))
        end_count = len(re.findall(r"\bEND\b", cleaned, flags=re.IGNORECASE))
        if case_count != end_count:
            return False

        return True

    def _extractSQLConservatively(self, text: str) -> str:
        return self._extractSQL(text)

    def _preprocessSQL(self, sql: str, dialect: str) -> str:
        if dialect.lower() == "oracle":
            return self._preprocessOracleSQL(sql)
        elif dialect.lower() == "mysql":
            return self._preprocessMySQLSQL(sql)
        else:
            return sql

    def _preprocessOracleSQL(self, sql: str) -> str:
        # Simplified replacements to avoid complex regex issues
        # 1. Fix DATE() function -> TO_DATE(), but avoid replacing TO_DATE()
        sql = re.sub(
            r"(?<!TO_)DATE\s*\(\s*'(.*?)'\s*\)",
            r"TO_DATE('\1', 'YYYY-MM-DD')",
            sql,
            flags=re.IGNORECASE,
        )

        # 2. Convert LIMIT -> FETCH FIRST
        limit_match = re.search(r"LIMIT\s+(\d+)\s*$", sql, re.IGNORECASE)
        if limit_match:
            num = limit_match.group(1)
            sql = re.sub(
                r"LIMIT\s+\d+\s*$",
                f"FETCH FIRST {num} ROWS ONLY",
                sql,
                flags=re.IGNORECASE,
            )

        # 3. Handle date strings -> TO_DATE(), but DO NOT alter ANSI DATE literals
        #    i.e., keep: DATE 'YYYY-MM-DD' as-is, and avoid nesting when already inside TO_DATE(
        def _replace_plain_date_literals(text: str) -> str:
            pattern = re.compile(r"'(\d{4}-\d{2}-\d{2})'")

            def repl(m: re.Match) -> str:
                start = m.start()
                before = text[:start]
                # Ignore if immediately preceded by DATE (ANSI literal)
                if re.search(r"(?i)DATE\s*$", before.rstrip()[-10:]):
                    return m.group(0)
                # Ignore if inside a TO_DATE( ... ) argument beginning
                if re.search(r"(?i)TO_DATE\s*\($", before.rstrip()[-15:]):
                    return m.group(0)
                value = m.group(1)
                return f"TO_DATE('{value}', 'YYYY-MM-DD')"

            return pattern.sub(repl, text)

        sql = _replace_plain_date_literals(sql)

        # 4. Ensure string literals use single quotes (preserve '=')
        sql = re.sub(r'="([^"]*)"', r"='\1'", sql)

        return sql

    def _preprocessMySQLSQL(self, sql: str) -> str:
        return sql

    def _handleSQLError(self, error: Exception, sql: str, dialect: str) -> str:
        error_str = str(error).upper()
        if dialect.lower() == "oracle":
            return self._handleOracleError(error_str, sql)
        else:
            return f"执行SQL语句failed: {error}"

    def _handleOracleError(self, error_str: str, sql: str) -> str:
        suggestions = []
        if "ORA-00904" in error_str:
            suggestions.append("字段不存在或无效。请检查字段名拼写和表别名。")
        elif "ORA-00942" in error_str:
            suggestions.append("表或视图不存在。请检查table name和用户权限。")
        elif "ORA-01843" in error_str:
            suggestions.append(
                "日期格式无效。请使用 TO_DATE('YYYY-MM-DD', 'YYYY-MM-DD') 格式。"
            )
        elif "ORA-00933" in error_str:
            suggestions.append("SQL命令未正确结束。请检查语法和括号匹配。")
        elif "ORA-00936" in error_str:
            suggestions.append("缺少表达式。请检查SELECT子句是否完整。")

        if suggestions:
            suggestion_text = "\n".join([f"  - {s}" for s in suggestions])
            return f"执行SQL语句failed: {error_str}\n\n建议修复方案:\n{suggestion_text}"
        else:
            return f"执行SQL语句failed: {error_str}"

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self.executeSQL, block_as_parameter=("sql", "sql")),
        ]

    def getTools(self) -> List[SkillFunction]:
        return self.getSkills()  # Uses base class getSkills() with caching
