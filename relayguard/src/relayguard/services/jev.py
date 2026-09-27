"""Optional Jev decision service. It classifies; it never writes answers."""

import json
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen

from relayguard.core.models import TaskClass


@dataclass(frozen=True)
class JevDecision:
    task_class: TaskClass
    confidence: float
    probability: float
    input_tokens: int | None
    model: str


class JevRouter:
    def __init__(self, api_key: str, model: str = "jev-1.13.0", timeout_seconds: float = 3.0):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def decide(self, prompt: str) -> JevDecision:
        payload = {
            "model": self.model,
            "state": {"request": prompt},
            "questions": {
                "workload": {
                    "type": "choice",
                    "instructions": (
                        "Classify the reasoning required. Choose the least demanding class "
                        "that can reliably do the task, not a class based on length alone."
                    ),
                    "criteria": {
                        "simple": "Short factual request with no meaningful inference.",
                        "moderate": "Focused question or short evidence-based answer.",
                        "involved": "Multiple facts, citation checks, or several steps.",
                        "complex": "Nuanced comparisons, strategy, or hard multi-step reasoning.",
                        "heavy": "Especially difficult reasoning with substantial evidence.",
                        "long_context": "Large input requiring reading but limited reasoning.",
                    },
                },
            },
        }
        request = Request(
            "https://api.typesafe.ai/v1/systemone",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.load(response)
            answer = data["answers"]["workload"]
            choice = TaskClass(answer["choice"])
            confidence = float(answer["confidence"])
            probability = float(answer["probabilities"][choice.value])
            if not (0 <= confidence <= 1 and 0 <= probability <= 1):
                raise ValueError("Jev confidence out of bounds")
            tokens = data.get("usage", {}).get("input_tokens")
            return JevDecision(choice, confidence, probability, tokens, str(data["model"]))
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as error:
            raise RuntimeError("Jev decision unavailable or malformed") from error
