"""
Dynamic Tool Provider Module

Provides the ability to dynamically load tools in Explore mode.
Tools can be loaded based on runtime parameters and automatically become available to the LLM.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any
from dataclasses import dataclass


@dataclass
class DynamicToolDefinition:
    """
    动态工具定义
    
    支持两种工具类型：
    1. 预实例化工具：提供 tool_instance（本地函数包装或预创建的工具对象）
    2. API 工具：提供 api_url、original_schema、fixed_params，系统自动创建 DynamicAPISkillFunction
    
    Attributes:
        name: 工具名称
        description: 工具描述（给 LLM 看的）
        parameters: OpenAI function schema 的 parameters 部分
        tool_instance: 工具对象实例（可选，如果提供则直接使用）
        api_url: API 工具的 URL 地址（用于 API 工具）
        original_schema: API 工具的原始 schema 信息（用于进一步处理）
        fixed_params: 固定参数字典（在调用时替换模型生成的值）
        api_call_strategy: API 调用策略（如 "kn_action_recall"），用于标识特殊的 API 工具类型
    
    Note:
        动态加载的工具会自动添加中断保护（interrupt_config），无需在此定义。
        SDK会在加载时自动为所有动态工具添加友好的中断提示。
    """
    name: str
    description: str
    parameters: Dict[str, Any]  # OpenAI function schema parameters
    tool_instance: Any = None  # 工具对象实例（可选）
    api_url: str = None  # API URL（用于 API 工具）
    original_schema: Dict[str, Any] = None  # 原始 schema（用于 API 工具）
    fixed_params: Dict[str, str] = None  # 固定参数（用于 API 工具）
    api_call_strategy: str = None  # API 调用策略（用于标识特殊的 API 工具）
    
    def __post_init__(self):
        """验证工具定义"""
        # 必须提供 tool_instance 或 api_call_strategy 之一
        if self.tool_instance is None and self.api_call_strategy is None:
            raise ValueError(
                f"工具 '{self.name}' 必须提供 tool_instance 或 api_call_strategy 之一。"
            )
        
        # 如果同时提供了两者，优先使用 tool_instance
        if self.tool_instance is not None and self.api_call_strategy is not None:
            import warnings
            warnings.warn(
                f"工具 '{self.name}' 同时提供了 tool_instance 和 api_call_strategy，"
                f"将使用 tool_instance。"
            )
        
        # 初始化可选字段
        if self.original_schema is None:
            self.original_schema = {}
        if self.fixed_params is None:
            self.fixed_params = {}
    
    def is_api_tool(self) -> bool:
        """判断是否为需要特殊处理的 API 工具"""
        return self.tool_instance is None and self.api_call_strategy is not None


class DynamicToolProvider(ABC):
    """
    Dynamic Tool Provider Base Class
    
    Usage:
    1. Inherit this class and implement the provide_tools method
    2. Return a list of DynamicToolDefinition based on the parameters
    3. Register the instance using DynamicToolProviderTool
    
    Example:
        class GitHubToolProvider(DynamicToolProvider):
            async def provide_tools(self, **kwargs):
                context = kwargs.get("context", "")
                
                async def list_repos(username: str, **kwargs):
                    return f"Repos for {username}: repo1, repo2"
                
                return [
                    DynamicToolDefinition(
                        name="github_list_repos",
                        description="List user's GitHub repositories",
                        parameters={
                            "type": "object",
                            "properties": {
                                "username": {"type": "string", "description": "Username"}
                            },
                            "required": ["username"]
                        },
                        implementation=list_repos
                    )
                ]
    """
    
    @abstractmethod
    async def provide_tools(self, **kwargs) -> List[DynamicToolDefinition]:
        """
        Provide tool list based on parameters
        
        Args:
            **kwargs: Call parameters (e.g., context="repository", platform="github")
            
        Returns:
            List[DynamicToolDefinition]: Tool definition list
        """
        pass
    
    def get_provider_name(self) -> str:
        """Get provider name"""
        return self.__class__.__name__


class DynamicToolProviderTool:
    """
    Wrapper for DynamicToolProvider as a callable tool
    
    This tool is special because:
    - Returns format {"_dynamic_tools": [...], "message": "..."}
    - Explore loop detects this format and automatically loads tools
    - Supports custom parameter schema
    """
    
    def __init__(
        self, 
        provider: DynamicToolProvider, 
        tool_name: str = None,
        tool_description: str = None,
        parameters_schema: Dict[str, Any] = None,
        headers: Dict[str, str] = None
    ):
        """
        Initialize Dynamic Tool Provider Tool
        
        Args:
            provider: DynamicToolProvider instance
            tool_name: Tool name (default: load_{provider_name}_tools)
            tool_description: Tool description (optional)
            parameters_schema: Parameter schema (optional, default only has context param)
            headers: HTTP headers to pass to all loaded tools (optional, e.g. x-account-type, x-account-id)
        """
        self.provider = provider
        self.tool_name = tool_name or f"load_{provider.get_provider_name().lower()}_tools"
        self.description = tool_description or (
            f"Dynamically load {provider.get_provider_name()} related toolset. "
            f"After calling this tool, related tools will be automatically available."
        )
        self.headers = headers or {}
        
        # Define tool input parameters
        self.inputs = parameters_schema or {
            "context": {
                "type": "string",
                "description": "Context information for tool loading (optional)",
                "required": False
            }
        }
        
        self.outputs = {
            "result": {
                "type": "object",
                "description": "Dynamically loaded tool list and loading result"
            }
        }
        
        # Required for TriditionalToolkit compatibility
        # Set result processing strategy for both app and llm categories
        self.result_process_strategy_cfg = [
            {"strategy": "default", "category": "app"},
            {"strategy": "default", "category": "llm"}
        ]
    
    async def arun_stream(self, **kwargs):
        """
        异步流式执行
        
        Args:
            **kwargs: 传递给 provider.provide_tools 的参数
            
        Yields:
            dict: 包含 _dynamic_tools 键的特殊格式响应
        """
        print(f"[DynamicToolProviderTool] arun_stream called with kwargs: {kwargs}")
        
        # 调用 provider 获取工具定义
        tool_definitions = await self.provider.provide_tools(**kwargs)
        
        # 构建工具信息列表
        tool_names = [tool_def.name for tool_def in tool_definitions]
        
        # 构建动态工具列表（新格式）
        _dynamic_tools = []
        for tool_def in tool_definitions:
            tool_data = {
                "name": tool_def.name,
                "description": tool_def.description,
                "parameters": tool_def.parameters,
            }
            
            # 根据工具类型添加不同的字段
            if tool_def.is_api_tool():
                # API 工具：添加 API 相关信息
                tool_data["api_url"] = tool_def.api_url
                tool_data["original_schema"] = tool_def.original_schema
                tool_data["fixed_params"] = tool_def.fixed_params
                tool_data["api_call_strategy"] = tool_def.api_call_strategy
                print(f"[DynamicToolProviderTool] Adding API tool: {tool_def.name}, strategy: {tool_def.api_call_strategy}")
            else:
                # 预实例化工具：直接添加实例
                tool_data["tool_instance"] = tool_def.tool_instance
                print(f"[DynamicToolProviderTool] Adding pre-instantiated tool: {tool_def.name}")
            
            # Note: interrupt_config 不需要在这里传递
            # SDK会在 _load_dynamic_tools() 中自动为所有动态工具添加中断保护
            
            _dynamic_tools.append(tool_data)
        
        # 构建动态工具响应内容
        dynamic_tools_data = {
            "_dynamic_tools": _dynamic_tools,
            "provider": self.provider.get_provider_name(),
            "loaded_count": len(tool_definitions),
            "tool_names": tool_names,
            "message": f"成功加载 {len(tool_definitions)} 个工具: {', '.join(tool_names)}"
        }
        
        # 如果有 headers，添加到响应中
        if self.headers:
            dynamic_tools_data["headers"] = self.headers
            print(f"[DynamicToolProviderTool] Adding headers to response: {self.headers}")
        
        # 包装在 answer 键中，以符合 Dolphin SDK 的期望格式
        result = {
            "answer": dynamic_tools_data
        }
        
        print(f"[DynamicToolProviderTool] Yielding result with {len(tool_definitions)} tools")
        print(f"[DynamicToolProviderTool] Result format: answer._dynamic_tools exists: {'_dynamic_tools' in dynamic_tools_data}")
        
        yield result
    
    def get_first_valid_app_strategy(self) -> str:
        """Get the first valid APP strategy"""
        if not self.result_process_strategy_cfg:
            return "default"
        
        for strategy in self.result_process_strategy_cfg:
            if strategy.get("category") == "app":
                return strategy.get("strategy")
        return "default"
    
    def get_first_valid_llm_strategy(self) -> str:
        """Get the first valid LLM strategy"""
        if not self.result_process_strategy_cfg:
            return "default"
        
        for strategy in self.result_process_strategy_cfg:
            if strategy.get("category") == "llm":
                return strategy.get("strategy")
        return "default"
    
    def get_tool_json(self):
        """
        Return tool's JSON description (for TriditionalToolkit)
        
        Returns:
            dict: OpenAI tool schema format
        """
        # Build properties and required from self.inputs
        properties = {}
        required = []
        
        for param_name, param_info in self.inputs.items():
            properties[param_name] = {
                "type": param_info.get("type", "string"),
                "description": param_info.get("description", "")
            }
            if param_info.get("required", False):
                required.append(param_name)
        
        return {
            "name": self.tool_name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

