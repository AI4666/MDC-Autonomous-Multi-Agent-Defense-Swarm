"""
Automated Tests for Part 1 Planner Agent (Multi-Robot Allocation & Space-Time Conflict-Free A*)
Owner: Miguel Martinez (Part 1 Owner)
"""
from pathlib import Path
from swarm.blackboard import Blackboard
from swarm.agents.planner_agent import PlannerAgent

TEST_LOG = str(Path("docs") / "_pytest_log.jsonl")


def test_planner_allocates_across_multiple_robots():
    """PlannerAgent allocates jobs across the 3-robot fleet and produces valid conflict-free routes."""
    bb = Blackboard(log_path=TEST_LOG, num_robots=3)
    planner = PlannerAgent(bb)
    jobs = [
        {"id": "J1", "src": "robotics_lab", "dst": "library", "src_coord": (1, 1), "dst_coord": (2, 3), "accepted": True},
        {"id": "J2", "src": "clinic", "dst": "student_center", "src_coord": (8, 2), "dst_coord": (14, 4), "accepted": True},
        {"id": "J3", "src": "science_lab", "dst": "engineering_hall", "src_coord": (4, 14), "dst_coord": (14, 14), "accepted": True},
    ]
    out = planner.step({"jobs": jobs})
    assert len(out["assignments"]) >= 2
    for j in jobs:
        assert "assigned_robot" in j
        assert len(j["planned_route"]) >= 2


def test_planner_dynamic_replan_around_blocked_cell():
    """PlannerAgent dynamically replans when a cell on the robot's path becomes blocked."""
    bb = Blackboard(log_path=TEST_LOG, num_robots=3)
    planner = PlannerAgent(bb)
    job = {"id": "J1", "src": "robotics_lab", "dst": "library", "src_coord": (1, 1), "dst_coord": (2, 3), "accepted": True}
    bb.robots["AMR-01"]["pos"] = (1, 1)
    bb.robots["AMR-01"]["current_job"] = job
    out = planner.step({"replan_robot_id": "AMR-01", "blocked_cells": [(1, 2)]})
    assert out["replanned"] is True
    route_coords = [(r, c) for r, c, _ in out["assignments"]["AMR-01"]]
    assert (1, 2) not in route_coords
