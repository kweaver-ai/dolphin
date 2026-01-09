"""
Test Configuration Loader

Loads integration test configurations from JSON files and converts them to test objects.
"""

import json
import os
import glob
from typing import Dict, Any
from .test_config import (
    IntegrationTest,
    IntegrationTestCase,
    TestConfig,
    TestParameters,
    ExpectedResult,
)


class TestConfigLoader:
    """Loader for test configurations from JSON files"""

    def __init__(self, basePath: str = None):
        """Initialize loader with base path for resolving relative paths"""
        self.basePath = basePath or os.getcwd()
        self.commonConfig = None

    def loadCommonConfig(self, dirPath: str) -> Dict[str, Any]:
        """Load common configuration from common.json file"""
        commonJsonPath = os.path.join(dirPath, "common.json")

        if os.path.exists(commonJsonPath):
            try:
                with open(commonJsonPath, "r", encoding="utf-8") as f:
                    commonData = json.load(f)
                    return commonData.get("defaultConfig", {})
            except Exception as e:
                print(f"Warning: Failed to load common.json: {e}")
                return {}
        else:
            print(f"Warning: common.json not found at {commonJsonPath}")
            return {}

    def loadFromFile(
        self, filePath: str, commonConfig: Dict[str, Any] = None
    ) -> IntegrationTest:
        """Load test configuration from JSON file"""
        if not os.path.isabs(filePath):
            filePath = os.path.join(self.basePath, filePath)

        with open(filePath, "r", encoding="utf-8") as f:
            data = json.load(f)

        return self.loadFromDict(data, commonConfig)

    def loadFromDirectory(self, dirPath: str) -> IntegrationTest:
        """Load test configurations from all JSON files in a directory"""
        if not os.path.isabs(dirPath):
            dirPath = os.path.join(self.basePath, dirPath)

        # Load common configuration first
        commonConfig = self.loadCommonConfig(dirPath)
        print(f"Loaded common configuration: {commonConfig}")

        integrationTest = IntegrationTest()

        # Find all JSON files in the directory, excluding common.json
        jsonFiles = [
            f
            for f in glob.glob(os.path.join(dirPath, "*.json"))
            if not f.endswith("common.json")
        ]

        print(f"Loading test cases from {len(jsonFiles)} files in directory: {dirPath}")

        for jsonFile in sorted(jsonFiles):
            print(f"  Loading: {os.path.basename(jsonFile)}")
            try:
                testConfig = self.loadFromFile(jsonFile, commonConfig)
                # Merge test cases from this file
                for testCase in testConfig.testCases:
                    integrationTest.addTestCase(testCase)
            except Exception as e:
                print(f"  Error loading {jsonFile}: {e}")
                continue

        print(f"Loaded total {len(integrationTest.testCases)} test cases")
        return integrationTest

    def loadFromDict(
        self, data: Dict[str, Any], commonConfig: Dict[str, Any] = None
    ) -> IntegrationTest:
        """Load test configuration from dictionary"""
        testSuite = data.get("testSuite", {})
        localDefaultConfig = testSuite.get("defaultConfig", {})

        # Merge common config with local default config
        # Local config overrides common config
        if commonConfig:
            mergedDefaultConfig = {**commonConfig, **localDefaultConfig}
        else:
            mergedDefaultConfig = localDefaultConfig

        testCasesData = data.get("testCases", [])

        integrationTest = IntegrationTest()

        for testCaseData in testCasesData:
            testCase = self._createTestCase(testCaseData, mergedDefaultConfig)
            integrationTest.addTestCase(testCase)

        return integrationTest

    def _createTestCase(
        self, data: Dict[str, Any], defaultConfig: Dict[str, Any]
    ) -> IntegrationTestCase:
        """Create a test case from dictionary data"""
        # Merge config with defaults
        configData = {**defaultConfig, **data.get("config", {})}

        # Handle apiKey for different API types
        apiKey = configData.get("apiKey", "")

        config = TestConfig(
            modelName=configData["modelName"],
            typeApi=configData["typeApi"],
            apiKey=apiKey,
            api=configData["api"],
            userId=configData["userId"],
            maxTokens=configData.get("maxTokens", 1000),
            temperature=configData.get("temperature", 0.0),
        )

        # Create parameters
        paramData = data.get("parameters", {})
        parameters = TestParameters(
            query=paramData["query"],
            history=paramData.get("history", []),
            variables=paramData.get("variables", {}),
        )

        # Create expected result
        expectedData = data.get("expectedResult", {})
        expectedResult = ExpectedResult(
            contentKeywords=expectedData.get("contentKeywords", []),
            excludeKeywords=expectedData.get("excludeKeywords", []),
            tools=expectedData.get("tools", {}),
            outputFormat=expectedData.get("outputFormat"),
            errorExpected=expectedData.get("errorExpected", False),
            variableChecks=expectedData.get("variableChecks", []),
            emptyAnswerCheck=expectedData.get("emptyAnswerCheck", False),
            outputKey=expectedData.get(
                "outputKey", "result"
            ),  # Default to 'result' for backward compatibility
        )

        # Resolve dolphin language path
        dolphinLangPath = data["dolphinLangPath"]
        if not os.path.isabs(dolphinLangPath):
            dolphinLangPath = os.path.join(self.basePath, dolphinLangPath)

        return IntegrationTestCase(
            name=data["name"],
            description=data["description"],
            config=config,
            parameters=parameters,
            dolphinLangPath=dolphinLangPath,
            expectedResult=expectedResult,
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30),
        )

    def saveToFile(
        self,
        integrationTest: IntegrationTest,
        filePath: str,
        testSuiteInfo: Dict[str, Any] = None,
    ):
        """Save test configuration to JSON file"""
        if not os.path.isabs(filePath):
            filePath = os.path.join(self.basePath, filePath)

        data = self.saveToDict(integrationTest, testSuiteInfo)

        with open(filePath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def saveToDict(
        self, integrationTest: IntegrationTest, testSuiteInfo: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Save test configuration to dictionary"""
        if testSuiteInfo is None:
            testSuiteInfo = {
                "name": "Dolphin Language Integration Tests",
                "description": "End-to-end integration tests for Dolphin Language functionality",
                "version": "1.0.0",
            }

        data = {"testSuite": testSuiteInfo, "testCases": []}

        for testCase in integrationTest.testCases:
            testCaseData = {
                "name": testCase.name,
                "description": testCase.description,
                "enabled": testCase.enabled,
                "timeout": testCase.timeout,
                "config": {
                    "modelName": testCase.config.modelName,
                    "api": testCase.config.api,
                    "userId": testCase.config.userId,
                    "maxTokens": testCase.config.maxTokens,
                    "temperature": testCase.config.temperature,
                },
                "parameters": {
                    "query": testCase.parameters.query,
                    "history": testCase.parameters.history,
                    "variables": testCase.parameters.variables,
                },
                "dolphinLangPath": os.path.relpath(
                    testCase.dolphinLangPath, self.basePath
                ),
                "expectedResult": {
                    "contentKeywords": testCase.expectedResult.contentKeywords,
                    "excludeKeywords": testCase.expectedResult.excludeKeywords,
                    "tools": testCase.expectedResult.tools,
                    "outputFormat": testCase.expectedResult.outputFormat,
                    "errorExpected": testCase.expectedResult.errorExpected,
                    "variableChecks": testCase.expectedResult.variableChecks,
                    "outputKey": testCase.expectedResult.outputKey,
                },
            }
            data["testCases"].append(testCaseData)

        return data


def loadTestConfig(filePath: str = None) -> IntegrationTest:
    """Convenience function to load test configuration"""
    currentDir = os.path.dirname(os.path.abspath(__file__))

    if filePath is None:
        # Default to testcases directory in the same directory
        testcasesDir = os.path.join(currentDir, "testcases")

        # If testcases directory exists, load from it
        if os.path.isdir(testcasesDir):
            loader = TestConfigLoader(basePath=currentDir)
            return loader.loadFromDirectory(testcasesDir)
        else:
            # Fall back to old test_cases.json file
            filePath = os.path.join(currentDir, "test_cases.json")

    # Check if path is a directory or file
    if os.path.isdir(filePath):
        loader = TestConfigLoader(basePath=currentDir)
        return loader.loadFromDirectory(filePath)
    else:
        loader = TestConfigLoader(basePath=currentDir)
        return loader.loadFromFile(filePath)
