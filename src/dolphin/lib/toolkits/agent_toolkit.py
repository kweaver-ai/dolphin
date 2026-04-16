from typing import List, Any

from dolphin.core.tool.toolkit import Toolkit
from dolphin.core.tool.tool_function import ToolFunction
from dolphin.core.agent.base_agent import BaseAgent


class AgentToolkit(Toolkit):
    """
    AgentToolkit acts as a bridge between Agent and Tool system
    Converts a single Agent into a callable tool
    """

    def __init__(self, agent: BaseAgent, agentName: str = None):
        """
        Initialize AgentToolkit with an agent

        Args:
            agent (BaseAgent): BaseAgent instance to wrap as a tool
            agentName (str, optional): Name for the agent tool. If None, uses agent.get_name()
        """
        super().__init__()
        self.agent = agent
        self.agentName = agentName or agent.get_name()
        self._context = None

        # Create the agent execution functions
        self._createAgentTools()

    def set_context(self, context):
        self._context = context
        self.agent.set_context(context)

    def _createAgentTools(self):
        """
        Create OpenAI functions for agent execution
        """
        # Get agent description for function documentation
        agentDesc = self.agent.get_description()

        # Create async execution function
        async def arunAgent(query_str: str = None, **kwargs) -> Any:
            """
            Execute the agent asynchronously

            Args:
                query_str (str, optional): Query or task description to pass to the agent
                **kwargs: Additional arguments to pass to the agent

            Returns:
                Agent execution result
            """
            lastResult = None
            # Use query_str if provided, otherwise use query, with query_str taking priority
            queryParam = query_str

            # Prepare arguments for agent.arun()
            agentArgs = kwargs.copy()
            if queryParam is not None:
                agentArgs["query"] = queryParam

            await self.agent.initialize()
            # The agent initialization may recreate its executor/context.
            # Re-attach the injected parent context to preserve shared state
            # (variables, history, CLI stream renderer factory, etc.).
            if self._context is not None:
                self.agent.set_context(self._context)
            async for result in self.agent.arun(**agentArgs):
                lastResult = result

            #return variables and last stage answer
            result = {}
            if isinstance(lastResult, dict):
                for k, v in lastResult.items():
                    if not k.startswith("_"):
                        result[k] = v
                    elif k == "_progress":
                        if len(v) > 1:
                            result.update(v[-1])
            return result

        # Update function names and docstrings dynamically
        arunAgent.__name__ = f"{self.agentName}"

        # Use agent description if available, otherwise use default description
        if agentDesc:
            arunAgent.__doc__ = f"""
        {agentDesc}
        
        Args:
            query_str (str, optional): Query or task description to pass to the agent
            query (str, optional): Alternative parameter name for backward compatibility
            **kwargs: Additional arguments to pass to the agent
            
        Returns:
            Agent execution result
        """
        else:
            arunAgent.__doc__ = f"""
        Execute agent '{self.agentName}' asynchronously
        
        Args:
            query_str (str, optional): Query or task description to pass to the agent
            query (str, optional): Alternative parameter name for backward compatibility
            **kwargs: Additional arguments to pass to the agent
            
        Returns:
            Agent execution result
        """

        # Store function references
        self.arunAgentFunc = arunAgent

    def getName(self) -> str:
        """
        Get the toolkit name

        Returns:
            Toolkit name
        """
        return f"agent_toolkit_{self.agentName}"

    def _createTools(self) -> List[ToolFunction]:
        """
        Create the tools (OpenAI functions) for this agent

        Returns:
            List of ToolFunction objects
        """
        tools = []

        # Add async execution function (with arun_ prefix for backward compatibility)
        tools.append(ToolFunction(self.arunAgentFunc))

        return tools

    def getAgent(self) -> BaseAgent:
        """
        Get the wrapped agent

        Returns:
            BaseAgent instance
        """
        return self.agent

    def getAgentName(self) -> str:
        """
        Get the agent name

        Returns:
            Agent name string
        """
        return self.agentName

    def __str__(self) -> str:
        """
        String representation of the AgentToolkit

        Returns:
            Description string
        """
        return f"AgentToolkit(agent={self.agentName})"
