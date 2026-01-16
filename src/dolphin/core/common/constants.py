import random


# Tool call ID prefix for generating fallback IDs
TOOL_CALL_ID_PREFIX = "call_"

MSG_CONTINUOUS_CONTENT = "如果问题未被解决我们就继续执行\n"
ANSWER_CONTENT_PREFIX = "<answer>"
ANSWER_CONTENT_SUFFIX = "</answer>"
MAX_ANSWER_CONTENT_LENGTH = 12288  # 12k - increased to prevent SKILL.md truncation
MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT = 2048
MAX_LOG_LENGTH = 2048

KEY_USER_ID = "_user_id"
KEY_SESSION_ID = "_session_id"
KEY_MAX_ANSWER_CONTENT_LENGTH = "_max_answer_len"

# Executor internal status variables (prefixed with underscore to avoid conflicts)
KEY_STATUS = "_status"
KEY_PREVIOUS_STATUS = "_previous_status"

MSG_DUPLICATE_SKILL_CALLS = [
    "发现工具重复调用，请检查历史记录，重新思考问题、解决进展及下面计划，我的思考如下:",
    "我发现存在重复调用的情况，重新思考吧，我新的思考如下：",
    "duplicated skillcall, need to change my mind ...",
    "检测到工具调用重复出现，请审视对话历史并调整思路，我的更新思考是：",
    "重复的技能调用被发现，让我们重新评估情况，以下是我的新计划：",
    "Noticed repeated tool invocations, time to rethink the approach. My updated thoughts:",
    "Duplicate skill calls detected, checking history and reformulating. Here's my new reasoning:",
    "重复工具调用警报！请允许我重新考虑问题，我的修订思考如下：",
    "Found looping skill calls, need to break the cycle. New thoughts incoming:",
    "技能调用出现冗余，历史审查中... 我的调整思路是：",
    "Repeated invocations spotted, let's pivot. My fresh perspective:",
]


def get_msg_duplicate_skill_call():
    return MSG_DUPLICATE_SKILL_CALLS[
        random.randint(0, len(MSG_DUPLICATE_SKILL_CALLS) - 1)
    ]


def is_msg_duplicate_skill_call(msg: str):
    return any(
        msg in msg_duplicate_skill_call
        for msg_duplicate_skill_call in MSG_DUPLICATE_SKILL_CALLS
    )


MSG_DUPLICATE_OUTPUT = [
    "稍等，我发现了重复的生成内容，我要冷静一下重新思考，或许需要借助工具，来吧：",
    "wait, i found duplicated output, i need to calm down and think again, maybe i need to use tools, let's go:",
    "检测到内容重复生成，暂停一下让我重新整理思路，可能要调用工具了：",
    "Oh no, repeating output detected. Taking a breath to rethink, tools might help:",
    "内容出现循环复制，我需要停下来反思一下，工具或许是关键，来试试：",
    "Duplicate content alert! Calming down for a fresh think, let's try some tools:",
    "发现了输出冗余，让我调整心态重新规划，或许借助外部工具：",
    "Spotted duplicated generation, need to reset my thoughts. Tools incoming?",
    "重复内容生成中... 等下，我要冷静分析，可能需要工具支持：",
    "Wait up, output looping. Time to reconsider, maybe with tool assistance:",
    "生成结果有重复迹象，我将重新思考策略，工具调用准备中：",
    "Repeated output found, rethinking now. Perhaps tools will break the loop:",
]


def get_msg_duplicate_output():
    return MSG_DUPLICATE_OUTPUT[random.randint(0, len(MSG_DUPLICATE_OUTPUT) - 1)]


SEARCH_TIMEOUT = 10  # seconds for search API calls

SEARCH_RETRY_COUNT = 2  # number of retries for failed search API calls

MAX_SKILL_CALL_TIMES = 100

# Compression constants
MAX_ANSWER_COMPRESSION_LENGTH = 100

# Chinese token estimation constants: character to token ratio
# Different models have different tokenization strategies:
# - OpenAI series: ~1 char = 2.0 tokens
# - DeepSeek series: ~1 char = 0.6 tokens
# - Qwen series: ~1 char = 1.0 tokens
# - General weighted average: ~1 char = 1.3 tokens (more accurate estimation)
CHINESE_CHAR_TO_TOKEN_RATIO = 1.3


def estimate_tokens_from_chars(text: str) -> int:
    """Estimate the number of tokens in Chinese text"""
    return int(len(text) * CHINESE_CHAR_TO_TOKEN_RATIO)


def estimate_chars_from_tokens(tokens: int) -> int:
    """Estimate the number of characters corresponding to the token count"""
    return int(tokens / CHINESE_CHAR_TO_TOKEN_RATIO)


# Dolphin variables output markers
DOLPHIN_VARIABLES_OUTPUT_START = "=== DOLPHIN_VARIABLES_OUTPUT_START ==="
DOLPHIN_VARIABLES_OUTPUT_END = "=== DOLPHIN_VARIABLES_OUTPUT_END ==="

# Marker: tool outputs containing this token will be persisted into conversation history (minimal pin-to-history)
PIN_MARKER = "[PIN]"
