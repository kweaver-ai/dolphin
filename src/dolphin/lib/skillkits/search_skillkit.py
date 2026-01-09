import json
from typing import List
import uuid

import requests
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.utils.cache_kv import GlobalCacheKVCenter

import time
from requests.exceptions import RequestException
from dolphin.core.common.constants import SEARCH_TIMEOUT, SEARCH_RETRY_COUNT
from dolphin.core.logging.logger import get_logger

logger = get_logger("skill")


class SearchSkillkit(Skillkit):
    MAX_KEYWORDS = 5

    def __init__(self):
        super().__init__()
        self.cacheMgr = None

    def getName(self) -> str:
        return "search_skillkit"

    def setGlobalConfig(self, globalConfig):
        """Set global context"""
        super().setGlobalConfig(globalConfig)

        if self.cacheMgr is None:
            self.cacheMgr = GlobalCacheKVCenter.getCacheMgr(
                "data/cache/", category="web_search", expireTimeByDay=10
            )

    def _search(
        self, query: str, maxResults: int = 10, site: str = "", **kwargs
    ) -> str:
        """Search for information on the internet using Chinese. If the keywords exceed 5, the subsequent content will be truncated.

        Args:
            query (str): The query string to search for, no more than 5 keywords
            maxResults (int): Maximum number of search results
            site (str): Specify the website domain to search, such as "github.com" or "stackoverflow.com"
            **kwargs: Additional properties passed to the tool.

        Returns: JSON string of search results
        """
        # Lazy initialization: If the global context is not set, an error is thrown.
        if self.globalConfig is None:
            raise ValueError(
                "Global context not set. Please call setGlobalConfig() first."
            )

        # Delayed Initialization Cache Manager
        if self.cacheMgr is None:
            self.cacheMgr = GlobalCacheKVCenter.getCacheMgr(
                "data/cache/", category="web_search", expireTimeByDay=10
            )

        query = self._query_preprocess(query)

        modelName = "zhipu_search"
        cacheKey = [{"query": query, "maxResults": maxResults, "site": site}]

        cachedResult = self.cacheMgr.getValue(modelName, cacheKey)
        if cachedResult:
            return json.dumps(cachedResult, ensure_ascii=False)

        try:
            # If the site parameter is specified, add the site: operator to the query string.
            searchQuery = query
            if site:
                searchQuery = f"site:{site} {query}"

            # Get API key from configuration file
            zhipuConfig = self.globalConfig.all_clouds_config.get_cloud_config("zhipu")
            if not zhipuConfig or not zhipuConfig.api_key:
                raise ValueError("Zhipu API key not found in configuration")

            # Configure the Zhipu API request, using the tools interface according to the official documentation.
            url = f"{zhipuConfig.api}/api/paas/v4/tools"
            headers = {
                "Authorization": f"{zhipuConfig.api_key}",
                "Content-Type": "application/json",
            }

            # Formatting requests according to the Zhipu AI documentation
            data = {
                "tool": "web-search-pro",
                "messages": [{"role": "user", "content": searchQuery}],
                "request_id": str(uuid.uuid4()),
                "stream": False,
            }

            for attempt in range(SEARCH_RETRY_COUNT):
                try:
                    response = requests.post(
                        url, headers=headers, json=data, timeout=SEARCH_TIMEOUT
                    )
                    response.raise_for_status()
                    break
                except RequestException:
                    if attempt == SEARCH_RETRY_COUNT - 1:
                        raise
                    time.sleep(2**attempt)  # exponential backoff

            # Parse response results
            responseData = response.json()

            # Check response format
            if (
                "choices" not in responseData
                or len(responseData["choices"]) == 0
                or "message" not in responseData["choices"][0]
                or "tool_calls" not in responseData["choices"][0]["message"]
            ):
                raise ValueError("Invalid response format from Zhipu API")

            # Extract search results
            toolCalls = responseData["choices"][0]["message"]["tool_calls"]
            searchResults = []

            for toolCall in toolCalls:
                if (
                    toolCall.get("type") == "search_result"
                    and "search_result" in toolCall
                ):
                    searchResults.extend(toolCall["search_result"])

            # Convert the result to a unified format
            responses = []
            for i, result in enumerate(searchResults[:maxResults], start=1):
                response = {
                    "resultId": i,
                    "title": result.get("title", ""),
                    "description": result.get("content", ""),
                    "url": result.get("link", ""),
                }
                responses.append(response)

            if len(responses) > 0:
                self.cacheMgr.setValue(modelName, cacheKey, responses)
            return json.dumps(responses, ensure_ascii=False)

        except Exception as e:
            logger.error(f"zhipu search failed: {str(e)}")
            return json.dumps(
                [{"error": f"zhipu search failed: {str(e)}"}], ensure_ascii=False
            )

    def _createSkills(self) -> List[SkillFunction]:
        return [
            SkillFunction(self._search),
        ]

    def _query_preprocess(self, query: str) -> str:
        query = query.strip()
        items = query.split(" ")
        if len(items) > self.MAX_KEYWORDS:
            return " ".join(items[: self.MAX_KEYWORDS])
        return query
