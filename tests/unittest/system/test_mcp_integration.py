import unittest
import tempfile
import os
import yaml
from unittest.mock import patch

# 引入被测试的模块
from dolphin.core.config.global_config import (
    GlobalConfig,
    MCPConfig,
    MCPServerConfig,
)
from dolphin.sdk.skill.global_skills import GlobalSkills


class TestMCPIntegration(unittest.TestCase):
    """测试MCP集成功能"""

    def setUp(self):
        """设置测试环境"""
        self.test_config = {
            "default": "test_llm",
            "clouds": {
                "default": "test_cloud",
                "test_cloud": {"api": "https://test.api.com", "api_key": "test_key"},
            },
            "llms": {
                "test_llm": {
                    "cloud": "test_cloud",
                    "model_name": "test_model",
                    "type_api": "openai",
                }
            },
            "mcp": {
                "enabled": True,
                "servers": [
                    {
                        "name": "test_server",
                        "connection_mode": "stdio",
                        "command": "npx",
                        "args": ["@modelcontextprotocol/server-filesystem", "/tmp"],
                        "timeout": 30,
                        "enabled": True,
                    }
                ],
            },
        }

    def test_mcp_config_from_dict(self):
        """测试从字典创建MCP配置"""
        mcp_config_dict = {
            "enabled": True,
            "servers": [
                {
                    "name": "test_server",
                    "connection_mode": "stdio",
                    "command": "npx",
                    "args": ["@modelcontextprotocol/server-filesystem", "/tmp"],
                    "timeout": 30,
                    "enabled": True,
                }
            ],
        }

        mcp_config = MCPConfig.from_dict(mcp_config_dict)

        self.assertTrue(mcp_config.enabled)
        self.assertEqual(len(mcp_config.servers), 1)
        self.assertEqual(mcp_config.servers[0].name, "test_server")
        self.assertEqual(mcp_config.servers[0].connection_mode, "stdio")
        self.assertEqual(mcp_config.servers[0].command, "npx")
        self.assertEqual(
            mcp_config.servers[0].args,
            ["@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        self.assertEqual(mcp_config.servers[0].timeout, 30)
        self.assertTrue(mcp_config.servers[0].enabled)

    def test_mcp_server_config_from_dict(self):
        """测试从字典创建MCP服务器配置"""
        server_config_dict = {
            "name": "test_server",
            "connection_mode": "http",
            "url": "http://localhost:3001",
            "auth": {"type": "bearer", "token": "test_token"},
            "timeout": 60,
            "enabled": False,
        }

        server_config = MCPServerConfig.from_dict(server_config_dict)

        self.assertEqual(server_config.name, "test_server")
        self.assertEqual(server_config.connection_mode, "http")
        self.assertEqual(server_config.url, "http://localhost:3001")
        self.assertEqual(server_config.auth, {"type": "bearer", "token": "test_token"})
        self.assertEqual(server_config.timeout, 60)
        self.assertFalse(server_config.enabled)

    def test_global_config_with_mcp(self):
        """测试全局配置包含MCP配置"""
        global_config = GlobalConfig.from_dict(self.test_config)

        self.assertIsNotNone(global_config.mcp_config)
        self.assertTrue(global_config.mcp_config.enabled)
        self.assertEqual(len(global_config.mcp_config.servers), 1)
        self.assertEqual(global_config.mcp_config.servers[0].name, "test_server")

    def test_global_config_without_mcp(self):
        """测试全局配置不包含MCP配置时的默认行为"""
        config_without_mcp = {
            "default": "test_llm",
            "clouds": {
                "default": "test_cloud",
                "test_cloud": {"api": "https://test.api.com", "api_key": "test_key"},
            },
            "llms": {
                "test_llm": {
                    "cloud": "test_cloud",
                    "model_name": "test_model",
                    "type_api": "openai",
                }
            },
        }

        global_config = GlobalConfig.from_dict(config_without_mcp)

        self.assertIsNotNone(global_config.mcp_config)
        self.assertTrue(global_config.mcp_config.enabled)  # 默认启用
        self.assertEqual(len(global_config.mcp_config.servers), 0)  # 默认没有服务器

    def test_mcp_config_to_dict(self):
        """测试MCP配置转换为字典"""
        server_config = MCPServerConfig(
            name="test_server",
            connection_mode="stdio",
            command="npx",
            args=["@modelcontextprotocol/server-filesystem", "/tmp"],
            timeout=30,
            enabled=True,
        )

        mcp_config = MCPConfig(enabled=True, servers=[server_config])

        config_dict = mcp_config.to_dict()

        self.assertTrue(config_dict["enabled"])
        self.assertEqual(len(config_dict["servers"]), 1)
        self.assertEqual(config_dict["servers"][0]["name"], "test_server")
        self.assertEqual(config_dict["servers"][0]["connection_mode"], "stdio")
        self.assertEqual(config_dict["servers"][0]["command"], "npx")

    @patch("dolphin.sdk.skill.global_skills.GlobalSkills._loadMCPSkills")
    def test_global_skills_skip_mcp_when_disabled(self, mock_load_mcp):
        """测试当MCP禁用时GlobalSkills不加载MCP技能"""
        config_with_disabled_mcp = self.test_config.copy()
        config_with_disabled_mcp["mcp"]["enabled"] = False

        global_config = GlobalConfig.from_dict(config_with_disabled_mcp)

        # 创建GlobalSkills实例
        global_skills = GlobalSkills(global_config)

        # 验证_loadMCPSkills方法未被调用
        mock_load_mcp.assert_not_called()

    def test_yaml_config_loading(self):
        """测试从YAML文件加载配置"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(self.test_config, f)
            yaml_file = f.name

        try:
            global_config = GlobalConfig.from_yaml(yaml_file)

            self.assertIsNotNone(global_config.mcp_config)
            self.assertTrue(global_config.mcp_config.enabled)
            self.assertEqual(len(global_config.mcp_config.servers), 1)
            self.assertEqual(global_config.mcp_config.servers[0].name, "test_server")

        finally:
            os.unlink(yaml_file)

    def test_mcp_server_config_defaults(self):
        """测试MCP服务器配置的默认值"""
        server_config = MCPServerConfig(name="test_server", command="npx")

        self.assertEqual(server_config.connection_mode, "stdio")
        self.assertEqual(server_config.auth, None)
        self.assertEqual(server_config.timeout, 30)
        self.assertFalse(server_config.enabled)

    def test_mcp_config_defaults(self):
        """测试MCP配置的默认值"""
        mcp_config = MCPConfig()

        self.assertTrue(mcp_config.enabled)
        self.assertEqual(len(mcp_config.servers), 0)

    def test_mcp_server_config_validation(self):
        """测试MCP服务器配置验证"""
        # 测试stdio模式需要command
        with self.assertRaises(ValueError):
            MCPServerConfig(
                name="test_server",
                connection_mode="stdio",
                # 缺少command参数
            )

        # 测试http模式需要url
        with self.assertRaises(ValueError):
            MCPServerConfig(
                name="test_server",
                connection_mode="http",
                # 缺少url参数
            )

        # 测试无效的connection_mode
        with self.assertRaises(ValueError):
            MCPServerConfig(name="test_server", connection_mode="invalid_mode")

    def test_mcp_server_config_to_dict(self):
        """测试MCP服务器配置转换为字典"""
        server_config = MCPServerConfig(
            name="test_server",
            connection_mode="stdio",
            command="npx",
            args=["@modelcontextprotocol/server-filesystem", "/tmp"],
            env={"NODE_ENV": "production"},
            timeout=45,
            enabled=True,
            auth={"type": "bearer", "token": "test_token"},
        )

        config_dict = server_config.to_dict()

        self.assertEqual(config_dict["name"], "test_server")
        self.assertEqual(config_dict["connection_mode"], "stdio")
        self.assertEqual(config_dict["command"], "npx")
        self.assertEqual(
            config_dict["args"], ["@modelcontextprotocol/server-filesystem", "/tmp"]
        )
        self.assertEqual(config_dict["env"], {"NODE_ENV": "production"})
        self.assertEqual(config_dict["timeout"], 45)
        self.assertTrue(config_dict["enabled"])
        self.assertEqual(config_dict["auth"], {"type": "bearer", "token": "test_token"})


if __name__ == "__main__":
    unittest.main()
