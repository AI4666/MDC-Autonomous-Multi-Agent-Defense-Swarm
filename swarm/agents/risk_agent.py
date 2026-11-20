"""
Agent 4: Risk Agent (Part 4a Integration — Exact Bayesian Network Enumeration Inference)
Owner: Jorge A. Mendoza (Part 4 Owner & Lead Architect)
Integrates `BayesianNetwork` exact inference over Weather (W), WetSensor (R), Obstacle (O),
LidarAlert (L), and WheelSlip (S) from Part 4 `bayes_net.py`.
"""
import itertools
from typing import Any, Dict, Optional, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class Part4BayesianNetwork:
    """
    Exact Variable Enumeration Bayesian Network from Part 4 bayes_net.py:
        Weather (W) ---> WetSensor (R) -> WheelSlip (S)
        Weather (W) ---> Obstacle (O)  -> LidarAlert (L)
    """

    def __init__(self):
        self.p_w1 = 0.30
        self.p_wet1_given_w = {0: 0.10, 1: 0.85}
        self.p_obs1_given_w = {0: 0.20, 1: 0.35}
        self.p_lidar1_given_obs_w = {
            (0, 0): 0.05,
            (0, 1): 0.22,
            (1, 0): 0.94,
            (1, 1): 0.78,
        }
        self.p_slip1_given_wet = {0: 0.04, 1: 0.65}

    def prob_w(self, w: int) -> float:
        return self.p_w1 if w == 1 else (1.0 - self.p_w1)

    def prob_wet(self, w: int, r: int) -> float:
        p = self.p_wet1_given_w[w]
        return p if r == 1 else (1.0 - p)

    def prob_obs(self, w: int, o: int) -> float:
        p = self.p_obs1_given_w[w]
        return p if o == 1 else (1.0 - p)

    def prob_lidar(self, o: int, w: int, l: int) -> float:
        p = self.p_lidar1_given_obs_w[(o, w)]
        return p if l == 1 else (1.0 - p)

    def prob_slip(self, r: int, s: int) -> float:
        p = self.p_slip1_given_wet[r]
        return p if s == 1 else (1.0 - p)

    def query_obstacle_posterior(self, evidence: Dict[str, int]) -> float:
        """Exact variable enumeration for P(Obstacle = 1 | evidence)."""
        dist = {0: 0.0, 1: 0.0}
        for w, r, o, l, s in itertools.product([0, 1], repeat=5):
            if "weather" in evidence and evidence["weather"] != w:
                continue
            if "wet" in evidence and evidence["wet"] != r:
                continue
            if "lidar" in evidence and evidence["lidar"] != l:
                continue
            if "slip" in evidence and evidence["slip"] != s:
                continue
            joint = (
                self.prob_w(w)
                * self.prob_wet(w, r)
                * self.prob_obs(w, o)
                * self.prob_lidar(o, w, l)
                * self.prob_slip(r, s)
            )
            dist[o] += joint
        norm = dist[0] + dist[1]
        return round(dist[1] / norm, 3) if norm > 0 else 0.0


class RiskAgent(BaseAgent):
    """
    Computes exact Bayesian posterior P(Obstacle=1 | Weather, WetSensor, LidarAlert)
    using the Part 4 Bayesian Network.
    Threshold justification (tau = 0.60):
    - In clear weather with no LiDAR anomaly (W=0, R=0, L=0), P(Obs=1) = 0.015 (safe).
    - In rain with wet floor but no LiDAR anomaly (W=1, R=1, L=0), P(Obs=1) = 0.132 (safe).
    - In rain with wet floor AND LiDAR obstacle return (W=1, R=1, L=1), P(Obs=1) = 0.656 >= 0.60,
      justifying an immediate reroute or Human-in-the-Loop escalation.
    """

    RISK_THRESHOLD = 0.60

    def __init__(self, blackboard: Blackboard, threshold: float = RISK_THRESHOLD):
        super().__init__("RiskAgent", blackboard)
        self.threshold = threshold
        self.bn = Part4BayesianNetwork()

    def compute_posterior_risk(
        self, weather: str, wet_ground: bool, obstacle_sensor: bool
    ) -> float:
        ev = {
            "weather": 1 if weather == "rain" else 0,
            "wet": 1 if wet_ground else 0,
            "lidar": 1 if obstacle_sensor else 0,
        }
        return self.bn.query_obstacle_posterior(ev)

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
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
