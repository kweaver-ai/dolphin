import json
from typing import Dict, Any, Optional, Iterator
from dolphin.core.utils.tools import Tool


class BaseMockedTool(Tool):
    """Base class for mocked tools to eliminate code duplication"""

    def __init__(
        self,
        name: str = None,
        description: str = None,
        inputs: dict = None,
        outputs: dict = None,
        props: dict = None,
    ):
        """Initialize base mocked tool with Tool parameters"""
        # Use class attributes as defaults if not provided
        name = name or getattr(self, "name", "")
        description = description or getattr(self, "description", "")
        inputs = inputs or getattr(self, "inputs", {})
        outputs = outputs or getattr(self, "outputs", {})
        props = props or getattr(self, "props", {})

        super().__init__(
            name=name,
            description=description,
            inputs=inputs,
            outputs=outputs,
            props=props,
        )

    async def arun_stream(
        self, tool_input: dict = None, props: Optional[dict] = None, **kwargs
    ) -> Any:
        """Default async implementation that delegates to sync run_stream"""
        # If kwargs are provided, use them as tool_input
        if kwargs:
            tool_input = kwargs
        elif tool_input is None:
            tool_input = {}

        sync_generator = self.run_stream(tool_input, props)
        for item in sync_generator:
            yield item

    def _parse_json_safely(self, json_string: str) -> dict:
        """Safely parse JSON string with error handling"""
        try:
            return json.loads(json_string, strict=False)
        except Exception as e:
            print(f"JSON parsing error: {e}")
            return {}

    def _process_api_response_list(self, api_response: list) -> Iterator[dict]:
        """Process a list of JSON strings and yield parsed objects"""
        for line in api_response:
            yield self._parse_json_safely(line)


class PoemWriterStreamTest(BaseMockedTool):
    name = "poemWriterStream"
    description = "创作诗歌"
    inputs = {}  # 不需要参数
    outputs = {"poem": {"type": "string", "description": "生成的诗歌内容"}}
    props = {}

    def __init__(self):
        """Initialize PoemWriterStreamTest"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def _get_poem_data(self) -> list:
        """Get poem generation response data"""
        return [
            '{"block_answer": {"retrievers_block_content": "春风拂面暖"}}',
            '{"block_answer": {"retrievers_block_content": "春风拂面暖，花开满园香。"}}',
            '{"block_answer": {"retrievers_block_content": "春风拂面暖，花开满园香。蝴蝶舞翩跹，"}}',
            '{"block_answer": {"retrievers_block_content": "春风拂面暖，花开满园香。蝴蝶舞翩跹，鸟儿唱悠扬。"}}',
        ]

    def run_stream(self, tool_input: dict = None, props: Optional[dict] = None) -> Any:
        """Generate poem content stream"""
        api_response = self._get_poem_data()
        yield from self._process_api_response_list(api_response)


class WebSearch(BaseMockedTool):
    name = "web_search"
    description = "互联网检索内容"
    inputs = {"texts": {"type": "string", "description": "检索query", "required": True}}
    outputs = {"content": {"type": "string", "description": "互联网检索内容"}}
    props = {}

    def __init__(self):
        """Initialize WebSearch"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def run(self, tool_input: dict, props: Optional[dict] = None) -> Any:
        return "检索结果"

    def run_stream(self, tool_input: dict, props: Optional[dict] = None) -> Any:
        yield self.run(tool_input, props)


class FinanceExpert(BaseMockedTool):
    name = "FinanceExpert"
    description = "金融专家回答金融问题"
    inputs = {"query": {"type": str, "description": "提问的问题", "required": True}}
    outputs = {
        "answer": {"type": str, "description": "agent最终输出"},
        "block_answer": {"type": dict, "description": "agent的逻辑块的输出"},
        "status": {
            "type": str,
            "description": 'agent运行状态。"True": 流式信息已结束."False": 流式信息未结束，正在返回."Error": 失败',
        },
    }
    props = {}

    def __init__(self):
        """Initialize FinanceExpert"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def _get_finance_response(self) -> list:
        """Get finance expert response data"""
        return [
            '{"answer": {"answer": "计算机金融是利用计算机技术和数据分析方法来优化金融交易、风险管理、投资决策和金融服务的过程。"}, "block_answer":"!!!!!!!!",  "status": "True"}\n\n'
        ]

    def run_stream(
        self, tool_input: Dict[str, Any], props: Optional[Dict] = None
    ) -> Any:
        api_response = self._get_finance_response()
        yield from self._process_api_response_list(api_response)


class ComputerExpert(BaseMockedTool):
    name = "ComputerExpert"
    description = "计算机专家回答计算机问题"
    inputs = {"query": {"type": str, "description": "提问的问题", "required": True}}
    outputs = {
        "answer": {"type": str, "description": "agent最终输出"},
        "block_answer": {"type": dict, "description": "agent的逻辑块的输出"},
        "status": {
            "type": str,
            "description": 'agent运行状态。"True": 流式信息已结束."False": 流式信息未结束，正在返回."Error": 失败',
        },
    }
    props = {}

    def __init__(self):
        """Initialize ComputerExpert"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def _get_computer_response(self) -> list:
        """Get computer expert response data"""
        return [
            '{"answer": {"answer": "计算机金融是利用计算机技术对金融数据进行处理和分析，以实现金融业务自动化、智能化的学科。"}, "block_answer":"!!!!!!!!",  "status": "True"}\n\n'
        ]

    def run_stream(
        self, tool_input: Dict[str, Any], props: Optional[Dict] = None
    ) -> Any:
        api_response = self._get_computer_response()
        yield from self._process_api_response_list(api_response)


class EmailSender(BaseMockedTool):
    name = "email_sender"
    description = "发送电子邮件"
    inputs = {
        "email_address": {
            "type": "string",
            "description": "收件人邮箱地址",
            "required": True,
        },
        "content": {"type": "string", "description": "邮件内容", "required": True},
    }
    outputs = {"status": {"type": "string", "description": "发送状态"}}
    props = {}

    def __init__(self):
        """Initialize EmailSender"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def run(self, tool_input: dict, props: Optional[dict] = None) -> Any:
        email = tool_input.get("email_address")
        content = tool_input.get("content")
        return f"邮件已发送到 {email}"

    def run_stream(self, tool_input: dict, props: Optional[dict] = None) -> Any:
        yield self.run(tool_input, props)


class SaveToLocal(BaseMockedTool):
    name = "saveToLocal"
    description = "将内容保存到本地文件"
    inputs = {
        "content": {"type": list, "description": "需要保存的内容", "required": True},
        "path": {"type": str, "description": "保存的路径", "required": True},
    }
    outputs = {"answer": {"type": list, "description": "通过校验的qa对"}}
    props = {}

    def __init__(self):
        """Initialize SaveToLocal"""
        super().__init__(
            name=self.name,
            description=self.description,
            inputs=self.inputs,
            outputs=self.outputs,
            props=self.props,
        )

    def _save_content_to_file(self, content: Any, file_path: str) -> str:
        """Save content to file based on file extension"""
        if file_path.strip().endswith("txt"):
            with open(file_path, "w", encoding="utf-8") as f:
                if isinstance(content, list):
                    for single_content in content:
                        lines = str(single_content).split("\n")
                        for line in lines:
                            f.write(line)
                            f.write("\n")
                else:
                    lines = str(content).split("\n")
                    for line in lines:
                        f.write(line)
                        f.write("\n")
        elif file_path.strip().endswith("json"):
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(content, f, ensure_ascii=False, indent=4)

        return f"内容已经保存至：{file_path}"

    def run_stream(
        self, tool_input: Dict[str, Any], props: Optional[Dict] = None
    ) -> Any:
        try:
            result_message = self._save_content_to_file(
                tool_input["content"], tool_input["path"]
            )
            yield {
                "answer": {"answer": result_message},
                "block_answer": "!!!!!!!!",
                "status": "True",
            }
        except Exception as e:
            yield {
                "answer": {"answer": f"保存失败: {str(e)}"},
                "block_answer": "",
                "status": "False",
            }
