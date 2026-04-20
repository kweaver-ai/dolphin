import unittest

from dolphin.core.config.global_config import ToolConfig


class TestToolConfig(unittest.TestCase):
    def test_should_load_tool_accepts_toolkit_suffix_for_entrypoint_names(self):
        config = ToolConfig(enabled_tools=["vm_toolkit", "resource_toolkit"])
        self.assertTrue(config.should_load_tool("vm"))
        self.assertTrue(config.should_load_tool("vm_toolkit"))
        self.assertTrue(config.should_load_tool("resource_toolkit"))

    def test_should_load_tool_accepts_entrypoint_names_for_file_names(self):
        config = ToolConfig(enabled_tools=["vm", "search"])
        self.assertTrue(config.should_load_tool("vm_toolkit"))
        self.assertTrue(config.should_load_tool("search_toolkit"))

    def test_should_load_tool_does_not_break_mcp_namespacing(self):
        config = ToolConfig(enabled_tools=["mcp.playwright"])
        self.assertTrue(config.should_load_tool("mcp.playwright"))
        self.assertFalse(config.should_load_tool("mcp.filesystem"))

        config_all = ToolConfig(enabled_tools=["mcp"])
        self.assertTrue(config_all.should_load_tool("mcp.playwright"))


if __name__ == "__main__":
    unittest.main()
