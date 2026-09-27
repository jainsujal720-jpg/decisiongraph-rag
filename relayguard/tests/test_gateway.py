import pytest
from fastapi import HTTPException

from relayguard.core.models import ChatRequest
from relayguard.services.gateway import GatewayService


def test_simple_prompt_uses_economy_model() -> None:
    response = GatewayService().complete(
        ChatRequest(tenant_id="acme", user_id="sujal", prompt="Summarize note")
    )
    assert response.served_by == "relay-basic"


def test_complex_prompt_uses_premium_model() -> None:
    response = GatewayService().complete(
        ChatRequest(tenant_id="acme", user_id="sujal", prompt="Analyze legal contract")
    )
    assert response.served_by == "relay-mid-sol"


def test_primary_failure_uses_backup_model() -> None:
    response = GatewayService().complete(
        ChatRequest(
            tenant_id="acme",
            user_id="sujal",
            prompt="Summarize note",
            simulate_primary_failure=True,
        )
    )
    assert response.served_by == "relay-mid-luna"
    assert response.fallback_used is True


def test_metrics_are_tenant_scoped() -> None:
    gateway = GatewayService()
    gateway.complete(ChatRequest(tenant_id="acme", user_id="sujal", prompt="Summarize note"))
    gateway.complete(ChatRequest(tenant_id="other", user_id="alex", prompt="Summarize note"))
    assert gateway.metrics("acme")["requests"] == 1
    assert gateway.metrics("acme")["models_used"] == {"relay-basic": 1}


def test_budget_blocks_request_before_model_call() -> None:
    gateway = GatewayService(tenant_budget_usd=0.000003)
    gateway.complete(ChatRequest(tenant_id="acme", user_id="sujal", prompt="Summarize note"))
    with pytest.raises(HTTPException) as error:
        gateway.complete(ChatRequest(tenant_id="acme", user_id="sujal", prompt="Summarize note"))
    assert error.value.status_code == 429
    assert gateway.metrics("acme")["requests"] == 1


def test_circuit_breaker_bypasses_primary_after_repeated_failure() -> None:
    gateway = GatewayService()
    request = ChatRequest(
        tenant_id="acme",
        user_id="sujal",
        prompt="Summarize note",
        simulate_primary_failure=True,
    )
    gateway.complete(request)
    gateway.complete(request)
    response = gateway.complete(
        ChatRequest(tenant_id="acme", user_id="sujal", prompt="Summarize note")
    )
    assert response.served_by == "relay-mid-luna"
    assert response.governance.circuit_open is True


@pytest.mark.parametrize(
    ("task", "primary", "fallback"),
    [
        ("simple", "relay-basic", "relay-mid-luna"),
        ("moderate", "relay-mid-luna", "relay-backup"),
        ("involved", "relay-mid-terra", "relay-mid-luna"),
        ("complex", "relay-mid-sol", "relay-mid-terra"),
        ("heavy", "relay-pro", "relay-mid-sol"),
        ("long_context", "relay-mini", "relay-mid-terra"),
    ],
)
def test_all_workload_routes_have_distinct_fallbacks(task, primary, fallback):
    route = GatewayService()._route(
        ChatRequest(tenant_id="acme", user_id="sujal", prompt="Sample", task_class=task)
    )
    assert route.primary_model == primary
    assert route.fallback_model == fallback
    assert primary != fallback
