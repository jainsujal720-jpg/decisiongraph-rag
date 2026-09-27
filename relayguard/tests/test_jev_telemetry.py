import io
import json
from types import SimpleNamespace
from unittest.mock import patch

from relayguard.core.models import ChatRequest, TaskClass
from relayguard.services.gateway import GatewayService
from relayguard.services.jev import JevDecision, JevRouter
from relayguard.services.pricing import usage_cost
from relayguard.services.providers import ProviderResult


class DecisionRouter:
    def __init__(self, task, confidence=0.95):
        self.task, self.confidence = task, confidence

    def decide(self, _prompt):
        return JevDecision(self.task, self.confidence, 0.95, 100, "jev-1.13.0")


class TrackedProvider:
    model_aliases = {"relay-mid-luna": "gpt-5.6-luna", "relay-mid-terra": "gpt-5.6-terra"}

    def complete_with_usage(self, model, prompt, system_prompt=None, response_schema=None):
        return ProviderResult("answer", 1000, 100, 200)


def test_jev_wire_contract_and_probability_decision():
    response = {"model": "jev-1.13.0", "answers": {"workload": {
        "type": "choice", "choice": "moderate", "confidence": 0.9,
        "probabilities": {"moderate": 0.95}}}, "usage": {"input_tokens": 123}}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_open(request, timeout):
        assert request.full_url == "https://api.typesafe.ai/v1/systemone"
        assert request.get_header("Authorization") == "Bearer secret"
        assert json.loads(request.data)["questions"]["workload"]["type"] == "choice"
        return FakeResponse(json.dumps(response).encode())

    with patch("relayguard.services.jev.urlopen", fake_open):
        decision = JevRouter("secret").decide("Find owner")
    assert decision.task_class == TaskClass.MODERATE
    assert decision.input_tokens == 123


def test_low_confidence_or_caller_floor_uses_rules():
    request = ChatRequest(tenant_id="acme", user_id="sujal", prompt="Question",
                          task_class=TaskClass.INVOLVED)
    gateway = GatewayService(jev_router=DecisionRouter(TaskClass.SIMPLE), jev_mode="active")
    assert gateway._choose_route(request)[1].source == "rules"
    gateway = GatewayService(jev_router=DecisionRouter(TaskClass.HEAVY, 0.2),
                             jev_mode="active")
    assert gateway._choose_route(request)[1].source == "rules"


def test_shadow_never_changes_route_and_active_can_upgrade():
    request = ChatRequest(tenant_id="acme", user_id="sujal", prompt="Question",
                          task_class=TaskClass.MODERATE)
    shadow = GatewayService(jev_router=DecisionRouter(TaskClass.INVOLVED), jev_mode="shadow")
    route, trace = shadow._choose_route(request)
    assert route.task_class == TaskClass.MODERATE
    assert trace.jev_class == "involved" and trace.source == "rules"
    active = GatewayService(jev_router=DecisionRouter(TaskClass.INVOLVED), jev_mode="active")
    route, trace = active._choose_route(request)
    assert route.task_class == TaskClass.INVOLVED and trace.source == "jev"


def test_actual_tokens_recorded_separately_from_legacy_budget():
    gateway = GatewayService(provider=TrackedProvider(),
                             jev_router=DecisionRouter(TaskClass.MODERATE), jev_mode="active")
    response = gateway.complete(ChatRequest(tenant_id="acme", user_id="sujal", prompt="Question",
                                            task_class=TaskClass.MODERATE))
    assert response.served_model == "gpt-5.6-luna"
    assert response.usage.input_tokens == 1000
    assert response.usage.cached_input_tokens == 100
    expected = usage_cost("gpt-5.6-luna", 1000, 100, 200)
    assert response.usage.token_cost_usd == expected
    assert gateway.metrics("acme")["token_cost_usd"] == expected
    assert gateway.audit_integrity("acme")["verified"] is True


def test_missing_provider_usage_is_not_fabricated():
    response = GatewayService().complete(ChatRequest(tenant_id="acme", user_id="sujal",
                                                      prompt="Question"))
    assert response.usage.token_cost_usd is None


def test_failed_jev_falls_back_to_rules():
    router = SimpleNamespace(decide=lambda prompt: (_ for _ in ()).throw(RuntimeError("offline")))
    gateway = GatewayService(jev_router=router, jev_mode="active")
    route, trace = gateway._choose_route(ChatRequest(tenant_id="acme", user_id="sujal",
                                                        prompt="Question"))
    assert route.task_class == TaskClass.SIMPLE
    assert trace.source == "rules"
