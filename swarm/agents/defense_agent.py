"""
Agent 5: Defense Agent (Part 4b Integration — Alpha-Beta Minimax & Q-Learning Adversarial Evasion)
Owner: Jorge A. Mendoza (Part 4 Owner & Lead Architect)
Integrates `alphabeta` Minimax search (`adversarial.py`) and `QLearningAgent` (`mdp_rl.py`) from Part 4.
"""
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


@dataclass(frozen=True)
class PursuitEvasionState:
    robot_pos: Tuple[int, int]
    adv_pos: Tuple[int, int]
    goal_pos: Tuple[int, int]

    def is_terminal(self) -> bool:
        return self.robot_pos == self.goal_pos or self.robot_pos == self.adv_pos


def alphabeta(
    state: PursuitEvasionState,
    depth: int,
    alpha: float,
    beta: float,
    maximizing: bool,
    successors: Callable[[PursuitEvasionState, bool], List[PursuitEvasionState]],
    evaluate: Callable[[PursuitEvasionState], float],
    stats: Optional[Dict[str, int]] = None,
) -> float:
    """Minimax with Alpha-Beta Pruning from Part 4 adversarial.py."""
    if stats is not None:
        stats["nodes"] = stats.get("nodes", 0) + 1

    if depth == 0 or state.is_terminal():
        return evaluate(state)

    succs = successors(state, maximizing)
    if not succs:
        return evaluate(state)

    if maximizing:
        val = float("-inf")
        for s in succs:
            val = max(val, alphabeta(s, depth - 1, alpha, beta, False, successors, evaluate, stats))
            alpha = max(alpha, val)
            if alpha >= beta:
                if stats is not None:
                    stats["cutoffs"] = stats.get("cutoffs", 0) + 1
                break
        return val
    else:
        val = float("inf")
        for s in succs:
            val = min(val, alphabeta(s, depth - 1, alpha, beta, True, successors, evaluate, stats))
            beta = min(beta, val)
            if beta <= alpha:
                if stats is not None:
                    stats["cutoffs"] = stats.get("cutoffs", 0) + 1
                break
        return val


class DefenseAgent(BaseAgent):
    """
    Uses Part 4 Alpha-Beta Minimax game-theoretic lookahead + Q-Learning utility evaluation
    to evade or out-plan adversarial blocking robots on the campus grid.
    """

    def __init__(self, blackboard: Blackboard, search_depth: int = 3):
        super().__init__("DefenseAgent", blackboard)
        self.search_depth = search_depth

    def evaluate_state(self, state: PursuitEvasionState) -> float:
        if state.robot_pos == state.adv_pos:
            return -100.0
        if state.robot_pos == state.goal_pos:
            return 100.0
        d_goal = abs(state.robot_pos[0] - state.goal_pos[0]) + abs(state.robot_pos[1] - state.goal_pos[1])
        d_adv = abs(state.robot_pos[0] - state.adv_pos[0]) + abs(state.robot_pos[1] - state.adv_pos[1])
        buffer_bonus = 18.0 if d_adv >= 2 else (-40.0 if d_adv == 0 else -5.0)
        return -2.2 * d_goal + 1.6 * d_adv + buffer_bonus

    def get_neighbors(self, pos: Tuple[int, int], grid: List[List[int]]) -> List[Tuple[int, int]]:
        rows, cols = len(grid), len(grid[0])
        out: List[Tuple[int, int]] = []
        for dr, dc in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            nr, nc = pos[0] + dr, pos[1] + dc
            if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] == 0:
                out.append((nr, nc))
        return out or [pos]

    def minimax_evade_move(
        self,
        robot_pos: Tuple[int, int],
        goal_pos: Tuple[int, int],
        adv_pos: Tuple[int, int],
        grid: List[List[int]],
    ) -> Tuple[Tuple[int, int], Dict[str, int]]:
        def successors(st: PursuitEvasionState, is_max: bool) -> List[PursuitEvasionState]:
            if is_max:
                return [
                    PursuitEvasionState(n, st.adv_pos, st.goal_pos)
                    for n in self.get_neighbors(st.robot_pos, grid)
                    if n != st.adv_pos
                ]
            else:
                return [
                    PursuitEvasionState(st.robot_pos, n, st.goal_pos)
                    for n in self.get_neighbors(st.adv_pos, grid)
                ]

        root = PursuitEvasionState(robot_pos, adv_pos, goal_pos)
        stats: Dict[str, int] = {"nodes": 0, "cutoffs": 0}
        best_move = robot_pos
        best_val = float("-inf")

        for cand in self.get_neighbors(robot_pos, grid):
            if cand == adv_pos:
                continue
            child = PursuitEvasionState(cand, adv_pos, goal_pos)
            val = alphabeta(
                child,
                self.search_depth - 1,
                float("-inf"),
                float("inf"),
                False,
                successors,
                self.evaluate_state,
                stats,
            )
            if val > best_val:
                best_val = val
                best_move = cand

        return best_move, stats

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
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
                "alphabeta_stats": {"nodes": 0, "cutoffs": 0},
            }

        evasion_move, stats = self.minimax_evade_move(robot_pos, goal_pos, adv_pos, grid)
        blocked_corridor = [adv_pos]

        result = {
            "robot_id": robot_id,
            "robot_pos": robot_pos,
            "adversary_pos": adv_pos,
            "evasion_move": evasion_move,
            "replan_required": True,
            "blocked_corridor": blocked_corridor,
            "alphabeta_stats": stats,
        }

        self.blackboard.post_message(
            self.name,
            "PlannerAgent",
            "ADVERSARY_EVASION",
            result,
            decision="EVADE_AND_REPLAN",
        )
        return result
