from abc import abstractmethod
from typing import Any, Dict, List, Optional
import re
import datetime

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

# Add NullPool import
from sqlalchemy.pool import NullPool

from dolphin.core.common.enums import Messages
from dolphin.lib.ontology.basic.concept import ConceptMemberType, Concept
from dolphin.lib.ontology.mapping import Mapping
from dolphin.lib.ontology.datasource.datasource import DataSource
from dolphin.lib.ontology.datasource.datasource import DataSourceType

from dolphin.core.logging.logger import get_logger

logger = get_logger("ontology")


def _camelCase(s: str) -> str:
    """Convert a string separated by underscores or spaces to camel case.

    Args:
        s: The input string to convert.

    Returns:
        The camel case version of the input string.
    """
    s = re.sub(r"[_\-]+", " ", s).title().replace(" ", "")
    return s[0].lower() + s[1:] if s else ""


class DataSourceSql(DataSource):
    """Base class for SQL type data sources, using SQLAlchemy"""

    def __init__(self, name: str, type: DataSourceType, config: Dict[str, Any]):
        super().__init__(name, type, config)
        self._engine: Engine = None
        self._inspector = None
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 3306)  # Default MySQL port
        self.username = config.get("username")
        self.password = config.get("password")
        self.database = config.get("database")

    @property
    def type(self) -> DataSourceType:
        return self._type  # Return the stored type

    @abstractmethod
    def connect(self) -> Engine:
        """Establish database connection"""
        pass

    @abstractmethod
    def get_schema(self) -> Dict[str, List[Dict[str, str]]]:
        """Get database schema (table name -> list of column info, each column info is {'name': column name, 'type': type string})"""
        pass

    def close(self) -> None:
        """Close database connection"""
        if self._engine:
            try:
                self._engine.dispose()
                logger.info(f"databaseconnect to已关闭: {self.name}")
                self._engine = None
            except Exception as e:
                logger.error(f"关闭databaseconnect to时出错 {self.name}: {e}")
        else:
            logger.warning(f"尝试关闭一个未建立或已关闭的connect to: {self.name}")

    def test_connection(self) -> bool:
        """Test whether the database connection is successful"""
        originalConnectionState = self._engine
        connToClose = None
        try:
            if not self._engine:
                connToClose = self.connect()
            if not self._engine:
                logger.warning(f"测试connect to {self.name} failed：无法建立connect to")
                return False
            # Simple test query
            self.executeQuery(
                "SELECT 1", fetchColumns=False
            )  # test_connection does not care about the result
            logger.info(f"测试connect to {self.name} successful")
            return True
        except Exception as e:
            logger.error(f"测试connect tofailed {self.name}: {e}")
            return False
        finally:
            # If the connection is temporarily established for testing purposes, close it.
            if connToClose and connToClose == self._engine:
                self.close()
            # Restore the original connection status (if there was already a connection before the test)
            elif originalConnectionState and not self._engine:
                self._engine = originalConnectionState  # Avoid affecting subsequent operations

    # SQL-specific methods can be added, such as executing SQL statements
    def executeQuery(self, query: str, fetchColumns: bool = True) -> Dict[str, Any]:
        """Execute an SQL query and return the results.

        Args:
            query (str): The SQL query statement to execute
            fetchColumns (bool): Whether to retrieve column name information, default is True

        Returns:
            Dict[str, Any]: A dictionary containing the query results and column names (if fetchColumns is True)
        """
        conn = self._engine
        shouldCloseConn = False
        if not conn:
            conn = self.connect()
            if not conn:
                raise ConnectionError(f"无法connect to到database: {self.name}")
            shouldCloseConn = True  # If it's a temporary connection, close it after use.

        cursor = None
        try:
            cursor = conn.connect().execute(text(query))
            results = cursor.fetchall()
            if fetchColumns:
                # Use cursor.keys() to get column names from SQLAlchemy's Result object
                # The Result object (cursor) itself doesn't have a 'description' attribute directly
                columns = list(cursor.keys())
                return {"columns": columns, "data": results}
            return {
                "columns": [],
                "data": results,
            }  # Return empty columns if not fetching
        except Exception as e:
            logger.error(f"Error executing query on {self.name}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if shouldCloseConn and conn:
                conn.dispose()
                if conn == self._engine:
                    self._engine = None  # Ensure internal state consistency

    def _map_db_type_to_concept_type(self, db_type_full: str) -> ConceptMemberType:
        """Map database-specific column type strings to ConceptMemberType.

Args:
    column_type (str): The database-specific column type string.
Returns:
    ConceptMemberType: The corresponding ConceptMemberType."""
        logger.debug(
            f"Mapping DB type: Original='{db_type_full}', Type='{type(db_type_full)}'"
        )
        try:
            if not db_type_full or not isinstance(
                db_type_full, str
            ):  # Ensure it's a non-empty string
                logger.warning(
                    f"Invalid db_type_full: '{db_type_full}'. Defaulting to ANY."
                )
                return ConceptMemberType.ANY

            # Extract the main type part before the parentheses and convert it to lowercase
            db_type_main = db_type_full.split("(")[0].strip().lower()

            result_type = ConceptMemberType.ANY  # Default

            if (
                "char" in db_type_main
                or "varchar" in db_type_main
                or "varchar2" in db_type_main  # Oracle VARCHAR2
                or "text" in db_type_main
                or "string" in db_type_main
                or "enum" in db_type_main
                or "set" in db_type_main
                or "clob" in db_type_main  # Oracle CLOB
            ):
                result_type = ConceptMemberType.STRING
            elif (
                "int" in db_type_main
                or "integer" in db_type_main
                or "tinyint" in db_type_main
                or "smallint" in db_type_main
                or "mediumint" in db_type_main
                or "bigint" in db_type_main
            ):
                result_type = ConceptMemberType.NUMBER
            elif (
                "float" in db_type_main
                or "double" in db_type_main
                or "decimal" in db_type_main
                or "numeric" in db_type_main
                or "real" in db_type_main
                or "number" in db_type_main  # Oracle NUMBER type
            ):
                result_type = ConceptMemberType.NUMBER
            elif "bool" in db_type_main or "boolean" in db_type_main:
                result_type = ConceptMemberType.BOOLEAN
            elif (
                "date" in db_type_main
                or "datetime" in db_type_main
                or "timestamp" in db_type_main
                or "time" in db_type_main
                or "year" in db_type_main
            ):
                result_type = (
                    ConceptMemberType.STRING
                )  # Or a more specific date/time type if available
            elif "json" in db_type_main:
                result_type = (
                    ConceptMemberType.STRING
                )  # Or OBJECT if handling structured JSON

            if (
                result_type == ConceptMemberType.ANY
                and db_type_main
                not in [
                    "unknown",
                    "",
                ]
            ):  # Log if no specific mapping found, unless it was already 'unknown' or empty
                logger.warning(
                    f"Unknown DB type: '{db_type_full}' (main: '{db_type_main}'), defaulted to ANY."
                )

            logger.debug(
                f"Mapped DB type '{db_type_full}' to ConceptMemberType '{result_type.name if result_type else 'None'}' (Python type: {type(result_type)})"
            )
            return result_type
        except Exception as e:
            logger.error(
                f"Error mapping DB type '{db_type_full}': {e}. Defaulting to ANY.",
                exc_info=True,
            )
            return ConceptMemberType.ANY

    def scan(self) -> List[Mapping]:
        """Scan SQL database schema and generate Concept and Mapping for each table"""
        logger.info(f"Starting to scan data source: {self.name}")
        mappings = []
        try:
            schema = self.get_schema()
            if not schema:
                logger.warning(f"无法Get数据源 {self.name}  schema 信息")
                return []

            for table_name, columns_details in schema.items():
                # 1. Create Concept
                concept_name = _camelCase(table_name).capitalize()

                members = {}
                valid_columns_for_mapping = []
                if not columns_details:
                    logger.warning(
                        f"表 '{table_name}' 在 {self.name} 中没有列信息，跳过"
                    )
                    continue

                for col_detail in columns_details:
                    col_name = col_detail.get("name")
                    col_type_str = col_detail.get("type")

                    if not col_name:  # Skip entries without column names
                        logger.debug(
                            f"Skipping column with no name in table '{table_name}'. Detail: {col_detail}"
                        )
                        continue

                    member_name = _camelCase(col_name)
                    member_type = self._map_db_type_to_concept_type(col_type_str)
                    members[member_name] = member_type
                    valid_columns_for_mapping.append(col_name)

                if not members:
                    logger.warning(
                        f"表 '{table_name}' 在 {self.name} 中没有可转换为成员的有效列，跳过创建 Concept"
                    )
                    continue

                try:
                    concept = Concept(name=concept_name, members=members)
                    logger.debug(
                        f"为表 '{table_name}' 创建了 Concept: {concept_name} with members: {members}"
                    )
                except ValueError as e:
                    logger.error(
                        f"为表 '{table_name}' 创建 Concept '{concept_name}' failed: {e}"
                    )
                    continue

                # 2. Create Mapping
                # Field to member mapping: column name -> camelCase member name
                # Use valid_columns_for_mapping to ensure only existing columns are mapped
                fieldToMemberMap = {
                    col: _camelCase(col) for col in valid_columns_for_mapping
                }
                if not fieldToMemberMap:  # Theoretically, if members has content, there should also be content here
                    logger.warning(
                        f"表 '{table_name}' 在 {self.name} 中没有有效列名可映射，跳过创建 Mapping"
                    )
                    continue

                try:
                    mapping = Mapping(
                        dataSource=self,
                        space=table_name,
                        concept=concept,
                        fieldToMemberMap=fieldToMemberMap,
                    )
                    mappings.append(mapping)
                    logger.debug(f"为 Concept '{concept_name}' 创建了 Mapping")
                except (ValueError, TypeError) as e:
                    logger.error(f"为 Concept '{concept_name}' 创建 Mapping failed: {e}")

            logger.info(
                f"数据源 {self.name} 扫描完成，生成了 {len(mappings)} 个 Mappings"
            )
            return mappings

        except ConnectionError as e:
            logger.error(f"扫描数据源 {self.name} failed：connect to错误 {e}")
            return []
        except Exception as e:
            logger.error(f"扫描数据源 {self.name} 时发生意外错误: {e}")
            # Consider throwing an exception or returning an empty list
            return []


class DataSourceMysql(DataSourceSql):
    """MySQL Data Source Implementation"""

    def __init__(self, name: str, config: Dict[str, Any]):
        # Pass the correct type directly DataSourceType.MYSQL
        super().__init__(name, DataSourceType.MYSQL, config)
        self._type = DataSourceType.MYSQL  # Store specific types

    def connect(self) -> Engine:
        """Connect to MySQL database"""
        if self._engine:
            logger.debug(f"Already connected to {self.name} , reconnecting")
            self.close()

        try:
            # Use pymysql to connect to MySQL database
            # Make sure to install: pip install pymysql
            import pymysql  # Move here, import only when needed

            # Modify the connection method to disable the connection pool for the test environment
            connection_url = f"mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}"

            # Use NullPool to disable connection pooling, or use a more appropriate connection pool configuration
            # In testing environments, it is usually simpler and more reliable to disable connection pooling.
            self._engine = create_engine(
                connection_url,
                poolclass=NullPool,  # Disable connection pooling
            )

            self._inspector = inspect(self._engine)
            logger.info(f"Successfully connected to MySQL database: {self.name}")
            return self._engine
        except ImportError:
            logger.error(
                f"connect to MySQL database {self.name}  failed: missing 'mysql-connector-python'  library. Please run 'pip install mysql-connector-python'"
            )
            self._engine = None
            raise ConnectionError(f"缺少 MySQL 驱动: {self.name}")
        except pymysql.Error as err:  # Catch specific database connection errors
            logger.error(f"connect to MySQL databasefailed {self.name}: {err}")
            self._engine = None
            raise ConnectionError(f"无法connect to到 MySQL database: {self.name}, {err}")
        except Exception as e:  # Other unexpected errors
            logger.error(f"connect to MySQL  unknown error occurred {self.name}: {e}")
            self._engine = None
            raise ConnectionError(f"connect to MySQL  unknown error occurred: {self.name}, {e}")

    def get_schema(self) -> Dict[str, List[Dict[str, str]]]:
        """Get MySQL database schema information (table name -> list of column information)"""
        if self.schema:
            return self.schema

        conn = self._engine
        should_close_conn = False
        if not conn:
            conn = self.connect()  # Try to connect
            if not conn:
                raise ConnectionError(f"无法Get模式，database未connect to: {self.name}")
            should_close_conn = True

        schema: Dict[str, List[Dict[str, str]]] = {}
        cursor = None
        try:
            # Use self._inspector to get the table name, which is more in line with SQLAlchemy's approach
            if not self._inspector:  # Ensure inspector exists
                if not conn:  # If conn was not previously established successfully
                    conn = self.connect()
                    if not conn:
                        raise ConnectionError(
                            f"无法Get模式，database未connect to: {self.name}"
                        )
                self._inspector = inspect(conn)

            tables = self._inspector.get_table_names()

            # Get column names and types for each table
            for table_name in tables:
                # Use self._inspector to get column information
                columns_info = self._inspector.get_columns(table_name)

                current_table_cols = []
                for column_data in columns_info:
                    # column_data is a dictionary containing keys such as 'name', 'type', 'nullable', 'default'
                    # 'type' is usually a SQLAlchemy type object, which needs to be converted to a string.
                    col_name = column_data.get("name")
                    col_type_obj = column_data.get("type")

                    if col_name and col_type_obj is not None:  # Ensure that column names and types exist
                        # Convert SQLAlchemy type objects to their string representations
                        # For example: VARCHAR(length=50), INTEGER(), NUMERIC(precision=10, scale=2)
                        col_type_str = str(col_type_obj).replace(
                            ' COLLATE "utf8mb4_unicode_ci"', ""
                        )
                        current_table_cols.append(
                            {"name": col_name, "type": col_type_str}
                        )
                    elif col_name:  # Unknown type, but column name exists
                        current_table_cols.append(
                            {"name": col_name, "type": "UNKNOWN"}
                        )  # Or record a default value
                        logger.warning(
                            f"Column '{col_name}' in table '{table_name}' has an unknown type."
                        )

                if current_table_cols:  # Only add to schema when the table has columns
                    schema[table_name] = current_table_cols
                else:
                    logger.info(
                        f"Table '{table_name}' has no columns or columns could not be retrieved."
                    )

            logger.debug(f"Get到 {self.name}  schema: {len(schema)}  tables")
            self.schema = schema
            return schema
        except Exception as err:  # Catch all database-related errors
            logger.error(f"Get MySQL 模式failed {self.name}: {err}")
            # Ensure that if the connection is temporarily open, it will be closed when an error occurs.
            # Instead of relying on the caller (such as scan) to handle it
            if (
                should_close_conn and conn and conn == self._engine
            ):  # If this connection was specifically opened for this method
                conn.dispose()
                self._engine = None  # Reset engine state
                self._inspector = None  # Reset inspector
            raise RuntimeError(f"Get MySQL 模式failed: {err}") from err
        finally:
            # The cursor is no longer directly managed at this method level, as methods such as inspector.get_columns handle the cursor internally.
            # if cursor:
            #     cursor.close()
            if should_close_conn and conn:
                if conn == self._engine:  # Only close when this method creates self._engine
                    conn.dispose()
                    self._engine = None
                    self._inspector = None  # Also clear the inspector
                elif conn != self._engine:  # If it's a temporarily created conn and not self._engine
                    conn.dispose()

    def sampleData(self, conceptName: str, count: int = 10) -> Messages:
        """Retrieve sample data from a MySQL data source for the specified Concept name.

                It converts the Concept name back to a possible table name (assuming the naming convention used in the scan method),
                then queries that table to retrieve the specified number of sample rows.

        Args:
            conceptName (str): The name of the Concept for which to retrieve sample data.
            count (int): The number of sample rows to retrieve, defaults to 10.

        Returns:
            Messages: A list of dictionaries, each representing a row of data,
                                          where keys are column names and values are corresponding data.
                                          Returns an empty list if the Concept is not found or an error occurs.
        """
        if count <= 0:
            logger.info(
                f"Sample count is {count}, returning empty list for concept '{conceptName}' in {self.name}."
            )
            return []

        target_table_name: Optional[str] = None
        actual_column_names: List[str] = []

        try:
            db_schema = self.get_schema()  # This might connect if not connected.
            if not db_schema:
                logger.warning(
                    f"Could not retrieve schema for {self.name} to find concept '{conceptName}'."
                )
                return []

            for table_name_from_schema, columns_details in db_schema.items():
                # Ensure table_name_from_schema is a string for _camelCase
                if not isinstance(table_name_from_schema, str):
                    logger.warning(
                        f"Skipping non-string table name in schema: {table_name_from_schema}"
                    )
                    continue

                generated_concept_name = _camelCase(table_name_from_schema).capitalize()
                if generated_concept_name == conceptName:
                    target_table_name = table_name_from_schema
                    actual_column_names = [
                        col_info["name"]
                        for col_info in columns_details
                        if col_info.get("name")
                    ]
                    if not actual_column_names:
                        logger.warning(
                            f"Concept '{conceptName}' (Table '{target_table_name}') found in {self.name} but has no columns. Cannot sample data."
                        )
                        return []  # Cannot select data if no columns
                    break  # Found the table

            if not target_table_name:
                logger.warning(
                    f"Concept '{conceptName}' not found as a discoverable table in datasource '{self.name}'."
                )
                return []

            # Quoting column names and table name for the SQL query
            quoted_column_names_str = ", ".join(
                [f"`{col}`" for col in actual_column_names]
            )
            # Ensure target_table_name is just the name, not schema.name, etc.
            # get_schema() returns table names as keys, so this should be fine.
            sql_query = f"SELECT {quoted_column_names_str} FROM `{target_table_name}` LIMIT {count}"

            logger.debug(
                f"Executing sample data query for concept '{conceptName}' on {self.name}: {sql_query}"
            )
            query_result = self.executeQuery(
                sql_query
            )  # fetchColumns is True by default

            result_columns = query_result.get("columns", [])
            result_data_rows = query_result.get("data", [])

            if not result_columns and result_data_rows:
                logger.warning(
                    f"Query for concept '{conceptName}' in {self.name} returned data but no column names. This might indicate an issue with executeQuery or the underlying table structure."
                )
                # Attempt to use actual_column_names if order and count match, but this is risky.
                # Sticking to result_columns from executeQuery is safer.

            formatted_samples: Messages = []
            for row_tuple in result_data_rows:
                processed_row = []
                for item in row_tuple:
                    if isinstance(
                        item, (datetime.datetime, datetime.date, datetime.time)
                    ):
                        processed_row.append(item.isoformat())
                    else:
                        processed_row.append(item)

                if len(processed_row) == len(result_columns):
                    formatted_samples.append(dict(zip(result_columns, processed_row)))
                else:
                    logger.warning(
                        f"Row data length mismatch for concept '{conceptName}' in {self.name}. "
                        f"Expected {len(result_columns)} columns based on query result, got {len(processed_row)}. Row: {processed_row}"
                    )
            return formatted_samples

        except ConnectionError as ce:
            logger.error(
                f"Connection error while fetching sample data for concept '{conceptName}' from {self.name}: {ce}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error fetching sample data for concept '{conceptName}' (table: {target_table_name or 'unknown'}) from {self.name}: {e}",
                exc_info=True,
            )
            return []

    # Can add MySQL-specific methods, such as executing MySQL-specific queries
    def execute_mysql_specific_query(self, query: str) -> Dict[str, Any]:
        """Execute a MySQL-specific query and return the results"""
        if not self._engine:
            self.connect()
        if not self._engine:
            raise ConnectionError(f"无法connect to到database: {self.name}")

        cursor = None
        try:
            cursor = self._engine.connect().execute(text(query))
            results = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return {"columns": columns, "data": results}
        except Exception as e:
            logger.error(f"执行 MySQL 特定查询时出错 on {self.name}: {e}")
            raise
        finally:
            if cursor:
                cursor.close()


class DataSourceSqlite(DataSourceSql):
    """SQLite Data Source Implementation"""

    def __init__(self, name: str, config: Dict[str, Any]):
        # Pass the correct type DataSourceType.SQLITE directly
        super().__init__(name, DataSourceType.SQLITE, config)
        self._type = DataSourceType.SQLITE  # Store specific types
        # SQLite only needs the database file path
        self.database_path = config.get(
            "database",
            config.get("path", config.get("file_path", config.get("database_path"))),
        )
        if not self.database_path:
            raise ValueError("SQLite 数据源配置缺少database文件路径")

    def connect(self) -> Engine:
        """Connect to SQLite database"""
        if self._engine:
            logger.debug(f"Already connected to {self.name} , reconnecting")
            self.close()

        try:
            # Using SQLite connection strings
            connection_url = f"sqlite:///{self.database_path}"

            # Use NullPool to disable connection pooling, which is simpler and more reliable in testing environments.
            self._engine = create_engine(
                connection_url,
                poolclass=NullPool,  # Disable connection pooling
            )

            self._inspector = inspect(self._engine)
            logger.info(
                f"Successfully connected to SQLite database: {self.name} at {self.database_path}"
            )
            return self._engine
        except Exception as e:
            logger.error(f"connect to SQLite databasefailed {self.name}: {e}")
            self._engine = None
            raise ConnectionError(f"无法connect to到 SQLite database: {self.name}, {e}")

    def get_schema(self) -> Dict[str, List[Dict[str, str]]]:
        """Get schema information of SQLite database (table name -> list of column information)"""
        if self.schema:
            return self.schema

        conn = self._engine
        should_close_conn = False
        if not conn:
            conn = self.connect()  # Try to connect
            if not conn:
                raise ConnectionError(f"无法Get模式，database未connect to: {self.name}")
            should_close_conn = True

        schema: Dict[str, List[Dict[str, str]]] = {}
        try:
            # Use self._inspector to get the table name, which is more in line with SQLAlchemy's approach
            if not self._inspector:  # Ensure inspector exists
                if not conn:  # If conn was not previously established successfully
                    conn = self.connect()
                    if not conn:
                        raise ConnectionError(
                            f"无法Get模式，database未connect to: {self.name}"
                        )
                self._inspector = inspect(conn)

            tables = self._inspector.get_table_names()

            # Get column names and types for each table
            for table_name in tables:
                # Use self._inspector to get column information
                columns_info = self._inspector.get_columns(table_name)

                current_table_cols = []
                for column_data in columns_info:
                    # column_data is a dictionary containing keys such as 'name', 'type', 'nullable', 'default', etc.
                    # 'type' is usually a SQLAlchemy type object, which needs to be converted to a string
                    col_name = column_data.get("name")
                    col_type_obj = column_data.get("type")

                    if col_name and col_type_obj is not None:  # Ensure that column names and types exist
                        # Convert SQLAlchemy type objects to their string representation
                        col_type_str = str(col_type_obj)
                        current_table_cols.append(
                            {"name": col_name, "type": col_type_str}
                        )
                    elif col_name:  # Unknown type, but column name exists
                        current_table_cols.append(
                            {"name": col_name, "type": "UNKNOWN"}
                        )  # Or record a default value
                        logger.warning(
                            f"Column '{col_name}' in table '{table_name}' has an unknown type."
                        )

                if current_table_cols:  # Only add to schema when the table has columns
                    schema[table_name] = current_table_cols
                else:
                    logger.info(
                        f"Table '{table_name}' has no columns or columns could not be retrieved."
                    )

            logger.debug(f"Get到 {self.name}  schema: {len(schema)}  tables")
            self.schema = schema
            return schema
        except Exception as err:  # Catch all database-related errors
            logger.error(f"Get SQLite 模式failed {self.name}: {err}")
            # Ensure that if the connection is temporarily open, it will be closed when an error occurs.
            if (
                should_close_conn and conn and conn == self._engine
            ):  # If this connection was specifically opened for this method
                conn.dispose()
                self._engine = None  # Reset engine state
                self._inspector = None  # Reset inspector
            raise RuntimeError(f"Get SQLite 模式failed: {err}") from err
        finally:
            if should_close_conn and conn:
                if conn == self._engine:  # Only close when this method creates self._engine
                    conn.dispose()
                    self._engine = None
                    self._inspector = None  # Also clear the inspector
                elif conn != self._engine:  # If it's a temporarily created conn and not self._engine
                    conn.dispose()

    def sampleData(self, conceptName: str, count: int = 10) -> Messages:
        """Retrieve sample data from an SQLite data source for a specified Concept name.

        It converts the Concept name back to a possible table name (assuming the naming convention used in the scan method),
        then queries that table to retrieve the specified number of sample rows.

        Args:
            conceptName (str): The name of the Concept for which to retrieve sample data.
            count (int): The number of sample rows to retrieve, defaults to 10.

        Returns:
            Messages: A list of dictionaries, each representing a row of data,
                      where keys are column names and values are corresponding data.
                      Returns an empty list if the Concept is not found or an error occurs.
        """
        if count <= 0:
            logger.info(
                f"Sample count is {count}, returning empty list for concept '{conceptName}' in {self.name}."
            )
            return []

        target_table_name: Optional[str] = None
        actual_column_names: List[str] = []

        try:
            db_schema = self.get_schema()  # This might connect if not connected.
            if not db_schema:
                logger.warning(
                    f"Could not retrieve schema for {self.name} to find concept '{conceptName}'."
                )
                return []

            for table_name_from_schema, columns_details in db_schema.items():
                # Ensure table_name_from_schema is a string for _camelCase
                if not isinstance(table_name_from_schema, str):
                    logger.warning(
                        f"Skipping non-string table name in schema: {table_name_from_schema}"
                    )
                    continue

                generated_concept_name = _camelCase(table_name_from_schema).capitalize()
                if generated_concept_name == conceptName:
                    target_table_name = table_name_from_schema
                    actual_column_names = [
                        col_info["name"]
                        for col_info in columns_details
                        if col_info.get("name")
                    ]
                    if not actual_column_names:
                        logger.warning(
                            f"Concept '{conceptName}' (Table '{target_table_name}') found in {self.name} but has no columns. Cannot sample data."
                        )
                        return []  # Cannot select data if no columns
                    break  # Found the table

            if not target_table_name:
                logger.warning(
                    f"Concept '{conceptName}' not found as a discoverable table in datasource '{self.name}'."
                )
                return []

            # SQLite uses double quotes or square brackets to quote identifiers, but special quoting is usually not needed.
            quoted_column_names_str = ", ".join(
                [f'"{col}"' for col in actual_column_names]
            )
            sql_query = f'SELECT {quoted_column_names_str} FROM "{target_table_name}" LIMIT {count}'

            logger.debug(
                f"Executing sample data query for concept '{conceptName}' on {self.name}: {sql_query}"
            )
            query_result = self.executeQuery(
                sql_query
            )  # fetchColumns is True by default

            result_columns = query_result.get("columns", [])
            result_data_rows = query_result.get("data", [])

            if not result_columns and result_data_rows:
                logger.warning(
                    f"Query for concept '{conceptName}' in {self.name} returned data but no column names. This might indicate an issue with executeQuery or the underlying table structure."
                )

            formatted_samples: Messages = []
            for row_tuple in result_data_rows:
                processed_row = []
                for item in row_tuple:
                    if isinstance(
                        item, (datetime.datetime, datetime.date, datetime.time)
                    ):
                        processed_row.append(item.isoformat())
                    else:
                        processed_row.append(item)

                if len(processed_row) == len(result_columns):
                    formatted_samples.append(dict(zip(result_columns, processed_row)))
                else:
                    logger.warning(
                        f"Row data length mismatch for concept '{conceptName}' in {self.name}. "
                        f"Expected {len(result_columns)} columns based on query result, got {len(processed_row)}. Row: {processed_row}"
                    )
            return formatted_samples

        except ConnectionError as ce:
            logger.error(
                f"Connection error while fetching sample data for concept '{conceptName}' from {self.name}: {ce}"
            )
            return []
        except Exception as e:
            logger.error(
                f"Error fetching sample data for concept '{conceptName}' (table: {target_table_name or 'unknown'}) from {self.name}: {e}",
                exc_info=True,
            )
            return []


# Import Oracle datasource
