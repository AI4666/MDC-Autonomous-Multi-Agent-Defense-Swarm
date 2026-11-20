"""
Agent 3: Request Agent (Part 3 Integration — NLP Intents, Slot Parsing, Logic Rules & Cyber-Defense)
Owner: Alexis Zisopulos (Part 3 Owner)
"""
import re
from typing import Any, Dict, List
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class RequestAgent(BaseAgent):
    """
    Turns text delivery requests into structured jobs, checks them against the Part 3 rule base,
    and rejects malicious/spoofed requests (prompt injections, restricted zones, outside hours, impossible times).
    """

    OPEN_HOURS = (7, 21)  # Campus buildings open 07:00 to 21:00
    INJECTION_PATTERNS = (
        r"ignore\s+(all\s+|the\s+|previous\s+)?rules",
        r"bypass\s+(safety|security|supervisor|check)",
        r"override\s+(protocol|restriction|safety|auth)",
        r"sudo\s+",
        r"system\s*prompt",
        r"act\s+as\s+admin",
        r"disable\s+kill[\s_-]?switch",
    )

    def __init__(self, blackboard: Blackboard):
        super().__init__("RequestAgent", blackboard)

    def detect_prompt_injection(self, text: str) -> bool:
        low = text.lower()
        return any(re.search(pat, low) for pat in self.INJECTION_PATTERNS)

    def validate_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        text = req.get("text", "")
        src = req.get("src", "robotics_lab").lower().strip()
        dst = req.get("dst", "").lower().strip()
        hour = req.get("hour", 12)
        deadline_steps = req.get("deadline_steps", 40)
        is_attack = bool(req.get("is_malicious", False))

        reasons: List[str] = []

        # Rule 0 (Cyber-Defense): Prompt Injection / Override attempt
        if self.detect_prompt_injection(text):
            reasons.append("R0_PROMPT_INJECTION_DETECTED")

        # Rule 1 (Restricted Zone Check): Never deliver to restricted buildings
        if dst in self.blackboard.restricted_zones or "server_room" in text.lower() or "restricted_vault" in text.lower():
            reasons.append("R1_RESTRICTED_BUILDING_ACCESS")

        # Rule 2 (Building Operating Hours Check)
        if hour is None or not (self.OPEN_HOURS[0] <= int(hour) <= self.OPEN_HOURS[1]):
            reasons.append("R2_OUTSIDE_BUILDING_HOURS")

        # Rule 3 (Conflict / Ill-formed src == dst or unknown building)
        if src == dst or dst not in self.blackboard.buildings:
            reasons.append("R3_INVALID_OR_CONFLICTING_DESTINATION")

        # Rule 4 (Impossible Time / Deadline Check)
        src_coord = self.blackboard.buildings.get(src, (1, 1))
        dst_coord = self.blackboard.buildings.get(dst, (17, 17))
        min_manhattan = abs(src_coord[0] - dst_coord[0]) + abs(src_coord[1] - dst_coord[1])
        if deadline_steps <= 0 or deadline_steps < min_manhattan:
            reasons.append("R4_IMPOSSIBLE_DEADLINE")

        accepted = len(reasons) == 0
        structured_job = {
            "id": req.get("id", "REQ-00"),
            "text": text,
            "src": src,
            "dst": dst,
            "src_coord": src_coord,
            "dst_coord": dst_coord,
            "hour": hour,
            "deadline_steps": deadline_steps,
            "is_malicious": is_attack or ("R0_PROMPT_INJECTION_DETECTED" in reasons) or ("R1_RESTRICTED_BUILDING_ACCESS" in reasons),
            "accepted": accepted,
            "rejection_reasons": reasons,
        }
        return structured_job

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"request": dict}
        Output: structured job dict with "accepted": bool and "rejection_reasons": list
        """
        req = input_data.get("request", input_data)
        self.blackboard.metrics["total_requests"] += 1
        job = self.validate_request(req)

        if job["is_malicious"]:
            self.blackboard.metrics["attacks_attempted"] += 1

        if job["accepted"]:
            self.blackboard.validated_jobs.append(job)
            self.blackboard.metrics["valid_jobs"] += 1
            decision = "ACCEPTED"
        else:
            self.blackboard.rejected_requests.append(job)
            if job["is_malicious"]:
                self.blackboard.metrics["malicious_blocked"] += 1
            decision = "REJECTED"

        self.blackboard.post_message(
            self.name,
            "PlannerAgent" if job["accepted"] else "SafetySupervisor",
            "REQUEST_VALIDATION",
            {
                "id": job["id"],
                "src": job["src"],
                "dst": job["dst"],
                "accepted": job["accepted"],
                "reasons": job["rejection_reasons"],
            },
            decision=decision,
        )
        return job
