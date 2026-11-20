"""
Agent 1: Planner Agent (Part 1 Integration — Space-Time A* Search & CSP Multi-Robot Scheduling)
Owner: Miguel Martinez (Part 1 Owner)
"""
import csv
import heapq
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class PlannerAgent(BaseAgent):
    """
    Assigns validated jobs across 3+ robots (greedy nearest-available / CSP auction)
    and computes conflict-free space-time A* routes (no two robots in the same cell at time t).
    """

    def __init__(self, blackboard: Blackboard, map_path: str = "data/campus_map_medium.csv"):
        super().__init__("PlannerAgent", blackboard)
        self.grid = self._load_map(map_path)
        self.rows = len(self.grid)
        self.cols = len(self.grid[0]) if self.rows > 0 else 0
        # Space-time reservation table: set of (r, c, t) and edge swaps (r1, c1, r2, c2, t)
        self.reservations: Set[Tuple[int, int, int]] = set()
        self.edge_reservations: Set[Tuple[int, int, int, int, int]] = set()

    def _load_map(self, map_path: str) -> List[List[int]]:
        path = Path(map_path)
        if not path.exists():
            return [[0] * 18 for _ in range(18)]
        with path.open("r", encoding="utf-8") as f:
            return [[int(cell.strip()) for cell in row] for row in csv.reader(f) if row]

    def clear_reservations(self) -> None:
        self.reservations.clear()
        self.edge_reservations.clear()

    def space_time_astar(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        start_time: int = 0,
        blocked_cells: Optional[Set[Tuple[int, int]]] = None,
        max_steps: int = 120,
    ) -> Optional[List[Tuple[int, int, int]]]:
        """Find a conflict-free path [(r, c, t), ...] avoiding static walls, dynamic blocks, and other robots."""
        blocked = blocked_cells or set()
        if start in blocked or goal in blocked:
            pass  # allow stepping out of start if needed, but goal cannot be an impassable wall
        if not (0 <= goal[0] < self.rows and 0 <= goal[1] < self.cols) or self.grid[goal[0]][goal[1]] == 1:
            return None

        def heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> int:
            return abs(a[0] - b[0]) + abs(a[1] - b[1])

        open_heap: List[Tuple[int, int, Tuple[int, int], int, List[Tuple[int, int, int]]]] = []
        h0 = heuristic(start, goal)
        heapq.heappush(open_heap, (h0, 0, start, start_time, [(start[0], start[1], start_time)]))
        visited: Set[Tuple[int, int, int]] = set()

        moves = [(0, 1), (1, 0), (0, -1), (-1, 0), (0, 0)]  # 4-neighbors + wait in place

        while open_heap:
            f, g, (r, c), t, path = heapq.heappop(open_heap)
            if (r, c) == goal:
                return path
            if g >= max_steps or (r, c, t) in visited:
                continue
            visited.add((r, c, t))

            nt = t + 1
            for dr, dc in moves:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                    continue
                if self.grid[nr][nc] == 1:
                    continue
                if (nr, nc) in blocked and (nr, nc) != goal:
                    continue
                # Space-time vertex conflict check
                if (nr, nc, nt) in self.reservations:
                    continue
                # Space-time edge swap conflict check
                if (nr, nc, r, c, nt) in self.edge_reservations:
                    continue

                new_g = g + 1
                new_f = new_g + heuristic((nr, nc), goal)
                heapq.heappush(
                    open_heap,
                    (new_f, new_g, (nr, nc), nt, path + [(nr, nc, nt)]),
                )
        return None

    def reserve_path(self, timed_path: List[Tuple[int, int, int]]) -> None:
        for i, (r, c, t) in enumerate(timed_path):
            self.reservations.add((r, c, t))
            if i > 0:
                pr, pc, _ = timed_path[i - 1]
                self.edge_reservations.add((pr, pc, r, c, t))

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"jobs": list_of_validated_jobs, "replan_robot_id": optional_str, "blocked_cells": optional_list}
        Output: {"assignments": dict_of_robot_routes, "replanned": bool}
        """
        blocked: Set[Tuple[int, int]] = set(self.blackboard.dynamic_obstacles)
        blocked.update(self.blackboard.adversaries.values())
        if "blocked_cells" in input_data:
            blocked.update(tuple(cell) for cell in input_data["blocked_cells"])

        # Handle dynamic replanning for a single blocked/risky robot
        replan_rid = input_data.get("replan_robot_id")
        if replan_rid and replan_rid in self.blackboard.robots:
            robot = self.blackboard.robots[replan_rid]
            job = robot.get("current_job")
            if job:
                goal = tuple(job["dst_coord"])
                new_path = self.space_time_astar(
                    tuple(robot["pos"]), goal, start_time=self.blackboard.timestep, blocked_cells=blocked
                )
                if new_path:
                    self.reserve_path(new_path)
                    robot["route"] = new_path
                    self.blackboard.metrics["replans"] += 1
                    self.blackboard.post_message(
                        self.name,
                        replan_rid,
                        "REPLAN_ROUTE",
                        {"robot_id": replan_rid, "job_id": job["id"], "new_steps": len(new_path)},
                        decision="REPLANNED",
                    )
                    return {"assignments": {replan_rid: new_path}, "replanned": True}

        # Allocate batch of validated jobs across the 3+ robots (CSP / Greedy Nearest-Available Auction)
        jobs = input_data.get("jobs", [])
        assignments: Dict[str, List[Tuple[int, int, int]]] = {}
        robot_available_time: Dict[str, int] = {
            rid: self.blackboard.timestep for rid in self.blackboard.robots
        }
        robot_virtual_pos: Dict[str, Tuple[int, int]] = {
            rid: tuple(r["pos"]) for rid, r in self.blackboard.robots.items()
        }

        for job in jobs:
            src = tuple(job["src_coord"])
            dst = tuple(job["dst_coord"])

            # Auction: pick robot minimizing (available_time + Manhattan distance to pickup)
            best_rid = min(
                self.blackboard.robots.keys(),
                key=lambda rid: (
                    robot_available_time[rid]
                    + abs(robot_virtual_pos[rid][0] - src[0])
                    + abs(robot_virtual_pos[rid][1] - src[1])
                ),
            )
            t0 = robot_available_time[best_rid]
            cur_pos = robot_virtual_pos[best_rid]

            leg1 = self.space_time_astar(cur_pos, src, start_time=t0, blocked_cells=blocked)
            if not leg1:
                continue
            t_pick = leg1[-1][2]
            leg2 = self.space_time_astar(src, dst, start_time=t_pick, blocked_cells=blocked)
            if not leg2:
                continue

            full_path = leg1 + leg2[1:]
            self.reserve_path(full_path)

            robot_available_time[best_rid] = full_path[-1][2]
            robot_virtual_pos[best_rid] = dst
            job["assigned_robot"] = best_rid
            job["planned_route"] = full_path
            assignments.setdefault(best_rid, []).extend(full_path)

            self.blackboard.post_message(
                self.name,
                best_rid,
                "JOB_ASSIGNED",
                {
                    "job_id": job["id"],
                    "robot_id": best_rid,
                    "src": job["src"],
                    "dst": job["dst"],
                    "path_cost": len(full_path) - 1,
                },
                decision="ALLOCATED",
            )

        return {"assignments": assignments, "replanned": False}
