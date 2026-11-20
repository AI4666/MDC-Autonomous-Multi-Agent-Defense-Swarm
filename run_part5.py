"""
One-Command Entrypoint for CAI 4505C Project Part 5: Autonomous Multi-Agent Defense Swarm
Usage:
    python run_part5.py --scenario all
    python run_part5.py --scenario attack --live-3d
Owner: Jorge A. Mendoza (Lead Architect)
"""
import argparse
import json
from pathlib import Path
from typing import List, Dict, Any
from swarm.simulator import SwarmSimulator


def print_results_table(results: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 114)
    print(" CAI 4505C PART 5 — AUTONOMOUS MULTI-AGENT DEFENSE SWARM EVALUATION RESULTS")
    print("=" * 114)
    header = (
        f"{'Scenario':<20} | {'Robots':>6} | {'On-Time %':>9} | {'Path Cost':>9} | "
        f"{'Collisions':>10} | {'Replans':>7} | {'Mal.Blocked':>11} | {'Atk Succ %':>10} | "
        f"{'Vetoed':>6} | {'Time(ms)':>8}"
    )
    print(header)
    print("-" * 114)
    for r in results:
        print(
            f"{r['scenario']:<20} | {r['robots']:>6} | {r['on_time_rate_pct']:>8.1f}% | "
            f"{r['total_path_cost']:>9} | {r['collisions']:>10} | {r['replans']:>7} | "
            f"{r['malicious_blocked']:>11} | {r['attack_success_rate_pct']:>9.1f}% | "
            f"{r['unsafe_actions_vetoed']:>6} | {r['runtime_ms']:>8.2f}"
        )
    print("=" * 114 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="MDC Autonomous Multi-Agent Defense Swarm Runner")
    parser.add_argument(
        "--scenario",
        type=str,
        default="all",
        choices=["all", "normal", "rain", "adversary", "attack", "ablation"],
        help="Scenario to run (default: all)",
    )
    parser.add_argument(
        "--live-3d",
        action="store_true",
        help="Stream live swarm telemetry to AI-3D-Robotics-Lab digital_twin_app (http://localhost:3000)",
    )
    args = parser.parse_args()

    log_file = Path("decision_log.jsonl")
    if log_file.exists():
        log_file.unlink()

    sim = SwarmSimulator(
        scenario_file="scenario_part5.json",
        log_path="decision_log.jsonl",
        live_3d=args.live_3d,
    )

    results: List[Dict[str, Any]] = []
    if args.scenario == "all":
        for sc in ("normal", "rain", "adversary", "attack"):
            results.append(sim.run_single_scenario(sc, num_robots=3, safety_enabled=True, defense_enabled=True))
        # Ablation 1: Safety Supervisor & Defense Agent switched OFF under Attack
        results.append(
            sim.run_single_scenario("ablation_no_safety", num_robots=3, safety_enabled=False, defense_enabled=False)
        )
        # Ablation 2: 1 Robot vs 3 Robots under Normal conditions
        results.append(
            sim.run_single_scenario("ablation_1_robot", num_robots=1, safety_enabled=True, defense_enabled=True)
        )
    elif args.scenario == "ablation":
        results.append(
            sim.run_single_scenario("attack", num_robots=3, safety_enabled=True, defense_enabled=True)
        )
        results.append(
            sim.run_single_scenario("ablation_no_safety", num_robots=3, safety_enabled=False, defense_enabled=False)
        )
    else:
        results.append(
            sim.run_single_scenario(args.scenario, num_robots=3, safety_enabled=True, defense_enabled=True)
        )

    print_results_table(results)

    out_path = Path("docs/evaluation_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"[OK] Saved decision audit trail to decision_log.jsonl and metrics to {out_path}")


if __name__ == "__main__":
    main()
