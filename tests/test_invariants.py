"""
Automated Tests for Safety Supervisor Invariants & Part 4 Risk/Defense (Requirement R3 & R5)
Owner: Jorge A. Mendoza (Lead Architect & Safety Supervisor Lead)
"""
from swarm.blackboard import Blackboard
from swarm.agents.safety_supervisor import SafetySupervisor
from swarm.agents.risk_agent import RiskAgent
from swarm.agents.defense_agent import DefenseAgent


def test_invariant_1_never_enter_restricted_zone(tmp_path):
    """INV-1: Safety Supervisor must veto any move into a restricted zone (e.g., server_room at (17, 17))."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    sup = SafetySupervisor(bb)
    res = sup.verify_action(
        robot_id="AMR-01",
        target_cell=(17, 17),
        occupied_cells=set(),
        job={"id": "J1", "dst": "server_room", "accepted": True},
    )
    assert res["approved"] is False
    assert "INV_1_RESTRICTED_ZONE_VIOLATION" in res["violated_invariants"]


def test_invariant_2_never_two_robots_in_same_cell(tmp_path):
    """INV-2: Safety Supervisor must veto any move into a cell already occupied by another robot."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    sup = SafetySupervisor(bb)
    res = sup.verify_action(
        robot_id="AMR-02",
        target_cell=(4, 5),
        occupied_cells={(4, 5)},
        job={"id": "J2", "dst": "library", "accepted": True},
    )
    assert res["approved"] is False
    assert "INV_2_CELL_COLLISION_PREVENTED" in res["violated_invariants"]


def test_invariant_3_never_act_on_unvalidated_request(tmp_path):
    """INV-3: Safety Supervisor must veto execution of any job that failed RequestAgent validation."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    sup = SafetySupervisor(bb)
    res = sup.verify_action(
        robot_id="AMR-01",
        target_cell=(2, 3),
        occupied_cells=set(),
        job={"id": "J3", "dst": "library", "accepted": False},
    )
    assert res["approved"] is False
    assert "INV_3_UNVALIDATED_OR_REJECTED_REQUEST" in res["violated_invariants"]


def test_invariant_4_kill_switch_halts_all_robots(tmp_path):
    """INV-4: Engaging the Kill-Switch immediately halts all robots and vetoes any proposed movement."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    sup = SafetySupervisor(bb)
    sup.engage_kill_switch("Emergency test")
    res = sup.verify_action(
        robot_id="AMR-03",
        target_cell=(1, 2),
        occupied_cells=set(),
        job={"id": "J4", "dst": "library", "accepted": True},
    )
    assert bb.kill_switch is True
    assert res["approved"] is False
    assert "INV_4_KILL_SWITCH_ACTIVE" in res["violated_invariants"]


def test_part4_risk_and_defense_agents(tmp_path):
    """Verify Bayes net risk threshold escalation in rain and Minimax adversarial evasion."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    bb.weather = "rain"
    risk_agent = RiskAgent(bb)
    out = risk_agent.step({"robot_id": "AMR-01", "cell": (5, 5), "obstacle_sensor": True})
    assert out["exceeds_threshold"] is True
    assert out["risk"] >= RiskAgent.RISK_THRESHOLD

    def_agent = DefenseAgent(bb)
    ev = def_agent.step({"robot_id": "AMR-01", "robot_pos": (7, 8), "goal_pos": (10, 8), "adv_pos": (8, 8)})
    assert ev["evasion_move"] != (8, 8)
    assert ev["replan_required"] is True
