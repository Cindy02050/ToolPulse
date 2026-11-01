"""SWE-agent integration. The host dependency is loaded only for the agent class."""
from toolpulse.integrations.sweagent.parser import SWEAgentActionParser

__all__ = ["SWEAgentActionParser", "ToolPulseSWEAgent"]


def __getattr__(name: str):
    if name == "ToolPulseSWEAgent":
        from toolpulse.integrations.sweagent.agent import ToolPulseSWEAgent
        return ToolPulseSWEAgent
    raise AttributeError(name)
