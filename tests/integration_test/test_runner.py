"""
Integration Test Runner

Executes integration tests for Dolphin Language functionality.
"""

import sys
import os
import asyncio
import time
import traceback
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

# Add project root and src directory to sys.path for relative imports

from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.executor.dolphin_executor import DolphinExecutor
from dolphin.sdk.runtime.env import Env
from dolphin.core.config.global_config import GlobalConfig

from tests.integration_test.mocked_skillkit import MockedSkillkit
from tests.integration_test.mocked_tools import (
    WebSearch,
    SaveToLocal,
    PoemWriterStreamTest,
    EmailSender,
    FinanceExpert,
    ComputerExpert,
)

from tests.integration_test.test_config import IntegrationTest, IntegrationTestCase
from tests.integration_test.test_loader import loadTestConfig

project_root = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, project_root)


@dataclass
class TestResult:
    """Result of a single test execution"""

    testCase: IntegrationTestCase
    success: bool
    executionTime: float
    actualResult: Optional[Dict[str, Any]] = None
    validationResults: Optional[Dict[str, bool]] = None
    errors: List[str] = None
    exception: Optional[Exception] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


@dataclass
class TestSuiteResult:
    """Result of test suite execution"""

    totalTests: int
    passedTests: int
    failedTests: int
    skippedTests: int
    totalExecutionTime: float
    testResults: List[TestResult]

    @property
    def successRate(self) -> float:
        """Calculate success rate as percentage"""
        if self.totalTests == 0:
            return 0.0
        return (self.passedTests / self.totalTests) * 100


class IntegrationTestRunner:
    """Runner for integration tests"""

    def __init__(self):
        """Initialize test runner"""
        self.toolMapping = {
            "poem_writer": PoemWriterStreamTest(),
            "save_to_local": SaveToLocal(),
            "web_search": WebSearch(),
            "email_sender": EmailSender(),
            "finance_expert": FinanceExpert(),
            "computer_expert": ComputerExpert(),
            "poemWriterStream": PoemWriterStreamTest(),
            "saveToLocal": SaveToLocal(),
            "webSearch": WebSearch(),
            "emailSender": EmailSender(),
            "financeExpert": FinanceExpert(),
            "computerExpert": ComputerExpert(),
        }
        self.skillkit: Skillkit = MockedSkillkit()
        self.env = None  # Agent environment for agent call tests

    def readFile(self, filePath: str) -> str:
        """Read content from file"""
        with open(filePath, "r", encoding="utf-8") as file:
            return file.read()

    def setupAgentEnvironment(self) -> bool:
        """Setup agent environment for agent call tests"""
        try:
            # Load global configuration
            config_path = os.path.join(project_root, "config", "global.yaml")
            if not os.path.exists(config_path):
                config_path = os.path.join(project_root, "config", "global_tmpl.yaml")

            global_config = GlobalConfig.from_yaml(config_path)

            # Create environment with test dolphins
            dolphins_path = os.path.join(
                project_root, "tests", "integration_test", "dolphins"
            )
            if os.path.exists(dolphins_path):
                # 设置正确的工作目录，确保Agent能找到配置文件
                original_cwd = os.getcwd()
                os.chdir(project_root)
                try:
                    self.env = Env(
                        globalConfig=global_config, agentFolderPath=dolphins_path
                    )
                    print(
                        f"Agent environment setup complete. Found {len(self.env.getAgentNames())} agents."
                    )
                    return True
                finally:
                    os.chdir(original_cwd)
            else:
                print(f"Warning: Dolphins directory not found at {dolphins_path}")
                return False

        except Exception as e:
            print(f"Failed to setup agent environment: {str(e)}")
            return False

    def isAgentCallTest(self, testCase: IntegrationTestCase) -> bool:
        """Check if this is an agent call test case"""
        return (
            testCase.dolphinLangPath
            and "dolphins/" in testCase.dolphinLangPath
            and (testCase.name.startswith("test_") and "agent" in testCase.name.lower())
        )

    async def runSingleTest(
        self, testCase: IntegrationTestCase, integrationTest: IntegrationTest
    ) -> TestResult:
        """Run a single test case"""
        startTime = time.time()

        try:
            print(f"Running test: {testCase.name}")
            print(f"Description: {testCase.description}")

            # Check if this is an agent call test and setup environment accordingly
            isAgentTest = self.isAgentCallTest(testCase)
            if isAgentTest and self.env is None:
                if not self.setupAgentEnvironment():
                    raise Exception(
                        "Failed to setup agent environment for agent call test"
                    )

            # Execute the test
            actualResult = await self.executeTest(testCase, isAgentTest)

            # Validate results
            validationResults = integrationTest.validateResults(testCase, actualResult)
            validationErrors = integrationTest.getValidationErrors(
                testCase, actualResult
            )

            # Determine success
            success = all(validationResults.values()) if validationResults else True

            executionTime = time.time() - startTime

            return TestResult(
                testCase=testCase,
                success=success,
                executionTime=executionTime,
                actualResult=actualResult,
                validationResults=validationResults,
                errors=validationErrors,
            )

        except Exception as e:
            executionTime = time.time() - startTime
            return TestResult(
                testCase=testCase,
                success=False,
                executionTime=executionTime,
                errors=[
                    f"Exception occurred: {str(e)} traceback: {traceback.format_exc()}"
                ],
                exception=e,
            )

    async def executeTest(
        self, testCase: IntegrationTestCase, isAgentTest: bool
    ) -> dict:
        """Execute a test case - unified method for both regular and agent tests"""

        # Check if this is an agent test that should use environment execution
        if isAgentTest and self.env is not None:
            # Agent call test execution using environment
            # Extract agent name from the DPH file path
            # e.g., "dolphins/simple_agent_test.dph" -> "simple_agent_test"
            dph_file = os.path.basename(testCase.dolphinLangPath)
            agent_name = dph_file.replace(".dph", "")

            # Get the agent instance to access its context after execution
            agent = self.env.getAgent(agent_name)
            if agent is None:
                raise ValueError(f"Agent not found: {agent_name}")

            # Execute using environment - properly handle async generator
            actualResult = None
            async for result in self.env.arun(
                agent_name, **testCase.parameters.variables
            ):
                actualResult = result  # Get the final result

            # Get variables from agent's context after execution
            gvpVariables = {}
            if hasattr(agent, "executor") and hasattr(agent.executor, "context"):
                raw_variables = agent.get_all_variables()

                # Extract the actual values from variable objects
                for key, var_obj in raw_variables.items():
                    if isinstance(var_obj, dict) and "value" in var_obj:
                        # Variable is wrapped in an object, extract the value
                        gvpVariables[key] = var_obj["value"]
                    else:
                        # Variable is already a direct value
                        gvpVariables[key] = var_obj

            # Prepare result for validation
            if actualResult is None:
                actualResult = {}
            actualResult["gvp_variables"] = gvpVariables

            # For agent tests, also set the outputKey variable at root level for validation
            # This allows format checking to work correctly
            output_key = testCase.expectedResult.outputKey if testCase else "result"
            if output_key in gvpVariables:
                actualResult[output_key] = gvpVariables[output_key]

        else:
            # Regular integration test execution or fallback for agent tests
            # Read dolphin language content
            dolphin_file_path = os.path.join(
                project_root, "tests", "integration_test", testCase.dolphinLangPath
            )
            content = self.readFile(dolphin_file_path)

            # Prepare configuration

            # Extract and apply feature flags from test variables
            from dolphin.core import flags
            flag_overrides = {}
            variables_to_pass = {}
            
            for key, value in testCase.parameters.variables.items():
                # Check if this is a feature flag (starts with enable_ or disable_)
                if key.startswith("enable_") or key.startswith("disable_"):
                    # Convert variable name to flag name
                    flag_name = key
                    flag_overrides[flag_name] = value
                else:
                    # Regular variable
                    variables_to_pass[key] = value

            # Prepare variables (removed toolDict construction since we use MockedSkillkit directly)
            variables = {
                **variables_to_pass,
                "query": testCase.parameters.query,
                "history": testCase.parameters.history,
            }

            # For agent tests, setup agent environment in DolphinExecutor
            if isAgentTest and self.env is not None:
                # Get all skills from environment (including agent skills)
                allSkills = self.env.getGlobalSkills().getAllSkills()
                variables["_agent_skills"] = allSkills

            # Execute test with feature flag overrides
            config_path = os.path.join(project_root, "config", "global.yaml")
            executor = DolphinExecutor(global_configpath=config_path)
            
            # Check if model exists in global config
            if testCase.config.modelName in executor.config.llmInstanceConfigs:
                llmConfig = executor.config.llmInstanceConfigs[testCase.config.modelName]
                
                # Merge test config with global config
                # Test config takes precedence, but empty strings fall back to global config
                config = {
                    "model_name": testCase.config.modelName,
                    "type_api": testCase.config.typeApi or llmConfig.type_api.value,
                    "api_key": testCase.config.apiKey or llmConfig.api_key,
                    "api": testCase.config.api or llmConfig.api,
                    "userid": testCase.config.userId or llmConfig.user_id,
                    "max_tokens": testCase.config.maxTokens,
                    "temperature": testCase.config.temperature,
                }
            else:
                # Model not in global config, use default LLM
                llmConfig = executor.config.llmInstanceConfigs[
                    executor.config.default_llm
                ]
                config = {
                    "name": executor.config.default_llm,
                    "model_name": llmConfig.model_name,
                    "type_api": llmConfig.type_api.value,
                    "api_key": llmConfig.api_key,
                    "api": llmConfig.api,
                    "userid": llmConfig.user_id,
                    "max_tokens": llmConfig.max_tokens,
                    "temperature": llmConfig.temperature,
                }

            params = {
                "config": config,
                "variables": variables,
                "skillkit": self.skillkit,
            }

            await executor.executor_init(params)

            # If agent skills are available, add them to executor context
            if isAgentTest and self.env is not None:
                allSkills = self.env.getGlobalSkills().getAllSkills()
                executor.context.set_skills(allSkills)

            # Apply feature flag overrides for this test
            # Note: Use try/finally to ensure flags are always reset, even if
            # set_flag raises an exception (e.g., unknown flag in strict mode)
            try:
                if flag_overrides:
                    print(f"  Applying feature flags: {flag_overrides}")
                    for flag_name, flag_value in flag_overrides.items():
                        flags.set_flag(flag_name, flag_value)

                actualResult = None
                async for resp in executor.run(content):
                    actualResult = resp

                # Get GlobalVariablePool variables after execution
                gvpVariables = executor.context.get_all_variables()

                # Add variables to actual result for validation
                if actualResult is None:
                    actualResult = {}
                actualResult["gvp_variables"] = gvpVariables
            finally:
                # Reset feature flags after test execution
                # Always reset to ensure clean state for subsequent tests
                if flag_overrides:
                    flags.reset()


        return actualResult

    async def runTestSuite(
        self, integrationTest: IntegrationTest, testFilter: Optional[str] = None
    ) -> TestSuiteResult:
        """Run all tests in the test suite"""
        startTime = time.time()
        testResults = []

        enabledTests = integrationTest.getEnabledTestCases()

        # Filter tests if specified
        if testFilter:
            enabledTests = [
                tc for tc in enabledTests if testFilter.lower() in tc.name.lower()
            ]

        print(f"Running {len(enabledTests)} integration tests...")
        print("=" * 60)

        for i, testCase in enumerate(enabledTests, 1):
            print(f"\n[{i}/{len(enabledTests)}] ", end="")
            result = await self.runSingleTest(testCase, integrationTest)
            testResults.append(result)

            # Print result summary
            status = "PASS" if result.success else "FAIL"
            print(f"Status: {status} ({result.executionTime:.2f}s)")

            if not result.success and result.errors:
                for error in result.errors:
                    print(f"  Error: {error}")

            print("-" * 40)

        totalExecutionTime = time.time() - startTime

        # Calculate statistics
        passedTests = sum(1 for r in testResults if r.success)
        failedTests = sum(1 for r in testResults if not r.success)
        skippedTests = len(integrationTest.testCases) - len(enabledTests)

        return TestSuiteResult(
            totalTests=len(enabledTests),
            passedTests=passedTests,
            failedTests=failedTests,
            skippedTests=skippedTests,
            totalExecutionTime=totalExecutionTime,
            testResults=testResults,
        )

    def printSummary(self, result: TestSuiteResult):
        """Print test execution summary"""
        print("\n" + "=" * 60)
        print("TEST EXECUTION SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {result.totalTests}")
        print(f"Passed: {result.passedTests}")
        print(f"Failed: {result.failedTests}")
        print(f"Skipped: {result.skippedTests}")
        print(f"Success Rate: {result.successRate:.1f}%")
        print(f"Total Execution Time: {result.totalExecutionTime:.2f}s")

        if result.failedTests > 0:
            print("\nFAILED TESTS:")
            print("-" * 30)
            for testResult in result.testResults:
                if not testResult.success:
                    print(f"- {testResult.testCase.name}")
                    for error in testResult.errors:
                        print(f"  {error}")

        print("=" * 60)


async def runIntegrationTests(
    configFile: str = None, testFilter: str = None
) -> TestSuiteResult:
    """Main function to run integration tests"""
    try:
        # Load test configuration
        integrationTest = loadTestConfig(configFile)

        # Create and run test runner
        runner = IntegrationTestRunner()
        result = await runner.runTestSuite(integrationTest, testFilter)

        # Print summary
        runner.printSummary(result)

        return result

    except Exception as e:
        print(f"Error running integration tests: {e}")
        raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Dolphin Language Integration Tests"
    )
    parser.add_argument("--config", "-c", help="Path to test configuration file")
    parser.add_argument(
        "--filter", "-f", help="Filter tests by name (case insensitive)"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Run tests
    result = asyncio.run(runIntegrationTests(args.config, args.filter))

    # Exit with appropriate code
    sys.exit(0 if result.failedTests == 0 else 1)
