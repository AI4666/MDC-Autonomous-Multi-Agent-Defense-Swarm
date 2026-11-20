"""
Automated Tests for Part 2 Perception Agent (Object Classification & Rain Sensor Degradation)
Owner: Jaime Florez (Part 2 Owner)
"""
from swarm.blackboard import Blackboard
from swarm.agents.perception_agent import PerceptionAgent


def test_perception_classifies_four_classes(tmp_path):
    """PerceptionAgent classifies package, door, person, and obstacle with high confidence in clear weather."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    perc = PerceptionAgent(bb)
    for label in ("package", "door", "person", "obstacle"):
        res = perc.step({"robot_id": "AMR-01", "cell": (3, 3), "stimulus": label})
        assert res["predicted_class"] == label
        assert res["confidence"] >= 0.85


def test_perception_confidence_degrades_in_rain_and_flags_obstacles(tmp_path):
    """PerceptionAgent reports lower sensor confidence in rain and registers blocking obstacles on Blackboard."""
    bb = Blackboard(log_path=str(tmp_path / "log.jsonl"))
    perc = PerceptionAgent(bb)
    clear_res = perc.classify_observation("obstacle", weather="clear")
    rain_res = perc.classify_observation("obstacle", weather="rain")
    assert rain_res["confidence"] < clear_res["confidence"]
    assert rain_res["is_blocking"] is True
