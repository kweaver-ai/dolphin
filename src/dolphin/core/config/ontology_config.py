from enum import Enum
from typing import List


class DataSourceType(Enum):
    MYSQL = 0
    SQLITE = 1
    ORACLE = 2
    # More data source types can be added in the future


class DataSourceConfig:
    def __init__(
        self,
        name: str,
        type: DataSourceType,
        host: str = None,
        port: int = None,
        username: str = None,
        password: str = None,
        database: str = None,
        additional_params: dict = None,
    ):
        self.name = name
        self.type = type
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.database = database
        self.additional_params = additional_params or {}

    @classmethod
    def from_dict(cls, config: dict):
        if not config:
            return None

        name = config.get("name")
        typeStr = config.get("type")

        if not name or not typeStr:
            raise Exception("数据源配置缺少必要字段: name 或 type")

        # Convert type string to DataSourceType enum
        try:
            dataSourceType = DataSourceType[typeStr.upper()]
        except KeyError:
            raise Exception(f"不支持的数据源类型: {typeStr}")

        # Get basic configuration
        host = config.get("host")
        port = config.get("port")
        username = config.get("username")
        password = config.get("password")
        database = config.get("database")

        # SQLite special handling: supports path, file_path, database_path as database paths
        if dataSourceType == DataSourceType.SQLITE:
            if not database:
                database = (
                    config.get("path")
                    or config.get("file_path")
                    or config.get("database_path")
                )
            if not database:
                raise Exception(
                    "SQLite 数据源配置缺少database文件路径：需要 'database', 'path', 'file_path' 或 'database_path' 参数"
                )

        # Get other possible parameters
        additional_params = {}
        for key, value in config.items():
            if key not in [
                "name",
                "type",
                "host",
                "port",
                "username",
                "password",
                "database",
                "path",
                "file_path",
                "database_path",
            ]:
                additional_params[key] = value

        return cls(
            name=name,
            type=dataSourceType,
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
            additional_params=additional_params,
        )


class DataSourcesConfig:
    def __init__(self, dataSourceConfigs: List[DataSourceConfig]):
        self.dataSourceConfigs = dataSourceConfigs
        self.source_map = (
            {ds.name: ds for ds in dataSourceConfigs} if dataSourceConfigs else {}
        )

    @classmethod
    def from_dict(cls, config: list):
        if not config:
            return cls([])

        sources = []
        for source_config in config:
            sources.append(DataSourceConfig.from_dict(source_config))

        return cls(sources)

    def getSourceConfig(self, name: str) -> DataSourceConfig:
        return self.source_map.get(name)

    def getAllSourceConfigs(self) -> List[DataSourceConfig]:
        return self.dataSourceConfigs


class OntologyConfig:
    def __init__(self, dataSourcesConfig: DataSourcesConfig):
        self.dataSourcesConfig = dataSourcesConfig

    @classmethod
    def from_dict(cls, config: dict):
        return cls(DataSourcesConfig.from_dict(config.get("dataSources", [])))

    def to_dict(self) -> dict:
        return {"dataSources": self.dataSourcesConfig.to_dict()}
