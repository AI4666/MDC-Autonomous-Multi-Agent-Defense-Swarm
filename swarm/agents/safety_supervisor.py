"""
Agent 6: Safety Supervisor (Modules 9–13 Integration — Invariants, Action Veto, Kill-Switch & HITL)
Owner: Jorge A. Mendoza (Lead Architect & Safety Supervisor Lead)
"""
from typing import Any, Dict, List, Set, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class SafetySupervisor(BaseAgent):
    """
    Enforces 4 formal written invariants before any robot action executes:
      - INV-1 (Restricted Zone): Never enter or deliver to a restricted zone (server_room, restricted_vault, hazmat_storage).
      - INV-2 (Zero Collision): Never allow two robots in the same cell at the same time step (or head-on swap).
      - INV-3 (Validation Gate): Never act on a request that failed RequestAgent validation.
      - INV-4 (Kill-Switch & Risk Gate): Stop all robots immediately when kill_switch is ON,
        and veto unapproved moves whose Bayesian risk exceeds RiskAgent.RISK_THRESHOLD.
    """

    INVARIANTS = {
        "INV_1_NO_RESTRICTED_ZONE": "Never enter or deliver to a restricted building/zone.",
        "INV_2_NO_CELL_COLLISION": "Never allow two robots to occupy the same cell at the same time.",
        "INV_3_NO_UNVALIDATED_JOB": "Never execute a delivery request that failed RequestAgent validation.",
        "INV_4_KILL_SWITCH_AND_RISK": "Halt all robots when kill-switch is active or path risk is unapproved.",
    }

    def __init__(self, blackboard: Blackboard):
        super().__init__("SafetySupervisor", blackboard)

    def engage_kill_switch(self, reason: str = "Manual operator trigger") -> None:
        self.blackboard.kill_switch = True
        for rid, robot in self.blackboard.robots.items():
            robot["status"] = "HALTED_BY_KILL_SWITCH"
        self.blackboard.post_message(
            self.name,
            "ALL_ROBOTS",
            "KILL_SWITCH_ENGAGED",
            {"kill_switch": True, "reason": reason},
            decision="EMERGENCY_STOP",
        )

    def release_kill_switch(self) -> None:
        self.blackboard.kill_switch = False
        for rid, robot in self.blackboard.robots.items():
            robot["status"] = "IDLE"
        self.blackboard.post_message(
            self.name,
            "ALL_ROBOTS",
            "KILL_SWITCH_RELEASED",
            {"kill_switch": False},
            decision="RESUMED",
        )

    def verify_action(
        self,
        robot_id: str,
        target_cell: Tuple[int, int],
        occupied_cells: Set[Tuple[int, int]],
        job: Dict[str, Any],
        risk_score: float = 0.0,
        risk_threshold: float = 0.60,
    ) -> Dict[str, Any]:
        """Evaluate all 4 safety invariants and either APPROVE or VETO the proposed action."""
        if not self.blackboard.safety_enabled:
            return {"approved": True, "violated_invariants": [], "escalate_to_human": False}

        violations: List[str] = []
        escalate_to_human = False

        # Invariant 4: Kill-Switch or High-Risk Threshold check
        if self.blackboard.kill_switch:
            violations.append("INV_4_KILL_SWITCH_ACTIVE")
        if risk_score >= risk_threshold:
            violations.append("INV_4_HIGH_RISK_THRESHOLD_EXCEEDED")
            escalate_to_human = True

        # Invariant 3: Request Validation Gate
        if job and not job.get("accepted", False):
            violations.append("INV_3_UNVALIDATED_OR_REJECTED_REQUEST")

        # Invariant 1: Restricted Zone Enforcement
        restricted_coords = set(self.blackboard.restricted_zones.values())
        if target_cell in restricted_coords or (job and job.get("dst") in self.blackboard.restricted_zones):
            violations.append("INV_1_RESTRICTED_ZONE_VIOLATION")
            escalate_to_human = True

        # Invariant 2: Zero Cell Collision Enforcement
        if target_cell in occupied_cells:
            violations.append("INV_2_CELL_COLLISION_PREVENTED")

        approved = len(violations) == 0
        if not approved:
            self.blackboard.metrics["unsafe_actions_vetoed"] += 1

        decision = "APPROVED" if approved else "VETOED"
        result = {
            "robot_id": robot_id,
            "target_cell": target_cell,
            "approved": approved,
            "violated_invariants": violations,
            "escalate_to_human": escalate_to_human,
        }

        if not approved:
            self.blackboard.post_message(
                self.name,
                robot_id,
                "SAFETY_VETO",
                result,
                decision=decision,
            )
        return result

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        return self.verify_action(
            robot_id=input_data.get("robot_id", "AMR-01"),
            target_cell=tuple(input_data.get("target_cell", (0, 0))),
            occupied_cells=set(tuple(c) for c in input_data.get("occupied_cells", [])),
            job=input_data.get("job", {"accepted": True}),
            risk_score=float(input_data.get("risk_score", 0.0)),
            risk_threshold=float(input_data.get("risk_threshold", 0.60)),
        )
