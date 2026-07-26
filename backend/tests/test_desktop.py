"""Desktop packaging concerns: path resolution and serving the bundled UI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deckforge import paths
from deckforge.api.spa import mount_spa

INDEX = "<!doctype html><html><body>DeckForge</body></html>"


@pytest.fixture
def web_bundle(tmp_path: Path) -> Path:
    """A minimal exported frontend."""
    out = tmp_path / "web"
    (out / "_next" / "static").mkdir(parents=True)
    (out / "index.html").write_text(INDEX, encoding="utf-8")
    (out / "_next" / "static" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return out


def build_app(web_dir: Path | None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    mount_spa(app, web_dir, "/api/v1")
    return app


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #


def test_paths_describe_reports_the_layout() -> None:
    described = paths.describe()
    assert described["frozen"] is False
    assert Path(str(described["themes"])).is_dir()
    assert Path(str(described["resource_root"])).is_dir()


def test_resource_root_follows_the_bundle(monkeypatch, tmp_path: Path) -> None:
    """A frozen build reads its data from the PyInstaller extraction dir."""
    bundled = tmp_path / "deckforge"
    (bundled / "themes" / "packages").mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    paths.resource_root.cache_clear()
    paths.repo_root.cache_clear()
    try:
        assert paths.resource_root() == bundled
        assert paths.builtin_theme_dir() == bundled / "themes" / "packages"
        assert paths.repo_root() is None, "a frozen build has no source checkout"
    finally:
        paths.resource_root.cache_clear()
        paths.repo_root.cache_clear()


def test_data_dir_honours_the_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path / "store"))
    paths.user_data_dir.cache_clear()
    try:
        assert paths.user_data_dir() == tmp_path / "store"
    finally:
        paths.user_data_dir.cache_clear()


def test_platform_data_dir_is_per_user() -> None:
    """Never inside the install directory, which is read-only once installed."""
    directory = paths._platform_data_dir()
    assert directory.is_absolute()
    assert "DeckForge" in str(directory) or "deckforge" in str(directory)


# --------------------------------------------------------------------------- #
# Serving the SPA
# --------------------------------------------------------------------------- #


def test_bundle_is_served_at_the_root(web_bundle: Path) -> None:
    with TestClient(build_app(web_bundle)) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "DeckForge" in response.text


def test_client_routes_fall_back_to_index(web_bundle: Path) -> None:
    with TestClient(build_app(web_bundle)) as client:
        response = client.get("/some/client/route")
        assert response.status_code == 200
        assert "DeckForge" in response.text


def test_api_routes_win_over_the_spa(web_bundle: Path) -> None:
    with TestClient(build_app(web_bundle)) as client:
        assert client.get("/api/v1/ping").json() == {"ok": True}


def test_unknown_api_paths_stay_json(web_bundle: Path) -> None:
    """An API 404 must not return the HTML shell."""
    with TestClient(build_app(web_bundle)) as client:
        response = client.get("/api/v1/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["error"]["code"] == "not_found"


def test_fingerprinted_assets_are_cached_forever(web_bundle: Path) -> None:
    with TestClient(build_app(web_bundle)) as client:
        asset = client.get("/_next/static/app.js")
        assert asset.status_code == 200
        assert "immutable" in asset.headers["cache-control"]

        shell = client.get("/")
        assert "no-cache" in shell.headers["cache-control"]


def test_missing_bundle_degrades_to_a_hint() -> None:
    """Running the API alone must still start and explain itself."""
    with TestClient(build_app(None)) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["app"] == "DeckForge"
        assert "npm run dev" in response.json()["ui"]


# --------------------------------------------------------------------------- #
# The desktop shell
# --------------------------------------------------------------------------- #


def test_windowed_builds_get_writable_streams(tmp_path: Path, monkeypatch) -> None:
    """PyInstaller sets stdout/stderr to None when console=False.

    Uvicorn's logging config names ``ext://sys.stdout``; with None it raises
    before the server binds a port, and a windowed app cannot report it. This
    is the exact failure the packaged build hit.
    """
    from deckforge.desktop.streams import ensure_std_streams

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    log_file = tmp_path / "logs" / "stdout.log"
    ensure_std_streams(log_file)

    assert sys.stdout is not None and sys.stderr is not None
    print("hello from a windowed app")
    sys.stdout.flush()
    assert log_file.is_file()
    assert "hello from a windowed app" in log_file.read_text(encoding="utf-8")


def test_existing_streams_are_left_alone() -> None:
    from deckforge.desktop.streams import ensure_std_streams

    before_out, before_err = sys.stdout, sys.stderr
    ensure_std_streams(None)
    assert sys.stdout is before_out and sys.stderr is before_err


def test_unwritable_log_path_still_yields_a_stream(monkeypatch, tmp_path: Path) -> None:
    """Logging setup must never be the thing that kills the app."""
    from deckforge.desktop.streams import ensure_std_streams

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    unwritable = tmp_path / "a-file"
    unwritable.write_text("not a directory", encoding="utf-8")

    ensure_std_streams(unwritable / "nested" / "stdout.log")
    assert sys.stdout is not None
    print("discarded, but not fatal")


def test_free_port_is_loopback_and_unused() -> None:
    import socket

    from deckforge.desktop.server import find_free_port

    port = find_free_port()
    assert 1024 < port < 65536
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))  # still free, so binding succeeds


def test_server_url_is_loopback_only() -> None:
    """The embedded API must never be reachable from the network."""
    from deckforge.desktop.server import EmbeddedServer

    assert EmbeddedServer(port=12345).url == "http://127.0.0.1:12345"


def test_window_state_round_trips(tmp_path: Path, monkeypatch) -> None:
    from deckforge import paths
    from deckforge.desktop.window import MIN_HEIGHT, MIN_WIDTH, WindowState

    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    paths.user_data_dir.cache_clear()
    try:
        WindowState(width=1600, height=1000, x=100, y=50).save()
        restored = WindowState.load()
        assert (restored.width, restored.height, restored.x, restored.y) == (1600, 1000, 100, 50)

        # Never smaller than the minimum, whatever the file says.
        WindowState(width=10, height=10).save()
        assert WindowState.load().width >= MIN_WIDTH
        assert WindowState.load().height >= MIN_HEIGHT
    finally:
        paths.user_data_dir.cache_clear()


def test_offscreen_window_position_is_discarded(tmp_path: Path, monkeypatch) -> None:
    """A monitor that has since been unplugged must not hide the window."""
    from deckforge import paths
    from deckforge.desktop.window import WindowState

    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    paths.user_data_dir.cache_clear()
    try:
        WindowState(x=-30_000, y=-30_000).save()
        restored = WindowState.load()
        assert restored.x is None and restored.y is None
    finally:
        paths.user_data_dir.cache_clear()


def test_corrupt_window_state_falls_back(tmp_path: Path, monkeypatch) -> None:
    from deckforge import paths
    from deckforge.desktop.window import DEFAULT_WIDTH, WindowState

    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    paths.user_data_dir.cache_clear()
    try:
        (tmp_path / "window.json").write_text("{not json", encoding="utf-8")
        assert WindowState.load().width == DEFAULT_WIDTH
    finally:
        paths.user_data_dir.cache_clear()


# --------------------------------------------------------------------------- #
# Saving downloads
# --------------------------------------------------------------------------- #


class FakeResponse:
    """Stands in for urlopen's context manager."""

    def __init__(self, body: bytes, filename: str = "") -> None:
        self._body = body
        disposition = f'attachment; filename="{filename}"' if filename else ""
        self.headers = {"content-disposition": disposition}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeWindow:
    """A save dialog that answers with a fixed path, or cancels."""

    def __init__(self, answer: Path | None) -> None:
        self.answer = answer
        self.asked_with: dict[str, object] = {}

    def create_file_dialog(self, _kind: int, **kwargs: object) -> str | None:
        self.asked_with = kwargs
        return str(self.answer) if self.answer else None


def make_bridge(monkeypatch, body: bytes = b"PK\x03\x04deck", filename: str = "deck.pptx"):
    from deckforge.desktop import bridge as bridge_module

    monkeypatch.setattr(
        bridge_module.urllib.request,
        "urlopen",
        lambda *_a, **_k: FakeResponse(body, filename),
    )
    return bridge_module.DesktopApi("http://127.0.0.1:9999")


def test_download_is_fetched_and_written(tmp_path: Path, monkeypatch) -> None:
    """The embedded webview ignores <a download>, so Python saves the file."""
    bridge = make_bridge(monkeypatch)
    target = tmp_path / "saved.pptx"
    window = FakeWindow(target)
    bridge.attach(window)

    result = bridge.save_download("/api/v1/presentations/p1/download?format=pptx", "fallback.pptx")

    assert result["ok"] is True
    assert result["path"] == str(target)
    assert target.read_bytes() == b"PK\x03\x04deck"
    # The server's own filename wins over the caller's suggestion.
    assert window.asked_with["save_filename"] == "deck.pptx"


def test_cancelling_the_dialog_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    bridge = make_bridge(monkeypatch)
    bridge.attach(FakeWindow(None))
    result = bridge.save_download("/api/v1/presentations/p1/download?format=pdf", "x.pdf")
    assert result == {"cancelled": True}
    assert not list(tmp_path.iterdir())


def test_bridge_refuses_paths_outside_the_api(monkeypatch, tmp_path: Path) -> None:
    """A bridge that fetches any URL on request is a confused deputy."""
    bridge = make_bridge(monkeypatch)
    bridge.attach(FakeWindow(tmp_path / "nope.bin"))

    for hostile in (
        "http://evil.example/secrets",
        "/etc/passwd",
        "//evil.example/x",
        "/api/v2/other",
    ):
        result = bridge.save_download(hostile, "x")
        assert result["ok"] is False
        assert "not allowed" in result["error"]
    assert not list(tmp_path.iterdir())


def test_a_failed_fetch_is_reported_not_raised(tmp_path: Path, monkeypatch) -> None:
    from deckforge.desktop import bridge as bridge_module

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("connection reset")

    monkeypatch.setattr(bridge_module.urllib.request, "urlopen", boom)
    bridge = bridge_module.DesktopApi("http://127.0.0.1:9999")
    bridge.attach(FakeWindow(tmp_path / "x.pptx"))

    result = bridge.save_download("/api/v1/presentations/p1/download?format=pptx", "x.pptx")
    assert result["ok"] is False
    assert "connection reset" in result["error"]


def test_reveal_only_accepts_files_this_session_saved(tmp_path: Path, monkeypatch) -> None:
    """Otherwise the page could use the bridge to poke around the disk."""
    bridge = make_bridge(monkeypatch)
    target = tmp_path / "saved.pptx"
    bridge.attach(FakeWindow(target))

    stranger = tmp_path / "someone-elses.txt"
    stranger.write_text("private", encoding="utf-8")
    assert bridge.reveal(str(stranger))["ok"] is False

    bridge.save_download("/api/v1/presentations/p1/download?format=pptx", "x.pptx")
    monkeypatch.setattr(bridge, "_reveal_in_file_manager", lambda _p: None)
    assert bridge.reveal(str(target))["ok"] is True


def test_stale_instance_lock_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """A lock left by a crash must not block the next launch."""
    import json

    from deckforge import paths
    from deckforge.desktop.window import SingleInstance

    monkeypatch.setenv("DECKFORGE_DATA_DIR", str(tmp_path))
    paths.user_data_dir.cache_clear()
    try:
        lock = tmp_path / "instance.json"
        # A port nothing is listening on.
        lock.write_text(json.dumps({"url": "http://127.0.0.1:1", "pid": 1}), encoding="utf-8")

        guard = SingleInstance()
        assert guard.running_instance_url() is None
        assert not lock.exists(), "the stale lock should be cleaned up"

        guard.acquire("http://127.0.0.1:5000")
        assert lock.is_file()
        guard.release()
        assert not lock.exists()
    finally:
        paths.user_data_dir.cache_clear()
