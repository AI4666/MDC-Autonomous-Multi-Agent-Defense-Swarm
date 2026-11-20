"""
Base Agent Contract (Requirement R1)
Owner: Jorge A. Mendoza
"""
from abc import ABC, abstractmethod
from typing import Any, Dict
from swarm.blackboard import Blackboard


class BaseAgent(ABC):
    """Standard input/output interface for all 6 agents in the defense swarm."""

    def __init__(self, name: str, blackboard: Blackboard):
        self.name = name
        self.blackboard = blackboard

    @abstractmethod
    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process structured input_data, update blackboard, log decision, and return output."""
        raise NotImplementedError
