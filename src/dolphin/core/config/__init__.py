# -*- coding: utf-8 -*-
"""Config 模块 - 核心配置"""

from dolphin.core.config.global_config import GlobalConfig
from dolphin.core.config.ontology_config import (
    DataSourceType,
    DataSourceConfig,
    OntologyConfig,
)

__all__ = [
    "GlobalConfig",
    "DataSourceType",
    "DataSourceConfig",
    "OntologyConfig",
]
