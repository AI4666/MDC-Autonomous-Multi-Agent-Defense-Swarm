"""
Agent 2: Perception Agent (Part 2 Integration — Computer Vision Object Classifier)
Owner: Jaime Florez (Part 2 Owner)
"""
from typing import Any, Dict
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class PerceptionAgent(BaseAgent):
    """
    Classifies what each robot sees (package, door, person, obstacle) and reports confidence.
    Accounts for clear vs. rain/noisy sensor conditions from Part 2 & Part 4.
    """

    CLASSES = ("package", "door", "person", "obstacle")

    def __init__(self, blackboard: Blackboard):
        super().__init__("PerceptionAgent", blackboard)

    def classify_observation(self, raw_feature: str, weather: str = "clear") -> Dict[str, Any]:
        """Classify observation into {package, door, person, obstacle} with confidence score."""
        label = raw_feature.lower().strip()
        if label not in self.CLASSES:
            label = "obstacle" if "block" in label or "hazard" in label else "package"

        # Base linear classifier confidence from Part 2 (~0.94 in clear weather, degraded in rain)
        base_conf = {
            "package": 0.95,
            "door": 0.93,
            "person": 0.91,
            "obstacle": 0.92,
        }[label]

        noise_penalty = 0.18 if weather == "rain" else 0.0
        confidence = round(max(0.50, base_conf - noise_penalty), 3)
        is_blocking = label in ("person", "obstacle")

        return {
            "predicted_class": label,
            "confidence": confidence,
            "weather": weather,
            "is_blocking": is_blocking,
        }

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"robot_id": str, "cell": (r, c), "stimulus": str}
        Output: {"predicted_class": str, "confidence": float, "is_blocking": bool}
        """
        robot_id = input_data.get("robot_id", "AMR-01")
        cell = tuple(input_data.get("cell", (0, 0)))
        stimulus = input_data.get("stimulus", "package")

        result = self.classify_observation(stimulus, weather=self.blackboard.weather)
        result["robot_id"] = robot_id
        result["cell"] = cell

        if result["is_blocking"] and cell not in self.blackboard.dynamic_obstacles:
            self.blackboard.dynamic_obstacles.append(cell)

        self.blackboard.post_message(
            self.name,
            "Blackboard",
            "PERCEPTION_REPORT",
            result,
            decision="OBSTACLE_DETECTED" if result["is_blocking"] else "CLEAR",
        )
        return result
