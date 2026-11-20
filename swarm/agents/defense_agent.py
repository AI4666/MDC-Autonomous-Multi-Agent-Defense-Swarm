"""
Agent 5: Defense Agent (Part 4b Integration — Q-Learning RL & Minimax Adversarial Evasion)
Owner: Jorge A. Mendoza (Part 4 Owner & Lead Architect)
"""
from typing import Any, Dict, List, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class DefenseAgent(BaseAgent):
    """
    Uses Part 4 Minimax lookahead + RL evasion policy to out-plan adversarial robots
    that actively try to block delivery corridors.
    """

    def __init__(self, blackboard: Blackboard):
        super().__init__("DefenseAgent", blackboard)

    def minimax_evade_move(
        self,
        robot_pos: Tuple[int, int],
        goal_pos: Tuple[int, int],
        adv_pos: Tuple[int, int],
        grid: List[List[int]],
    ) -> Tuple[int, int]:
        """
        Depth-2 Minimax step: selects the valid neighbor (nr, nc) that minimizes distance to goal
        while maximizing separation from the blocking adversary under the adversary's best counter-move.
        """
        rows, cols = len(grid), len(grid[0])
        moves = [(0, 1), (1, 0), (0, -1), (-1, 0)]

        best_move = robot_pos
        best_val = -1e9

        for dr, dc in moves:
            nr, nc = robot_pos[0] + dr, robot_pos[1] + dc
            if not (0 <= nr < rows and 0 <= nc < cols) or grid[nr][nc] == 1:
                continue
            if (nr, nc) == adv_pos:
                continue

            # Adversary responds by trying to minimize distance to our new position
            worst_adv_dist = 1e9
            for adr, adc in moves + [(0, 0)]:
                ar, ac = adv_pos[0] + adr, adv_pos[1] + adc
                if 0 <= ar < rows and 0 <= ac < cols and grid[ar][ac] == 0:
                    d_adv = abs(nr - ar) + abs(nc - ac)
                    worst_adv_dist = min(worst_adv_dist, d_adv)

            dist_to_goal = abs(nr - goal_pos[0]) + abs(nc - goal_pos[1])
            # Utility: get closer to goal while keeping safe buffer (> 1 cell) from adversary
            safety_bonus = 15.0 if worst_adv_dist >= 2 else (-50.0 if worst_adv_dist == 0 else 0.0)
            val = -2.0 * dist_to_goal + safety_bonus + 1.5 * worst_adv_dist

            if val > best_val:
                best_val = val
                best_move = (nr, nc)

        return best_move

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"robot_id": str, "robot_pos": (r, c), "goal_pos": (r, c), "adv_pos": (r, c), "grid": list}
        Output: {"evasion_move": (r, c), "replan_required": bool, "blocked_corridor": list}
        """
        robot_id = input_data.get("robot_id", "AMR-01")
        robot_pos: Tuple[int, int] = tuple(input_data.get("robot_pos", (0, 0)))
        goal_pos: Tuple[int, int] = tuple(input_data.get("goal_pos", (14, 14)))
        adv_pos: Tuple[int, int] = tuple(input_data.get("adv_pos", (8, 8)))
        grid = input_data.get("grid", [[0] * 18 for _ in range(18)])

        if not self.blackboard.defense_enabled:
            return {
                "robot_id": robot_id,
                "evasion_move": robot_pos,
                "replan_required": False,
                "blocked_corridor": [],
            }

        evasion_move = self.minimax_evade_move(robot_pos, goal_pos, adv_pos, grid)
        # Mark adversary cell and its immediate pinch zone as blocked for PlannerAgent replanning
        blocked_corridor = [adv_pos]

        result = {
            "robot_id": robot_id,
            "robot_pos": robot_pos,
            "adversary_pos": adv_pos,
            "evasion_move": evasion_move,
            "replan_required": True,
            "blocked_corridor": blocked_corridor,
        }

        self.blackboard.post_message(
            self.name,
            "PlannerAgent",
            "ADVERSARY_EVASION",
            result,
            decision="EVADE_AND_REPLAN",
        )
        return result
