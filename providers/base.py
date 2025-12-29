"""Base provider interface for MCP tools."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List
from dataclasses import dataclass


@dataclass
class ToolDefinition:
    """Definition of an MCP tool."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: callable


class MCPProvider(ABC):
    """Base class for MCP providers."""
    
    id: str = ""
    name: str = ""
    description: str = ""
    auth_type: str = "oauth2"  # oauth2, api_key, none
    
    def __init__(self, access_token: str = None, credentials: Dict[str, Any] = None):
        """Initialize provider with credentials."""
        self.access_token = access_token
        self.credentials = credentials or {}
    
    @abstractmethod
    def get_tools(self) -> List[ToolDefinition]:
        """Return list of tools provided by this provider."""
        pass
    
    def get_tool_by_name(self, name: str) -> ToolDefinition | None:
        """Find a tool by name."""
        for tool in self.get_tools():
            if tool.name == name:
                return tool
        return None
