from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


class ProviderUnavailable(Exception):
    """The upstream model provider could not safely complete a request."""


@dataclass(frozen=True)
class ProviderResult:
    answer: str
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None


class CompletionProvider(Protocol):
    def complete(
        self,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
    ) -> str: ...


class MockProvider:
    """Local predictable responses: useful for demos and automated tests."""

    def complete(
        self,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        return f"[{model}] Processed safely: {prompt.strip()}"


class OpenAIProvider:
    """Optional production adapter. The API key always remains server-side."""

    model_aliases = {
        "relay-basic": "gpt-4.1-mini",
        "relay-mid-luna": "gpt-5.6-luna",
        "relay-mid-terra": "gpt-5.6-terra",
        "relay-mid-sol": "gpt-5.6-sol",
        "relay-mini": "gpt-6-luna",
        "relay-pro": "gpt-6-sol",
        "relay-backup": "gpt-4.1-mini",
    }

    def __init__(self, api_key: str, timeout_seconds: float = 60.0) -> None:
        self.client = OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=0)

    def complete(
        self,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        return self.complete_with_usage(model, prompt, system_prompt, response_schema).answer

    def complete_with_usage(
        self,
        model: str,
        prompt: str,
        system_prompt: str | None = None,
        response_schema: dict | None = None,
    ) -> ProviderResult:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            actual_model = self.model_aliases[model]
            kwargs = {"model": actual_model, "messages": messages}
            if actual_model.startswith(("gpt-5.6-", "gpt-6-")):
                kwargs["reasoning_effort"] = "low"
            else:
                kwargs["temperature"] = 0
            if response_schema:
                kwargs["response_format"] = {"type": "json_schema", "json_schema": response_schema}
            response = self.client.chat.completions.create(**kwargs)
            usage = getattr(response, "usage", None)
            prompt_details = getattr(usage, "prompt_tokens_details", None)
            return ProviderResult(
                answer=response.choices[0].message.content or "",
                input_tokens=getattr(usage, "prompt_tokens", None),
                cached_input_tokens=getattr(prompt_details, "cached_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
            )
        except Exception as error:
            raise ProviderUnavailable("The configured provider did not respond safely.") from error
