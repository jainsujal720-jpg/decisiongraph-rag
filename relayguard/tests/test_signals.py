from relayguard.services.gateway import GatewayService
from relayguard.storage.memory import MemoryAuditStore


def test_fallback_rate_creates_a_governance_signal() -> None:
    store = MemoryAuditStore()
    store.add({"request_id": "one", "tenant_id": "acme", "user_id": "sujal", "primary_model": "relay-mini", "served_by": "relay-backup", "fallback_used": True, "cost_usd": 0.0008})
    signals = GatewayService(audit_store=store).risk_signals("acme")
    assert signals["status"] == "attention"
    assert "Fallback rate" in signals["signals"][0]["message"]
