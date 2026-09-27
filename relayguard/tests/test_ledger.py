from relayguard.storage.memory import MemoryAuditStore


def test_memory_ledger_verifies_linked_events() -> None:
    store = MemoryAuditStore()
    first = {"request_id": "one", "tenant_id": "acme", "user_id": "sujal", "primary_model": "relay-mini", "served_by": "relay-mini", "fallback_used": False, "cost_usd": 0.0002}
    second = {**first, "request_id": "two", "served_by": "relay-backup", "fallback_used": True}
    store.add(first)
    store.add(second)
    assert store.verify_integrity("acme")["verified"] is True
    assert store.verify_integrity("acme")["events_checked"] == 2
