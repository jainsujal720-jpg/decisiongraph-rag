from types import SimpleNamespace

from relayguard.services.providers import OpenAIProvider


def test_gpt6_route_keeps_structured_output_without_temperature():
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"claims":[]}'))]
        )

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    assert provider.complete("relay-pro", "Question", "Cite sources", {"name": "draft"}) == '{"claims":[]}'
    assert requests[-1]["model"] == "gpt-6-sol"
    assert requests[-1]["reasoning_effort"] == "low"
    assert "temperature" not in requests[-1]
    assert requests[-1]["response_format"]["json_schema"]["name"] == "draft"

    provider.complete("relay-mini", "Question")
    assert requests[-1]["model"] == "gpt-6-luna"

    for alias, model in (
        ("relay-mid-luna", "gpt-5.6-luna"),
        ("relay-mid-terra", "gpt-5.6-terra"),
        ("relay-mid-sol", "gpt-5.6-sol"),
    ):
        provider.complete(alias, "Question")
        assert requests[-1]["model"] == model
        assert requests[-1]["reasoning_effort"] == "low"
        assert "temperature" not in requests[-1]

    provider.complete("relay-backup", "Question")
    assert requests[-1]["model"] == "gpt-4.1-mini"
    assert requests[-1]["temperature"] == 0
    assert "reasoning_effort" not in requests[-1]
