# DeckForge

A local-first, agentic presentation workspace. You describe a deck in
conversation; a team of agents plans, researches, writes, designs, reviews and
renders it — then keeps editing it with you, turn after turn, without ever
losing context.

```
You:  Create a presentation about reinforcement learning.
      ↓  plan → research → outline → write → design → layout → review
You:  Make it more modern.            ↓  edits only what changed
You:  Move slide 7 before slide 4.    ↓  one operation, not a regeneration
You:  Download the PPTX.              ↓  rendered locally
```

Everything runs on your machine. The only component that may talk to the
internet is the LLM provider — and it doesn't have to.

---

## Why it is built this way

**The deck is JSON, not a file format.** `Presentation → Section → Slide →
Element` is the single source of truth. PPTX, PDF, HTML, Reveal.js, Marp and
Markdown are all *projections* of that JSON. No exporter ever reads a `.pptx`
back to figure out what the deck says.

**Edits are operations, not regenerations.** "Move slide 7 before slide 4"
becomes one `move_slide` operation applied deterministically in Python. The
model decides *what* changes; the engine guarantees the deck stays valid. Your
hand-written slide 3 is still there afterwards.

**Geometry is computed once and shared.** The layout engine resolves each slide
into absolute boxes on a 1280×720 canvas. The HTML preview, the PPTX exporter
and the PDF exporter all consume the *same* boxes — which is why the download
matches what you approved on screen.

**Every capability is a registry entry.** Providers, themes, layouts, exporters,
extractors and icons all live in registries that plugins mutate at import time.
Adding a theme is adding a folder. Adding an LLM backend is one adapter class.

---

## Install it as a desktop app

The simplest way to use DeckForge is to install it. No terminal, no Docker, no
`.env` — launch it, add a model connection in Settings, and start.

```powershell
./packaging/build.ps1 -Installer     # dist/installer/DeckForge-0.1.0-windows-x64-setup.exe
```

It installs per user (no administrator prompt), stores everything in
`%LOCALAPPDATA%\DeckForge`, and opens in a native window driven by the
operating system's own webview — no Chromium bundled, ~74 MB.

On first run you get a **Model connections** screen: pick a provider, paste a
key or point at `http://localhost:11434` for Ollama, press **Test** to see the
models the endpoint really offers, and save. Keep as many connections as you
like and switch whenever you want.

Full details, macOS/Linux scripts and troubleshooting: **[DESKTOP.md](DESKTOP.md)**.

---

## Or run it from source

Requires **Python 3.14+** and **Node 20+**.

### 1. A model to talk to

Fastest fully-offline path:

```bash
ollama pull qwen3:8b
```

Prefer a cloud model? Add it in Settings once the app is running, or put a key
in `.env` (see `.env.example`) and it becomes your first saved connection
automatically. Supported out of the box: **Ollama, LM Studio, llama.cpp, vLLM,
OpenAI, Anthropic, OpenRouter, Gemini, Groq, Together, DeepSeek, Mistral, Azure
OpenAI**.

### 2. Backend

```bash
cd backend
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m deckforge.cli doctor    # checks config + model
.venv/Scripts/python.exe -m deckforge.cli serve
```

On macOS/Linux the interpreter path is `.venv/bin/python`.

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. API docs live at <http://localhost:8000/docs>.

Or run the native window against the source tree:

```bash
cd backend && .venv/Scripts/python.exe -m deckforge.desktop
```

### Docker

```bash
cp .env.example .env
docker compose up --build              # backend + frontend
docker compose --profile ollama up     # ... and a model server
```

---

## What it does

### Model connections
Save as many as you like — a local model, a work endpoint, a personal key — each
with its own provider, base URL, model and credentials. One is active at a time
and switching is a click. **Test** makes a real request and lists the models the
endpoint actually offers, so a wrong key or a stopped server is obvious before
you generate anything. Keys are never sent back to the UI; the settings screen
only ever sees a masked hint.

### Conversation
Multiple conversations, each with its own messages, uploads, settings, model and
deck history. Responses stream token by token; progress is reported as plain
status ("Writing slides (4 of 12)") — never as exposed agent chatter.

### Presentations
Every accepted change appends an immutable version. Undo, restore any version,
compare two versions slide-by-slide, or fork a deck into an independent copy.

### Editing, in natural language
Rewrite, add, delete, merge, split, reorder, translate, change the audience,
change the theme, restyle colours and typography, add charts, timelines,
diagrams, metrics, quizzes, references, speaker notes.

### Documents in, decks out
Upload PDF, DOCX, PPTX, Markdown, TXT, CSV, XLSX or images. They are extracted,
chunked and indexed locally (BM25 — no embedding model to download), and the
research agent grounds the deck in them.

### Export
`pptx` · `pdf` · `html` · `revealjs` · `marp` · `markdown`, all rendered locally.
No PowerPoint, no LibreOffice, no headless browser.

### Usable by other agents
DeckForge is also an [MCP](https://modelcontextprotocol.io) server, so another
agent can build, refine and export decks over stdio without the app running:

```json
{ "mcpServers": { "deckforge": { "command": "/absolute/path/to/deckforge-mcp" } } }
```

It shares the desktop app's database, so the model connection you configured in
Settings works straight away and agent-built decks show up in the sidebar.
Details: **[MCP.md](MCP.md)**.

---

## The agents

| Agent | Responsibility |
| --- | --- |
| **Coordinator** | Owns the turn; runs only the agents the request needs. |
| **Intent router** | Create, edit, restyle, reorder, export, question or chat. |
| **Planner** | Goal, audience, tone, length, visual direction. |
| **Research** | Retrieves and condenses evidence from your documents. |
| **Outline** | Designs the narrative arc and the slide inventory. |
| **Slide writer** | Writes copy and speaker notes, one slide at a time, in parallel. |
| **Visual designer** | Icons, accents, emphasis. |
| **Layout selector** | Assigns layouts, maximising variety. |
| **Theme selector** | Picks the theme that fits the audience. |
| **Fact checker** | Audits claims against your source material. |
| **Critic** | Reviews density, clarity, repetition and endings. |
| **Revision** | Turns requests and critiques into deck operations. |

A creation runs the whole pipeline. An edit runs the router and the revision
agent — two model calls instead of thirty.

---

## Extending it

Everything below happens without touching core code.

**A theme** — drop a folder with a `theme.json` into
`backend/src/deckforge/themes/packages/` (or any path in
`DECKFORGE_THEME_PATHS`). `extends` lets a brand variant be ten lines. See
[the theme guide](backend/src/deckforge/themes/packages/README.md).

**A plugin** — a directory in `plugins/` exposing `register(registry)`. It can
add providers, themes, layouts, exporters, document extractors and icons. See
[`plugins/example_brand`](plugins/example_brand/__init__.py), which contributes
one of each.

**An LLM provider** — subclass `LLMProvider`, register a `ProviderSpec`. Most
backends need only a five-line subclass of the OpenAI-compatible adapter.

---

## Project layout

```
backend/src/deckforge/
  agents/       the agent framework and the twelve agents
  api/          FastAPI routes (versioned) and the SSE stream
  core/         registries, errors, events, logging
  database/     SQLAlchemy 2.0 async entities and repositories
  exporters/    pptx, pdf, html, revealjs, marp, markdown
  layouts/      geometry engine, 37 built-in layouts
  memory/       conversation, deck and preference memory
  models/       the deck model and the operation language
  plugins/      plugin contract and loader
  providers/    LLM adapters behind one interface
  renderers/    HTML, charts, icons, SVG paths, vector primitives
  retrieval/    extraction, chunking, BM25
  services/     use-case layer between API and domain
  themes/       theme engine + 20 theme packages
  desktop/      native window, embedded server, single-instance guard
frontend/       Next.js workspace: chat, preview, versions, export
packaging/      PyInstaller spec, Windows installer, build scripts
plugins/        drop-in extensions
```

Further reading: **[DESKTOP.md](DESKTOP.md)** for installing and packaging,
**[MCP.md](MCP.md)** for driving DeckForge from another agent,
**[ARCHITECTURE.md](ARCHITECTURE.md)** for the design and the reasoning behind
it, **[DEVELOPMENT.md](DEVELOPMENT.md)** for workflows, testing and how to add
each kind of extension.

---

## Status

Backend: 202 tests, strict `mypy`, clean `ruff`. The agent pipeline is exercised
end to end in tests against a scripted provider, so the whole loop — routing,
generation, editing, versioning, export — is verified offline. The Windows
desktop build is verified by hand: install, first-run setup, generation against
a real model, and export.

Known limits are listed at the end of [ARCHITECTURE.md](ARCHITECTURE.md).

## Licence

Apache-2.0.
