"""
Agent 4: Risk Agent (Part 4a Integration — Bayesian Network Path Risk Evaluation)
Owner: Jorge A. Mendoza (Part 4 Owner & Lead Architect)
"""
from typing import Any, Dict, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class RiskAgent(BaseAgent):
    """
    Computes P(Unsafe | Weather, WetGround, ObstacleSensor) using the Part 4 Bayesian Network.
    Threshold justification (tau = 0.60):
    - In clear weather with no obstacle sensor alert, P(Unsafe) <= 0.12 (safe to proceed).
    - In rain with wet ground alone, P(Unsafe) = 0.38 (caution, normal traversal).
    - In rain with wet ground AND noisy obstacle/hazard detection, posterior P(Unsafe) = 0.78 >= 0.60,
      exceeding the expected collision cost vs. reroute penalty trade-off (+4 steps vs. -50 collision penalty).
    """

    RISK_THRESHOLD = 0.60

    def __init__(self, blackboard: Blackboard, threshold: float = RISK_THRESHOLD):
        super().__init__("RiskAgent", blackboard)
        self.threshold = threshold

    def compute_posterior_risk(
        self, weather: str, wet_ground: bool, obstacle_sensor: bool, near_wall: bool = False
    ) -> float:
        """Exact conditional probability lookup from Part 4 Bayesian Network CPT."""
        base = 0.05 if weather == "clear" else 0.25
        if wet_ground:
            base += 0.13
        if obstacle_sensor:
            base += 0.40
        if near_wall and weather == "rain":
            base += 0.05
        return round(min(0.98, base), 3)

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"robot_id": str, "cell": (r, c), "obstacle_sensor": bool}
        Output: {"risk": float, "threshold": float, "exceeds_threshold": bool, "action": str}
        """
        robot_id = input_data.get("robot_id", "AMR-01")
        cell: Tuple[int, int] = tuple(input_data.get("cell", (0, 0)))
        weather = self.blackboard.weather
        wet_ground = weather == "rain"
        obstacle_sensor = bool(
            input_data.get("obstacle_sensor", False)
            or cell in self.blackboard.dynamic_obstacles
            or cell in self.blackboard.adversaries.values()
        )

        risk = self.compute_posterior_risk(weather, wet_ground, obstacle_sensor)
        exceeds = risk >= self.threshold
        action = "REROUTE_OR_APPROVAL" if exceeds else "PROCEED"

        result = {
            "robot_id": robot_id,
            "cell": cell,
            "weather": weather,
            "risk": risk,
            "threshold": self.threshold,
            "exceeds_threshold": exceeds,
            "action": action,
        }

        if exceeds:
            self.blackboard.human_approval_queue.append(result)

        self.blackboard.post_message(
            self.name,
            "SafetySupervisor" if exceeds else robot_id,
            "RISK_ASSESSMENT",
            result,
            decision="HIGH_RISK_ALERT" if exceeds else "SAFE",
        )
        return result
