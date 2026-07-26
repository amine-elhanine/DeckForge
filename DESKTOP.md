# DeckForge as a desktop application

DeckForge installs and runs as a normal desktop app. There is no terminal, no
Docker, no Node process, and no `.env` to edit: you launch it from the Start
menu, add a model connection in Settings, and start making decks.

```
DeckForge.exe
  └── native OS webview (WebView2 / WKWebView / WebKitGTK)
        └── http://127.0.0.1:<ephemeral>      ← embedded FastAPI, loopback only
              ├── /                            ← the exported UI, served from the bundle
              └── /api/v1/…                    ← the agent pipeline, themes, exporters
```

No Chromium is bundled — the window uses the webview the operating system
already ships. That is why the build is ~74 MB rather than ~250 MB.

---

## Installing

### Windows

Run `DeckForge-0.1.0-windows-x64-setup.exe`. It installs **per user**, so there
is no administrator prompt.

| | |
| --- | --- |
| Application | `%LOCALAPPDATA%\Programs\DeckForge` |
| Your data | `%LOCALAPPDATA%\DeckForge` |
| Logs | `%LOCALAPPDATA%\DeckForge\logs\deckforge.log` |

Windows 11 and current Windows 10 already include the WebView2 runtime. On an
older build the installer says so and links to the download.

### macOS and Linux

Build scripts are provided (`packaging/build.sh`) and produce a `.app`/`.dmg`
and an AppImage respectively. **They have not been run by the author** — only
the Windows pipeline is verified. Expect to adjust paths, and note that an
unsigned macOS build is quarantined by Gatekeeper until you sign and notarise
it; the script prints the commands.

| | macOS | Linux |
| --- | --- | --- |
| Your data | `~/Library/Application Support/DeckForge` | `~/.local/share/deckforge` |

---

## First run

The app opens with **"Connect a model to get started"**. Click **Set up**.

In **Settings → Model connections** you can save as many connections as you
like and switch between them at any time:

| Field | Notes |
| --- | --- |
| **Provider** | Thirteen adapters, grouped into "Runs on this machine" and "Cloud". |
| **Name** | Your label, e.g. *Work DeepSeek*. |
| **Base URL** | Prefilled from the provider; change it for a self-hosted endpoint. |
| **Model** | **Test** fills the dropdown with the models the endpoint actually offers, and warns if the one you typed is not among them. |
| **API key** | Not needed for local providers. |
| **Temperature** | Optional; blank uses the application default. |

**Test** makes one real request and reports latency and the model list, so a
wrong key or a stopped local server is obvious before you generate anything.

Several connections can share a provider — two OpenAI-compatible endpoints with
different keys is a normal setup. One is active at a time; **Use this one**
switches. The sidebar always shows which is in use, with a warning dot if the
last run failed.

### Fully offline

Install [Ollama](https://ollama.com), then:

```bash
ollama pull qwen3:8b
```

Add a connection with provider **Ollama**, base URL `http://localhost:11434`,
model `qwen3:8b`. Nothing leaves your machine after that — generation,
rendering and export are all local.

---

## Where your data lives

Everything is in one folder (`%LOCALAPPDATA%\DeckForge` on Windows):

```
deckforge.db     conversations, decks, every version, saved connections
uploads/         documents you attached
exports/         generated PPTX/PDF/HTML files
assets/          images used in slides
logs/            application log
window.json      remembered window size and position
```

Back up or move DeckForge by copying that folder. Uninstalling **does not**
delete it — remove it by hand if you want a clean slate.

> **On API keys.** Keys are stored in that database in plain text, on your own
> machine, in your own user profile. The app never sends a key back to the UI —
> the settings screen only ever sees a masked hint like `sk-…f8149b`. It is not
> a secrets vault; treat the folder like any other personal data.

Point the app somewhere else with `DECKFORGE_DATA_DIR`, e.g. to keep everything
on a portable drive.

---

## Building it yourself

Prerequisites: Python 3.14+, Node 20+, and (for the installer) Inno Setup 6.

```powershell
# Windows
./packaging/build.ps1              # dist/DeckForge/DeckForge.exe
./packaging/build.ps1 -Installer   # ... plus dist/installer/*.exe
```

```bash
# macOS / Linux
./packaging/build.sh
./packaging/build.sh --package     # .dmg or AppImage
```

The pipeline is: install `[desktop,build]` extras → export the frontend to
`frontend/out` → generate the icon → freeze with PyInstaller
(`packaging/deckforge.spec`) → optionally build the installer.

Useful flags: `-SkipFrontend` reuses the existing export, `-SkipInstall` skips
dependency installation.

### Diagnosing a build

A windowed application has no console, so a startup crash is invisible. Build a
console variant:

```powershell
$env:DECKFORGE_BUILD_CONSOLE="1"
backend/.venv/Scripts/python.exe -m PyInstaller packaging/deckforge.spec `
    --noconfirm --clean --distpath dist/debug --workpath build/debug
dist/debug/DeckForge/DeckForge.exe
```

That is how the one genuine packaging bug was found: with `console=False`,
PyInstaller sets `sys.stdout` and `sys.stderr` to `None`, and uvicorn's default
logging configuration names `ext://sys.stdout` — so `dictConfig` raised before
the server ever bound a port. The fix is in
[`desktop/streams.py`](backend/src/deckforge/desktop/streams.py).

---

## Running from source

```bash
python -m deckforge.desktop                     # native window, bundled UI
python -m deckforge.desktop --dev-url http://localhost:3000   # against `npm run dev`
python -m deckforge.desktop --port 8000         # fixed port instead of ephemeral
```

`--dev-url` gives you the native window with hot reload and devtools open.

---

## How it behaves

**Port.** The API binds an ephemeral loopback port. A fixed port would collide
with other software and would let anything on the machine find it; only the
window knows the number.

**One instance.** A second launch detects the running one (by calling its
health endpoint) and opens it rather than starting a second process against the
same SQLite file. A lock file left behind by a crash is validated and discarded.

**Window state.** Size and position are remembered in `window.json`, and a
position on a monitor that no longer exists is discarded rather than putting
the window off-screen.

**Shutdown.** Closing the window stops the embedded server and releases the
lock; nothing is left running in the background.

---

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Window never appears | Check `logs/deckforge.log`. On older Windows 10, install the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/). |
| Export does nothing | Fixed in 0.1.0. An embedded WebView2 hands `<a download>` to the host application and stays silent if the host ignores it, so exports now go through the Python bridge and a native save dialog. If a build still does nothing, check `desktop.download_*` entries in the log. |
| "could not start its local service" | The embedded server failed; the dialog names the log file. |
| Generation fails immediately | Open Settings and press **Test**. The sidebar shows a warning dot and the last error. |
| A local model is not found | Start the server first (`ollama serve`), then **Test** again — the model list comes from the endpoint. |
| Want to start over | Quit and delete the data folder. |
