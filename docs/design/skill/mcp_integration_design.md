# MCP (Model Context Protocol) 集成技术设计方案

> ⚠️ **重要更新** - 根据项目实际情况进行了关键修正：
> 
> 1. **🎯 使用官方 MCP SDK**: 采用 `modelcontextprotocol/python-sdk` 替代自研实现
> 2. **✅ 修正 Dolphin 语法**: 所有示例已更新为正确的 `.dph` 语法格式
> 3. **🚀 简化架构**: 基于官方 SDK 大幅简化实现复杂度
> 4. **📝 完善集成**: 与现有 Skillkit 系统无缝集成

## 目录

- [1. 概述](#1)
- [2. 设计目标](#2)
- [3. 整体架构](#3)
- [4. 核心组件设计](#4)
- [5. 配置系统](#5)
- [6. 集成方案](#6)
- [7. 使用示例](#7)
- [8. 测试策略](#8)
- [9. 性能优化](#9)
- [10. 安全考虑](#10)
- [11. 实现指南](#11_1)
- [12. 故障排除](#12_1)

---

## 1. 概述

### 1.1 背景

Model Context Protocol (MCP) 是一个开放标准，用于连接 AI 应用与外部工具和服务。通过集成 MCP，Dolphin Language 可以无缝使用各种外部服务，如浏览器自动化、文件操作、数据库访问等。

### 1.2 设计理念

- **客户端模式**: Dolphin Language 作为 MCP 客户端，连接到独立运行的 MCP 服务器
- **统一接口**: 通过现有的 Skill 系统无缝集成 MCP 功能
- **异步优先**: 支持异步操作以提高性能和响应性
- **服务分离**: MCP 服务器独立部署和运行，确保高可用性和可扩展性
- **配置驱动**: 通过配置文件管理 MCP 服务器连接信息，无需代码修改
- **向后兼容**: 不影响现有功能，平滑升级

### 1.3 支持的功能

- ✅ 浏览器自动化 (连接到 Playwright MCP 服务器)
- ✅ 文件系统操作 (连接到文件系统 MCP 服务器)
- ✅ 数据库访问 (连接到数据库 MCP 服务器)
- ✅ 自定义工具集成 (连接到任何符合 MCP 协议的服务器)
- 🔄 实时数据流处理
- 🔄 分布式 MCP 集群负载均衡

---

## 2. 设计目标

### 2.1 功能目标

1. **无缝集成**: 在 `.dph` 文件中直接使用 MCP 工具
2. **动态加载**: 支持运行时添加/移除 MCP 服务器
3. **错误处理**: 完善的错误处理和恢复机制
4. **性能优化**: 连接池、缓存等性能优化措施

### 2.2 非功能目标

- **可用性**: 99.9% 的服务可用性
- **响应时间**: MCP 调用响应时间 < 5秒
- **并发支持**: 支持 100+ 并发 MCP 调用
- **资源占用**: 内存占用 < 100MB per MCP server

---

## 3. 整体架构

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    Dolphin Language                         │
├─────────────────────────────────────────────────────────────┤
│  .dph Files  →  Executor  →  Context  →  GlobalSkills      │
├─────────────────────────────────────────────────────────────┤
│                    技能管理层                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ installedSkillset│  │ agentSkillset   │  │MCPSkillset  │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    MCP Integration Layer                    │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │  MCPSkillkit    │  │  MCPAdapter     │  │官方MCP SDK  │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
├─────────────────────────────────────────────────────────────┤
│                    MCP Servers                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │ Playwright MCP  │  │  File System    │  │ Database    │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 组件关系

1. **Executor**: 执行 `.dph` 文件的主要引擎，支持异步和并行处理
2. **Context**: 管理执行上下文和变量池
3. **GlobalSkills**: 全局技能管理器，统一管理所有技能套件
4. **MCPSkillkit**: MCP 技能套件基类，继承自现有的 Skillkit
5. **MCPAdapter**: MCP 适配器，封装官方 MCP SDK 的 ClientSession
6. **官方MCP SDK**: 使用 `mcp.client.session.ClientSession` 与 MCP 服务器通信

---

## 4. 核心组件设计

### 4.1 MCP 集成适配器 (`src/DolphinLanguageSDK/skill/installed/mcp_adapter.py`)

#### 4.1.1 使用官方 MCP SDK 作为客户端

我们使用官方 MCP Python SDK 作为客户端，连接到已运行的 MCP 服务器：

```python
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# 使用官方 MCP SDK
from mcp.client.session import ClientSession
from mcp.client.sse import SseServerParameters, sse_client
from mcp.client.websocket import WebSocketServerParameters, websocket_client

@dataclass
class MCPServerConfig:
    """MCP 服务器配置"""
    name: str
    url: str  # 服务器 URL，如 http://localhost:3001
    connection_type: str = "sse"  # 连接类型：sse, websocket
    timeout: int = 30
    enabled: bool = True
    auth: Optional[Dict[str, str]] = None  # 认证信息

class MCPAdapter:
    """MCP 适配器 - 连接到已运行的 MCP 服务器"""
    
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self.tools_cache: List[Dict[str, Any]] = []
        self.logger = logging.getLogger(f"mcp.{config.name}")
        self._connection_context = None
        
    async def connect(self) -> None:
        """连接到 MCP 服务器"""
        if self.session is not None:
            return
            
        try:
            # 根据连接类型选择客户端
            if self.config.connection_type == "sse":
                server_params = SseServerParameters(url=self.config.url)
                self._connection_context = sse_client(server_params)
            elif self.config.connection_type == "websocket":
                server_params = WebSocketServerParameters(url=self.config.url)
                self._connection_context = websocket_client(server_params)
            else:
                raise ValueError(f"Unsupported connection type: {self.config.connection_type}")
            
            # 建立连接
            read_stream, write_stream = await self._connection_context.__aenter__()
            
            # 创建会话
            self.session = ClientSession(read_stream, write_stream)
            await self.session.__aenter__()
            
            # 初始化连接
            await self.session.initialize()
            
            # 加载工具列表
            await self._load_tools()
            
            self.logger.info(f"Connected to MCP server: {self.config.name} at {self.config.url}")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to MCP server {self.config.name}: {e}")
            await self.disconnect()
            raise
    
    async def _load_tools(self) -> None:
        """加载可用工具"""
        if not self.session:
            return
            
        try:
            tools_response = await self.session.list_tools()
            self.tools_cache = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema or {}
                }
                for tool in tools_response.tools
            ]
            self.logger.debug(f"Loaded {len(self.tools_cache)} tools from {self.config.name}")
        except Exception as e:
            self.logger.error(f"Failed to load tools from {self.config.name}: {e}")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """调用工具"""
        if not self.session:
            await self.connect()
        
        try:
            result = await self.session.call_tool(tool_name, arguments)
            
            # 处理结果 - 提取文本内容
            if hasattr(result, 'content') and result.content:
                # 如果有结构化内容，提取文本
                content_texts = []
                for content in result.content:
                    if hasattr(content, 'text'):
                        content_texts.append(content.text)
                    elif hasattr(content, 'data'):
                        content_texts.append(str(content.data))
                return "\n".join(content_texts) if content_texts else str(result)
            
            return str(result)
            
        except Exception as e:
            self.logger.error(f"Tool call failed: {tool_name}, error: {e}")
            raise
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具列表"""
        return self.tools_cache.copy()
    
    async def disconnect(self) -> None:
        """断开连接"""
        try:
            if self.session:
                await self.session.__aexit__(None, None, None)
                self.session = None
            
            if self._connection_context:
                await self._connection_context.__aexit__(None, None, None)
                self._connection_context = None
                
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
        
        self.logger.info(f"Disconnected from MCP server: {self.config.name}")
```

### 4.2 MCP 技能套件 (`src/DolphinLanguageSDK/skill/installed/mcp_skillkit.py`)

```python
import asyncio
import logging
from typing import List, Dict, Any, Optional
from DolphinLanguageSDK.skill.skillkit import Skillkit
from DolphinLanguageSDK.skill.skill_function import SkillFunction
from .mcp_adapter import MCPAdapter, MCPServerConfig

class MCPSkillkit(Skillkit):
    """MCP 技能套件基类 - 使用官方 MCP SDK"""
    
    def __init__(self, server_config: MCPServerConfig):
        super().__init__()
        self.server_config = server_config
        self.mcp_adapter: Optional[MCPAdapter] = None
        self.skills_cache: List[SkillFunction] = []
        self.logger = logging.getLogger(f"mcp.{server_config.name}")
        self.initialized = False
        self.globalConfig = None
    
    def getName(self) -> str:
        return f"MCP_{self.server_config.name}_Skillkit"
    
    def setGlobalConfig(self, globalConfig):
        """设置全局上下文（保持与现有skillkit一致的接口）"""
        self.globalConfig = globalConfig
    
    async def initialize(self) -> None:
        """初始化 MCP 适配器"""
        if self.initialized:
            return
        
        try:
            self.mcp_adapter = MCPAdapter(self.server_config)
            await self.mcp_adapter.connect()
            
            # 生成技能
            self._generate_skills()
            self.initialized = True
            self.logger.info(f"MCP skillkit initialized: {self.server_config.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize MCP skillkit {self.server_config.name}: {e}")
            raise
    
    def _generate_skills(self) -> None:
        """生成基于 MCP 工具的技能"""
        self.skills_cache = []
        
        if not self.mcp_adapter:
            return
        
        for tool in self.mcp_adapter.get_available_tools():
            # 创建动态技能函数
            skill_func = self._create_skill_function(tool)
            self.skills_cache.append(SkillFunction(skill_func))
    
    def _create_skill_function(self, tool: Dict[str, Any]):
        """创建技能函数"""
        tool_name = tool["name"]
        tool_description = tool["description"]
        
        def skill_func(**kwargs) -> str:
            f"""
            {tool_description}
            
            Args:
                **kwargs: 工具参数
                
            Returns:
                str: 工具执行结果
            """
            try:
                if self.mcp_adapter is None:
                    return f"Error: MCP adapter not initialized for {tool_name}"
                
                # 使用线程池执行异步操作，避免事件循环冲突
                import concurrent.futures
                
                async def _async_call():
                    return await self.mcp_adapter.call_tool(tool_name, kwargs)
                
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _async_call())
                    result = future.result(timeout=self.server_config.timeout)
                
                return str(result)
                    
            except Exception as e:
                self.logger.error(f"MCP tool execution failed: {tool_name}, error: {e}")
                return f"Error executing {tool_name}: {str(e)}"
        
        # 设置函数元数据
        skill_func.__name__ = f"{self.server_config.name}_{tool_name}"
        skill_func.__doc__ = tool_description
        
        return skill_func
    
    def getSkills(self) -> List[SkillFunction]:
        """获取技能列表"""
        if not self.initialized:
            # 尝试初始化
            try:
                asyncio.run(self.initialize())
            except Exception as e:
                self.logger.error(f"Failed to initialize during getSkills: {e}")
                return []
        return self.skills_cache
    
    def shutdown(self) -> None:
        """关闭 MCP 适配器"""
        if self.mcp_adapter:
            asyncio.run(self.mcp_adapter.disconnect())
            self.mcp_adapter = None
        self.initialized = False
```

### 4.3 通用 MCP 集成原理

`MCPSkillkit` 是一个通用的基类，可以连接到任何 MCP 服务器：

- **动态技能生成**: 根据 MCP 服务器提供的工具自动生成技能
- **统一接口**: 所有 MCP 服务器都使用相同的技能套件类
- **可扩展性**: 添加新的 MCP 服务器只需要在配置文件中添加连接信息

```python
# 使用示例 - 不需要为每个 MCP 服务器创建专用类
playwright_skillkit = MCPSkillkit(MCPServerConfig(
    name="playwright",
    url="http://localhost:3001"
))

filesystem_skillkit = MCPSkillkit(MCPServerConfig(
    name="filesystem", 
    url="http://localhost:3002"
))

database_skillkit = MCPSkillkit(MCPServerConfig(
    name="database",
    url="http://localhost:3003"
))
```

---

## 5. 配置系统

### 5.1 全局配置扩展 (`src/DolphinLanguageSDK/config/global_config.py`)

```python
# 在现有的GlobalConfig类中添加MCP配置支持

from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class MCPServerConfig:
    """MCP 服务器配置数据类"""
    name: str
    url: str  # 服务器 URL
    connection_type: str = "sse"  # 连接类型：sse, websocket
    timeout: int = 30
    enabled: bool = True
    auth: Optional[Dict[str, str]] = None  # 认证信息

@dataclass
class MCPConfig:
    """MCP 配置数据类"""
    enabled: bool = True
    servers: List[MCPServerConfig] = field(default_factory=list)
    
    @staticmethod
    def from_dict(config_dict: dict) -> "MCPConfig":
        servers = []
        for server_dict in config_dict.get("servers", []):
            server = MCPServerConfig(
                name=server_dict["name"],
                url=server_dict["url"],
                connection_type=server_dict.get("connection_type", "sse"),
                timeout=server_dict.get("timeout", 30),
                enabled=server_dict.get("enabled", True),
                auth=server_dict.get("auth", None)
            )
            servers.append(server)
        
        return MCPConfig(
            enabled=config_dict.get("enabled", True),
            servers=servers
        )

# 扩展现有的GlobalConfig类
class GlobalConfig:
    def __init__(self, 
                 default_llm: str,
                 llmInstanceConfigs: dict,
                 fast_llm: str = None,
                 all_clouds_config: AllCloudsConfig = None,
                 vm_config: VMConfig = None,
                 context_engineer_config: ContextEngineerConfig = None,
                 memory_config: MemoryConfig = None,
                 mcp_config: MCPConfig = None):  # 添加MCP配置
        # 现有初始化代码...
        self._mcp_config = mcp_config or MCPConfig()
    
    @property
    def mcp_config(self) -> MCPConfig:
        return self._mcp_config
    
    @staticmethod
    def from_dict(config_dict: dict) -> "GlobalConfig":
        # 现有解析代码...
        
        # 解析MCP配置
        mcp_config = None
        if "mcp" in config_dict:
            mcp_config = MCPConfig.from_dict(config_dict["mcp"])
        
        return GlobalConfig(
            # 现有参数...
            mcp_config=mcp_config
        )
```

### 5.2 配置文件示例 (`config/global.yaml`)

```yaml
# 现有配置保持不变...
default: Tome-Max
clouds:
  default: aishu
  aishu:
    userid: 9dfb036c-ef2f-11ef-8094-76156d7873be
    api: http://10.4.134.253:9898/api/model-factory/v1/chat/completions
    api_key: sk-atyahnnvfgxogwfopseezxavxrvjqolunozksdlngdwlnz

llms:
  Tome-Max:
    cloud: aishu
    id: 18928543177492439044
    name: Tome-Max
    model_name: Tome-Max
    type_api: aishu_model_factory

vm:
  host: "localhost"
  port: 53936
  username: ""
  encrypted_password: ""
  connection_type: "ssh"
  ssh_key_path: ""

context_engineer:
  import_mem: true
  default_strategy: "truncation"
  constraints:
    max_input_tokens: 64000
    reserve_output_tokens: 16384
    preserve_system: true

memory:
  enabled: true
  storage_path: "data/memory/"
  max_extraction_retries: 3
  extraction_timeout: 300
  merge_interval_hours: 24
  merge_batch_size: 1000
  default_top_k: 5
  min_score_threshold: 20
  max_knowledge_points: 10

# MCP 集成配置 - 连接到已运行的 MCP 服务器
mcp:
  enabled: true
  servers:
    - name: "playwright"
      url: "http://localhost:3001"  # Playwright MCP 服务器地址
      connection_type: "sse"  # 连接类型：sse 或 websocket
      timeout: 60
      enabled: true
      auth:  # 可选的认证信息
        type: "bearer"
        token: "your-playwright-token"
    
    - name: "filesystem"
      url: "http://localhost:3002"  # 文件系统 MCP 服务器地址
      connection_type: "sse"
      timeout: 30
      enabled: true
      auth:
        type: "basic"
        username: "fs_user"
        password: "fs_password"
    
    - name: "database"
      url: "http://localhost:3003"  # 数据库 MCP 服务器地址
      connection_type: "websocket"
      timeout: 45
      enabled: false  # 默认禁用，按需开启
      auth:
        type: "api_key"
        key: "db_api_key"
```

---

## 6. 集成方案

### 6.1 GlobalSkills 集成 (`src/DolphinLanguageSDK/skill/global_skills.py`)

在现有的 `GlobalSkills` 类中添加 MCP 支持：

```python
# 在 GlobalSkills 类的 _loadInstalledSkills 方法中添加 MCP 技能套件加载逻辑

class GlobalSkills:
    def __init__(self, globalConfig: GlobalConfig):
        """
        Initialize global skills manager
        
        Args:
            globalConfig (GlobalConfig): Global configuration object
        """
        self.globalConfig = globalConfig
        self.installedSkillset = Skillset()
        self.agentSkillset = Skillset()
        self.agentSkills: Dict[str, 'Agent'] = {}
        
        # Load installed skills from skill/installed directory
        self._loadInstalledSkills()
        
        # Load MCP skills if enabled
        if globalConfig.mcp_config and globalConfig.mcp_config.enabled:
            self._loadMCPSkills()
    
    def _loadMCPSkills(self):
        """加载 MCP 技能套件"""
        from DolphinLanguageSDK.skill.installed.mcp_skillkit import MCPSkillkit
        from DolphinLanguageSDK.skill.installed.mcp_adapter import MCPServerConfig
        
        for server_config_dict in self.globalConfig.mcp_config.servers:
            if not server_config_dict.enabled:
                continue
                
            try:
                # 创建 MCP 技能套件
                skillkit = MCPSkillkit(server_config_dict)
                skillkit.setGlobalConfig(self.globalConfig)
                
                # 获取技能并添加到已安装技能集
                skills = skillkit.getSkills()
                for skill in skills:
                    self.installedSkillset.addSkill(skill)
                
                console(f"Loaded MCP skillkit: {server_config_dict.name} ({len(skills)} skills)")
                
            except Exception as e:
                console(f"Failed to load MCP skillkit {server_config_dict.name}: {str(e)}")
                continue
    
    # 现有的其他方法保持不变...
    def _loadSkillkitsFromPath(self, folderPath: str, skillkitType: str = "installed"):
        """
        现有的技能套件加载逻辑保持不变
        """
        # 现有代码...
```

### 6.2 依赖管理 (`pyproject.toml`)

在现有的依赖配置中添加 MCP 相关依赖：

```toml
[project]
# 现有配置保持不变...
dependencies = [
    # 现有依赖
    "requests>=2.31.0",
    "openai==1.75.0",
    "docstring-parser>=0.15",
    "jsonschema>=4.17.0", 
    "pydantic>=2.0.0",
    "PyYAML",
    "paramiko",
    "cryptography",
    
    # MCP 官方 SDK
    "mcp>=1.0.0",  # 官方 MCP Python SDK
]

[project.optional-dependencies]
dev = [
    # 现有开发依赖
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
    "black>=23.0.0",
    "flake8>=6.0.0",
    "mypy>=1.0.0",
    "build>=0.10.0",
]

# MCP 服务器依赖（通过外部安装）
mcp-servers = [
    # 这些需要通过npm/pip等方式单独安装
    # "@playwright/mcp"  # npm install -g @playwright/mcp
    # "mcp-server-filesystem"  # pip install mcp-server-filesystem
    # "mcp-server-database"  # pip install mcp-server-database
]
```

---

## 7. 使用示例

### 7.1 基础浏览器自动化 (`examples/mcp_browser_demo.dph`)

```dolphin
# MCP 浏览器自动化示例
# DESC: 演示如何使用 Playwright MCP 进行浏览器自动化

# 导航到网页
@playwright_browser_navigate(url="https://example.com") -> nav_result
print("导航结果: " + $nav_result)

# 等待页面加载完成
@playwright_wait_for_load_state(state="networkidle") -> wait_result

# 获取页面标题
@playwright_page_title() -> page_title
print("页面标题: " + $page_title)

# 检查元素是否可见并点击
@playwright_is_visible(selector="button") -> button_visible
/if/ $button_visible == "true":
    @playwright_click(selector="button") -> click_result
    print("点击按钮成功: " + $click_result)
else:
    print("按钮不可见")
/end/

# 截图保存
@playwright_screenshot(path="./screenshots/demo.png") -> screenshot_result
print("截图已保存: " + $screenshot_result)
```

### 7.2 复杂工作流程 (`examples/mcp_workflow_demo.dph`)

```dolphin
# MCP 复杂工作流程示例
# DESC: 演示多步骤的自动化工作流程

# 设置工作目录
@filesystem_create_directory(path="./mcp_workflow_output") -> create_dir_result

# 第一步：网页数据收集
@playwright_goto(url="https://example.com") -> nav_result
print("导航到目标网站: " + $nav_result)

# 等待页面加载
@playwright_wait_for_load_state(state="networkidle") -> wait_result

# 提取页面信息
@playwright_inner_text(selector="h1") -> page_title
@playwright_inner_text(selector="meta[name='description']") -> page_desc

# 第二步：保存数据到文件
@filesystem_write_file(
    path="./mcp_workflow_output/page_info.txt", 
    content="页面标题: " + $page_title + "\n描述: " + $page_desc
) -> write_result

print("页面信息已保存: " + $write_result)

# 第三步：截图存档
@playwright_screenshot(path="./mcp_workflow_output/page_screenshot.png") -> screenshot_result

# 第四步：生成当前时间
@get_current_time() -> current_time

# 生成报告内容并保存
@filesystem_write_file(
    path="./mcp_workflow_output/report.md", 
    content="自动化工作流程报告\n========================\n执行时间: " + $current_time + "\n页面标题: " + $page_title + "\n截图文件: page_screenshot.png"
) -> report_result

print("工作流程完成！报告已生成: " + $report_result)
```

### 7.3 错误处理示例 (`examples/mcp_error_handling.dph`)

```dolphin
# MCP 错误处理示例
# DESC: 演示如何处理 MCP 操作中的错误

# 尝试导航到不存在的网站
@playwright_browser_navigate(url="https://nonexistent-site.com") -> nav_result

# 检查导航结果
/if/ $nav_result contains "Error":
    print("导航失败，尝试备用网站")
    @playwright_browser_navigate(url="https://example.com") -> backup_nav
    print("备用导航结果: " + $backup_nav)
else:
    print("导航成功: " + $nav_result)
/end/

# 尝试点击可能不存在的元素
@playwright_browser_click(selector="#nonexistent-button") -> click_result

# 处理点击错误
/if/ $click_result contains "Error":
    print("元素不存在，进行截图记录")
    @playwright_screenshot(path="error_page.png") -> error_screenshot
    print("错误截图已保存: " + $error_screenshot)
else:
    print("点击成功: " + $click_result)
/end/
```

---

## 8. 测试策略

### 8.1 单元测试 (`tests/unittest/test_mcp_skillkit.py`)

```python
import unittest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from DolphinLanguageSDK.skill.installed.mcp_skillkit import MCPSkillkit
from DolphinLanguageSDK.skill.installed.mcp_adapter import MCPServerConfig, MCPAdapter

class TestMCPSkillkit(unittest.TestCase):
    def setUp(self):
        self.server_config = MCPServerConfig(
            name="test_server",
            command="python",
            args=["-m", "test_mcp_server"]
        )
        self.skillkit = MCPSkillkit(self.server_config)
    
    async def test_initialization(self):
        """测试 MCP 技能套件初始化"""
        with patch('DolphinLanguageSDK.skill.installed.mcp_adapter.MCPAdapter.connect') as mock_connect:
            mock_connect.return_value = None
            await self.skillkit.initialize()
            self.assertTrue(self.skillkit.initialized)
    
    async def test_tool_execution(self):
        """测试工具执行"""
        with patch('DolphinLanguageSDK.skill.installed.mcp_adapter.MCPAdapter.call_tool') as mock_call:
            mock_call.return_value = "测试结果"
            
            await self.skillkit.initialize()
            skills = self.skillkit.getSkills()
            
            if skills:
                result = skills[0].func(test_param="test_value")
                self.assertIsInstance(result, str)
    
    async def test_error_handling(self):
        """测试错误处理"""
        with patch('DolphinLanguageSDK.skill.installed.mcp_adapter.MCPAdapter.connect') as mock_connect:
            mock_connect.side_effect = Exception("Connection failed")
            
            await self.skillkit.initialize()
            skills = self.skillkit.getSkills()
            self.assertEqual(len(skills), 0)  # 应该没有技能被加载

if __name__ == '__main__':
    unittest.main()
```

### 8.2 集成测试 (`tests/integration_test/test_mcp_integration.py`)

```python
import unittest
import asyncio
import tempfile
import os
from DolphinLanguageSDK.skill.installed.mcp_skillkit import MCPSkillkit
from DolphinLanguageSDK.skill.installed.mcp_adapter import MCPServerConfig

class TestMCPIntegration(unittest.TestCase):
    def setUp(self):
        self.playwright_config = MCPServerConfig(
            name="playwright",
            url="http://localhost:3001"
        )
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)
    
    async def test_playwright_workflow(self):
        """测试 Playwright MCP 完整工作流程"""
        skillkit = MCPSkillkit(self.playwright_config)
        
        try:
            await skillkit.initialize()
            
            # 获取可用技能
            skills = skillkit.getSkills()
            
            # 查找导航技能
            nav_skill = None
            screenshot_skill = None
            
            for skill in skills:
                if 'navigate' in skill.func.__name__ or 'goto' in skill.func.__name__:
                    nav_skill = skill
                elif 'screenshot' in skill.func.__name__:
                    screenshot_skill = skill
            
            if nav_skill:
                result = nav_skill.func(url="https://example.com")
                self.assertIsInstance(result, str)
                self.assertNotIn("Error", result)
            
            if screenshot_skill:
                screenshot_path = os.path.join(self.temp_dir, "test.png")
                result = screenshot_skill.func(path=screenshot_path)
                self.assertIsInstance(result, str)
                self.assertNotIn("Error", result)
            
        finally:
            skillkit.shutdown()
    
    async def test_concurrent_operations(self):
        """测试并发操作"""
        skillkit = MCPSkillkit(self.playwright_config)
        
        try:
            await skillkit.initialize()
            
            # 获取可用技能
            skills = skillkit.getSkills()
            
            # 查找可用技能
            test_skills = []
            for skill in skills:
                if len(test_skills) < 3:  # 最多取3个技能进行测试
                    test_skills.append(skill)
            
            # 并发执行技能
            tasks = []
            for skill in test_skills:
                if 'navigate' in skill.func.__name__ or 'goto' in skill.func.__name__:
                    task = asyncio.create_task(
                        asyncio.to_thread(skill.func, url="https://example.com")
                    )
                    tasks.append(task)
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # 检查结果
                for result in results:
                    if isinstance(result, Exception):
                        self.fail(f"Concurrent operation failed: {result}")
                    
        finally:
            skillkit.shutdown()

if __name__ == '__main__':
    unittest.main()
```

### 8.3 性能测试 (`tests/performance/test_mcp_performance.py`)

```python
import unittest
import asyncio
import time
from DolphinLanguageSDK.skill.installed.mcp_skillkit import MCPSkillkit
from DolphinLanguageSDK.skill.installed.mcp_adapter import MCPServerConfig

class TestMCPPerformance(unittest.TestCase):
    def setUp(self):
        self.server_config = MCPServerConfig(
            name="performance_test_server",
            url="http://localhost:3004"
        )
        self.skillkit = MCPSkillkit(self.server_config)
    
    async def test_response_time(self):
        """测试响应时间"""
        await self.skillkit.initialize()
        
        start_time = time.time()
        skills = self.skillkit.getSkills()
        
        if skills:
            result = skills[0].func()
            end_time = time.time()
            
            response_time = end_time - start_time
            self.assertLess(response_time, 5.0, f"Response time {response_time}s exceeds 5s limit")
    
    async def test_concurrent_load(self):
        """测试并发负载"""
        await self.skillkit.initialize()
        skills = self.skillkit.getSkills()
        
        if skills:
            # 创建 10 个并发任务
            tasks = []
            for _ in range(10):
                task = asyncio.create_task(
                    asyncio.to_thread(skills[0].func)
                )
                tasks.append(task)
            
            start_time = time.time()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            end_time = time.time()
            
            total_time = end_time - start_time
            self.assertLess(total_time, 10.0, f"Concurrent load test took {total_time}s")

if __name__ == '__main__':
    unittest.main()
```

---

## 9. 性能优化

### 9.1 连接池管理 (`src/DolphinLanguageSDK/mcp/connection_pool.py`)

```python
import asyncio
import logging
from typing import Dict, List, Optional
from DolphinLanguageSDK.skill.installed.mcp_adapter import MCPAdapter, MCPServerConfig

class MCPConnectionPool:
    """MCP 连接池"""
    
    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.connections: Dict[str, List[MCPAdapter]] = {}
        self.locks: Dict[str, asyncio.Lock] = {}
        self.logger = logging.getLogger("mcp.connection_pool")
    
    async def get_adapter(self, server_name: str, config: MCPServerConfig) -> MCPAdapter:
        """获取可用的适配器"""
        if server_name not in self.locks:
            self.locks[server_name] = asyncio.Lock()
        
        async with self.locks[server_name]:
            if server_name not in self.connections:
                self.connections[server_name] = []
            
            # 查找可用的连接
            for adapter in self.connections[server_name]:
                if adapter.session is not None:
                    return adapter
            
            # 创建新连接
            if len(self.connections[server_name]) < self.max_connections:
                adapter = MCPAdapter(config)
                await adapter.connect()
                self.connections[server_name].append(adapter)
                self.logger.info(f"Created new connection for {server_name}")
                return adapter
            
            # 等待可用连接
            while True:
                for adapter in self.connections[server_name]:
                    if adapter.session is not None:
                        return adapter
                await asyncio.sleep(0.1)
    
    async def return_adapter(self, server_name: str, adapter: MCPAdapter) -> None:
        """归还适配器（连接池保持连接）"""
        # 连接池中的连接保持活跃状态
        pass
    
    async def close_all(self) -> None:
        """关闭所有连接"""
        for server_name, adapters in self.connections.items():
            for adapter in adapters:
                await adapter.disconnect()
        self.connections.clear()
```

### 9.2 缓存机制 (`src/DolphinLanguageSDK/mcp/cache.py`)

```python
import asyncio
import time
from typing import Any, Optional, Dict
from DolphinLanguageSDK.utils.cache_kv import GlobalCacheKVCenter

class MCPCache:
    """MCP 缓存管理器"""
    
    def __init__(self, cache_dir: str = "data/cache/mcp", expire_time_by_day: int = 1):
        self.cache_mgr = GlobalCacheKVCenter.getCacheMgr(
            cache_dir, 
            category='mcp', 
            expireTimeByDay=expire_time_by_day
        )
    
    def get_cache_key(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> list:
        """生成缓存键"""
        return [
            {
                "server": server_name,
                "tool": tool_name,
                "arguments": arguments
            }
        ]
    
    def get(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Optional[Any]:
        """获取缓存值"""
        cache_key = self.get_cache_key(server_name, tool_name, arguments)
        return self.cache_mgr.getValue(server_name, cache_key)
    
    def set(self, server_name: str, tool_name: str, arguments: Dict[str, Any], value: Any) -> None:
        """设置缓存值"""
        cache_key = self.get_cache_key(server_name, tool_name, arguments)
        self.cache_mgr.setValue(server_name, cache_key, value)
    
    def invalidate(self, server_name: str, tool_name: str = None) -> None:
        """清除缓存"""
        if tool_name:
            # 清除特定工具的缓存
            pass
        else:
            # 清除整个服务器的缓存
            pass
```

### 9.3 监控和日志 (`src/DolphinLanguageSDK/mcp/monitor.py`)

```python
import time
import logging
from functools import wraps
from typing import Dict, Any, Callable
from dataclasses import dataclass, field
from collections import defaultdict

@dataclass
class MCPMetrics:
    """MCP 性能指标"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_response_time: float = 0.0
    min_response_time: float = float('inf')
    max_response_time: float = 0.0
    last_call_time: float = 0.0

class MCPMonitor:
    """MCP 监控器"""
    
    def __init__(self):
        self.metrics: Dict[str, MCPMetrics] = defaultdict(MCPMetrics)
        self.logger = logging.getLogger("mcp.monitor")
    
    def record_call(self, server_name: str, tool_name: str, response_time: float, success: bool):
        """记录调用指标"""
        key = f"{server_name}.{tool_name}"
        metric = self.metrics[key]
        
        metric.total_calls += 1
        metric.last_call_time = time.time()
        metric.total_response_time += response_time
        
        if success:
            metric.successful_calls += 1
        else:
            metric.failed_calls += 1
        
        metric.min_response_time = min(metric.min_response_time, response_time)
        metric.max_response_time = max(metric.max_response_time, response_time)
    
    def get_stats(self, server_name: str = None) -> Dict[str, Any]:
        """获取统计信息"""
        if server_name:
            return {k: v for k, v in self.metrics.items() if k.startswith(server_name)}
        return dict(self.metrics)
```

---

## 10. 安全考虑

### 10.1 命令执行安全

- **白名单机制**: 只允许执行预定义的安全命令
- **参数验证**: 严格验证传递给 MCP 服务器的参数
- **沙箱环境**: 在隔离的环境中运行 MCP 服务器

### 10.2 网络安全

- **本地通信**: 优先使用本地 stdio 通信，避免网络暴露
- **访问控制**: 限制 MCP 服务器的文件系统访问权限
- **日志审计**: 记录所有 MCP 操作用于安全审计

---

## 11. 实现指南

### 11.1 开发步骤

按照以下步骤实现 MCP 集成：

#### 步骤 1: 安装官方 MCP SDK
```bash
# 安装官方 MCP Python SDK
pip install "mcp>=1.0.0"

# 安装 MCP 服务器（可选）
npm install -g @playwright/mcp  # Playwright 浏览器自动化
npx playwright install
```

#### 步骤 2: 创建 MCP 集成文件
```bash
# 创建 MCP 适配器和技能套件文件
touch src/DolphinLanguageSDK/skill/installed/mcp_adapter.py
touch src/DolphinLanguageSDK/skill/installed/mcp_skillkit.py
```

#### 步骤 3: 实现核心组件
1. 在 `mcp_adapter.py` 中实现 `MCPAdapter` 封装官方 SDK
2. 在 `mcp_skillkit.py` 中实现 `MCPSkillkit` 基类
3. 扩展 `global_config.py` 添加 MCP 配置支持

#### 步骤 4: 集成到现有系统
1. 修改 `GlobalSkills` 类，添加 MCP 技能加载逻辑
2. 更新配置文件，添加 MCP 配置段
3. 更新 `pyproject.toml` 添加 `mcp` 依赖

#### 步骤 5: 测试验证
```bash
# 创建测试文件
touch examples/mcp_test.dph

# 编写测试内容
echo '@playwright_goto(url="https://example.com") -> result' > examples/mcp_test.dph
echo 'print("结果: " + $result)' >> examples/mcp_test.dph

# 运行测试
python -m DolphinLanguageSDK examples/mcp_test.dph
```

### 11.2 关键实现要点

1. **官方 SDK 优势**: 使用官方 MCP Python SDK 确保协议兼容性和稳定性
2. **异步兼容性**: 通过线程池处理异步调用，与现有同步技能系统兼容
3. **错误处理**: 实现完善的错误处理和恢复机制
4. **配置验证**: 添加配置文件验证逻辑
5. **日志集成**: 使用现有的日志系统记录 MCP 操作

### 11.3 测试策略

1. **单元测试**: 测试 MCP 适配器和技能套件的核心功能
2. **集成测试**: 验证与 Dolphin Language 系统的集成
3. **端到端测试**: 编写完整的工作流程测试用例

### 11.4 设计优势

✅ **使用官方 SDK**: 避免重复造轮子，确保协议兼容性  
✅ **语法规范**: 修正 Dolphin 语法，符合项目实际规范  
✅ **简化实现**: 减少自定义代码，提高可维护性  
✅ **标准化**: 遵循 MCP 官方最佳实践

---

## 12. 故障排除

### 12.1 常见问题

**问题**: MCP 服务器启动失败
- **原因**: 依赖未安装或配置错误
- **解决**: 检查依赖安装和配置文件

**问题**: 技能调用超时
- **原因**: MCP 服务器响应慢或网络问题
- **解决**: 增加超时时间或检查网络连接

**问题**: 权限错误
- **原因**: 文件系统权限不足
- **解决**: 检查和调整文件权限设置

### 12.2 调试建议

1. 启用详细日志记录
2. 使用调试模式运行 MCP 服务器
3. 检查进程状态和资源使用
4. 验证配置文件格式和内容