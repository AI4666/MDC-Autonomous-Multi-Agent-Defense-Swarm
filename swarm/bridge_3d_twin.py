"""
3D Digital Twin Bridge for AI-3D-Robotics-Lab (digital_twin_app/server.js)
Owner: Jorge A. Mendoza (Lead Architect & 3D Twin Lead)
"""
from typing import Any, Dict
import urllib.request
import json
from swarm.blackboard import Blackboard


class DigitalTwinBridge:
    """Streams live Blackboard robot positions, status, and safety vetoes to the Three.js Digital Twin."""

    def __init__(self, base_url: str = "http://localhost:3000", enabled: bool = False):
        self.base_url = base_url.rstrip("/")
        self.enabled = enabled

    def push_state(self, blackboard: Blackboard, scenario_name: str) -> bool:
        if not self.enabled:
            return False
        payload: Dict[str, Any] = {
            "scenario": scenario_name,
            "timestep": blackboard.timestep,
            "weather": blackboard.weather,
            "kill_switch": blackboard.kill_switch,
            "robots": [
                {
                    "id": rid,
                    "x": r["pos"][1],
                    "y": r["pos"][0],
                    "status": r["status"],
                    "battery": r["battery"],
                }
                for rid, r in blackboard.robots.items()
            ],
            "metrics": blackboard.metrics,
        }
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/anylogic/update",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=0.35) as resp:
                return resp.status == 200
        except Exception:
            return False
