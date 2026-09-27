from collections import defaultdict
import hashlib
import json


class MemoryAuditStore:
    """Ephemeral store used for tests and local non-Docker development."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.usage_events: list[dict] = []

    def add_usage(self, usage: dict) -> None:
        self.usage_events.append(usage)

    def add(self, event: dict) -> None:
        tenant_events = [item for item in self.events if item["tenant_id"] == event["tenant_id"]]
        previous_hash = tenant_events[-1]["ledger_hash"] if tenant_events else "GENESIS"
        self.events.append({**event, "previous_hash": previous_hash, "ledger_hash": self._hash_event(event, previous_hash)})

    def metrics(self, tenant_id: str) -> dict:
        events = [event for event in self.events if event["tenant_id"] == tenant_id]
        models: dict[str, int] = defaultdict(int)
        for event in events:
            models[event["served_by"]] += 1
        return {
            "requests": len(events),
            "fallbacks": sum(event["fallback_used"] for event in events),
            "total_cost_usd": round(sum(event["cost_usd"] for event in events), 6),
            "models_used": dict(models),
            "token_cost_usd": round(sum(item["token_cost_usd"] for item in self.usage_events
                                        if item["tenant_id"] == tenant_id), 9),
            "measured_requests": sum(item["tenant_id"] == tenant_id for item in self.usage_events),
        }

    def total_cost(self, tenant_id: str) -> float:
        return round(
            sum(event["cost_usd"] for event in self.events if event["tenant_id"] == tenant_id),
            6,
        )

    def verify_integrity(self, tenant_id: str) -> dict:
        previous_hash, checked = "GENESIS", 0
        for event in (item for item in self.events if item["tenant_id"] == tenant_id):
            if event["previous_hash"] != previous_hash or event["ledger_hash"] != self._hash_event(event, previous_hash):
                return {"tenant_id": tenant_id, "verified": False, "events_checked": checked}
            previous_hash, checked = event["ledger_hash"], checked + 1
        return {"tenant_id": tenant_id, "verified": True, "events_checked": checked, "head_hash": previous_hash}

    def evidence_events(self, tenant_id: str) -> list[dict]:
        return [
            {key: event[key] for key in ("request_id", "user_id", "primary_model", "served_by", "fallback_used", "cost_usd", "ledger_hash")}
            for event in self.events if event["tenant_id"] == tenant_id
        ]

    @staticmethod
    def _hash_event(event: dict, previous_hash: str) -> str:
        payload = {key: event[key] for key in ("request_id", "tenant_id", "user_id", "primary_model", "served_by", "fallback_used", "cost_usd")}
        encoded = json.dumps({"previous_hash": previous_hash, "event": payload}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()
