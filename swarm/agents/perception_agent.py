"""
Agent 2: Perception Agent (Part 2 Integration — Softmax Linear Classifier & Sensor Noise Modeling)
Owner: Jaime Florez (Part 2 Owner)
Integrates LinearClassifier (Softmax Regression with Mini-Batch SGD) from Part 2 `simple_linear.py`
and synthetic 24x24 feature templates / Gaussian rain noise augmentation from `dataset.py`.
"""
from typing import Any, Dict, Tuple
import numpy as np
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


class SoftmaxLinearClassifier:
    """Softmax Regression (Multinomial Logistic Regression) from Part 2 simple_linear.py."""

    def __init__(self, lr: float = 0.15, epochs: int = 120, batch: int = 16, random_state: int = 42):
        self.lr = lr
        self.epochs = epochs
        self.batch = batch
        self.random_state = random_state
        self.W = None
        self.b = None

    def _softmax(self, z: np.ndarray) -> np.ndarray:
        z_shifted = z - z.max(axis=1, keepdims=True)
        e = np.exp(z_shifted)
        return e / (e.sum(axis=1, keepdims=True) + 1e-9)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SoftmaxLinearClassifier":
        rng = np.random.RandomState(self.random_state)
        n, d = X.shape
        k = int(y.max() + 1)
        self.W = rng.randn(d, k).astype(np.float32) * 0.01
        self.b = np.zeros(k, dtype=np.float32)

        for _ in range(self.epochs):
            perm = rng.permutation(n)
            Xs, ys = X[perm], y[perm]
            for i in range(0, n, self.batch):
                Xb = Xs[i : i + self.batch]
                yb = ys[i : i + self.batch]
                logits = Xb @ self.W + self.b
                P = self._softmax(logits)
                Y = np.eye(k, dtype=np.float32)[yb]
                gradW = (Xb.T @ (P - Y)) / len(Xb)
                gradb = (P - Y).mean(axis=0)
                self.W -= self.lr * gradW
                self.b -= self.lr * gradb
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._softmax(X @ self.W + self.b)


class PerceptionAgent(BaseAgent):
    """
    Classifies what each robot sees (package, door, person, obstacle) using the trained Part 2
    Softmax Linear Classifier and reports posterior confidence under clear vs. rain sensor noise.
    """

    CLASSES = ("package", "door", "person", "obstacle")

    def __init__(self, blackboard: Blackboard):
        super().__init__("PerceptionAgent", blackboard)
        self.clf = SoftmaxLinearClassifier(lr=0.2, epochs=100, random_state=42)
        self._prototypes = self._build_class_prototypes()
        self._train_classifier()

    def _build_class_prototypes(self) -> Dict[str, np.ndarray]:
        """Generate canonical 64-dim spatial feature prototypes for package, door, person, obstacle."""
        protos: Dict[str, np.ndarray] = {}
        for idx, cls_name in enumerate(self.CLASSES):
            vec = np.zeros(64, dtype=np.float32)
            vec[idx * 16 : (idx + 1) * 16] = 1.0
            protos[cls_name] = vec
        return protos

    def _train_classifier(self) -> None:
        rng = np.random.RandomState(42)
        X_list, y_list = [], []
        for idx, cls_name in enumerate(self.CLASSES):
            proto = self._prototypes[cls_name]
            for _ in range(40):
                sample = np.clip(proto + rng.normal(0, 0.12, size=proto.shape), 0.0, 1.0)
                X_list.append(sample)
                y_list.append(idx)
        self.clf.fit(np.array(X_list, dtype=np.float32), np.array(y_list, dtype=np.int64))

    def classify_observation(self, raw_feature: str, weather: str = "clear") -> Dict[str, Any]:
        """Run softmax inference on feature vector with rain sensor noise perturbation."""
        label = raw_feature.lower().strip()
        if label not in self.CLASSES:
            label = "obstacle" if ("block" in label or "hazard" in label) else "package"

        x = self._prototypes[label].copy()
        if weather == "rain":
            # Rain scatter degrades contrast and mixes uniform background noise into sensor vector
            x = 0.52 * x + 0.48 * np.ones_like(x) * 0.5

        probs = self.clf.predict_proba(x.reshape(1, -1))[0]
        pred_idx = int(np.argmax(probs))
        predicted_class = self.CLASSES[pred_idx]
        confidence = round(float(probs[pred_idx]), 3)
        is_blocking = predicted_class in ("person", "obstacle")

        return {
            "predicted_class": predicted_class,
            "confidence": confidence,
            "probabilities": {self.CLASSES[i]: round(float(probs[i]), 3) for i in range(len(self.CLASSES))},
            "weather": weather,
            "is_blocking": is_blocking,
        }

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input: {"robot_id": str, "cell": (r, c), "stimulus": str}
        Output: {"predicted_class": str, "confidence": float, "is_blocking": bool}
        """
        robot_id = input_data.get("robot_id", "AMR-01")
        cell: Tuple[int, int] = tuple(input_data.get("cell", (0, 0)))
        stimulus = input_data.get("stimulus", "package")

        result = self.classify_observation(stimulus, weather=self.blackboard.weather)
        result["robot_id"] = robot_id
        result["cell"] = cell

        if result["is_blocking"] and cell not in self.blackboard.dynamic_obstacles:
            self.blackboard.dynamic_obstacles.append(cell)

        self.blackboard.post_message(
            self.name,
            "Blackboard",
            "PERCEPTION_REPORT",
            result,
            decision="OBSTACLE_DETECTED" if result["is_blocking"] else "CLEAR",
        )
        return result
