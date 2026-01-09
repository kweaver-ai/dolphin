import unittest
from dolphin.lib.skillkits.sql_skillkit import SQLSkillkit


class TestSQLSkillkit(unittest.TestCase):
    def setUp(self):
        self.skillkit = SQLSkillkit()

    def test_extract_sql_empty_input(self):
        """测试空输入"""
        result = self.skillkit._extractSQL("")
        self.assertEqual(result, "")

        result = self.skillkit._extractSQL(None)
        self.assertEqual(result, "")

    def test_extract_sql_simple_query(self):
        """测试简单的SQL查询"""
        sql = "SELECT * FROM users"
        result = self.skillkit._extractSQL(sql)
        self.assertEqual(result, "SELECT * FROM users")

    def test_extract_sql_code_block_with_sql_tag(self):
        """测试带sql标签的代码块"""
        content = """```sql
SELECT name, age FROM users WHERE age > 18
```"""
        expected = "SELECT name, age FROM users WHERE age > 18"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_code_block_without_tag(self):
        """测试不带标签的代码块"""
        content = """```
SELECT COUNT(*) FROM products
```"""
        expected = "SELECT COUNT(*) FROM products"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_single_quotes(self):
        """测试单引号包围的SQL"""
        content = "'SELECT * FROM orders'"
        expected = "SELECT * FROM orders"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_double_quotes(self):
        """测试双引号包围的SQL"""
        content = '"SELECT id, name FROM customers"'
        expected = "SELECT id, name FROM customers"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_backticks(self):
        """测试反引号包围的SQL"""
        content = "`SELECT price FROM products WHERE category = 'electronics'`"
        expected = "SELECT price FROM products WHERE category = 'electronics'"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_multiline_in_code_block(self):
        """测试代码块中的多行SQL"""
        content = """```sql
SELECT u.name, p.title
FROM users u
JOIN posts p ON u.id = p.user_id
WHERE u.active = 1
ORDER BY p.created_at DESC
```"""
        expected = """SELECT u.name, p.title
FROM users u
JOIN posts p ON u.id = p.user_id
WHERE u.active = 1
ORDER BY p.created_at DESC"""
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_complex_queries(self):
        """测试复杂SQL语句的各种关键字"""
        test_cases = [
            (
                "INSERT INTO users (name) VALUES ('John')",
                "INSERT INTO users (name) VALUES ('John')",
            ),
            (
                "UPDATE users SET age = 25 WHERE id = 1",
                "UPDATE users SET age = 25 WHERE id = 1",
            ),
            (
                "DELETE FROM users WHERE inactive = 1",
                "DELETE FROM users WHERE inactive = 1",
            ),
            (
                "CREATE TABLE test (id INT PRIMARY KEY)",
                "CREATE TABLE test (id INT PRIMARY KEY)",
            ),
            ("DROP TABLE old_table", "DROP TABLE old_table"),
            (
                "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
                "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
            ),
            (
                "WITH cte AS (SELECT * FROM users) SELECT * FROM cte",
                "WITH cte AS (SELECT * FROM users) SELECT * FROM cte",
            ),
        ]

        for input_sql, expected in test_cases:
            with self.subTest(sql=input_sql):
                result = self.skillkit._extractSQL(input_sql)
                self.assertEqual(result, expected)

    def test_extract_sql_case_insensitive(self):
        """测试SQL关键字大小写不敏感"""
        test_cases = [
            "select * from users",
            "Select * From Users",
            "SELECT * FROM USERS",
            "insert into table values (1)",
            "UPDATE table SET col = 1",
        ]

        for sql in test_cases:
            with self.subTest(sql=sql):
                result = self.skillkit._extractSQL(sql)
                self.assertEqual(result, sql)

    def test_extract_sql_no_keywords(self):
        """测试不包含SQL关键字的输入"""
        content = "This is just plain text without SQL keywords"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, content.strip())

    def test_extract_sql_with_extra_whitespace(self):
        """测试包含额外空白的SQL"""
        content = "   \n\n  SELECT * FROM users  \n\n  "
        expected = "SELECT * FROM users"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_nested_quotes_in_code_block(self):
        """测试代码块中包含引号的SQL"""
        content = """```sql
SELECT name FROM users WHERE status = "active"
```"""
        expected = 'SELECT name FROM users WHERE status = "active"'
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_code_block_with_extra_spaces(self):
        """测试代码块标记周围有额外空格的情况"""
        content = """```  sql  
        SELECT * FROM products
        ```"""
        expected = "SELECT * FROM products"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_multiple_patterns(self):
        """测试多种模式组合的情况"""
        # 代码块中包含引号的SQL
        content = """```sql
"SELECT * FROM users"
```"""
        # 应该先处理代码块，然后处理内部的引号
        expected = "SELECT * FROM users"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_complex_analysis_with_explanation(self):
        """测试复杂分析文本中的SQL提取"""
        content = """根据查询结果，Sacramento县在1980年代报告了最多的学校关闭数量（1所），这些学校的所有权代码属于Youth Authority Facilities (SOC = 11)。

但题目要求的是返回SQL语句，而不是结果。让我重新组织最终的SQL语句：

SELECT County, COUNT(*) as closure_count
FROM schools
WHERE StatusType = 'Closed' 
AND SOC = '11'
AND ClosedDate >= '1980-01-01' 
AND ClosedDate <= '1989-12-31'
GROUP BY County
ORDER BY closure_count DESC
LIMIT 1"""

        expected = """SELECT County, COUNT(*) as closure_count
FROM schools
WHERE StatusType = 'Closed' 
AND SOC = '11'
AND ClosedDate >= '1980-01-01' 
AND ClosedDate <= '1989-12-31'
GROUP BY County
ORDER BY closure_count DESC
LIMIT 1"""

        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_mixed_content_with_multiple_paragraphs(self):
        """测试包含多个段落的混合内容中的SQL提取"""
        content = """This is some analysis text with explanations.

The query we need is:

SELECT id, name FROM users WHERE active = 1

This query will return all active users.

Some additional explanation follows here."""

        expected = "SELECT id, name FROM users WHERE active = 1"
        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_complex_chinese_analysis_with_cast_functions(self):
        """测试包含中文分析和复杂SQL函数的混合内容提取"""
        content = """根据查询结果，我确认在洛杉矶县没有恰好提供从幼儿园(K)到9年级教育的学校。因此，最终的SQL语句如下：

SELECT 
    "School Name",
    (CAST("FRPM Count (Ages 5-17)" AS REAL) / CAST("Enrollment (Ages 5-17)" AS REAL)) * 100 AS "Percent (%) Eligible FRPM (Ages 5-17)"
FROM frpm
WHERE "County Name" = 'Los Angeles' 
AND "Low Grade" = 'K' 
AND "High Grade" = '9'"""

        expected = """SELECT 
    "School Name",
    (CAST("FRPM Count (Ages 5-17)" AS REAL) / CAST("Enrollment (Ages 5-17)" AS REAL)) * 100 AS "Percent (%) Eligible FRPM (Ages 5-17)"
FROM frpm
WHERE "County Name" = 'Los Angeles' 
AND "Low Grade" = 'K' 
AND "High Grade" = '9'"""

        result = self.skillkit._extractSQL(content)
        self.assertEqual(result, expected)

    def test_extract_sql_join_with_limit(self):
        """测试包含JOIN和LIMIT的复杂查询"""
        # 测试原始的SQL字符串（用于验证_extractSQL方法能够处理JOIN和LIMIT语法）
        content = "SELECT s.School, f.Percent FROM frpm f JOIN schools s ON f.CDSCode = s.CDSCode WHERE s.SOCType = 'Continuation High Schools' LIMIT 5"
        result = self.skillkit._extractSQL(content)
        # 验证能够识别并处理包含JOIN和LIMIT的SQL语句
        self.assertEqual(result, content)

        # 同时测试代码块格式
        code_block_content = """```sql
SELECT s.School, f.Percent FROM frpm f JOIN schools s ON f.CDSCode = s.CDSCode WHERE s.SOCType = 'Continuation High Schools' LIMIT 5
```"""
        result_from_block = self.skillkit._extractSQL(code_block_content)
        self.assertEqual(result_from_block, content)

    def test_extract_sql_complex_case_statement(self):
        """测试包含CASE语句的复杂SQL查询"""
        sql_query = """SELECT 
    s.School,
    s.District,
    s.County,
    f."Enrollment (Ages 5-17)",
    f."Free Meal Count (Ages 5-17)",
    CASE 
        WHEN f."Enrollment (Ages 5-17)" > 0 
        THEN f."Free Meal Count (Ages 5-17)" / f."Enrollment (Ages 5-17)"
        ELSE 0 
    END AS free_rate
FROM schools s
JOIN frpm f ON s.CDSCode = f.CDSCode
WHERE s.SOCType = 'Continuation High Schools'
    AND f."Enrollment (Ages 5-17)" > 0
    AND f."Free Meal Count (Ages 5-17)" IS NOT NULL
ORDER BY free_rate ASC
LIMIT 3"""

        result = self.skillkit._extractSQL(sql_query)
        self.assertEqual(result, sql_query)

    def test_extract_sql_complex_join_case(self):
        """测试包含JOIN和复杂结构的SQL解析（简化版）"""
        # 使用一个相对简单但包含关键问题的SQL
        sql_with_join = """WITH sales_data AS (
    SELECT
        CASE
            WHEN O.MKT_CHANNEL = 'My store' THEN 'My Store'
            WHEN O.MKT_CHANNEL = 'E-Commerce' THEN 'Ecom'
            ELSE 'Other'
        END AS channel,
        SUM(S.ORDER_AMT) AS sales_current
    FROM
        WATSONS.ORDER_TABLE S
        JOIN WATSONS.ORG_TABLE O ON S.LOC_ID = O.LOC_ID
        JOIN WATSONS.PRODUCT_TABLE P ON S.ITEM_ID = P.ITEM_ID
    WHERE
        S.FLAG IN ('N', 'C')
        AND P.ACTIVE = 'Y'
    GROUP BY
        O.MKT_CHANNEL
)
SELECT
    channel,
    sales_current AS sales
FROM sales_data
ORDER BY channel"""

        # 提取SQL
        extracted_sql = self.skillkit._extractSQL(sql_with_join)

        # 验证SQL被正确提取
        self.assertGreater(
            len(extracted_sql), 50, "SQL extraction should work for complex queries"
        )

        # 验证SQL包含关键部分
        self.assertIn("WITH", extracted_sql.upper(), "Should contain WITH clause")
        self.assertIn(
            "SELECT", extracted_sql.upper(), "Should contain SELECT statements"
        )
        self.assertIn("FROM", extracted_sql.upper(), "Should contain FROM clauses")
        self.assertIn("JOIN", extracted_sql.upper(), "Should contain JOIN clauses")
        self.assertIn("WHERE", extracted_sql.upper(), "Should contain WHERE clauses")
        self.assertIn("GROUP BY", extracted_sql.upper(), "Should contain GROUP BY")
        self.assertIn("ORDER BY", extracted_sql.upper(), "Should contain ORDER BY")

        # 验证SQL结构完整性
        is_complete = self.skillkit._validateSQLCompleteness(extracted_sql)
        self.assertTrue(is_complete, "Extracted SQL should be structurally complete")

        # 验证提取比例合理
        extraction_ratio = len(extracted_sql) / len(sql_with_join)
        self.assertGreater(
            extraction_ratio,
            0.8,
            f"Extraction ratio should be > 0.8 for this SQL, got {extraction_ratio}",
        )

    def test_extract_sql_chinese_characters_case(self):
        """测试包含中文字符的SQL解析"""
        sql_with_chinese = """SELECT
    CASE category
        WHEN '全渠道' THEN 1
        WHEN '线上' THEN 2
        WHEN '线下' THEN 3
        ELSE 4
    END AS sort_order,
    category,
    sales_amount
FROM sales_table
WHERE category IN ('全渠道', '线上', '线下')
ORDER BY sort_order"""

        # 提取SQL
        extracted_sql = self.skillkit._extractSQL(sql_with_chinese)
        print(f"Extracted SQL for Chinese character test:\n---\n{extracted_sql}\n---")

        # 验证中文字符被正确保留
        self.assertIn("全渠道", extracted_sql, "Should contain Chinese characters")
        self.assertIn("线上", extracted_sql, "Should contain Chinese characters")
        self.assertIn("线下", extracted_sql, "Should contain Chinese characters")

        # 验证SQL结构完整
        is_complete = self.skillkit._validateSQLCompleteness(extracted_sql)
        self.assertTrue(is_complete, "SQL with Chinese characters should be valid")

    def test_extract_sql_simple_chinese(self):
        """测试简单的带中文的SQL"""
        sql = "SELECT * FROM 表 WHERE 名称 = '值'"
        extracted_sql = self.skillkit._extractSQL(sql)
        self.assertEqual(extracted_sql, sql)
        is_complete = self.skillkit._validateSQLCompleteness(extracted_sql)
        self.assertTrue(is_complete, "Simple Chinese SQL should be valid")

    def test_oracle_preprocess_preserves_equals_with_double_quotes(self):
        """确保Oracle预处理将双引号值转为单引号，同时保留等号"""
        raw = 'SELECT 1 FROM dual WHERE region_desc="广东省"'
        processed = self.skillkit._preprocessSQL(raw, dialect="oracle")
        self.assertIn("region_desc='广东省'", processed)
        # 不应删除等号
        self.assertIn("=", processed.split("region_desc")[1])

    def test_oracle_preprocess_date_literals_and_no_nesting(self):
        """DATE 'YYYY-MM-DD' 保持不变，且不应嵌套 TO_DATE(TO_DATE(...))"""
        raw = (
            "SELECT * FROM dual WHERE d1 >= DATE '2025-03-01' "
            "AND d1 < DATE '2025-05-01' AND d2 = TO_DATE('2025-03-01', 'YYYY-MM-DD')"
        )
        processed = self.skillkit._preprocessSQL(raw, dialect="oracle")
        # 保留 ANSI DATE 字面量
        self.assertIn("DATE '2025-03-01'", processed)
        self.assertIn("DATE '2025-05-01'", processed)
        # 不嵌套 TO_DATE
        self.assertNotIn("DATE TO_DATE", processed.upper())
        self.assertNotIn("TO_DATE(TO_DATE", processed.upper())

    def test_user_oracle_sql_example_top5_cities(self):
        """用户提供的城市Top5贡献SQL应能被正确提取并校验结构完整"""
        sql = (
            "SELECT * FROM (\n"
            "    SELECT\n"
            "        O.DISTT_DESC AS city,\n"
            "        ROUND(((SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "                SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)) /\n"
            "               NULLIF(SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END), 0)) * 100, 2) AS growth_rate_pct,\n"
            "        (SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "         SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)) AS growth_amount,\n"
            "        ROUND(((SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "                SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)) /\n"
            "               NULLIF((SELECT SUM(CASE WHEN T2.MTH_IDNT = 202503 THEN S2.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "                              SUM(CASE WHEN T2.MTH_IDNT = 202502 THEN S2.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)\n"
            "                       FROM WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY S2\n"
            "                       JOIN WATSONS.DIM_ORGANIZATION O2 ON S2.LOC_IDNT = O2.LOC_IDNT\n"
            "                       JOIN WATSONS.DIM_PRODUCT P2 ON S2.ITEM_ID = P2.ITEM_IDNT\n"
            "                       JOIN WATSONS.DIM_TIME_DAY T2 ON S2.DEAL_DATE = T2.DAY_DT\n"
            "                       WHERE O2.REGN_DESC = '广东省' AND S2.ITEM_FLAG IN ('N', 'C') AND P2.IS_EXCL_SKU = 'N' \n"
            "                       AND S2.STATUS IN ('DISPATCHED', 'HAVESIGN', 'warehousingSuccess')), 0)) * 100, 2) AS contribution_pct,\n"
            "        '推动总体上涨' AS contribution_type\n"
            "    FROM\n"
            "        WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY S\n"
            "        JOIN WATSONS.DIM_ORGANIZATION O ON S.LOC_IDNT = O.LOC_IDNT\n"
            "        JOIN WATSONS.DIM_PRODUCT P ON S.ITEM_ID = P.ITEM_IDNT\n"
            "        JOIN WATSONS.DIM_TIME_DAY T ON S.DEAL_DATE = T.DAY_DT\n"
            "    WHERE\n"
            "        O.REGN_DESC = '广东省'\n"
            "        AND T.MTH_IDNT IN (202502, 202503)\n"
            "        AND S.ITEM_FLAG IN ('N', 'C')\n"
            "        AND P.IS_EXCL_SKU = 'N'\n"
            "        AND S.STATUS IN ('DISPATCHED', 'HAVESIGN', 'warehousingSuccess')\n"
            "    GROUP BY\n"
            "        O.DISTT_DESC\n"
            "    HAVING\n"
            "        SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) > \n"
            "        SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)\n"
            "    ORDER BY\n"
            "        contribution_pct DESC\n"
            ") WHERE ROWNUM <= 5"
        )

        extracted = self.skillkit._extractSQL(sql)
        self.assertGreater(len(extracted), 100)
        self.assertIn("FROM WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY S", extracted)
        self.assertIn("O.REGN_DESC = '广东省'", extracted)
        self.assertTrue(self.skillkit._validateSQLCompleteness(extracted))

        # Oracle预处理不应破坏等号
        processed = self.skillkit._preprocessSQL(extracted, dialect="oracle")
        self.assertIn("O.REGN_DESC = '广东省'", processed)
        self.assertFalse(
            processed.strip().endswith(","), "SQL should not end with a comma"
        )

    def test_user_oracle_sql_example_total_growth(self):
        """用户提供的总量增长SQL应能被正确提取并校验结构完整"""
        sql = (
            "SELECT \n"
            "    SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) AS sales_mar,\n"
            "    SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) AS sales_feb,\n"
            "    ROUND(((SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "            SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)) /\n"
            "           NULLIF(SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END), 0)) * 100, 2) AS growth_rate_pct,\n"
            "    (SUM(CASE WHEN T.MTH_IDNT = 202503 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END) - \n"
            "     SUM(CASE WHEN T.MTH_IDNT = 202502 THEN S.ORDER_2AF_AMT_EXCL_VAT ELSE 0 END)) AS growth_amount\n"
            "FROM\n"
            "    WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY S\n"
            "    JOIN WATSONS.DIM_ORGANIZATION O ON S.LOC_IDNT = O.LOC_IDNT\n"
            "    JOIN WATSONS.DIM_PRODUCT P ON S.ITEM_ID = P.ITEM_IDNT\n"
            "    JOIN WATSONS.DIM_TIME_DAY T ON S.DEAL_DATE = T.DAY_DT\n"
            "WHERE\n"
            "    O.REGN_DESC = '广东省'\n"
            "    AND T.MTH_IDNT IN (202502, 202503)\n"
            "    AND S.ITEM_FLAG IN ('N', 'C')\n"
            "    AND P.IS_EXCL_SKU = 'N'\n"
            "    AND S.STATUS IN ('DISPATCHED', 'HAVESIGN', 'warehousingSuccess')"
        )

        extracted = self.skillkit._extractSQL(sql)
        self.assertGreater(len(extracted), 100)
        self.assertIn(
            "FROM\n    WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY S", extracted
        )
        self.assertIn("O.REGN_DESC = '广东省'", extracted)
        self.assertTrue(self.skillkit._validateSQLCompleteness(extracted))

        processed = self.skillkit._preprocessSQL(extracted, dialect="oracle")
        self.assertIn("O.REGN_DESC = '广东省'", processed)
        self.assertFalse(processed.strip().endswith(","))

    def test_user_oracle_sql_with_cte_monthly_metrics(self):
        """用户提供的WITH CTE月度指标SQL应能被正确提取和校验"""
        sql = (
            "WITH\n"
            "financial_dates AS (\n"
            "    SELECT\n"
            "        DAY_DT,\n"
            "        MTH_IDNT\n"
            "    FROM\n"
            "        WATSONS.DIM_TIME_DAY\n"
            "    WHERE\n"
            "        MTH_IDNT IN (202507, 202508)\n"
            ")\n"
            "SELECT\n"
            "    dt.MTH_IDNT,\n"
            "    SUM(d.ORDER_2BF_AMT_EXCL_VAT) AS total_sales_amount,\n"
            "    COUNT(DISTINCT d.FINAL_SUB_ORDER_ID) AS total_orders,\n"
            "    SUM(d.ORDER_QTY) AS total_sales_qty,\n"
            "    SUM(d.ORDER_2BF_AMT_EXCL_VAT) / COUNT(DISTINCT d.FINAL_SUB_ORDER_ID) AS avg_order_value\n"
            "FROM\n"
            "    WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY d\n"
            "JOIN\n"
            "    WATSONS.DIM_ORGANIZATION o ON d.SALES_STORE_ID = o.LOC_IDNT\n"
            "JOIN\n"
            "    WATSONS.DIM_PRODUCT p ON d.ITEM_ID = p.ITEM_IDNT\n"
            "JOIN\n"
            "    financial_dates dt ON d.DEAL_DATE = dt.DAY_DT\n"
            "WHERE\n"
            "    d.ITEM_FLAG IN ('N', 'C')\n"
            "    AND p.IS_EXCL_SKU = 'N'\n"
            "    AND d.STATUS IN ('DISPATCHED', 'HAVESIGN', 'warehousingSuccess')\n"
            "    AND o.REGN_DESC = '吉林省'\n"
            "GROUP BY\n"
            "    dt.MTH_IDNT\n"
            "ORDER BY\n"
            "    dt.MTH_IDNT"
        )

        extracted = self.skillkit._extractSQL(sql)
        self.assertGreater(len(extracted), 200)
        self.assertTrue(self.skillkit._validateSQLCompleteness(extracted))
        # 关键片段应存在
        self.assertIn("WITH", extracted.upper())
        self.assertIn("FINANCIAL_DATES AS (", extracted.upper())
        self.assertIn(
            "FROM\n    WATSONS.DWS_ORDER_ITEM_STAFF_ORDER_BY_DAY D", extracted.upper()
        )
        self.assertIn(
            "JOIN\n    FINANCIAL_DATES DT ON D.DEAL_DATE = DT.DAY_DT", extracted.upper()
        )
        # 预处理不应破坏SQL
        processed = self.skillkit._preprocessSQL(extracted, dialect="oracle")
        self.assertTrue(self.skillkit._validateSQLCompleteness(processed))


if __name__ == "__main__":
    unittest.main()
