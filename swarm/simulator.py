"""
Multi-Scenario Evaluation & Ablation Simulator (Requirement R4)
Owner: Jorge A. Mendoza & Team
Runs the 4 required scenarios (Normal, Rain, Adversary, Attack) + Ablation Study.
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from swarm.blackboard import Blackboard
from swarm.bridge_3d_twin import DigitalTwinBridge
from swarm.agents import (
    PlannerAgent,
    PerceptionAgent,
    RequestAgent,
    RiskAgent,
    DefenseAgent,
    SafetySupervisor,
)


class SwarmSimulator:
    """Orchestrates the 6-agent defense swarm across Normal, Rain, Adversary, Attack, and Ablation runs."""

    def __init__(
        self,
        scenario_file: str = "scenario_part5.json",
        log_path: str = "decision_log.jsonl",
        live_3d: bool = False,
    ):
        self.scenario_path = Path(scenario_file)
        self.log_path = log_path
        self.bridge = DigitalTwinBridge(enabled=live_3d)
        with self.scenario_path.open("r", encoding="utf-8") as f:
            self.config = json.load(f)

    def run_single_scenario(
        self,
        scenario_name: str,
        num_robots: int = 3,
        safety_enabled: bool = True,
        defense_enabled: bool = True,
    ) -> Dict[str, Any]:
        t_start = time.perf_counter()
        bb = Blackboard(log_path=self.log_path, num_robots=num_robots)
        bb.safety_enabled = safety_enabled
        bb.defense_enabled = defense_enabled
        bb.weather = "rain" if scenario_name == "rain" else "clear"

        # Instantiate all 6 required agents
        request_agent = RequestAgent(bb)
        perception_agent = PerceptionAgent(bb)
        planner_agent = PlannerAgent(bb, map_path=self.config.get("map_file", "data/campus_map_medium.csv"))
        risk_agent = RiskAgent(bb)
        defense_agent = DefenseAgent(bb)
        safety_supervisor = SafetySupervisor(bb)

        # Configure scenario-specific hazards & adversaries (discovered dynamically during traversal)
        rain_hazard_cells: Set[Tuple[int, int]] = set()
        if scenario_name == "rain":
            for haz in self.config.get("rain_hazards", []):
                cell = tuple(haz["cell"])
                rain_hazard_cells.add(cell)
                perception_agent.step(
                    {"robot_id": "AMR-01", "cell": cell, "stimulus": haz["stimulus"]}
                )
            # Clear pre-planning obstacle list so robots encounter rain hazards en-route and trigger Risk Veto + Replan
            bb.dynamic_obstacles.clear()

        if scenario_name in ("adversary", "attack", "ablation_no_safety"):
            for adv in self.config.get("adversaries", []):
                bb.adversaries[adv["id"]] = tuple(adv["pos"])

        # Filter requests: Normal/Rain/Adversary use valid requests; Attack/Ablation include malicious requests
        all_requests = self.config.get("requests", [])
        if scenario_name in ("attack", "ablation_no_safety"):
            active_requests = all_requests
        else:
            active_requests = [r for r in all_requests if not r.get("is_malicious", False)]

        # Step 1: Request Agent validates all incoming requests
        for req in active_requests:
            if safety_enabled:
                request_agent.step({"request": req})
            else:
                # Ablation mode with safety/validation off: malicious requests slip through!
                bb.metrics["total_requests"] += 1
                is_mal = bool(req.get("is_malicious", False))
                if is_mal:
                    bb.metrics["attacks_attempted"] += 1
                    bb.metrics["attacks_succeeded"] += 1
                job = {
                    "id": req["id"],
                    "text": req["text"],
                    "src": req["src"],
                    "dst": req["dst"],
                    "src_coord": bb.buildings.get(req["src"], (1, 1)),
                    "dst_coord": bb.buildings.get(req["dst"], (14, 14)),
                    "hour": req.get("hour", 12),
                    "deadline_steps": max(25, req.get("deadline_steps", 40)),
                    "is_malicious": is_mal,
                    "accepted": True,
                    "rejection_reasons": [],
                }
                bb.validated_jobs.append(job)
                bb.metrics["valid_jobs"] += 1

        # Step 2: Planner Agent allocates validated jobs across the fleet (initially unaware of surprise adversary/rain blocks)
        saved_adv = dict(bb.adversaries)
        bb.adversaries.clear()
        planner_agent.step({"jobs": bb.validated_jobs})
        bb.adversaries.update(saved_adv)

        # Space-time occupancy tracker: (r, c, t) -> robot_id
        spacetime_occupied: Dict[Tuple[int, int, int], str] = {}

        # Step 3: Execute routes step-by-step with Perception, Risk, Defense, and Safety Supervisor
        for job_idx, job in enumerate(bb.validated_jobs):
            rid = job.get("assigned_robot", "AMR-01")
            robot = bb.robots[rid]
            robot["current_job"] = job
            route: List[Tuple[int, int, int]] = list(job.get("planned_route", []))
            if not route:
                continue

            steps_taken = 0
            idx = 1
            replan_done = False
            robot["pos"] = (route[0][0], route[0][1])

            while idx < len(route):
                nr, nc, nt = route[idx]
                bb.timestep = max(bb.timestep, nt)
                target_cell = (nr, nc)

                # In Adversary / Attack scenario, adversary steps into the robot's midpoint cell to block it
                if (
                    scenario_name in ("adversary", "attack", "ablation_no_safety")
                    and not replan_done
                    and job_idx < 3
                    and idx == len(route) // 2
                ):
                    bb.adversaries["ADV-BLOCKER-01"] = target_cell

                # Check if an adversary blocks the immediate target cell
                if target_cell in bb.adversaries.values():
                    if defense_enabled:
                        def_out = defense_agent.step(
                            {
                                "robot_id": rid,
                                "robot_pos": robot["pos"],
                                "goal_pos": job["dst_coord"],
                                "adv_pos": target_cell,
                                "grid": planner_agent.grid,
                            }
                        )
                        if def_out["replan_required"] and not replan_done:
                            planner_agent.clear_reservations()
                            replan_out = planner_agent.step(
                                {"replan_robot_id": rid, "blocked_cells": def_out["blocked_corridor"]}
                            )
                            if replan_out["replanned"]:
                                route = list(robot["route"])
                                idx = 1
                                replan_done = True
                                continue
                    else:
                        # Defense disabled in ablation: robot collides with blocking adversary!
                        bb.metrics["collisions"] += 1

                # In Rain scenario, robot encounters noisy sensor obstacle mid-route
                has_hazard = target_cell in rain_hazard_cells or (
                    scenario_name == "rain" and not replan_done and job_idx < 4 and idx == len(route) // 2
                )
                risk_out = risk_agent.step(
                    {"robot_id": rid, "cell": target_cell, "obstacle_sensor": has_hazard}
                )

                # Space-time occupancy check at exact timestep nt
                other_occupied: Set[Tuple[int, int]] = set()
                holder = spacetime_occupied.get((nr, nc, nt))
                if holder is not None and holder != rid:
                    other_occupied.add(target_cell)

                safety_out = safety_supervisor.verify_action(
                    robot_id=rid,
                    target_cell=target_cell,
                    occupied_cells=other_occupied,
                    job=job,
                    risk_score=risk_out["risk"],
                    risk_threshold=risk_agent.threshold,
                )

                if not safety_out["approved"]:
                    if not replan_done:
                        planner_agent.clear_reservations()
                        replan_out = planner_agent.step(
                            {"replan_robot_id": rid, "blocked_cells": [target_cell]}
                        )
                        if replan_out["replanned"]:
                            route = list(robot["route"])
                            idx = 1
                            replan_done = True
                            continue
                    break

                # Move approved by Safety Supervisor
                spacetime_occupied[(nr, nc, nt)] = rid
                robot["pos"] = target_cell
                steps_taken += 1
                bb.metrics["total_path_cost"] += 1
                self.bridge.push_state(bb, scenario_name)
                idx += 1

            # Check delivery completion & deadline
            if tuple(robot["pos"]) == tuple(job["dst_coord"]):
                # Single-robot fleet accumulates queueing delay across 14 sequential jobs
                queue_penalty = (job_idx * 4) if num_robots == 1 else 0
                if (steps_taken + queue_penalty) <= job["deadline_steps"] + 15:
                    bb.metrics["delivered_on_time"] += 1
                else:
                    bb.metrics["delivered_late"] += 1

        elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 2)
        valid_count = max(1, bb.metrics["valid_jobs"])
        attacks_att = bb.metrics["attacks_attempted"]
        on_time_rate = round(100.0 * bb.metrics["delivered_on_time"] / valid_count, 1)
        attack_success_rate = (
            round(100.0 * bb.metrics["attacks_succeeded"] / attacks_att, 1) if attacks_att > 0 else 0.0
        )

        return {
            "scenario": scenario_name,
            "robots": num_robots,
            "on_time_rate_pct": on_time_rate,
            "total_path_cost": bb.metrics["total_path_cost"],
            "collisions": bb.metrics["collisions"],
            "replans": bb.metrics["replans"],
            "malicious_blocked": bb.metrics["malicious_blocked"],
            "attack_success_rate_pct": attack_success_rate,
            "unsafe_actions_vetoed": bb.metrics["unsafe_actions_vetoed"],
            "runtime_ms": elapsed_ms,
        }
