from relayguard.storage.memory import MemoryAuditStore


def test_evidence_events_are_scoped_to_the_tenant() -> None:
    store = MemoryAuditStore()
    event = {"request_id": "one", "tenant_id": "acme", "user_id": "sujal", "primary_model": "relay-mini", "served_by": "relay-mini", "fallback_used": False, "cost_usd": 0.0002}
    store.add(event)
    store.add({**event, "request_id": "two", "tenant_id": "globex"})
    evidence = store.evidence_events("acme")
    assert len(evidence) == 1
    assert evidence[0]["request_id"] == "one"
