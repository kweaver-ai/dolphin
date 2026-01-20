from typing import List, Any

from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit


class MockedSkillkit(Skillkit):
    def __init__(self):
        super().__init__()
        self.name = "mocked_skillkit"
        self.description = "mocked_skillkit"
        self.inputs = {}
        self.outputs = {}
        self.props = {}

    async def poemWriterStream(self, keyword: str, **kwargs) -> Any:
        """
        创作一首诗.

        Args:
            keyword: 包含的关键词
        """
        api_response = [
            {"answer": {"answer": f"{keyword}春风拂面暖"}},
            {"answer": {"answer": f"{keyword}春风拂面暖，花开满园香。"}},
            {"answer": {"answer": f"{keyword}春风拂面暖，花开满园香。蝴蝶舞翩跹，"}},
            {
                "answer": {
                    "answer": f"{keyword}春风拂面暖，花开满园香。蝴蝶舞翩跹，鸟儿唱悠扬。"
                }
            },
        ]

        async def async_generator(data):
            for item in data:
                yield item

        async for line in async_generator(api_response):
            try:
                item = line
            except Exception as e:
                print(e)
            yield item

    async def webSearch(self, texts: str = "", **kwargs) -> Any:
        """
        web search skill.

        Args:
            texts: 检索的文本
        """
        yield "检索结果"

    async def financeExpert(self, query: str = "", **kwargs) -> Any:
        """
        finance expert skill.

        Args:
            query: 提问的问题
        """
        yield '{"answer": {"answer": "计算机金融是利用计算机技术和数据分析方法来优化金融交易、风险管理、投资决策和金融服务的过程。"}, "block_answer":"!!!!!!!!",  "status": "True"}\n\n'

    async def computerExpert(self, query: str = "", **kwargs) -> Any:
        """
        computer expert skill.

        Args:
            query: 提问的问题
        """
        yield '{"answer": {"answer": "计算机金融是利用计算机技术和数据分析方法来优化金融交易、风险管理、投资决策和金融服务的过程。"}, "block_answer":"!!!!!!!!",  "status": "True"}\n\n'

    async def emailSender(
        self, email_address: str = "", content: str = "", **kwargs
    ) -> Any:
        """
        email sender skill.

        Args:
            email_address: 邮件地址
            content: 邮件内容
        """
        yield "邮件已发送到" + email_address + "，内容为：" + content

    async def saveToLocal(self, content: str = "", path: str = "", **kwargs) -> Any:
        """
        save to local skill.

        Args:
            content: 需要保存的内容
            path: 保存的路径
        """
        yield "内容已经保存至：" + path

    async def high_risk_tool(self, param: str = "", **kwargs) -> Any:
        """
        High risk operation that requires user confirmation.

        Args:
            param: Operation parameter
        """
        yield f"High risk operation completed successfully with param: {param}"

    async def safe_tool(self, param: str = "", **kwargs) -> Any:
        """
        Safe operation that doesn't require confirmation.

        Args:
            param: Operation parameter
        """
        yield f"Safe operation completed with param: {param}"

    def getSkills(self) -> List[SkillFunction]:
        """
        get tools skill.
        """
        high_risk_skill = SkillFunction(self.high_risk_tool)
        high_risk_skill.interrupt_config = {
            "requires_confirmation": True,
            "confirmation_message": "⚠️  Confirm high risk operation with param='{param}'? This operation cannot be undone!"
        }
        
        safe_skill = SkillFunction(self.safe_tool)
        
        return [
            SkillFunction(self.poemWriterStream),
            SkillFunction(self.webSearch),
            SkillFunction(self.financeExpert),
            SkillFunction(self.computerExpert),
            SkillFunction(self.emailSender),
            SkillFunction(self.saveToLocal),
            high_risk_skill,
            safe_skill,
        ]
