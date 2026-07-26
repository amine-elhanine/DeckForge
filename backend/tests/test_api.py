"""HTTP API, end to end, against the scripted provider."""

from __future__ import annotations

import json

import pytest

SOURCE_DOC = b"""# Internal pilot notes

The pilot reduced average handling time by 23% over eight weeks.
The reward model was trained on 4,200 ranked preference pairs.
"""


async def sse_events(client, url: str, payload: dict) -> list[tuple[str, dict]]:
    """Collect (event, data) pairs from an SSE response."""
    events: list[tuple[str, dict]] = []
    async with client.stream("POST", url, json=payload, timeout=60.0) as response:
        assert response.status_code == 200
        name = ""
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                raw = line.split(":", 1)[1].strip()
                try:
                    events.append((name, json.loads(raw) if raw else {}))
                except json.JSONDecodeError:
                    events.append((name, {}))
    return events


async def test_health(client) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["themes"] >= 20 and body["layouts"] >= 30


async def test_capabilities_lists_every_registry(client) -> None:
    body = (await client.get("/api/v1/capabilities")).json()
    assert len(body["themes"]) >= 20
    assert len(body["layouts"]) >= 30
    assert {e["name"] for e in body["exporters"]} >= {"pptx", "pdf", "html", "markdown"}
    assert "pdf" in body["uploads"]
    assert body["plugin_errors"] == []


async def test_conversation_crud(client) -> None:
    created = (await client.post("/api/v1/conversations", json={"title": "Test"})).json()
    assert created["title"] == "Test"

    listed = (await client.get("/api/v1/conversations")).json()
    assert any(c["id"] == created["id"] for c in listed)

    patched = (
        await client.patch(f"/api/v1/conversations/{created['id']}", json={"title": "Renamed"})
    ).json()
    assert patched["title"] == "Renamed"

    assert (await client.delete(f"/api/v1/conversations/{created['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/conversations/{created['id']}")).status_code == 404


async def test_unknown_conversation_returns_a_domain_error(client) -> None:
    response = await client.get("/api/v1/conversations/conv_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_upload_indexes_a_document(client) -> None:
    conv = (await client.post("/api/v1/conversations", json={})).json()
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/uploads",
        files={"files": ("notes.md", SOURCE_DOC, "text/markdown")},
    )
    assert response.status_code == 201
    asset = response.json()[0]
    assert asset["indexed"] is True
    assert "23%" in asset["excerpt"]

    assets = (await client.get(f"/api/v1/conversations/{conv['id']}/assets")).json()
    assert len(assets) == 1


async def test_upload_rejects_unknown_types(client) -> None:
    conv = (await client.post("/api/v1/conversations", json={})).json()
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/uploads",
        files={"files": ("evil.exe", b"\x00\x01", "application/octet-stream")},
    )
    assert response.status_code == 422


async def test_full_conversation_flow(client) -> None:
    """Create a deck, edit it, export it — the whole product loop over HTTP."""
    conv = (await client.post("/api/v1/conversations", json={})).json()

    events = await sse_events(
        client,
        f"/api/v1/conversations/{conv['id']}/messages",
        {"content": "Create a presentation about reinforcement learning"},
    )
    names = [name for name, _ in events]
    assert "status" in names and "deck" in names and "message" in names
    assert names[-1] == "done"
    assert "error" not in names

    message = next(data for name, data in events if name == "message")
    assert message["role"] == "assistant"
    assert message["presentation_id"]
    presentation_id = message["presentation_id"]

    # The conversation was auto-titled from the first message.
    conversation = (await client.get(f"/api/v1/conversations/{conv['id']}")).json()
    assert conversation["title"] != "New conversation"
    assert conversation["latest_presentation_id"] == presentation_id

    presentation = (await client.get(f"/api/v1/presentations/{presentation_id}")).json()
    assert presentation["slide_count"] == 6
    assert presentation["version"] == 1
    assert len(presentation["versions"]) == 1
    deck = presentation["deck"]
    assert deck["slides"][0]["kind"] == "cover"

    # Reorder through the operation API — the same language the agent emits.
    seventh_free = deck["slides"][4]["id"]
    updated = (
        await client.post(
            f"/api/v1/presentations/{presentation_id}/operations",
            json={
                "summary": "Move a slide",
                "operations": [{"op": "move_slide", "slide_id": seventh_free, "to_index": 1}],
            },
        )
    ).json()
    assert updated["deck"]["slides"][1]["id"] == seventh_free
    assert updated["version"] == 2

    # Undo restores the previous ordering as a new version.
    undone = (await client.post(f"/api/v1/presentations/{presentation_id}/undo")).json()
    assert undone["deck"]["slides"][1]["id"] != seventh_free
    assert undone["version"] == 3

    # Compare two versions.
    diff = (
        await client.get(
            f"/api/v1/presentations/{presentation_id}/compare", params={"left": 1, "right": 2}
        )
    ).json()
    assert diff["moved"] or diff["changed"]

    # Preview renders server-side.
    preview = await client.get(f"/api/v1/presentations/{presentation_id}/preview")
    assert preview.status_code == 200
    assert preview.text.count('class="df-stage"') == 6

    # Client-side rendering payload.
    payload = (await client.get(f"/api/v1/presentations/{presentation_id}/stylesheet")).json()
    assert payload["css"].startswith("\n:root")
    assert len(payload["slides"]) == 6

    # Export every format.
    for fmt in ("pptx", "pdf", "html", "markdown", "revealjs", "marp"):
        export = (
            await client.post(
                f"/api/v1/presentations/{presentation_id}/exports", json={"format": fmt}
            )
        ).json()
        assert export["size_bytes"] > 500
        download = await client.get(export["download_url"])
        assert download.status_code == 200
        assert len(download.content) == export["size_bytes"]

    history = (await client.get(f"/api/v1/presentations/{presentation_id}/exports")).json()
    assert len(history) == 6

    # Fork branches the deck.
    forked = (await client.post(f"/api/v1/presentations/{presentation_id}/fork")).json()
    assert forked["id"] != presentation_id
    assert forked["title"].endswith("(copy)")


async def test_export_intent_produces_artifacts(client) -> None:
    conv = (await client.post("/api/v1/conversations", json={})).json()
    await sse_events(
        client, f"/api/v1/conversations/{conv['id']}/messages", {"content": "Deck about RL"}
    )
    events = await sse_events(
        client,
        f"/api/v1/conversations/{conv['id']}/messages",
        {"content": "download it as pptx"},
    )
    artifacts = [data for name, data in events if name == "artifact"]
    assert artifacts and artifacts[0]["format"] == "pptx"
    assert artifacts[0]["download_url"]


async def test_sync_endpoint(client) -> None:
    conv = (await client.post("/api/v1/conversations", json={})).json()
    body = (
        await client.post(
            f"/api/v1/conversations/{conv['id']}/messages/sync",
            json={"content": "Deck about RL"},
            timeout=60.0,
        )
    ).json()
    assert body["deck"]["slides"]
    assert body["message"]["role"] == "assistant"


async def test_message_history_is_persisted(client) -> None:
    conv = (await client.post("/api/v1/conversations", json={})).json()
    await sse_events(
        client, f"/api/v1/conversations/{conv['id']}/messages", {"content": "Deck about RL"}
    )
    messages = (await client.get(f"/api/v1/conversations/{conv['id']}/messages")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["metadata"]["intent"] == "create"


async def test_provider_catalog_is_exposed(client) -> None:
    providers = (await client.get("/api/v1/providers")).json()
    assert {p["name"] for p in providers} >= {"ollama", "openai", "anthropic", "gemini"}


async def test_custom_theme_becomes_usable(client) -> None:
    definition = {
        "name": "acme",
        "extends": "minimal",
        "label": "Acme",
        "palette": {"primary": "#e2231a"},
    }
    assert (await client.post("/api/v1/themes", json=definition)).json()["saved"] is True

    themes = (await client.get("/api/v1/themes")).json()
    assert any(t["name"] == "acme" for t in themes)

    resolved = (await client.get("/api/v1/themes/acme")).json()
    assert resolved["palette"]["primary"] == "#e2231a"
    assert resolved["css_variables"]["--df-primary"] == "#e2231a"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/themes", "/api/v1/layouts", "/api/v1/formats", "/api/v1/icons", "/api/v1/plugins"],
)
async def test_catalog_endpoints(client, path: str) -> None:
    response = await client.get(path)
    assert response.status_code == 200
    assert response.json() is not None
