from typing import List, Any

from dolphin.core.skill.skillkit import Skillkit
from dolphin.core.skill.skill_function import SkillFunction
from dolphin.core.agent.base_agent import BaseAgent


class AgentSkillKit(Skillkit):
    """
    AgentSkillKit acts as a bridge between Agent and Skill system
    Converts a single Agent into a callable skill
    """

    def __init__(self, agent: BaseAgent, agentName: str = None):
        """
        Initialize AgentSkillKit with an agent

        Args:
            agent (BaseAgent): BaseAgent instance to wrap as a skill
            agentName (str, optional): Name for the agent skill. If None, uses agent.get_name()
        """
        super().__init__()
        self.agent = agent
        self.agentName = agentName or agent.get_name()

        # Create the agent execution functions
        self._createAgentSkills()

    def set_context(self, context):
        self.agent.set_context(context)

    def _createAgentSkills(self):
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
        Get the skillkit name

        Returns:
            Skillkit name
        """
        return f"agent_skillkit_{self.agentName}"

    def _createSkills(self) -> List[SkillFunction]:
        """
        Create the skills (OpenAI functions) for this agent

        Returns:
            List of SkillFunction objects
        """
        skills = []

        # Add async execution function (with arun_ prefix for backward compatibility)
        skills.append(SkillFunction(self.arunAgentFunc))

        return skills

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
        String representation of the AgentSkillKit

        Returns:
            Description string
        """
        return f"AgentSkillKit(agent={self.agentName})"
