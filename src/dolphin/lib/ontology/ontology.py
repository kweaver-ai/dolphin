"""
Base class for all ontology objects
"""

import json
from typing import List, Dict, Optional, TypeVar, Type, Any
from dolphin.core.common.enums import Messages
from dolphin.core.config import DataSourceType, OntologyConfig, DataSourceConfig
from dolphin.lib.ontology.basic.concept import Concept
from dolphin.lib.ontology.mapping import Mapping
import concurrent.futures
from dataclasses import dataclass, asdict
from enum import Enum, auto
from concurrent.futures import ThreadPoolExecutor

from dolphin.lib.ontology.datasource.datasource import DataSource

# 延迟导入 SQL 相关的数据源类（需要 sqlalchemy）
try:
    from dolphin.lib.ontology.datasource.sql import (
        DataSourceMysql,
        DataSourceSqlite,
    )
    from dolphin.lib.ontology.datasource.oracle_datasource import DataSourceOracle
    _SQL_AVAILABLE = True
except ImportError:
    # sqlalchemy 未安装，这些类不可用
    _SQL_AVAILABLE = False
    DataSourceMysql = None
    DataSourceSqlite = None
    DataSourceOracle = None

# Add import of Dolphin SDK log
from dolphin.core.logging.logger import get_logger

logger = get_logger("ontology")

# Custom Types
T = TypeVar("T")


class MergeStrategy(Enum):
    """Concept Merging Strategy"""

    REPLACE = auto()  # Completely replace existing concepts
    EXTEND = auto()  # Keep existing members, add new members
    KEEP_EXISTING = auto()  # Keep existing concepts, ignore new concepts
    RENAME_NEW = auto()  # Rename new concepts to avoid conflicts


class OntologyStatus(Enum):
    """Ontology Status"""

    INITIALIZED = auto()  # Initialization completed
    LOADING = auto()  # Loading
    BUILDING = auto()  # Building
    READY = auto()  # Ready
    ERROR = auto()  # An error occurred


@dataclass
class OntologyStats:
    """Ontology Statistics Information"""

    dataSourcesCount: int = 0
    conceptsCount: int = 0
    mappingsCount: int = 0
    lastBuildTime: str = ""
    lastConfigLoadTime: str = ""


class Ontology:
    """Ontology Management Class

        Responsible for managing data sources (DataSource), concepts (Concept), and their mappings (Mapping).
        Can load data sources from configuration files and trigger scans to automatically generate concepts and mappings.
        Supports ontology serialization, validation, and state management.
    """

    # Mapping of data source types to implementation classes
    # 动态构建注册表，只在 SQL 数据源类可用时添加
    _DATA_SOURCE_REGISTRY: Dict[DataSourceType, Type[DataSource]] = {}
    
    @classmethod
    def _build_data_source_registry(cls):
        """构建数据源注册表（延迟初始化）"""
        if not cls._DATA_SOURCE_REGISTRY:
            # 基础数据源总是可用
            # SQL 数据源只在 sqlalchemy 安装时可用
            if _SQL_AVAILABLE and DataSourceMysql is not None:
                cls._DATA_SOURCE_REGISTRY[DataSourceType.MYSQL] = DataSourceMysql
            if _SQL_AVAILABLE and DataSourceSqlite is not None:
                cls._DATA_SOURCE_REGISTRY[DataSourceType.SQLITE] = DataSourceSqlite
            if _SQL_AVAILABLE and DataSourceOracle is not None:
                cls._DATA_SOURCE_REGISTRY[DataSourceType.ORACLE] = DataSourceOracle
        return cls._DATA_SOURCE_REGISTRY

    def __init__(self, ontologyConfig: OntologyConfig):
        self._ontologyConfig = ontologyConfig
        self._dataSources: Dict[str, DataSource] = {}
        self._concepts: Dict[str, Concept] = {}
        self._mappings: Dict[tuple[str, str], Mapping] = {}
        self._status: OntologyStatus = OntologyStatus.INITIALIZED
        self._stats: OntologyStats = OntologyStats()
        logger.debug("Ontology manager initialized")

        if ontologyConfig:
            self._loadDataSourcesFromConfig()

    @property
    def status(self) -> OntologyStatus:
        """Get the current ontology status"""
        return self._status

    @property
    def stats(self) -> OntologyStats:
        """Get ontology statistics"""
        self._stats.dataSourcesCount = len(self._dataSources)
        self._stats.conceptsCount = len(self._concepts)
        self._stats.mappingsCount = len(self._mappings)
        return self._stats

    def registerDataSourceType(
        self, dataType: DataSourceType, cls: Type[DataSource]
    ) -> None:
        """Register a new data source type

        Args:
            dataType (DataSourceType): Data source type enumeration (from config.py)
            cls (Type[DataSource]): DataSource subclass that handles this type
        """
        # 确保注册表已初始化
        Ontology._build_data_source_registry()
        Ontology._DATA_SOURCE_REGISTRY[dataType] = cls
        logger.debug(f"Registered data source type {dataType.name} -> {cls.__name__}")

    def addDataSource(self, dataSource: DataSource) -> None:
        """Add a data source instance"""
        if dataSource.name in self._dataSources:
            logger.warning(f"Data source '{dataSource.name}' already exists，will be overwritten")
        self._dataSources[dataSource.name] = dataSource
        logger.debug(f"Data source added: {dataSource.name}")

    def getDataSource(self, name: str) -> Optional[DataSource]:
        """Get data source instance by name"""
        return self._dataSources.get(name)

    def getAllDataSources(self) -> List[DataSource]:
        """Get all data source instances"""
        return list(self._dataSources.values())

    def addConcept(
        self, concept: Concept, strategy: MergeStrategy = MergeStrategy.REPLACE
    ) -> Concept:
        """Add a concept instance, handling conflicts using the specified merge strategy.

        Args:
            concept (Concept): The concept to add
            strategy (MergeStrategy): The merge strategy to apply when the concept already exists

        Returns:
            Concept: The final concept after addition/merging
        """
        existingConcept = self._concepts.get(concept.name)
        if existingConcept is None:
            # Concept does not exist, add directly
            self._concepts[concept.name] = concept
            logger.debug(f"Concept added: {concept.name}")
            return concept

        # Concept already exists, handle according to policy
        if strategy == MergeStrategy.REPLACE:
            # Fully replace
            self._concepts[concept.name] = concept
            logger.warning(f"Concept '{concept.name}' already exists，has been replaced")
            return concept

        elif strategy == MergeStrategy.EXTEND:
            # Merge Members
            mergedMembers = dict(existingConcept.members)
            for name, type_ in concept.members.items():
                if name in mergedMembers:
                    logger.debug(
                        f"Concept '{concept.name}'  member  '{name}' already exists，keeping original type"
                    )
                else:
                    mergedMembers[name] = type_
                    logger.debug(f"Concept '{concept.name}'  added new member '{name}'")

            # Create a new Concept instance
            mergedConcept = Concept(concept.name, mergedMembers)
            self._concepts[concept.name] = mergedConcept
            logger.debug(
                f"Concept '{concept.name}' merged with {len(mergedMembers)}  members"
            )
            return mergedConcept

        elif strategy == MergeStrategy.KEEP_EXISTING:
            # Retain existing concepts
            logger.debug(f"Concept '{concept.name}' already exists，keeping original definition, ignoring new")
            return existingConcept

        elif strategy == MergeStrategy.RENAME_NEW:
            # Rename New Concept
            i = 1
            newName = f"{concept.name}_{i}"
            while newName in self._concepts:
                i += 1
                newName = f"{concept.name}_{i}"

            # Create a new Concept instance
            renamedConcept = Concept(newName, concept.members)
            self._concepts[newName] = renamedConcept
            logger.warning(f"Concept '{concept.name}' already exists，renamed to '{newName}'")
            return renamedConcept

    def getConcept(self, name: str) -> Optional[Concept]:
        """Get concept instance by name"""
        return self._concepts.get(name)

    def getAllConcepts(self, **kwargs) -> List[Concept]:
        """Get all concept instances"""
        return list(self._concepts.values())

    def getConceptDescription(self, name: str, **kwargs) -> str:
        """Get concept descriptions"""
        concept = self._concepts.get(name)
        if concept is None:
            return f"Concept '{name}' does not exist"

        return json.dumps(concept.toDict(), ensure_ascii=False, indent=2)

    def getAllConceptsDescription(self) -> str:
        """Generate a JSON format string for concept descriptions

        Returns:
            str: A JSON format string containing all concepts and their members
        """
        import json

        concepts_data = {}
        for concept in self._concepts.values():
            concepts_data[concept.name] = concept.toDict()

        return json.dumps(concepts_data, ensure_ascii=False, indent=2)

    def addMapping(self, mapping: Mapping) -> None:
        """Add a mapping instance"""
        mappingKey = (mapping.dataSource.name, mapping.concept.name)
        if mappingKey in self._mappings:
            logger.warning(
                f"Data source '{mapping.dataSource.name}' toConcept '{mapping.concept.name}' 的Mappingalready exists，will be overwritten"
            )
        self._mappings[mappingKey] = mapping
        logger.debug(f"Mapping added: {mapping.dataSource.name} -> {mapping.concept.name}")

    def getMapping(self, dataSourceName: str, conceptName: str) -> Optional[Mapping]:
        """Get mapping instance by data source name and concept name"""
        return self._mappings.get((dataSourceName, conceptName))

    def getMappingsForDataSource(self, dataSourceName: str) -> List[Mapping]:
        """Get all mappings for the specified data source"""
        return [m for k, m in self._mappings.items() if k[0] == dataSourceName]

    def getMappingsForConcept(self, conceptName: str) -> List[Mapping]:
        """Get all mappings for the specified concept"""
        return [m for k, m in self._mappings.items() if k[1] == conceptName]

    def getAllMappings(self) -> List[Mapping]:
        """Get all mapping instances"""
        return list(self._mappings.values())

    def getDataSourceFromConcept(self, conceptName: str) -> Optional[DataSource]:
        """Get data source by concept"""
        for k, m in self._mappings.items():
            if m.concept.name == conceptName:
                return m.dataSource
        return None

    def getDataSourcesFromConcepts(self, concepts: list) -> list:
        """Get data source by concept"""
        # Collect configuration dictionaries, using the data source name as the key for deduplication
        configsMap = {}
        for m in self._mappings.values():
            if m.concept.name in concepts:
                # Use the data source name as a key to avoid duplicate configurations
                configsMap[m.dataSource.name] = m.dataSource.config
        return list(configsMap.values())

    def getDataSourceSchemasFromConcepts(self, concepts: List[str]) -> Dict[str, Any]:
        """Get the schema of a data source by concept"""
        data = {}
        for conceptName in concepts:
            dataSource = self.getDataSourceFromConcept(conceptName)
            if dataSource is None:
                continue
            data[conceptName] = dataSource.get_schema()
        return data

    def sampleData(self, conceptNames: List[str], count: int = 1) -> Dict[str, Any]:
        """Get sample data according to concept"""
        data = {}
        for conceptName in conceptNames:
            dataSource = self.getDataSourceFromConcept(conceptName)
            if dataSource is None:
                continue

            sampledata = dataSource.sampleData(conceptName, count)
            if sampledata:
                data[conceptName] = sampledata
        return data

    def executeSql(self, sql: str, dataSourceName: Optional[str] = None) -> Messages:
        """Execute an SQL statement and return the result.

        Args:
            sql (str): The SQL statement to execute
            dataSourceName (Optional[str]): Specifies the data source name; if not provided, the first registered data source is selected

        Returns:
            Messages: A list of query results, with each element being a dictionary where keys are column names and values are corresponding values
        """
        if not self._dataSources:
            raise RuntimeError("No data sources available to execute SQL")
        if dataSourceName is None:
            # Select the first registered data source
            ds = next(iter(self._dataSources.values()))
        else:
            ds = self._dataSources.get(dataSourceName)
            if ds is None:
                raise KeyError(f"Data source '{dataSourceName}' does not exist")
        return ds.executeSql(sql)

    def buildOntologyFromSources(
        self,
        runScan: bool = True,
        concurrent: bool = True,
        maxWorkers: int = None,
        conceptStrategy: MergeStrategy = MergeStrategy.EXTEND,
    ) -> None:
        """Build ontology (Concepts and Mappings) from the added data sources.

        Args:
            run_scan (bool): Whether to perform a scan operation on each data source, default is True
            concurrent (bool): Whether to scan multiple data sources concurrently, default is True
            max_workers (int): Maximum number of worker threads, default is None (determined by the system)
            concept_strategy (MergeStrategy): Concept merging strategy, default is EXTEND
        """
        import datetime

        if not self._dataSources:
            logger.warning("No data sources available for building ontology")
            return

        self._status = OntologyStatus.BUILDING
        logger.debug("Starting to build ontology from data sources...")

        # If scanning is not performed, return directly
        if not runScan:
            logger.debug("Skipping all data source scanning (runScan=False)")
            self._status = OntologyStatus.READY
            return

        # Concurrent scanning data source
        if concurrent and len(self._dataSources) > 1:
            self._scanDataSourcesConcurrently(maxWorkers, conceptStrategy)
        else:
            self._scanDataSourcesSequentially(conceptStrategy)

        self._stats.lastBuildTime = datetime.datetime.now().isoformat()
        self._status = OntologyStatus.READY
        logger.debug("Ontology building process completed")

    def validate(self) -> List[str]:
        """Validate ontology consistency

                Check whether the reference relationships among data sources, concepts, and mappings are consistent.

        Returns:
            List[str]: List of validation error messages; empty list if no errors found
        """
        errors = []

        # 1. Check that all data sources referenced in the mappings exist
        for (dsName, conceptName), mapping in self._mappings.items():
            if mapping.data_source.name != dsName:
                errors.append(
                    f"Mapping键 ({dsName}, {conceptName}) 与Mapping对象中的Data sourcename {mapping.data_source.name} inconsistent"
                )

            if dsName not in self._dataSources:
                errors.append(
                    f"Mapping ({dsName}, {conceptName}) 引用了does not exist的Data source '{dsName}'"
                )

            # 2. Check that all mapped reference concepts exist
            if mapping.concept.name != conceptName:
                errors.append(
                    f"Mapping键 ({dsName}, {conceptName}) 与Mapping对象中的Conceptname {mapping.concept.name} inconsistent"
                )

            if conceptName not in self._concepts:
                errors.append(
                    f"Mapping ({dsName}, {conceptName}) 引用了does not exist的Concept '{conceptName}'"
                )

            # 3. Check whether the field-to-member mapping in the mapping is valid
            for memberName in mapping.fieldToMemberMap.values():
                concept = self._concepts.get(conceptName)
                if concept and memberName not in concept.members:
                    errors.append(
                        f"Mapping ({dsName}, {conceptName}) 引用了Concept中does not exist的member '{memberName}'"
                    )

        if not errors:
            logger.debug("Ontology validation passed, no issues found")
        else:
            logger.warning(f"Ontology validation found {len(errors)}  issues")
            for i, error in enumerate(errors, 1):
                logger.warning(f"Issue {i}: {error}")

        return errors

    def saveToFile(self, filePath: str) -> bool:
        """Save the ontology to a file.

        The saved format is JSON, containing concept definitions, data source references, and mapping relationships.
        Data source connection details are not saved to avoid leaking sensitive information.

        Args:
            file_path (str): Save path

        Returns:
            bool: Whether the save was successful
        """
        try:
            # 1. Collect concept information
            conceptsData = {}
            for name, concept in self._concepts.items():
                conceptsData[name] = concept.toDict()

            # 2. Collect data source reference information (excluding sensitive information such as passwords)
            datasourcesRef = {}
            for name, ds in self._dataSources.items():
                datasourcesRef[name] = {"name": name, "type": ds.type.name}

            # 3. Collect mapping information
            mappingsData = []
            for (dsName, conceptName), mapping in self._mappings.items():
                mappingsData.append(
                    {
                        "data_source": dsName,
                        "concept": conceptName,
                        "field_to_member_map": mapping.fieldToMemberMap,
                    }
                )

            # 4. Assemble complete data
            ontologyData = {
                "concepts": conceptsData,
                "datasources_ref": datasourcesRef,
                "mappings": mappingsData,
                "stats": asdict(self._stats),
            }

            # 5. Writing Files
            with open(filePath, "w", encoding="utf-8") as f:
                json.dump(ontologyData, f, indent=2, ensure_ascii=False)

            logger.debug(f"Ontology saved to file: {filePath}")
            return True

        except Exception as e:
            logger.exception(f"保存本体toFile {filePath} 时error: {e}")
            return False

    def loadFromFile(self, filePath: str) -> bool:
        """Load ontology structure from file

        Args:
            filePath (str): Path to the ontology file

        Returns:
            bool: Whether the loading was successful
        """
        try:
            with open(filePath, "r", encoding="utf-8") as f:
                ontologyData = json.load(f)

            # Validate data format
            if not all(key in ontologyData for key in ["concepts", "mappings"]):
                logger.error(f"File {filePath} has incorrect format, missing required keys")
                return False

            # Loading Concepts
            from dolphin.lib.ontology.basic.concept import (
                Concept,
                ConceptMemberType,
            )

            concepts = {}
            for name, conceptData in ontologyData["concepts"].items():
                members = {}
                for memberName, typeName in conceptData["members"].items():
                    try:
                        memberType = ConceptMemberType[typeName]
                        members[memberName] = memberType
                    except KeyError:
                        logger.warning(f"Unknown member type: {typeName}，using ANY instead")
                        members[memberName] = ConceptMemberType.ANY

                concepts[name] = Concept(name=name, members=members)

            # Load mapping (requires an existing data source instance)
            from dolphin.lib.ontology.mapping import Mapping

            mappings = {}
            for mappingData in ontologyData["mappings"]:
                dsName = mappingData["data_source"]
                conceptName = mappingData["concept"]
                fieldMap = mappingData["field_to_member_map"]

                # Check if data source and concept are available
                dataSource = self._dataSources.get(dsName)
                concept = concepts.get(conceptName)

                if not dataSource:
                    logger.warning(f"Mapping中引用的Data source '{dsName}' does not exist，跳过")
                    continue

                if not concept:
                    logger.warning(f"Mapping中引用的Concept '{conceptName}' does not exist，跳过")
                    continue

                # Create mapping
                try:
                    mapping = Mapping(
                        dataSource=dataSource,
                        concept=concept,
                        fieldToMemberMap=fieldMap,
                    )
                    mappings[(dsName, conceptName)] = mapping
                except ValueError as e:
                    logger.warning(f"CreatingMapping ({dsName}, {conceptName}) failed: {e}")

            # Update internal state
            self._concepts = concepts
            self._mappings = mappings

            logger.debug(
                f"Loaded from file {filePath} ontology with {len(concepts)} 个Concept和 {len(mappings)} 个Mapping"
            )
            self._status = OntologyStatus.READY
            return True

        except FileNotFoundError:
            logger.error(f"本体File未找to: {filePath}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing ontology file {filePath} error: {e}")
            return False
        except Exception:
            logger.exception(f"Loading ontology file {filePath}  unexpected error occurred")
            return False

    def reset(self) -> None:
        """Reset the ontology, clearing all data sources, concepts, and mappings"""
        self._dataSources.clear()
        self._concepts.clear()
        self._mappings.clear()
        self._status = OntologyStatus.INITIALIZED
        logger.debug("Ontology has been reset")

    def _loadDataSourcesFromConfig(self) -> None:
        """Load data source instance from global configuration"""
        import datetime

        self._status = OntologyStatus.LOADING
        logger.debug("Loading data sources from global configuration")
        try:
            # Get a list of DataSourceConfig from global configuration
            dataSourcesConfigs: List["DataSourceConfig"] = (
                self._ontologyConfig.dataSourcesConfig.getAllSourceConfigs()
            )

            if not dataSourcesConfigs:
                logger.warning("No data sources in global configuration")
                self._status = OntologyStatus.INITIALIZED
                return

            loadedCount = 0
            # Traverse DataSourceConfig loaded from configuration
            for dsConfig in dataSourcesConfigs:
                name = dsConfig.name
                # Use the type enumeration loaded from config.py directly
                dataSourceType: DataSourceType = dsConfig.type

                if not name or not dataSourceType:
                    logger.warning(
                        f"跳过无效的Data source配置（missing name or type）：{dsConfig}"
                    )
                    continue

                # Create DataSource instance directly using config.DataSourceType
                datasourceInstance: Optional[DataSource] = self._createDataSource(
                    name, dataSourceType, dsConfig.__dict__
                )
                if datasourceInstance:
                    self.addDataSource(datasourceInstance)
                    logger.debug(
                        f"successful加载并添加Data source: {name} ({dataSourceType.name})"
                    )
                    loadedCount += 1

            self._stats.lastConfigLoadTime = datetime.datetime.now().isoformat()
            logger.debug(f"Successfully loaded from global config {loadedCount} 个Data source")
            self._status = (
                OntologyStatus.READY if loadedCount > 0 else OntologyStatus.INITIALIZED
            )

        except Exception as e:
            logger.exception(f"加载Data source配置 unexpected error occurred: {e}")
            self._status = OntologyStatus.ERROR

    def _createDataSource(
        self, name: str, dataType: DataSourceType, config: Dict[str, Any]
    ) -> Optional[DataSource]:
        """Create a data source instance based on type and configuration.

        Args:
            name (str): Data source name
            dataType (DataSourceType): Data source type enumeration (config.DataSourceType)
            config (Dict[str, Any]): Specific configuration for the data source
        """
        # 确保注册表已初始化
        registry = self._build_data_source_registry()
        
        # First try direct lookup
        datasourceCls = registry.get(dataType)

        # If direct lookup fails, try string-based matching as fallback
        # This handles cases where different module loading paths create different enum instances
        if datasourceCls is None:
            dataTypeStr = str(dataType)  # e.g., "DataSourceType.MYSQL"
            for key, value in registry.items():
                if str(key) == dataTypeStr:
                    datasourceCls = value
                    break

        if not datasourceCls:
            logger.warning(f"Data source类型 '{dataType.name}' not registered, skipping '{name}'")
            return None

        try:
            # Create data source instance
            datasourceInstance = datasourceCls(name=name, config=config)
            return datasourceInstance
        except Exception as e:
            logger.error(f"Creating {dataType.name} Data source '{name}' 实例failed: {e}")
            return None

    def _scanDataSourcesSequentially(self, conceptStrategy: MergeStrategy) -> None:
        """Scan the data source in order"""
        for dsName, dataSource in self._dataSources.items():
            self._scanSingleDataSource(dsName, dataSource, conceptStrategy)

    def _scanDataSourcesConcurrently(
        self, maxWorkers: int, conceptStrategy: MergeStrategy
    ) -> None:
        """Concurrent scanning data source"""
        with ThreadPoolExecutor(max_workers=maxWorkers) as executor:
            # Submit all tasks
            futures = {
                executor.submit(
                    self._scanSingleDataSource, dsName, dataSource, conceptStrategy
                ): dsName
                for dsName, dataSource in self._dataSources.items()
            }

            # Wait for completion
            for future in concurrent.futures.as_completed(futures):
                dsName = futures[future]
                try:
                    future.result()  # Get result (if there is an exception, it will be thrown here)
                except Exception as e:
                    logger.exception(f"并发扫描Data source {dsName}  unhandled exception: {e}")

    def _scanSingleDataSource(
        self, dsName: str, dataSource: DataSource, conceptStrategy: MergeStrategy
    ) -> None:
        """Scan a single data source"""
        logger.debug(f"Scanning data source: {dsName}...")
        try:
            # Test connection, skip scanning if failed
            if not dataSource.test_connection():
                logger.warning(f"Data source {dsName} connection test failed, skipping scan")
                return

            # Perform scanning to retrieve Mappings (Concepts will be created internally within scan)
            mappings = dataSource.scan()
            if not mappings:
                logger.debug(f"Data source {dsName} scan returned no mappings")
                return

            # Add Concepts and Mappings generated by scanning
            added_mappings = 0
            for mapping in mappings:
                finalConcept = self.addConcept(
                    mapping.concept, strategy=conceptStrategy
                )
                if finalConcept is not mapping.concept:
                    from dolphin.lib.ontology.mapping import Mapping

                    newMapping = Mapping(
                        dataSource=mapping.dataSource,
                        space=mapping.space,
                        concept=finalConcept,
                        fieldToMemberMap=mapping.fieldToMemberMap,
                    )
                    self.addMapping(newMapping)
                else:
                    self.addMapping(mapping)

                added_mappings += 1

            logger.debug(f"Data source {dsName} scan completed, added {len(mappings)} 个Mapping")

        except NotImplementedError:
            logger.error(f"Data source {dsName} ({dataSource.type.name})  scan method not implemented")
        except ConnectionError as e:
            logger.error(f"扫描Data source {dsName} 时connect tofailed: {e}")
        except Exception:
            logger.exception(f"扫描Data source {dsName}  unexpected error occurred")
