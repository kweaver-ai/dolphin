from .datasource import DataSource

# 延迟导入 SQL 相关的数据源类（需要 sqlalchemy）
# 如果 sqlalchemy 未安装，这些类将不可用，但不会阻止模块导入
try:
    from .sql import DataSourceSql, DataSourceMysql, DataSourceSqlite
    from .oracle_datasource import DataSourceOracle
    _SQL_AVAILABLE = True
except ImportError:
    # sqlalchemy 未安装，这些类不可用
    _SQL_AVAILABLE = False
    DataSourceSql = None
    DataSourceMysql = None
    DataSourceSqlite = None
    DataSourceOracle = None

__all__ = [
    "DataSource",
]

if _SQL_AVAILABLE:
    __all__.extend([
        "DataSourceSql",
        "DataSourceMysql",
        "DataSourceSqlite",
        "DataSourceOracle",
    ])
