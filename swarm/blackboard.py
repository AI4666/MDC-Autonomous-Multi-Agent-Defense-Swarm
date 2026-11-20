"""
Blackboard Shared State & JSONL Audit Logger (Requirement R2)
Owner: Jorge A. Mendoza (Lead Architect & Safety Supervisor Lead)
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class Blackboard:
    """Central shared state object (blackboard) and message bus for the 6-agent swarm."""

    def __init__(self, log_path: str = "decision_log.jsonl", num_robots: int = 3):
        self.log_path = Path(log_path)
        self.weather: str = "clear"
        self.kill_switch: bool = False
        self.safety_enabled: bool = True
        self.defense_enabled: bool = True
        self.timestep: int = 0

        # Restricted zones on the 18x18 campus_map_medium.csv grid (e.g. Server Room, Vault)
        self.restricted_zones: Dict[str, Tuple[int, int]] = {
            "server_room": (17, 17),
            "restricted_vault": (16, 17),
            "hazmat_storage": (17, 16),
        }

        # Named campus buildings mapped to 18x18 grid coordinates
        self.buildings: Dict[str, Tuple[int, int]] = {
            "library": (2, 3),
            "science_lab": (4, 14),
            "robotics_lab": (1, 1),
            "student_center": (14, 4),
            "engineering_hall": (14, 14),
            "admin_office": (2, 15),
            "cafeteria": (15, 8),
            "clinic": (8, 2),
            "server_room": (17, 17),
            "restricted_vault": (16, 17),
        }

        # Fleet of 3+ cooperating robots (AMR-01, AMR-02, AMR-03)
        default_starts = [(0, 0), (0, 2), (2, 0), (0, 4)]
        self.robots: Dict[str, Dict[str, Any]] = {}
        for i in range(num_robots):
            rid = f"AMR-0{i + 1}"
            self.robots[rid] = {
                "id": rid,
                "pos": default_starts[i % len(default_starts)],
                "route": [],
                "current_job": None,
                "status": "IDLE",
                "battery": 100.0,
            }

        # Dynamic obstacles & adversarial blocking robots
        self.dynamic_obstacles: List[Tuple[int, int]] = []
        self.adversaries: Dict[str, Tuple[int, int]] = {}

        # Queues & Metrics
        self.validated_jobs: List[Dict[str, Any]] = []
        self.rejected_requests: List[Dict[str, Any]] = []
        self.human_approval_queue: List[Dict[str, Any]] = []
        self.messages: List[Dict[str, Any]] = []

        self.metrics: Dict[str, Any] = {
            "total_requests": 0,
            "valid_jobs": 0,
            "delivered_on_time": 0,
            "delivered_late": 0,
            "total_path_cost": 0,
            "collisions": 0,
            "replans": 0,
            "malicious_blocked": 0,
            "attacks_attempted": 0,
            "attacks_succeeded": 0,
            "unsafe_actions_vetoed": 0,
        }

    def post_message(
        self,
        sender: str,
        recipient: str,
        event_type: str,
        payload: Dict[str, Any],
        decision: str = "INFO",
    ) -> Dict[str, Any]:
        """Post a message to the shared blackboard and append to decision_log.jsonl."""
        entry = {
            "timestamp": round(time.time(), 4),
            "timestep": self.timestep,
            "sender": sender,
            "recipient": recipient,
            "event_type": event_type,
            "decision": decision,
            "payload": payload,
        }
        self.messages.append(entry)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry
