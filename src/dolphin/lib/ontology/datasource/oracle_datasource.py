from typing import Any, Dict, List, Optional
import re
import datetime

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

# Add NullPool import
from sqlalchemy.pool import NullPool

from dolphin.core.common.enums import Messages
from dolphin.lib.ontology.datasource.datasource import DataSourceType
from dolphin.lib.ontology.datasource.sql import DataSourceSql

from dolphin.core.logging.logger import get_logger

logger = get_logger("ontology")


def _camelCase(s: str) -> str:
    """Convert a string separated by underscores or spaces to camel case"""
    s = re.sub(r"[_\-]+", " ", s).title().replace(" ", "")
    return s[0].lower() + s[1:] if s else ""


class DataSourceOracle(DataSourceSql):
    """Oracle data source implementation"""

    def __init__(self, name: str, config: Dict[str, Any]):
        # Pass the correct type DataSourceType.ORACLE
        super().__init__(name, DataSourceType.ORACLE, config)
        self._type = DataSourceType.ORACLE  # Store specific types
        # The default Oracle port is 1521
        self.port = config.get("port", 1521)

    def connect(self) -> Engine:
        """Connect to Oracle Database"""
        if self._engine:
            logger.debug(f"Already connected to {self.name} , reconnecting")
            self.close()

        try:
            # Using python-oracledb's thin mode, no local Oracle Client required
            import oracledb  # Import only when needed

            try:
                # Explicitly disable thick mode to avoid searching for local Client
                oracledb.defaults.thick_mode = False
            except Exception:
                pass

            # Build SQLAlchemy connection URL (oracle+oracledb dialect)
            # Prioritize using service_name，then SID；if neither configured, treat database as service_name
            service_name = (
                self.config.get("service_name") or self.config.get("service") or None
            )
            sid = self.config.get("sid")

            if service_name:
                connection_url = (
                    f"oracle+oracledb://{self.username}:{self.password}@{self.host}:{self.port}"
                    f"/?service_name={service_name}"
                )
            elif sid:
                connection_url = (
                    f"oracle+oracledb://{self.username}:{self.password}@{self.host}:{self.port}"
                    f"/?sid={sid}"
                )
            elif self.database:
                connection_url = (
                    f"oracle+oracledb://{self.username}:{self.password}@{self.host}:{self.port}"
                    f"/?service_name={self.database}"
                )
            else:
                connection_url = f"oracle+oracledb://{self.username}:{self.password}@{self.host}:{self.port}"

            # Disable connection pooling using NullPool
            self._engine = create_engine(
                connection_url,
                poolclass=NullPool,  # Disable connection pooling
            )

            self._inspector = inspect(self._engine)
            logger.info(f"Successfully connected to Oracle database: {self.name}")
            return self._engine
        except ImportError:
            logger.error(
                f"connect to Oracle database {self.name}  failed: missing 'oracledb'  library. Please run 'pip install oracledb'"
            )
            self._engine = None
            raise ConnectionError(f"Missing Oracle driver: {self.name}")
        except Exception as e:  # Other unexpected errors
            # If available, try to identify the database error types of oracledb
            try:
                import oracledb as _odb

                if isinstance(e, _odb.Error):
                    logger.error(f"connect to Oracle databasefailed {self.name}: {e}")
                    self._engine = None
                    raise ConnectionError(f"无法connect to到 Oracle database: {self.name}, {e}")
            except Exception:
                pass

            logger.error(f"connect to Oracle  unknown error occurred {self.name}: {e}")
            self._engine = None
            raise ConnectionError(f"connect to Oracle  unknown error occurred: {self.name}, {e}")

    def test_connection(self) -> bool:
        """Test Oracle connection, using DUAL for Oracle compatibility.

        Returns:
            bool: True if the connection is successful, False otherwise.
        """
        originalConnectionState = self._engine
        connToClose = None
        try:
            if not self._engine:
                connToClose = self.connect()
            if not self._engine:
                logger.warning(f"测试connect to {self.name} failed：无法建立connect to")
                return False
            # Oracle requires FROM DUAL
            self.executeQuery("SELECT 1 FROM DUAL", fetchColumns=False)
            logger.info(f"测试connect to {self.name} successful")
            return True
        except Exception as e:
            logger.error(f"测试connect tofailed {self.name}: {e}")
            return False
        finally:
            # If the connection is temporarily established for testing, close it.
            if connToClose and connToClose == self._engine:
                self.close()
            # Restore the original connection status (if there was already a connection before the test)
            elif originalConnectionState and not self._engine:
                self._engine = originalConnectionState

    def get_schema(self) -> Dict[str, List[Dict[str, str]]]:
        """Get Oracle database schema information (table name -> list of column information).

        Returns:
            dict: A mapping of table name to column info list.
        """
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
                if not conn:  # If conn was not successfully established previously
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
                    # 'type' is usually a SQLAlchemy type object, which needs to be converted to a string.
                    col_name = column_data.get("name")
                    col_type_obj = column_data.get("type")

                    if col_name and col_type_obj is not None:  # Ensure column names and types exist
                        # Convert SQLAlchemy type objects to their string representations
                        # For example: VARCHAR2(length=50), NUMBER(precision=10, scale=2), DATE
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
            logger.error(f"Get Oracle 模式failed {self.name}: {err}")
            # Ensure that if the connection is temporarily open, it will be closed when an error occurs
            if (
                should_close_conn and conn and conn == self._engine
            ):  # If this connection was specifically opened for this method
                conn.dispose()
                self._engine = None  # Reset engine state
                self._inspector = None  # Reset inspector
            raise RuntimeError(f"Get Oracle 模式failed: {err}") from err
        finally:
            if should_close_conn and conn:
                if conn == self._engine:  # Only close when this method creates self._engine
                    conn.dispose()
                    self._engine = None
                    self._inspector = None  # Also clear the inspector
                elif conn != self._engine:  # If it's a temporarily created conn and not self._engine
                    conn.dispose()

    def sampleData(self, conceptName: str, count: int = 10) -> Messages:
        """Retrieve sample data from an Oracle data source for a specified Concept name.

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

            # Oracle uses double quotes to quote identifiers, supporting case sensitivity
            quoted_column_names_str = ", ".join(
                [f'"{col}"' for col in actual_column_names]
            )
            # Oracle limits rows using ROWNUM or FETCH FIRST (Oracle 12c+)
            # ROWNUM method with better compatibility is used here
            sql_query = f'SELECT {quoted_column_names_str} FROM "{target_table_name}" WHERE ROWNUM <= {count}'

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
