"""Saved LLM connections: CRUD, switching, probing and resolution."""

from __future__ import annotations

import httpx
import pytest

from deckforge.core.errors import ConflictError, NotFoundError, ValidationError
from deckforge.database.repositories import UnitOfWork
from deckforge.models.llm import LlmProbeRequest, LlmProfileCreate, LlmProfileUpdate, mask_secret
from deckforge.services.llm_service import UNCHANGED_KEY, LlmService


@pytest.fixture
async def service(container):
    """An LlmService starting from an empty connection list.

    Container startup seeds one connection from the environment (see
    ``test_startup_seeds_a_connection_from_env``); these tests exercise the CRUD
    surface itself, so they begin from a clean slate.
    """
    async with container.database.session() as session:
        instance = LlmService(UnitOfWork.create(session), container.settings, container.providers)
        for existing in await instance.uow.llm_profiles.all_profiles():
            await instance.uow.llm_profiles.delete(existing.id)
        await instance.uow.flush()
        yield instance


async def clear_connections(client) -> None:
    """Remove every saved connection over HTTP."""
    for connection in (await client.get("/api/v1/llm/connections")).json():
        await client.delete(f"/api/v1/llm/connections/{connection['id']}")


async def test_startup_seeds_a_connection_from_env(container) -> None:
    """A key already in .env should not have to be retyped on first launch."""
    async with container.database.session() as session:
        service = LlmService(UnitOfWork.create(session), container.settings, container.providers)
        profiles = await service.list_all()
    assert len(profiles) == 1
    assert profiles[0].is_active
    assert profiles[0].provider == container.settings.default_provider


def make(name: str, **kwargs) -> LlmProfileCreate:
    payload = {
        "name": name,
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen3:8b",
    }
    payload.update(kwargs)
    return LlmProfileCreate(**payload)


# --------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------- #


def test_keys_are_masked_not_returned() -> None:
    assert mask_secret("sk-abcdef123456") == "sk-…123456"
    assert mask_secret("short") == "•••••"
    assert mask_secret(None) is None
    assert "abcdef" not in (mask_secret("sk-abcdefXYZ789") or "")


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


async def test_first_connection_becomes_active(service: LlmService) -> None:
    profile = await service.create(make("Local Qwen", activate=False))
    assert profile.is_active, "with nothing else configured, the first must be selected"


async def test_multiple_connections_one_active(service: LlmService) -> None:
    a = await service.create(make("Local Qwen"))
    b = await service.create(
        make("DeepSeek", provider="deepseek", api_key="sk-x", model="deepseek-chat")
    )

    assert (await service.active()).id == b.id
    listed = await service.list_all()
    assert [p.is_active for p in listed] == [False, True]

    await service.activate(a.id)
    assert (await service.active()).id == a.id
    assert sum(p.is_active for p in await service.list_all()) == 1


async def test_same_provider_twice_with_different_endpoints(service: LlmService) -> None:
    """Two OpenAI-compatible endpoints must be able to coexist."""
    await service.create(
        make("Work", provider="openai", base_url="https://work.example/v1", api_key="sk-work")
    )
    await service.create(
        make("Personal", provider="openai", base_url="https://api.openai.com/v1", api_key="sk-me")
    )
    listed = await service.list_all()
    assert [p.base_url for p in listed] == ["https://work.example/v1", "https://api.openai.com/v1"]


async def test_duplicate_label_is_rejected(service: LlmService) -> None:
    await service.create(make("Local"))
    with pytest.raises(ConflictError, match="already exists"):
        await service.create(make("Local"))


async def test_unknown_provider_is_rejected(service: LlmService) -> None:
    with pytest.raises(NotFoundError, match="unknown provider"):
        await service.create(make("Nope", provider="not-a-provider"))


async def test_cloud_provider_requires_a_key(service: LlmService) -> None:
    with pytest.raises(ValidationError, match="API key"):
        await service.create(make("Keyless", provider="openai", api_key=None))


async def test_editing_without_a_key_keeps_the_stored_one(service: LlmService) -> None:
    """The UI never receives the key, so a plain save must not wipe it."""
    profile = await service.create(
        make("DeepSeek", provider="deepseek", api_key="sk-secret", model="deepseek-chat")
    )
    await service.update(profile.id, LlmProfileUpdate(model="deepseek-reasoner"))
    assert (await service.get(profile.id)).api_key == "sk-secret"

    await service.update(profile.id, LlmProfileUpdate(api_key=UNCHANGED_KEY))
    assert (await service.get(profile.id)).api_key == "sk-secret"

    await service.update(profile.id, LlmProfileUpdate(api_key="sk-rotated"))
    assert (await service.get(profile.id)).api_key == "sk-rotated"

    await service.update(profile.id, LlmProfileUpdate(api_key=""))
    assert (await service.get(profile.id)).api_key is None


async def test_deleting_the_active_connection_promotes_another(service: LlmService) -> None:
    first = await service.create(make("First"))
    second = await service.create(make("Second"))
    assert second.is_active

    await service.delete(second.id)
    remaining = await service.list_all()
    assert len(remaining) == 1
    assert remaining[0].id == first.id
    assert remaining[0].is_active, "something must stay selected"


async def test_deleting_the_last_connection_leaves_none(service: LlmService) -> None:
    only = await service.create(make("Only"))
    await service.delete(only.id)
    assert await service.list_all() == []
    assert await service.active() is None


# --------------------------------------------------------------------------- #
# Templates and probing
# --------------------------------------------------------------------------- #


def test_templates_prefill_the_form(service: LlmService) -> None:
    templates = {t.name: t for t in service.templates()}
    assert {"ollama", "openai", "deepseek", "anthropic"} <= set(templates)

    ollama = templates["ollama"]
    assert ollama.kind == "local"
    assert ollama.requires_api_key is False
    assert ollama.default_base_url and ollama.default_base_url.startswith("http")

    openai = templates["openai"]
    assert openai.requires_api_key is True
    assert openai.suggested_models


async def test_probe_reports_models_on_success(service: LlmService, monkeypatch) -> None:
    async def fake_list_models(self) -> list[str]:
        return ["qwen3:8b", "llama3.1:8b"]

    monkeypatch.setattr("deckforge.providers.ollama.OllamaProvider.list_models", fake_list_models)
    result = await service.probe(
        LlmProbeRequest(provider="ollama", base_url="http://localhost:11434", model="qwen3:8b")
    )
    assert result.ok
    assert result.models == ["qwen3:8b", "llama3.1:8b"]
    assert result.model_available is True
    assert result.latency_ms is not None


async def test_probe_warns_about_a_missing_model(service: LlmService, monkeypatch) -> None:
    async def fake_list_models(self) -> list[str]:
        return ["llama3.1:8b"]

    monkeypatch.setattr("deckforge.providers.ollama.OllamaProvider.list_models", fake_list_models)
    result = await service.probe(
        LlmProbeRequest(provider="ollama", base_url="http://localhost:11434", model="qwen3:8b")
    )
    assert result.ok and result.model_available is False
    assert "not in the model list" in (result.hint or "")


async def test_probe_explains_an_unreachable_local_server(service: LlmService, monkeypatch) -> None:
    async def boom(self) -> list[str]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("deckforge.providers.ollama.OllamaProvider.list_models", boom)
    result = await service.probe(
        LlmProbeRequest(provider="ollama", base_url="http://localhost:11434")
    )
    assert not result.ok
    assert "refused" in (result.error or "")
    assert "local server running" in (result.hint or "")


async def test_probe_reuses_the_stored_key(service: LlmService, monkeypatch) -> None:
    """Testing a saved connection must not require re-sending the key."""
    seen: dict[str, str | None] = {}

    async def capture(self) -> list[str]:
        seen["key"] = self.config.api_key
        return ["deepseek-chat"]

    monkeypatch.setattr(
        "deckforge.providers.openai_compatible.OpenAICompatibleProvider.list_models", capture
    )
    profile = await service.create(
        make("DeepSeek", provider="deepseek", api_key="sk-stored", model="deepseek-chat")
    )
    result = await service.probe(LlmProbeRequest(profile_id=profile.id))
    assert result.ok
    assert seen["key"] == "sk-stored"


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #


async def test_resolution_uses_the_active_connection(service: LlmService) -> None:
    await service.create(make("Local Qwen"))
    active = await service.create(
        make("DeepSeek", provider="deepseek", api_key="sk-live", model="deepseek-chat")
    )

    provider, profile, defaults = await service.resolve()
    assert profile is not None and profile.id == active.id
    assert provider.name == "deepseek"
    assert provider.config.api_key == "sk-live"
    assert provider.config.default_model == "deepseek-chat"
    assert defaults == {"temperature": None, "max_tokens": None}


async def test_resolution_honours_sampling_defaults(service: LlmService) -> None:
    await service.create(make("Tuned", temperature=0.15, max_tokens=2048))
    _, _, defaults = await service.resolve()
    assert defaults == {"temperature": 0.15, "max_tokens": 2048}


async def test_conversation_override_beats_the_active_connection(service: LlmService) -> None:
    await service.create(make("Local Qwen"))
    provider, profile, _ = await service.resolve({"provider": "lmstudio", "model": "custom"})
    assert provider.name == "lmstudio"
    assert profile is None, "an override sidesteps the saved connection"


async def test_resolution_falls_back_to_the_environment(service: LlmService) -> None:
    """With no saved connection the .env provider still works (server mode)."""
    assert await service.active() is None
    provider, profile, _ = await service.resolve()
    assert profile is None
    assert provider.name == service.settings.default_provider


async def test_bootstrap_creates_one_connection_from_env(service: LlmService) -> None:
    created = await service.bootstrap_from_env()
    assert created is not None
    assert created.is_active
    assert created.provider == service.settings.default_provider
    assert "from .env" in created.name

    # Idempotent: a second call must not duplicate it.
    assert await service.bootstrap_from_env() is None


async def test_bootstrap_skips_unconfigured_providers(service: LlmService) -> None:
    service.settings.default_provider = "openai"  # no key in the test settings
    assert await service.bootstrap_from_env() is None


async def test_bootstrap_skips_an_unreachable_local_server(
    service: LlmService, monkeypatch
) -> None:
    """Every machine has a plausible Ollama URL; only a live one counts.

    Seeding a dead connection would hide the "connect a model" prompt and make
    a fresh install look broken rather than unconfigured.
    """

    async def unreachable(self) -> list[str]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("deckforge.providers.ollama.OllamaProvider.list_models", unreachable)
    service.settings.default_provider = "ollama"
    assert await service.bootstrap_from_env() is None
    assert await service.list_all() == []


async def test_bootstrap_adopts_a_live_local_server(service: LlmService, monkeypatch) -> None:
    async def reachable(self) -> list[str]:
        return ["qwen3:8b"]

    monkeypatch.setattr("deckforge.providers.ollama.OllamaProvider.list_models", reachable)
    service.settings.default_provider = "ollama"
    created = await service.bootstrap_from_env()
    assert created is not None and created.provider == "ollama"


# --------------------------------------------------------------------------- #
# HTTP surface
# --------------------------------------------------------------------------- #


async def test_connection_api_round_trip(client) -> None:
    await clear_connections(client)
    templates = (await client.get("/api/v1/llm/providers")).json()
    assert any(t["name"] == "ollama" and t["kind"] == "local" for t in templates)

    created = (
        await client.post(
            "/api/v1/llm/connections",
            json={
                "name": "My DeepSeek",
                "provider": "deepseek",
                "api_key": "sk-abcdef123456",
                "model": "deepseek-chat",
            },
        )
    ).json()
    assert created["is_active"] is True
    assert created["has_api_key"] is True
    assert created["api_key_hint"] == "sk-…123456"
    assert "api_key" not in created, "the raw key must never leave the server"

    second = (
        await client.post(
            "/api/v1/llm/connections",
            json={"name": "Local", "provider": "ollama", "model": "qwen3:8b", "activate": False},
        )
    ).json()
    assert second["is_active"] is False

    switched = (await client.post(f"/api/v1/llm/connections/{second['id']}/activate")).json()
    assert switched["is_active"] is True

    listed = (await client.get("/api/v1/llm/connections")).json()
    assert sum(c["is_active"] for c in listed) == 1

    edited = (
        await client.patch(
            f"/api/v1/llm/connections/{created['id']}", json={"model": "deepseek-reasoner"}
        )
    ).json()
    assert edited["model"] == "deepseek-reasoner"
    assert edited["has_api_key"] is True, "editing without a key must not clear it"

    assert (await client.delete(f"/api/v1/llm/connections/{created['id']}")).status_code == 204
    assert len((await client.get("/api/v1/llm/connections")).json()) == 1


async def test_connection_api_rejects_duplicates(client) -> None:
    await clear_connections(client)
    body = {"name": "Dup", "provider": "ollama", "model": "qwen3:8b"}
    assert (await client.post("/api/v1/llm/connections", json=body)).status_code == 201
    conflict = await client.post("/api/v1/llm/connections", json=body)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "conflict"
