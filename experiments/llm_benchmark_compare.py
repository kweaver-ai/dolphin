#!/usr/bin/env python3
"""
LLM-based benchmark answer comparison for Dolphin Language experiments.
"""

import json
import sys
import os
from pathlib import Path

# Add the src directory to the path to import DolphinLanguageSDK
root_dir = Path(__file__).parent.parent
sys.path.insert(0, str(root_dir / "src"))

from dolphin.core import Context, get_logger
from dolphin.core.llm import LLMCall

logger = get_logger()


class LLMBenchmarkCompare(LLMCall):
    """LLM-based comparison for benchmark answers."""

    def __init__(self, llm_client, memory_config=None):
        """
        Initialize the LLM benchmark compare.

        :param llm_client: LLM client instance
        :param memory_config: Memory configuration (optional)
        """
        # Create a minimal config if none provided
        if memory_config is None:
            memory_config = type("Config", (), {"max_extraction_retries": 2})()

        super().__init__(llm_client, memory_config)

    def _log(self, time_cost: float, **kwargs) -> str:
        """Log the execution result."""
        golden = kwargs.get("golden", "N/A")
        predicted = kwargs.get("predicted", "N/A")
        result = kwargs.get("result", "N/A")

        logger.info(
            f"LLM benchmark comparison completed in {time_cost:.2f}s - Result: {result}"
        )
        logger.debug(f"Golden: {golden[:100]}{'...' if len(str(golden)) > 100 else ''}")
        logger.debug(
            f"Predicted: {predicted[:100]}{'...' if len(str(predicted)) > 100 else ''}"
        )

        return f"LLM comparison: {result} (time: {time_cost:.2f}s)"

    def _no_merge_result(self, **kwargs) -> bool:
        """Return False when no comparison is needed (shouldn't happen in normal usage)."""
        logger.warning("No comparison needed - returning False")
        return False

    def _build_prompt(self, **kwargs) -> str:
        """Build the prompt for LLM answer comparison."""
        golden = kwargs.get("golden")
        predicted = kwargs.get("predicted")

        if golden is None or predicted is None:
            return None

        prompt = f"""You are an expert evaluator tasked with comparing two answers to determine if they are semantically equivalent, even if they differ in exact wording, formatting, or minor details.

**Golden Answer (Expected):**
{golden}

**Predicted Answer (Actual):**
{predicted}

**Instructions:**
1. Compare the semantic meaning and factual content of both answers
2. Ignore minor differences in wording, formatting, punctuation, or presentation style
3. Focus on whether the core information and conclusions are the same
4. Consider partial matches if the predicted answer contains the essential information from the golden answer
5. Be reasonably lenient with formatting differences, extra explanations, or different phrasing that conveys the same meaning

**Response Format:**
Respond with ONLY one of these two options:
- "MATCH" if the answers are semantically equivalent or the predicted answer correctly addresses the same question with equivalent information
- "NO_MATCH" if the answers are fundamentally different in meaning, facts, or conclusions

**Your evaluation:**"""

        return prompt

    def _post_process(self, llm_output: str, **kwargs) -> bool:
        """Post-process the LLM output to extract boolean result."""
        try:
            # Clean up the output
            result = llm_output.strip().upper()

            # Extract the final decision
            if "MATCH" in result and "NO_MATCH" not in result:
                return True
            elif "NO_MATCH" in result:
                return False
            else:
                # If the output doesn't contain clear indicators, try to parse more carefully
                lines = result.split("\n")
                for line in lines:
                    line = line.strip()
                    if line == "MATCH":
                        return True
                    elif line == "NO_MATCH":
                        return False

                # If still unclear, log warning and default to False
                logger.warning(
                    f"Unclear LLM comparison result: '{llm_output}'. Defaulting to False."
                )
                return False

        except Exception as e:
            logger.error(f"Failed to post-process LLM comparison output: {e}")
            return False


def create_llm_benchmark_comparer(config_path=None):
    """
    Create an LLM benchmark comparer instance.

    :param config_path: Optional path to global config file
    :return: LLMBenchmarkCompare instance or None if setup fails
    """
    try:
        # Import required SDK modules
        from dolphin.core import GlobalConfig, LLMClient

        # Load global config
        if config_path and os.path.exists(config_path):
            global_config = GlobalConfig.from_yaml(config_path)
        else:
            # Try to find config in current directory or parent directories
            current_dir = Path.cwd()
            config_candidates = [
                current_dir / "config" / "global.yaml",
                current_dir.parent / "config" / "global.yaml",
                current_dir / "global.yaml",
            ]

            global_config = None
            for candidate in config_candidates:
                if candidate.exists():
                    global_config = GlobalConfig.from_yaml(str(candidate))
                    break

            if global_config is None:
                logger.error("Could not find global.yaml config file")
                return None

        # Create LLM client
        context = Context(global_config)
        llm_client = LLMClient(context)

        # Create and return comparer
        comparer = LLMBenchmarkCompare(llm_client)
        return comparer

    except Exception as e:
        logger.error(f"Failed to create LLM benchmark comparer: {e}")
        return None


def compare_answers_with_llm(golden, predicted, config_path=None):
    """
    Compare two answers using LLM.

    :param golden: Golden/expected answer
    :param predicted: Predicted/actual answer
    :param config_path: Optional path to global config file
    :return: True if answers match, False otherwise, None if comparison fails
    """
    try:
        comparer = create_llm_benchmark_comparer(config_path)
        if comparer is None:
            return None

        # Execute comparison
        result = comparer.execute(llm_args={}, golden=golden, predicted=predicted)

        return result

    except Exception as e:
        logger.error(f"LLM answer comparison failed: {e}")
        return None


if __name__ == "__main__":
    # Test the LLM comparison functionality
    import argparse

    parser = argparse.ArgumentParser(description="Test LLM benchmark comparison")
    parser.add_argument("--golden", required=True, help="Golden answer")
    parser.add_argument("--predicted", required=True, help="Predicted answer")
    parser.add_argument("--config", help="Path to global.yaml config file")

    args = parser.parse_args()

    result = compare_answers_with_llm(args.golden, args.predicted, args.config)

    if result is None:
        print("❌ Comparison failed")
        sys.exit(1)
    elif result:
        print("✅ MATCH")
        sys.exit(0)
    else:
        print("❌ NO_MATCH")
        sys.exit(1)
