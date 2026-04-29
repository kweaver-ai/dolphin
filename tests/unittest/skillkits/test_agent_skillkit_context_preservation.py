import pytest

from dolphin.core.context.context import Context
from dolphin.lib.skillkits.agent_skillkit import AgentSkillKit


class _FakeExecutor:
    def __init__(self, context: Context):
        self.context = context

    def set_context(self, context: Context):
        self.context = context


class _FakeAgent:
    def __init__(self):
        self.executor = None

    def get_name(self) -> str:
        return "fake_agent"

    def get_description(self) -> str:
        return "fake"

    async def initialize(self) -> bool:
        # Simulate real DolphinAgent behavior: initialize recreates executor/context.
        self.executor = _FakeExecutor(Context(verbose=True, is_cli=True))
        return True

    def set_context(self, context: Context):
        if self.executor is None:
            self.executor = _FakeExecutor(context)
        else:
            self.executor.set_context(context)

    async def arun(self, **_kwargs):
        yield {"answer": {"answer": "ok", "think": ""}}


@pytest.mark.asyncio
async def test_agent_skillkit_re_attaches_parent_context_after_initialize():
    parent_context = Context(verbose=True, is_cli=True)
    fake_agent = _FakeAgent()
    kit = AgentSkillKit(fake_agent, "fake_agent")

    kit.set_context(parent_context)
    await kit.arunAgentFunc(query_str="hello")

    assert fake_agent.executor.context is parent_context

