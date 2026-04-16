import unittest

from dolphin.core.config.global_config import SkillConfig


class TestSkillConfig(unittest.TestCase):
    def test_should_load_skill_accepts_toolkit_suffix_for_entrypoint_names(self):
        config = SkillConfig(enabled_skills=["vm_toolkit", "resource_toolkit"])
        self.assertTrue(config.should_load_skill("vm"))
        self.assertTrue(config.should_load_skill("vm_toolkit"))
        self.assertTrue(config.should_load_skill("resource_toolkit"))

    def test_should_load_skill_accepts_entrypoint_names_for_file_names(self):
        config = SkillConfig(enabled_skills=["vm", "search"])
        self.assertTrue(config.should_load_skill("vm_toolkit"))
        self.assertTrue(config.should_load_skill("search_toolkit"))

    def test_should_load_skill_does_not_break_mcp_namespacing(self):
        config = SkillConfig(enabled_skills=["mcp.playwright"])
        self.assertTrue(config.should_load_skill("mcp.playwright"))
        self.assertFalse(config.should_load_skill("mcp.filesystem"))

        config_all = SkillConfig(enabled_skills=["mcp"])
        self.assertTrue(config_all.should_load_skill("mcp.playwright"))


if __name__ == "__main__":
    unittest.main()

