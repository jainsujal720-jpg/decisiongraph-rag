from decisiongraph.generation.service import RelayGuardAnswerModels


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_relayguard_models_forward_tenant_identity_and_strict_schema(monkeypatch):
    captured = {}

    def fake_post(url, json, headers, timeout):
        captured.update(url=url, json=json, headers=headers, timeout=timeout)
        return FakeResponse({"answer": '{"claims": []}'})

    monkeypatch.setattr("decisiongraph.generation.service.httpx.post", fake_post)
    result = RelayGuardAnswerModels("http://gateway:8100", "gateway-key").draft(
        "Who owns the workstream?", "[E1] Priya owns it.", 3, "acme", "u-1"
    )

    assert result.claims == []
    assert captured["url"] == "http://gateway:8100/v1/chat/completions"
    assert captured["headers"] == {"X-API-Key": "gateway-key"}
    assert captured["json"]["tenant_id"] == "acme"
    assert captured["json"]["user_id"] == "u-1"
    assert captured["json"]["task_class"] == "moderate"
    assert captured["json"]["response_schema"]["name"] == "grounded_answer_draft"


def test_decisiongraph_records_gateway_models_per_call(monkeypatch):
    responses = iter([
        FakeResponse({"answer": '{"claims": []}', "served_model": "gpt-5.6-luna",
                      "usage": {"input_tokens": 200, "output_tokens": 40,
                                "token_cost_usd": 0.000088},
                      "routing": {"source": "rules", "jev_mode": "shadow",
                                  "jev_class": "moderate"}}),
        FakeResponse({"answer": '{"verdicts": []}', "served_model": "gpt-5.6-terra",
                      "usage": {"input_tokens": 300, "output_tokens": 30,
                                "token_cost_usd": 0.00096},
                      "routing": {"source": "jev", "jev_mode": "active",
                                  "jev_class": "involved"}}),
    ])

    monkeypatch.setattr("decisiongraph.generation.service.httpx.post",
                        lambda *args, **kwargs: next(responses))
    models = RelayGuardAnswerModels("http://gateway:8100")
    models.start_trace()
    models.draft("Owner?", "[E1] Priya", 3, "acme", "u-1")
    assert models.get_calls()[0]["model"] == "gpt-5.6-luna"
    from decisiongraph.generation.models import DraftResponse
    models.verify(DraftResponse(), "[E1] Priya", "acme", "u-1")
    assert [call["purpose"] for call in models.get_calls()] == ["draft", "verify"]
    assert models.get_calls()[1]["model"] == "gpt-5.6-terra"
    models.start_trace()
    assert models.get_calls() == ()


def test_decisiongraph_routes_analysis_and_long_context():
    classify = RelayGuardAnswerModels._classify_answer
    assert classify("Compare risks", "Evidence") == "complex"
    assert classify("Who owns this?", "Evidence" * 1500) == "long_context"
    assert classify("Analyze risks", "Evidence" * 1500) == "heavy"


def test_direct_causal_evidence_opt_in_selects_moderate():
    classify = RelayGuardAnswerModels._classify_answer
    context = "[E1] source=atlas_status.md\nThe launch was delayed because payment retry testing failed."
    assert classify("Why was the launch delayed?", context) == "complex"
    assert classify("Why was the launch delayed?", context, True) == "moderate"
    assert classify("Why was the launch delayed?", "[E1] The launch was delayed.", True) == "complex"
    assert classify("Analyze why the launch was delayed", context, True) == "complex"
    assert classify("Why was the launch delayed?", context * 100, True) == "heavy"


def test_direct_causal_evidence_can_be_second_relevant_block():
    classify = RelayGuardAnswerModels._classify_answer
    context = ("[E1] source=meridian_launch_plan.md\nMeridian will launch in October.\n\n"
               "[E2] source=orion_launch_plan.md\nThe Orion launch moved from 12 to 20 October "
               "because rollback rehearsals missed the recovery target.\n\n"
               "[E3] source=orion_operations.md\nThe Orion canary begins at 5%.")
    assert classify("Why was the Orion launch delayed?", context, True) == "moderate"
    assert classify("Why was the Atlas launch delayed?", context, True) == "complex"


def test_causal_evidence_after_three_blocks_matches_orion_only():
    classify = RelayGuardAnswerModels._classify_answer
    context = ("[E1] source=atlas_status.md\nThe Atlas launch was delayed because payment testing failed.\n\n"
               "[E2] source=orion_launch_plan.md\nThe Orion launch was scheduled for October.\n\n"
               "[E3] source=orion_operations.md\nNadia owns the Orion migration.\n\n"
               "[E4] source=orion_launch_plan.md\nThe Orion launch moved from 12 October 2026 "
               "to 20 October 2026 because rollback rehearsals had not met the required "
               "99.5% recovery target.")
    assert classify("Why was the Orion launch delayed?", context, True) == "moderate"
    assert classify("Analyze why the Orion launch was delayed", context, True) == "complex"
    assert classify("Why was the Meridian launch delayed?", context, True) == "complex"


def test_cause_and_topic_must_appear_in_same_evidence_sentence():
    context = ("[E1] source=orion_launch_plan.md\nOrion is launching soon. "
               "The Atlas launch was delayed because payment testing failed.")
    assert RelayGuardAnswerModels._classify_answer(
        "Why was the Orion launch delayed?", context, True
    ) == "complex"


def test_parent_chunk_blank_lines_do_not_hide_causal_sentence():
    context = ("[E1] source=atlas_status.md; section=Atlas Launch > Decision\n"
               "Section: Atlas Launch > Decision\n\nDecision\n\n"
               "The launch was delayed because payment retry testing failed.\n\n"
               "[E2] source=orion_launch_plan.md; section=Ownership and schedule\n"
               "Section: Orion Migration > Ownership and schedule\n\n"
               "Ownership and schedule\n\nNadia Iyer owns the Orion service migration. "
               "The Orion launch moved from 12 October 2026 to 20 October 2026 "
               "because rollback rehearsals had not met the required 99.5% recovery target.")
    classify = RelayGuardAnswerModels._classify_answer
    assert classify("Why was the Orion launch delayed?", context, True) == "moderate"
    assert classify("Why was the Meridian launch delayed?", context, True) == "complex"


def test_empty_optimized_draft_escalates_once_and_records_both_calls(monkeypatch):
    responses = iter([
        FakeResponse({"answer": '{"claims": []}', "served_model": "gpt-5.6-luna"}),
        FakeResponse({"answer": '{"claims": [{"text": "Payment testing failed.", '
                                '"citations": ["E1"]}]}', "served_model": "gpt-5.6-sol"}),
    ])
    task_classes = []

    def fake_post(_url, json, _headers=None, **kwargs):
        task_classes.append(json["task_class"])
        return next(responses)

    monkeypatch.setattr("decisiongraph.generation.service.httpx.post", fake_post)
    models = RelayGuardAnswerModels("http://gateway:8100", optimize_causal_drafts=True)
    result = models.draft("Why was the launch delayed?", "[E1] The launch was delayed "
                          "because payment testing failed.", 3, "acme", "u-1")
    assert result.claims[0].citations == ["E1"]
    assert task_classes == ["moderate", "complex"]
    assert [call["model"] for call in models.get_calls()] == ["gpt-5.6-luna", "gpt-5.6-sol"]
