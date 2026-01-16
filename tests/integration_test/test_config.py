"""
Integration Test Configuration Classes

Defines the structure for integration test cases and configurations.
"""

import sys
import os

# Add project root to sys.path for relative imports (must be before other imports)
project_root = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, project_root)

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod

from dolphin.core.common.enums import Messages


@dataclass
class TestConfig:
    """Configuration for test execution"""

    modelName: str
    typeApi: str
    apiKey: str = ""
    api: str = ""
    userId: str = ""
    maxTokens: int = 1000
    temperature: float = 0.0


@dataclass
class TestParameters:
    """Parameters for test execution"""

    query: str
    history: Messages = None
    variables: Dict[str, Any] = None

    def __post_init__(self):
        if self.history is None:
            self.history = []
        if self.variables is None:
            self.variables = {}


@dataclass
class ExpectedResult:
    """Expected results for test validation"""

    contentKeywords: List[str] = None
    excludeKeywords: List[str] = None
    tools: List[str] = None
    outputFormat: Optional[str] = None
    errorExpected: bool = False
    variableChecks: List[Dict[str, str]] = None
    emptyAnswerCheck: bool = False  # Check that no stage instance has empty answer
    outputKey: str = "result"  # Output key to validate, defaults to "result"

    def __post_init__(self):
        if self.contentKeywords is None:
            self.contentKeywords = []
        if self.excludeKeywords is None:
            self.excludeKeywords = []
        if self.tools is None:
            self.tools = []
        if self.variableChecks is None:
            self.variableChecks = []


class Checker(ABC):
    """Abstract base class for result checkers"""

    @abstractmethod
    def check(self, actual: Any, expected: Any) -> bool:
        """Check if actual result matches expected result"""
        pass

    @abstractmethod
    def getErrorMessage(self, actual: Any, expected: Any) -> str:
        """Get error message when check fails"""
        pass


class KeywordMatchChecker(Checker):
    """Checker for content keywords"""

    def check(self, actual: str, expected: List[str]) -> bool:
        """Check if all expected keywords are present in actual content"""
        if not expected:
            return True

        actual_lower = str(actual).lower().strip()
        for keyword in expected:
            if keyword.strip().lower() not in actual_lower:
                return False
        return True

    def getErrorMessage(self, actual: str, expected: List[str]) -> str:
        """Get error message for keyword check failure"""
        missing_keywords = []
        actual_lower = str(actual).lower().strip()
        for keyword in expected:
            if keyword.strip().lower() not in actual_lower:
                missing_keywords.append(keyword)
        return f"Missing keywords: {missing_keywords}"


class KeywordExcludeChecker(Checker):
    """Checker for keywords that should not be present in content"""

    def check(self, actual: str, expected: List[str]) -> bool:
        """Check if none of the excluded keywords are present in actual content"""
        if not expected:
            return True

        actual_lower = actual.lower().strip()
        for keyword in expected:
            if keyword.strip().lower() in actual_lower:
                return False
        return True

    def getErrorMessage(self, actual: str, expected: List[str]) -> str:
        """Get error message for keyword exclusion check failure"""
        found_keywords = []
        actual_lower = actual.lower().strip()
        for keyword in expected:
            if keyword.strip().lower() in actual_lower:
                found_keywords.append(keyword)
        return f"Found excluded keywords: {found_keywords}"


class ToolUsageChecker(Checker):
    """Checker for tool usage using set matching instead of count matching"""

    def check(self, actual: List[str], expected: List[str]) -> bool:
        """Check if all expected tools are used (regardless of count)"""
        if not expected:
            return True

        actual_set = set(actual)
        expected_set = set(expected)

        # Check if all expected tools are present in actual usage
        return expected_set.issubset(actual_set)

    def getErrorMessage(self, actual: List[str], expected: List[str]) -> str:
        """Get error message for tool usage check failure"""
        if not expected:
            return "No tools expected"

        actual_set = set(actual)
        expected_set = set(expected)

        missing_tools = expected_set - actual_set

        if missing_tools:
            return f"Tool usage mismatch: Missing tools: {sorted(missing_tools)}"
        else:
            return "Tool usage check passed"


class OutputFormatChecker(Checker):
    """Checker for output format"""

    def check(self, actual: Any, expected: str) -> bool:
        """Check if output matches expected format"""
        if not expected:
            return True

        if expected.lower() == "json":
            try:
                import json

                if isinstance(actual, str):
                    json.loads(actual)
                return True
            except:
                return False
        elif expected.lower() == "list":
            return isinstance(actual, list)
        elif expected.lower() == "dict":
            return isinstance(actual, dict)
        elif expected.lower() == "string":
            return isinstance(actual, str)

        return True

    def getErrorMessage(self, actual: Any, expected: str) -> str:
        """Get error message for format check failure"""
        return f"Expected format '{expected}', but got {type(actual).__name__}"


class EmptyAnswerChecker(Checker):
    """Checker for ensuring no stage instance has empty answer"""

    def check(self, actual_progress: List[Dict[str, Any]], expected: bool) -> bool:
        """Check if all stage instances have non-empty answers

        Args:
            actual_progress: List of progress stages from _progress variable
            expected: Expected value (True means check should be performed)

        Returns:
            bool: True if all stages have non-empty answers, False otherwise
        """
        if not expected or not actual_progress:
            return True

        for stage in actual_progress:
            if not isinstance(stage, dict):
                continue

            # Check if this stage has empty answer
            # A stage has empty answer if all of answer, think, and block_answer are empty
            answer = stage.get("answer", "")
            think = stage.get("think", "")
            block_answer = stage.get("block_answer", "")

            # Convert to string and strip whitespace for proper checking
            answer_str = str(answer).strip() if answer is not None else ""
            think_str = str(think).strip() if think is not None else ""
            block_answer_str = (
                str(block_answer).strip() if block_answer is not None else ""
            )

            # If all three are empty, this stage has empty answer - which violates the check
            if not answer_str and not think_str and not block_answer_str:
                return False

        return True

    def getErrorMessage(
        self, actual_progress: List[Dict[str, Any]], expected: bool
    ) -> str:
        """Get error message for empty answer check failure"""
        if not expected or not actual_progress:
            return "Empty answer check not configured"

        empty_stages = []
        for i, stage in enumerate(actual_progress):
            if not isinstance(stage, dict):
                continue

            answer = stage.get("answer", "")
            think = stage.get("think", "")
            block_answer = stage.get("block_answer", "")

            answer_str = str(answer).strip() if answer is not None else ""
            think_str = str(think).strip() if think is not None else ""
            block_answer_str = (
                str(block_answer).strip() if block_answer is not None else ""
            )

            if not answer_str and not think_str and not block_answer_str:
                agent_name = stage.get("agent_name", "unknown")
                stage_type = stage.get("stage", "unknown")
                empty_stages.append(f"Stage {i}: {agent_name}({stage_type})")

        if empty_stages:
            return f"Found stages with empty answers: {', '.join(empty_stages)}"
        else:
            return "Empty answer check passed"


class VariableContentChecker(Checker):
    """Checker for GlobalVariablePool variable content"""

    def check(
        self, actual_variables: Dict[str, Any], expected_checks: List[Dict[str, str]]
    ) -> bool:
        """Check if variables contain expected content

        Args:
            actual_variables: Dictionary of variables from GlobalVariablePool
            expected_checks: List of checks, each containing 'variableName' and 'expectedContent'

        Returns:
            bool: True if all checks pass, False otherwise
        """
        if not expected_checks:
            return True

        for check in expected_checks:
            variable_name = check.get("variableName")
            expected_content = check.get("expectedContent")

            if not variable_name or expected_content is None:
                continue

            # Get variable value from the pool
            variable_value = actual_variables.get(variable_name)
            if variable_value is None:
                return False

            # Extract searchable content from variable value
            searchable_content = self._extractSearchableContent(variable_value)
            expected_str = str(expected_content).lower()

            # Check if expected content is present in variable
            if expected_str not in searchable_content:
                return False

        return True

    def _extractSearchableContent(self, variable_value: Any) -> str:
        """Extract searchable content from variable value, handling variable history"""
        content_parts = []

        if isinstance(variable_value, dict):
            # Handle dict structure like {'name': 'var', 'value': [...]}
            if "value" in variable_value:
                value = variable_value["value"]
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            # Handle variable history item structure
                            if "value" in item:
                                item_value = item["value"]
                                # Check if the item value is a complex structure (like LLM response)
                                if isinstance(item_value, dict):
                                    if "answer" in item_value:
                                        content_parts.append(str(item_value["answer"]))
                                    if "think" in item_value:
                                        content_parts.append(str(item_value["think"]))
                                    # Also include the whole dict as string for comprehensive search
                                    content_parts.append(str(item_value))
                                else:
                                    # Simple value (string, number, etc.)
                                    content_parts.append(str(item_value))
                            else:
                                # Extract any answer/content fields
                                if "answer" in item:
                                    content_parts.append(str(item["answer"]))
                                if "content" in item:
                                    content_parts.append(str(item["content"]))
                                # Also add the whole item for comprehensive search
                                content_parts.append(str(item))
                        else:
                            # Simple value
                            content_parts.append(str(item))
                else:
                    # Single value
                    if isinstance(value, dict):
                        if "answer" in value:
                            content_parts.append(str(value["answer"]))
                        if "think" in value:
                            content_parts.append(str(value["think"]))
                        content_parts.append(str(value))
                    else:
                        content_parts.append(str(value))
            else:
                # Regular dict, convert to string
                content_parts.append(str(variable_value))
        elif isinstance(variable_value, list):
            # Handle list of items
            for item in variable_value:
                content_parts.append(str(item))
        else:
            # Simple value
            content_parts.append(str(variable_value))

        # Join all content and convert to lowercase for searching
        return " ".join(content_parts).lower()

    def getErrorMessage(
        self, actual_variables: Dict[str, Any], expected_checks: List[Dict[str, str]]
    ) -> str:
        """Get error message for variable content check failure"""
        if not expected_checks:
            return "No variable checks expected"

        failed_checks = []
        for check in expected_checks:
            variable_name = check.get("variableName")
            expected_content = check.get("expectedContent")

            if not variable_name or expected_content is None:
                continue

            variable_value = actual_variables.get(variable_name)
            if variable_value is None:
                failed_checks.append(
                    f"Variable '{variable_name}' not found in GlobalVariablePool"
                )
                continue

            # Use the same content extraction logic as check method
            searchable_content = self._extractSearchableContent(variable_value)
            expected_str = str(expected_content).lower()

            if expected_str not in searchable_content:
                # Show extracted content for debugging
                content_preview = (
                    searchable_content[:200]
                    if len(searchable_content) > 200
                    else searchable_content
                )
                failed_checks.append(
                    f"Variable '{variable_name}' does not contain '{expected_content}'. Actual content: {content_preview}..."
                )

        return (
            "; ".join(failed_checks)
            if failed_checks
            else "Variable content checks passed"
        )


@dataclass
class IntegrationTestCase:
    """Single integration test case"""

    name: str
    description: str
    config: TestConfig
    parameters: TestParameters
    dolphinLangPath: str
    expectedResult: ExpectedResult
    enabled: bool = True
    timeout: int = 30

    def __post_init__(self):
        """Validate test case after initialization"""
        if not self.name:
            raise ValueError("Test case name cannot be empty")
        if not self.dolphinLangPath:
            raise ValueError("Dolphin language path cannot be empty")


class IntegrationTest:
    """Integration test suite manager"""

    def __init__(self, testCases: List[IntegrationTestCase] = None):
        self.testCases = testCases or []
        self.checkers = {
            "keyword": KeywordMatchChecker(),
            "excludeKeyword": KeywordExcludeChecker(),
            "tool": ToolUsageChecker(),
            "format": OutputFormatChecker(),
            "variable": VariableContentChecker(),
            "emptyAnswer": EmptyAnswerChecker(),
        }

    def addTestCase(self, testCase: IntegrationTestCase):
        """Add a test case to the suite"""
        self.testCases.append(testCase)

    def getEnabledTestCases(self) -> List[IntegrationTestCase]:
        """Get all enabled test cases"""
        return [tc for tc in self.testCases if tc.enabled]

    def getTestCaseByName(self, name: str) -> Optional[IntegrationTestCase]:
        """Get test case by name"""
        for tc in self.testCases:
            if tc.name == name:
                return tc
        return None

    def _extractActualData(
        self, testCase: IntegrationTestCase, actualResult: Dict[str, Any]
    ) -> tuple[str, List[str]]:
        """Extract full answer and used tools from actual result

        Args:
            testCase: Test case configuration
            actualResult: Actual execution result

        Returns:
            tuple: (fullAnswer, usedTools)
        """
        outputKey = testCase.expectedResult.outputKey
        fullAnswer = ""
        usedTools = []

        # Check if output key exists in actual result
        if outputKey not in actualResult:
            return fullAnswer, usedTools

        outputValue = actualResult[outputKey]

        # Handle special case for intervention_judge_block_vars
        if "intervention_judge_block_vars" in actualResult:
            fullAnswer = str(outputValue) if outputValue is not None else ""
            toolName = actualResult["intervention_judge_block_vars"].get(
                "tool_name", ""
            )
            usedTools = [toolName] if toolName else []
            return fullAnswer, usedTools

        # Handle different output value structures
        if isinstance(outputValue, dict) and "value" in outputValue:
            value = outputValue["value"]
            if isinstance(value, list):
                # Extract answers from list of items
                fullAnswer = "".join([str(item.get("answer", "")) for item in value])

                # Extract agent names (tools), excluding "main"
                usedTools = [
                    item.get("agent_name", "")
                    for item in value
                    if item.get("agent_name", "")
                    and item.get("agent_name", "") != "main"
                ]

                # Also check for skill_info to extract tool names
                for item in value:
                    if (
                        isinstance(item, dict)
                        and "skill_info" in item
                        and item["skill_info"]
                    ):
                        skill_info = item["skill_info"]
                        if isinstance(skill_info, dict) and "name" in skill_info:
                            tool_name = skill_info["name"]
                            if tool_name and tool_name not in usedTools:
                                usedTools.append(tool_name)
            elif isinstance(value, str):
                fullAnswer = value
                usedTools = []
            else:
                fullAnswer = str(value) if value is not None else ""
                usedTools = []
        else:
            # Direct value without 'value' wrapper
            fullAnswer = str(outputValue) if outputValue is not None else ""
            usedTools = []

        # Also check the _progress variable for tool usage information
        if (
            "gvp_variables" in actualResult
            and "_progress" in actualResult["gvp_variables"]
        ):
            progress_data = actualResult["gvp_variables"]["_progress"]
            if isinstance(progress_data, list):
                for stage in progress_data:
                    if (
                        isinstance(stage, dict)
                        and "skill_info" in stage
                        and stage["skill_info"]
                    ):
                        skill_info = stage["skill_info"]
                        if isinstance(skill_info, dict) and "name" in skill_info:
                            tool_name = skill_info["name"]
                            if tool_name and tool_name not in usedTools:
                                usedTools.append(tool_name)

        return fullAnswer, usedTools

    def validateResults(
        self, testCase: IntegrationTestCase, actualResult: Dict[str, Any]
    ) -> Dict[str, bool]:
        """Validate actual results against expected results"""
        results = {}

        # Extract actual data using the new method
        fullAnswer, usedTools = self._extractActualData(testCase, actualResult)

        # Check keywords
        if testCase.expectedResult.contentKeywords:
            results["keyword"] = self.checkers["keyword"].check(
                fullAnswer, testCase.expectedResult.contentKeywords
            )

        # Check exclude keywords
        if testCase.expectedResult.excludeKeywords:
            results["excludeKeyword"] = self.checkers["excludeKeyword"].check(
                fullAnswer, testCase.expectedResult.excludeKeywords
            )

        # Check tool usage
        if testCase.expectedResult.tools:
            results["tool"] = self.checkers["tool"].check(
                usedTools, testCase.expectedResult.tools
            )

        # Check output format
        if testCase.expectedResult.outputFormat:
            results["format"] = self.checkers["format"].check(
                actualResult.get(testCase.expectedResult.outputKey),
                testCase.expectedResult.outputFormat,
            )

        # Check variable content
        if testCase.expectedResult.variableChecks:
            gvp_variables = actualResult.get("gvp_variables", {})
            results["variable"] = self.checkers["variable"].check(
                gvp_variables, testCase.expectedResult.variableChecks
            )

        # Check empty answer
        if testCase.expectedResult.emptyAnswerCheck:
            progress_data = actualResult.get("_progress", [])
            results["emptyAnswer"] = self.checkers["emptyAnswer"].check(
                progress_data, testCase.expectedResult.emptyAnswerCheck
            )

        return results

    def getValidationErrors(
        self, testCase: IntegrationTestCase, actualResult: Dict[str, Any]
    ) -> List[str]:
        """Get detailed validation error messages"""
        errors = []

        # Extract actual data using the new method
        fullAnswer, usedTools = self._extractActualData(testCase, actualResult)

        # Check keywords
        if testCase.expectedResult.contentKeywords:
            if not self.checkers["keyword"].check(
                fullAnswer, testCase.expectedResult.contentKeywords
            ):
                errors.append(
                    self.checkers["keyword"].getErrorMessage(
                        fullAnswer, testCase.expectedResult.contentKeywords
                    )
                )

        # Check exclude keywords
        if testCase.expectedResult.excludeKeywords:
            if not self.checkers["excludeKeyword"].check(
                fullAnswer, testCase.expectedResult.excludeKeywords
            ):
                errors.append(
                    self.checkers["excludeKeyword"].getErrorMessage(
                        fullAnswer, testCase.expectedResult.excludeKeywords
                    )
                )

        # Check tool usage
        if testCase.expectedResult.tools:
            if not self.checkers["tool"].check(
                usedTools, testCase.expectedResult.tools
            ):
                errors.append(
                    self.checkers["tool"].getErrorMessage(
                        usedTools, testCase.expectedResult.tools
                    )
                )

        # Check output format
        if testCase.expectedResult.outputFormat:
            if not self.checkers["format"].check(
                actualResult.get(testCase.expectedResult.outputKey),
                testCase.expectedResult.outputFormat,
            ):
                errors.append(
                    self.checkers["format"].getErrorMessage(
                        actualResult.get(testCase.expectedResult.outputKey),
                        testCase.expectedResult.outputFormat,
                    )
                )

        # Check variable content
        if testCase.expectedResult.variableChecks:
            gvp_variables = actualResult.get("gvp_variables", {})
            if not self.checkers["variable"].check(
                gvp_variables, testCase.expectedResult.variableChecks
            ):
                errors.append(
                    self.checkers["variable"].getErrorMessage(
                        gvp_variables, testCase.expectedResult.variableChecks
                    )
                )

        # Check empty answer
        if testCase.expectedResult.emptyAnswerCheck:
            progress_data = actualResult.get("_progress", [])
            if not self.checkers["emptyAnswer"].check(
                progress_data, testCase.expectedResult.emptyAnswerCheck
            ):
                errors.append(
                    self.checkers["emptyAnswer"].getErrorMessage(
                        progress_data, testCase.expectedResult.emptyAnswerCheck
                    )
                )

        return errors
