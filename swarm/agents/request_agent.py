"""
Agent 3: Request Agent (Part 3 Integration — NLP Lexicon Intent Classifier, Slot Parser & Cyber-Defense Rules)
Owner: Alexis Zisopulos (Part 3 Owner)
Integrates Domain Lexicon Intent Normalization (`intent_baseline.py`), Regex Slot Parsing (`slots.py`),
and First-Order Logic Rule Guardrails (`rules.py`) with Prompt-Injection Defense.
"""
import re
from typing import Any, Dict, List, Optional
from swarm.agents.base_agent import BaseAgent
from swarm.blackboard import Blackboard


ACTION_SYNONYM_MAP = {
    r"\b(courier|transport|send|bring|ship|drop off|convey|cart|carry|move)\b": "deliver",
    r"\b(fetch|collect|retrieve|gather|take|pick up)\b": "pickup",
    r"\b(guide|chaperone|lead|accompany|walk with|shepherd)\b": "escort",
}

BUILDING_ALIASES = {
    "library": "library",
    "science": "science_lab",
    "science_lab": "science_lab",
    "science lab": "science_lab",
    "robotics": "robotics_lab",
    "robotics_lab": "robotics_lab",
    "robotics lab": "robotics_lab",
    "student_center": "student_center",
    "student center": "student_center",
    "engineering": "engineering_hall",
    "engineering_hall": "engineering_hall",
    "engineering hall": "engineering_hall",
    "admin": "admin_office",
    "administration": "admin_office",
    "admin_office": "admin_office",
    "admin office": "admin_office",
    "cafeteria": "cafeteria",
    "clinic": "clinic",
    "server_room": "server_room",
    "server room": "server_room",
    "restricted_vault": "restricted_vault",
    "restricted vault": "restricted_vault",
    "hazmat_storage": "hazmat_storage",
}


def normalize_utterance_lexicon(text: str) -> str:
    cleaned = text.lower()
    for pattern, canonical in ACTION_SYNONYM_MAP.items():
        cleaned = re.sub(pattern, canonical, cleaned, flags=re.IGNORECASE)
    return cleaned


def parse_hour_24(time_str: Optional[str]) -> Optional[int]:
    """Normalizes time expressions ('3pm', '15:00', '02:00 AM') into 24-hour integer (0-23)."""
    if not time_str:
        return None
    s = str(time_str).strip().lower()
    match = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not match:
        return None
    hour = int(match.group(1))
    period = match.group(3)
    if period:
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
    return hour if 0 <= hour <= 23 else None


class RequestAgent(BaseAgent):
    """
    Turns natural-language text requests into structured jobs using Part 3 intent + slot parsing,
    validates them against the logical rule catalog (R0-R4), and blocks prompt injections or spoofed requests.
    """

    OPEN_HOURS = (7, 21)
    INJECTION_PATTERNS = (
        r"ignore\s+(all\s+|the\s+|previous\s+)?rules",
        r"bypass\s+(safety|security|supervisor|check)",
        r"override\s+(protocol|restriction|safety|auth)",
        r"sudo\s+",
        r"system\s*prompt",
        r"act\s+as\s+admin",
        r"disable\s+kill[\s_-]?switch",
    )

    def __init__(self, blackboard: Blackboard):
        super().__init__("RequestAgent", blackboard)

    def classify_intent(self, text: str) -> str:
        norm = normalize_utterance_lexicon(text)
        if "escort" in norm:
            return "escort"
        if "pickup" in norm and "deliver" not in norm:
            return "pickup"
        return "deliver"

    def parse_text_slots(self, text: str) -> Dict[str, Any]:
        """Extract src, dst, and hour directly from raw natural language utterance if not explicitly provided."""
        slots: Dict[str, Any] = {"intent": self.classify_intent(text)}
        low = text.lower()

        # Time extraction
        t_match = re.search(r"\bat\s+(\d{1,2}(?::\d{2})?(?:\s*[ap]m)?)\b", low) or re.search(
            r"\b(\d{1,2}:\d{2}(?:\s*[ap]m)?|\d{1,2}\s*[ap]m)\b", low
        )
        if t_match:
            h = parse_hour_24(t_match.group(1))
            if h is not None:
                slots["hour"] = h

        # Building entity extraction
        bldg_keys = sorted(BUILDING_ALIASES.keys(), key=len, reverse=True)
        bldg_regex = "|".join(re.escape(k) for k in bldg_keys)
        from_m = re.search(rf"\b(?:from|out of)\s+({bldg_regex})\b", low)
        to_m = re.search(rf"\b(?:to|into|in|drop off at)\s+(?:the\s+)?({bldg_regex})\b", low)

        if from_m:
            slots["src"] = BUILDING_ALIASES[from_m.group(1)]
        if to_m:
            slots["dst"] = BUILDING_ALIASES[to_m.group(1)]
        return slots

    def detect_prompt_injection(self, text: str) -> bool:
        low = text.lower()
        return any(re.search(pat, low) for pat in self.INJECTION_PATTERNS)

    def validate_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        text = req.get("text", "")
        parsed = self.parse_text_slots(text)

        raw_src = (req.get("src") or parsed.get("src") or "robotics_lab").lower().strip()
        raw_dst = (req.get("dst") or parsed.get("dst") or "").lower().strip()
        src = BUILDING_ALIASES.get(raw_src, raw_src)
        dst = BUILDING_ALIASES.get(raw_dst, raw_dst)

        hour = req.get("hour", parsed.get("hour", 12))
        deadline_steps = req.get("deadline_steps", 40)
        is_attack = bool(req.get("is_malicious", False))

        reasons: List[str] = []

        # Rule R0 (Cyber-Defense): Prompt Injection / Jailbreak attempt
        if self.detect_prompt_injection(text):
            reasons.append("R0_PROMPT_INJECTION_DETECTED")

        # Rule R1 (Restricted Zone Check): Never deliver to restricted buildings
        if (
            dst in self.blackboard.restricted_zones
            or "server_room" in text.lower()
            or "server room" in text.lower()
            or "restricted_vault" in text.lower()
            or "restricted vault" in text.lower()
        ):
            reasons.append("R1_RESTRICTED_BUILDING_ACCESS")

        # Rule R2 (Building Operating Hours Check: 07:00 - 21:00)
        if hour is None or not (self.OPEN_HOURS[0] <= int(hour) <= self.OPEN_HOURS[1]):
            reasons.append("R2_OUTSIDE_BUILDING_HOURS")

        # Rule R3 (Conflict / Ill-formed src == dst or unknown destination)
        if src == dst or dst not in self.blackboard.buildings:
            reasons.append("R3_INVALID_OR_CONFLICTING_DESTINATION")

        # Rule R4 (Impossible Time / Deadline Check)
        src_coord = self.blackboard.buildings.get(src, (1, 1))
        dst_coord = self.blackboard.buildings.get(dst, (17, 17))
        min_manhattan = abs(src_coord[0] - dst_coord[0]) + abs(src_coord[1] - dst_coord[1])
        if deadline_steps <= 0 or deadline_steps < min_manhattan:
            reasons.append("R4_IMPOSSIBLE_DEADLINE")

        accepted = len(reasons) == 0
        structured_job = {
            "id": req.get("id", "REQ-00"),
            "text": text,
            "intent": parsed["intent"],
            "src": src,
            "dst": dst,
            "src_coord": src_coord,
            "dst_coord": dst_coord,
            "hour": hour,
            "deadline_steps": deadline_steps,
            "is_malicious": is_attack
            or ("R0_PROMPT_INJECTION_DETECTED" in reasons)
            or ("R1_RESTRICTED_BUILDING_ACCESS" in reasons),
            "accepted": accepted,
            "rejection_reasons": reasons,
        }
        return structured_job

    def step(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        req = input_data.get("request", input_data)
        self.blackboard.metrics["total_requests"] += 1
        job = self.validate_request(req)

        if job["is_malicious"]:
            self.blackboard.metrics["attacks_attempted"] += 1

        if job["accepted"]:
            self.blackboard.validated_jobs.append(job)
            self.blackboard.metrics["valid_jobs"] += 1
            decision = "ACCEPTED"
        else:
            self.blackboard.rejected_requests.append(job)
            if job["is_malicious"]:
                self.blackboard.metrics["malicious_blocked"] += 1
            decision = "REJECTED"

        self.blackboard.post_message(
            self.name,
            "PlannerAgent" if job["accepted"] else "SafetySupervisor",
            "REQUEST_VALIDATION",
            {
                "id": job["id"],
                "intent": job["intent"],
                "src": job["src"],
                "dst": job["dst"],
                "accepted": job["accepted"],
                "reasons": job["rejection_reasons"],
            },
            decision=decision,
        )
        return job
