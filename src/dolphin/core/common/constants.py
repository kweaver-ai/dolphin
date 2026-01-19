import os
import random
import re
from functools import lru_cache


# Tool call ID prefix for generating fallback IDs
TOOL_CALL_ID_PREFIX = "call_"

MSG_CONTINUOUS_CONTENT = "如果问题未被解决我们就继续执行\n"
ANSWER_CONTENT_PREFIX = "<answer>"
ANSWER_CONTENT_SUFFIX = "</answer>"
MAX_ANSWER_CONTENT_LENGTH = 12288  # 12k - increased to prevent SKILL.md truncation

# Duplicate output detection thresholds
# - MIN_LENGTH: Start detection early to catch loops quickly (default: 2KB)
# - COUNT: Set above max legitimate repetitions (default: 50 for 30-50 SVG cards with same CSS)
# - PATTERN_LENGTH: Length of pattern to check for repetition (default: 50 chars)
# - All can be overridden via environment variables for flexibility
MIN_LENGTH_TO_DETECT_DUPLICATE_OUTPUT = int(
    os.environ.get("DOLPHIN_DUPLICATE_MIN_LENGTH", "2048")
)  # 2KB - start checking early
COUNT_TO_PROVE_DUPLICATE_OUTPUT = int(
    os.environ.get("DOLPHIN_DUPLICATE_COUNT_THRESHOLD", "50")
)  # Allow up to 50 repetitions before triggering
DUPLICATE_PATTERN_LENGTH = int(
    os.environ.get("DOLPHIN_DUPLICATE_PATTERN_LENGTH", "50")
)  # Length of pattern to check for repetition
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


@lru_cache(maxsize=128)
def _compile_duplicate_pattern(pattern: str):
    """
    Cache compiled regex patterns for duplicate detection.

    Uses LRU cache to avoid recompiling the same pattern repeatedly,
    providing an additional 10-20% performance improvement on top of
    the existing 6.8x speedup from the regex implementation.

    Args:
        pattern: The pattern to compile (will be escaped for regex safety)

    Returns:
        Compiled regex pattern object
    """
    return re.compile(f'(?={re.escape(pattern)})')


def count_overlapping_occurrences(text: str, pattern: str) -> int:
    """
    Count overlapping occurrences of pattern in text using regex lookahead.

    This function is optimized for LLM duplicate output detection, achieving 6.8x average
    speedup over the original loop-based implementation. See PERFORMANCE_OPTIMIZATION_REPORT.md
    for detailed benchmarks and analysis.

    Key Design Decisions:
        - Uses regex lookahead (?=...) for overlapping matches (required for accurate loop detection)
        - C-based regex vs Python loop reduces interpreter overhead significantly
        - LRU-cached compilation provides additional 10-20% improvement on repeated patterns

    Why Overlapping Matches:
        - "XXXXX" contains 4 overlapping matches of "XX" (positions 0,1,2,3)
        - Non-overlapping would find only 2, causing false negatives in loop detection
        - Threshold set to allow legitimate repetitions (e.g., 30 SVG cards with same CSS)

    Args:
        text: The text to search in
        pattern: The pattern to search for (auto-escaped for regex safety)

    Returns:
        Number of overlapping occurrences found

    Example:
        >>> count_overlapping_occurrences("XXXXX", "XX")
        4

    Performance (typical 5-50KB input):
        - First call: 0.05-0.5ms
        - Cached pattern: 0.04-0.4ms
        - Memory: O(matches), typically <1KB
    """
    compiled_pattern = _compile_duplicate_pattern(pattern)
    return len(compiled_pattern.findall(text))


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
