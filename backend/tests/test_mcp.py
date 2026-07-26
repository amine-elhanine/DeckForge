"""The MCP server: transport hygiene, tool behaviour, and coexistence.

The pipeline itself is covered elsewhere; what is specific here is that the
server must not corrupt its own transport, must reach the *installed* app's
data, and must turn expected failures into sentences an agent can act on.
"""

from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from deckforge import paths
from deckforge.config import Settings
from deckforge.container import Container
from deckforge.core.errors import DeckForgeError, NotFoundError
from deckforge.core.logging import configure_logging
from deckforge.database.repositories import UnitOfWork
from deckforge.mcp import server as mcp_server
from deckforge.mcp import tools
from deckforge.mcp.runtime import Runtime
from deckforge.models.enums import ContentDensity
from deckforge.providers.base import ProviderConfiguration


@pytest.fixture
async def runtime(settings: Settings) -> AsyncIterator[Runtime]:
    """A live runtime on a temporary database, answered by the scripted provider."""
    instance = await Runtime.start(settings)
    # `Runtime.start` builds the real provider factory; point it at the scripted
    # one so the suite never reaches the network.
    instance.container.providers.apply_override(
        ProviderConfiguration(name="scripted", default_model="scripted-1")
    )
    try:
        yield instance
    finally:
        await instance.stop()


async def call(runtime: Runtime, name: str, **arguments: Any) -> dict[str, Any]:
    return await tools.dispatch(runtime, name, arguments, None)


# --------------------------------------------------------------------------- #
# Transport hygiene — the failure that is hardest to diagnose from the outside
# --------------------------------------------------------------------------- #


def test_logging_can_be_kept_off_stdout() -> None:
    """On stdio, stdout is the protocol. A log line there breaks the session.

    The client's symptom is a JSON parse error naming a byte offset, which
    points nowhere near the code that logged.
    """
    import deckforge.core.logging as logging_module

    original = logging_module._CONFIGURED
    root_handlers = logging.root.handlers[:]
    out, err = io.StringIO(), io.StringIO()
    try:
        logging_module._CONFIGURED = False
        logging.root.handlers = []
        configure_logging("DEBUG", "console", stream=err)

        stdout = sys.stdout
        sys.stdout = out
        try:
            logging.getLogger("deckforge.test").warning("this must not reach the client")
            logging_module.get_logger("deckforge.test").info("structlog.event", key="value")
        finally:
            sys.stdout = stdout
    finally:
        logging_module._CONFIGURED = original
        logging.root.handlers = root_handlers

    assert out.getvalue() == "", "stdout must stay clean for JSON-RPC"
    assert "this must not reach the client" in err.getvalue()
    assert "structlog.event" in err.getvalue()


def test_configure_process_leaves_stdout_alone(tmp_path: Path, monkeypatch) -> None:
    """End to end: the entry point's own setup writes nothing to stdout."""
    import deckforge.core.logging as logging_module

    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(logging_module, "_CONFIGURED", False)
    monkeypatch.setattr(logging.root, "handlers", [])

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdout", captured)
    from deckforge.mcp.runtime import configure_process

    settings = configure_process()
    logging_module.get_logger("deckforge.test").warning("noise")

    assert captured.getvalue() == ""
    assert settings.data_dir == tmp_path.resolve()


def test_no_module_in_the_mcp_package_prints() -> None:
    """`print` defaults to stdout, so it is banned on this path."""
    package = Path(mcp_server.__file__).parent
    offenders = []
    for module in package.glob("*.py"):
        for number, line in enumerate(module.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("print(") and "stderr" not in line:
                offenders.append(f"{module.name}:{number}")
    assert not offenders, f"print() to stdout would corrupt the protocol: {offenders}"


# --------------------------------------------------------------------------- #
# Finding the user's real data
# --------------------------------------------------------------------------- #


def test_shared_data_dir_ignores_the_repo_checkout(monkeypatch) -> None:
    """The LLM connection lives in the installed app's database, not <repo>/data.

    `user_data_dir` resolves to the checkout during development, which keeps the
    suite isolated. The MCP server must not inherit that or it opens an empty
    database and fails every request with "no LLM configured".
    """
    monkeypatch.delenv("DECKFORGE_DATA_DIR", raising=False)
    shared = paths.shared_data_dir()
    assert shared == paths._platform_data_dir()

    repo = paths.repo_root()
    if repo is not None:
        assert shared != repo / "data"


def test_shared_data_dir_still_honours_the_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    assert paths.shared_data_dir() == tmp_path


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


def test_every_advertised_tool_is_dispatchable() -> None:
    """A tool an agent can see but not call is worse than one that is absent."""
    advertised = {tool.name for tool in tools.tool_definitions()}
    source = Path(tools.__file__).read_text(encoding="utf-8")
    for name in advertised:
        assert f'case "{name}"' in source, f"{name} is advertised but has no dispatch branch"


def test_tool_schemas_are_usable() -> None:
    for tool in tools.tool_definitions():
        assert tool.description
        schema = tool.inputSchema
        assert schema["type"] == "object"
        for field, spec in schema.get("properties", {}).items():
            assert spec.get("description") or spec.get("enum"), f"{tool.name}.{field} undocumented"


async def test_capabilities_reports_setup_state(runtime: Runtime) -> None:
    result = await call(runtime, "deckforge_capabilities")
    assert "minimal" in result["themes"]
    assert any(f["name"] == "pptx" for f in result["export_formats"])
    assert result["content_densities"] == [d.value for d in ContentDensity]
    assert result["data_dir"] == str(runtime.container.settings.data_dir)
    # `Container.startup` adopts an environment-configured provider as a saved
    # connection, so this installation is ready to generate.
    assert result["llm_configured"] is True
    assert result["llm"]["provider"] == "scripted"
    assert result["setup_help"] is None


async def test_capabilities_explains_an_unconfigured_install(runtime: Runtime) -> None:
    """Without this an agent cannot tell "not set up" from "broken"."""
    async with runtime.services() as services:
        for profile in await services.uow.llm_profiles.all_profiles():
            await services.uow.llm_profiles.delete(profile.id)

    result = await call(runtime, "deckforge_capabilities")
    assert result["llm_configured"] is False
    assert "Settings" in result["setup_help"], "an agent must be told which door to open"


async def test_create_refine_export_round_trip(runtime: Runtime, tmp_path: Path) -> None:
    created = await call(
        runtime, "create_deck", prompt="A deck about reinforcement learning", density="rich"
    )
    deck_id = created["deck_id"]
    assert created["slide_count"] > 0
    assert created["outline"].strip()
    assert created["version"] >= 1

    refined = await call(runtime, "refine_deck", deck_id=deck_id, instruction="tighten the ending")
    assert refined["deck_id"] == deck_id

    target = tmp_path / "out" / "deck.pptx"
    exported = await call(
        runtime, "export_deck", deck_id=deck_id, format="pptx", output_path=str(target)
    )
    written = Path(exported["path"])
    assert written == target.resolve()
    assert written.exists() and exported["size_bytes"] > 1000
    with zipfile.ZipFile(written) as archive:
        assert "ppt/presentation.xml" in archive.namelist()


async def test_export_without_a_path_lands_in_the_data_dir(runtime: Runtime) -> None:
    created = await call(runtime, "create_deck", prompt="A short deck")
    exported = await call(runtime, "export_deck", deck_id=created["deck_id"], format="pdf")
    written = Path(exported["path"])
    assert written.is_absolute(), "an agent needs a path it can open"
    assert written.exists()
    assert runtime.container.settings.exports_dir in written.parents


async def test_export_to_a_directory_uses_the_exporter_filename(
    runtime: Runtime, tmp_path: Path
) -> None:
    created = await call(runtime, "create_deck", prompt="A short deck")
    exported = await call(
        runtime, "export_deck", deck_id=created["deck_id"], output_path=str(tmp_path)
    )
    assert Path(exported["path"]).parent == tmp_path.resolve()
    assert exported["filename"].endswith(".pptx")


@pytest.mark.parametrize("fmt", ["outline", "markdown", "json"])
async def test_get_deck_reads_back(runtime: Runtime, fmt: str) -> None:
    created = await call(runtime, "create_deck", prompt="A deck about bandits")
    result = await call(runtime, "get_deck", deck_id=created["deck_id"], format=fmt)
    assert result["format"] == fmt
    if fmt == "json":
        assert result["content"]["slides"]
    else:
        assert isinstance(result["content"], str) and result["content"].strip()


async def test_list_decks_surfaces_what_was_made(runtime: Runtime) -> None:
    created = await call(runtime, "create_deck", prompt="A deck about bandits")
    listed = await call(runtime, "list_decks")
    assert created["deck_id"] in {d["deck_id"] for d in listed["decks"]}


async def test_density_reaches_the_pipeline(runtime: Runtime) -> None:
    """The knob has to survive the trip into the conversation's settings."""
    created = await call(runtime, "create_deck", prompt="A deck", density="concise")
    async with runtime.services() as services:
        row = await services.presentations.get_row(created["deck_id"])
        conversation = await services.conversations.get(row.conversation_id)
    assert conversation.settings["density"] == "concise"


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #


async def test_unknown_deck_is_a_clean_error(runtime: Runtime) -> None:
    with pytest.raises(NotFoundError):
        await call(runtime, "get_deck", deck_id="pres_missing")


async def test_unknown_tool_is_a_clean_error(runtime: Runtime) -> None:
    with pytest.raises(NotFoundError):
        await call(runtime, "no_such_tool")


async def test_unknown_format_is_a_clean_error(runtime: Runtime) -> None:
    created = await call(runtime, "create_deck", prompt="A deck")
    with pytest.raises(DeckForgeError):
        await call(runtime, "export_deck", deck_id=created["deck_id"], format="powerpoint")


async def test_progress_is_reported_while_generating(runtime: Runtime) -> None:
    seen: list[tuple[float, str]] = []

    async def record(value: float, message: str) -> None:
        seen.append((value, message))

    await tools.dispatch(runtime, "create_deck", {"prompt": "A deck"}, record)

    assert seen, "a four-minute call with no progress looks like a hang"
    assert all(0.0 <= value <= 1.0 for value, _ in seen), "MCP progress is a fraction of total=1.0"
    assert [v for v, _ in seen] == sorted(v for v, _ in seen), "progress must not walk backwards"


# --------------------------------------------------------------------------- #
# Coexistence with the desktop app
# --------------------------------------------------------------------------- #


async def test_a_second_process_can_read_while_we_write(runtime: Runtime) -> None:
    """The desktop app and the MCP server share one SQLite file (WAL)."""
    created = await call(runtime, "create_deck", prompt="A deck about bandits")

    observer = Container.create(runtime.container.settings)
    try:
        async with observer.database.session() as session:
            uow = UnitOfWork.create(session)
            row = await uow.presentations.get(created["deck_id"])
            assert row is not None, "a second connection must see committed work"
        # ... and the first connection keeps writing afterwards.
        await call(runtime, "refine_deck", deck_id=created["deck_id"], instruction="polish it")
    finally:
        await observer.database.dispose()


# --------------------------------------------------------------------------- #
# The protocol itself
# --------------------------------------------------------------------------- #


def _frame(message: dict[str, Any]) -> bytes:
    return (json.dumps(message) + "\n").encode("utf-8")


@pytest.mark.slow
def test_speaks_mcp_over_a_real_stdio_pipe(tmp_path: Path) -> None:
    """Spawn the server as a client would and complete a handshake."""
    env = {
        **os.environ,
        "DECKFORGE_DATA_DIR": str(tmp_path),
        "DECKFORGE_LOG_LEVEL": "DEBUG",  # noisy on purpose: stdout must stay clean
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "PYTHONIOENCODING": "utf-8",
    }
    process = subprocess.run(
        [sys.executable, "-m", "deckforge.mcp.server"],
        input=b"".join(
            [
                _frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    }
                ),
                _frame({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                _frame({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            ]
        ),
        capture_output=True,
        env=env,
        timeout=180,
        check=False,
    )

    assert process.returncode == 0, process.stderr.decode("utf-8", "replace")[-2000:]

    lines = [line for line in process.stdout.decode("utf-8").splitlines() if line.strip()]
    messages = []
    for line in lines:
        # Every byte on stdout must be a JSON-RPC frame, including at DEBUG.
        messages.append(json.loads(line))

    initialize = next(m for m in messages if m.get("id") == 1)
    assert initialize["result"]["serverInfo"]["name"] == "deckforge"

    listed = next(m for m in messages if m.get("id") == 2)
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"create_deck", "refine_deck", "export_deck"} <= names
