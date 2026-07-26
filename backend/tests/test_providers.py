"""Provider adapters, against mocked HTTP endpoints.

These are the protocol details that break silently in production — SSE framing,
JSON-mode flags, Anthropic's prefill trick — so they get exercised without a
network.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel

from deckforge.config import Settings
from deckforge.core.errors import ProviderError, ProviderNotConfiguredError
from deckforge.providers.anthropic import AnthropicProvider
from deckforge.providers.base import ChatMessage, GenerationOptions, ProviderConfiguration
from deckforge.providers.gemini import GeminiProvider
from deckforge.providers.ollama import OllamaProvider
from deckforge.providers.openai_compatible import AzureOpenAIProvider, OpenAICompatibleProvider
from deckforge.providers.registry import PROVIDERS, ProviderFactory


class Answer(BaseModel):
    answer: str
    score: int = 0


def bind(provider, handler) -> None:
    """Give a provider a mocked transport."""
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=provider.default_headers()
    )


def sse(chunks: list[str]) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


# --------------------------------------------------------------------------- #
# OpenAI-compatible
# --------------------------------------------------------------------------- #


@pytest.fixture
def openai_provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        ProviderConfiguration(
            name="openai", base_url="https://api.test/v1", api_key="sk-x", default_model="gpt-test"
        )
    )


async def test_openai_streaming(openai_provider) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert json.loads(request.content)["stream"] is True
        assert request.headers["authorization"] == "Bearer sk-x"
        return httpx.Response(
            200,
            text=sse(
                [
                    json.dumps({"choices": [{"delta": {"content": "Hello"}}]}),
                    json.dumps({"choices": [{"delta": {"content": " world"}}]}),
                    "[DONE]",
                ]
            ),
        )

    bind(openai_provider, handler)
    chunks = [c async for c in openai_provider.stream([ChatMessage(role="user", content="hi")])]
    assert "".join(chunks) == "Hello world"


async def test_openai_completion_reports_usage(openai_provider) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-test",
                "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3},
            },
        )

    bind(openai_provider, handler)
    completion = await openai_provider.complete([ChatMessage(role="user", content="hi")])
    assert completion.text == "hi"
    assert completion.usage.total_tokens == 14


async def test_json_mode_sets_response_format(openai_provider) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer":"yes"}'}}]})

    bind(openai_provider, handler)
    result = await openai_provider.structured(
        [ChatMessage(role="user", content="q")], Answer, GenerationOptions()
    )
    assert result.answer == "yes"
    assert seen["response_format"] == {"type": "json_object"}


async def test_structured_retries_then_succeeds(openai_provider) -> None:
    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        body = "not json" if attempts["n"] == 1 else '{"answer":"recovered","score":3}'
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    bind(openai_provider, handler)
    result = await openai_provider.structured([ChatMessage(role="user", content="q")], Answer)
    assert result.answer == "recovered"
    assert attempts["n"] == 2


async def test_structured_gives_up_with_a_clear_error(openai_provider) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "nope"}}]})

    bind(openai_provider, handler)
    with pytest.raises(ProviderError, match="Answer"):
        await openai_provider.structured([ChatMessage(role="user", content="q")], Answer, retries=1)


async def test_http_errors_become_provider_errors(openai_provider) -> None:
    bind(openai_provider, lambda _r: httpx.Response(429, text="slow down"))
    with pytest.raises(ProviderError, match="429"):
        await openai_provider.complete([ChatMessage(role="user", content="hi")])


async def test_azure_builds_a_deployment_url() -> None:
    provider = AzureOpenAIProvider(
        ProviderConfiguration(
            name="azure",
            base_url="https://acme.openai.azure.com",
            api_key="k",
            default_model="my-deployment",
            options={"api_version": "2024-10-21"},
        )
    )
    assert "deployments/my-deployment/chat/completions" in provider.chat_url()
    assert "api-version=2024-10-21" in provider.chat_url()
    assert provider.default_headers()["api-key"] == "k"


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #


async def test_ollama_streams_ndjson() -> None:
    provider = OllamaProvider(
        ProviderConfiguration(
            name="ollama", base_url="http://localhost:11434", default_model="qwen3:8b"
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["format"] == "json"
        assert payload["options"]["temperature"] == 0.2
        return httpx.Response(
            200,
            text="\n".join(
                [
                    json.dumps({"message": {"content": "part "}}),
                    json.dumps({"message": {"content": "two"}, "done": True}),
                ]
            ),
        )

    bind(provider, handler)
    options = GenerationOptions(temperature=0.2, json_mode=True)
    chunks = [c async for c in provider.stream([ChatMessage(role="user", content="hi")], options)]
    assert "".join(chunks) == "part two"


async def test_ollama_surfaces_errors() -> None:
    provider = OllamaProvider(
        ProviderConfiguration(name="ollama", base_url="http://localhost:11434", default_model="m")
    )
    bind(provider, lambda _r: httpx.Response(200, json={"error": "model not found"}))
    with pytest.raises(ProviderError, match="model not found"):
        await provider.complete([ChatMessage(role="user", content="hi")])


async def test_ollama_lists_models() -> None:
    provider = OllamaProvider(
        ProviderConfiguration(name="ollama", base_url="http://localhost:11434", default_model="m")
    )
    bind(provider, lambda _r: httpx.Response(200, json={"models": [{"name": "b"}, {"name": "a"}]}))
    assert await provider.list_models() == ["a", "b"]


# --------------------------------------------------------------------------- #
# Anthropic and Gemini
# --------------------------------------------------------------------------- #


async def test_anthropic_prefills_json_mode() -> None:
    provider = AnthropicProvider(
        ProviderConfiguration(name="anthropic", api_key="k", default_model="claude-test")
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "claude-test",
                "content": [{"type": "text", "text": '"answer":"prefilled"}'}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    bind(provider, handler)
    result = await provider.structured(
        [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="q")], Answer
    )
    assert result.answer == "prefilled"
    assert seen["system"] == "sys"
    assert seen["messages"][-1] == {"role": "assistant", "content": "{"}


async def test_gemini_maps_roles_and_system_instruction() -> None:
    provider = GeminiProvider(
        ProviderConfiguration(name="gemini", api_key="k", default_model="gemini-test")
    )
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        assert "key=k" in str(request.url)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    bind(provider, handler)
    completion = await provider.complete(
        [
            ChatMessage(role="system", content="be brief"),
            ChatMessage(role="assistant", content="prior"),
            ChatMessage(role="user", content="q"),
        ]
    )
    assert completion.text == "ok"
    assert seen["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert [c["role"] for c in seen["contents"]] == ["model", "user"]


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def test_every_documented_provider_is_registered() -> None:
    expected = {
        "ollama",
        "lmstudio",
        "llamacpp",
        "vllm",
        "openai",
        "anthropic",
        "openrouter",
        "gemini",
        "groq",
        "together",
        "deepseek",
        "mistral",
        "azure",
    }
    assert expected <= set(PROVIDERS.names())


def test_factory_caches_instances() -> None:
    factory = ProviderFactory(Settings(ollama_base_url="http://localhost:11434"))
    assert factory.get("ollama", "qwen3:8b") is factory.get("ollama", "qwen3:8b")
    assert factory.get("ollama", "qwen3:8b") is not factory.get("ollama", "llama3.1:8b")


def test_factory_reports_missing_credentials() -> None:
    factory = ProviderFactory(Settings(openai_api_key=None))
    with pytest.raises(ProviderNotConfiguredError, match="not configured"):
        factory.get("openai")


def test_factory_applies_overrides() -> None:
    factory = ProviderFactory(Settings(openai_api_key=None))
    factory.apply_override(
        ProviderConfiguration(name="openai", api_key="sk-from-db", default_model="gpt-4o")
    )
    provider = factory.get("openai")
    assert provider.is_configured
    assert provider.config.api_key == "sk-from-db"


def test_describe_flags_local_providers_as_ready() -> None:
    described = {p["name"]: p for p in ProviderFactory(Settings()).describe()}
    assert described["ollama"]["configured"] is True
    assert described["ollama"]["kind"] == "local"
    assert described["openai"]["kind"] == "cloud"
