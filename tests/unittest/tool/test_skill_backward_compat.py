import pytest

from dolphin.core import Skillkit, Skillset
from dolphin.core.config.global_config import SkillConfig
from dolphin.sdk import GlobalSkills
from dolphin.sdk.runtime.env import Env


class _DummyTool:
    def __init__(self, name: str):
        self._name = name

    def get_function_name(self):
        return self._name


class _DummySkillkit(Skillkit):
    def _createTools(self):
        return [_DummyTool("demo_tool")]


def test_skillkit_get_skills_delegates_to_get_tools():
    skillkit = _DummySkillkit()

    with pytest.warns(DeprecationWarning):
        skills = skillkit.getSkills()

    assert [tool.get_function_name() for tool in skills] == ["demo_tool"]


def test_skillset_legacy_methods_delegate_to_toolset_methods():
    skillset = Skillset()
    tool = _DummyTool("demo_tool")
    skillkit = _DummySkillkit()

    with pytest.warns(DeprecationWarning):
        skillset.addSkill(tool)
    with pytest.warns(DeprecationWarning):
        skillset.addSkillkit(skillkit)
    with pytest.warns(DeprecationWarning):
        skills = skillset.getSkills()

    assert {item.get_function_name() for item in skills} == {"demo_tool"}


def test_global_skills_legacy_members_delegate_to_global_toolkits():
    global_skills = object.__new__(GlobalSkills)
    installed_toolset = object()
    agent_toolset = object()
    all_tools = object()
    called = {}

    global_skills.installedToolSet = installed_toolset
    global_skills.agentToolSet = agent_toolset
    global_skills.getAllTools = lambda: all_tools
    global_skills.getInstalledTools = lambda: installed_toolset
    global_skills.getAgentTools = lambda: agent_toolset
    global_skills.registerAgentTool = lambda name, agent: called.update(
        register=(name, agent)
    )
    global_skills.unregisterAgentTool = lambda name: called.update(unregister=name)

    with pytest.warns(DeprecationWarning):
        assert global_skills.installedSkillset is installed_toolset
    with pytest.warns(DeprecationWarning):
        assert global_skills.agentSkillset is agent_toolset
    with pytest.warns(DeprecationWarning):
        assert global_skills.getAllSkills() is all_tools
    with pytest.warns(DeprecationWarning):
        assert global_skills.getInstalledSkills() is installed_toolset
    with pytest.warns(DeprecationWarning):
        assert global_skills.getAgentSkills() is agent_toolset

    agent = object()
    with pytest.warns(DeprecationWarning):
        global_skills.registerAgentSkill("demo", agent)
    with pytest.warns(DeprecationWarning):
        global_skills.unregisterAgentSkill("demo")

    assert called == {"register": ("demo", agent), "unregister": "demo"}


def test_env_get_global_skills_delegates_to_global_toolkits():
    env = object.__new__(Env)
    env.globalToolkits = object()

    with pytest.warns(DeprecationWarning):
        result = env.getGlobalSkills()

    assert result is env.globalToolkits


def test_skill_config_legacy_members_delegate_to_tool_config():
    config = SkillConfig(enabled_tools=["vm_toolkit"])

    with pytest.warns(DeprecationWarning):
        assert config.enabled_skills == ["vm_toolkit"]
    with pytest.warns(DeprecationWarning):
        assert config.should_load_skill("vm") is True
    with pytest.warns(DeprecationWarning):
        config.enabled_skills = ["search"]

    assert config.enabled_tools == ["search"]


def test_deprecated_skill_modules_export_wrapped_compat_classes():
    from dolphin.core.skill import Skillkit as DeprecatedSkillkit
    from dolphin.sdk.skill import GlobalSkills as DeprecatedGlobalSkills

    assert DeprecatedSkillkit is Skillkit
    assert DeprecatedGlobalSkills is GlobalSkills
