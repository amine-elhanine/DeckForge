# Architecture

This document explains how DeckForge is put together and, more importantly, why.
Every section states the decision, the alternative that was rejected, and the
consequence you would feel if it were done the other way.

---

## 1. The deck is JSON

```
Presentation
├── meta          audience, tone, goal, duration, language
├── theme         a name plus overrides
├── sections[]    ordered grouping, addressable by title
├── slides[]      flat, ordered
│   └── elements[]  discriminated union: text, bullets, image, chart,
│                   diagram, table, quote, metric, cards, timeline, code, icon
└── references[]
```

`deckforge/models/deck.py` is the single source of truth. Agents read and write
it; renderers project it; exporters serialise it. **No exporter ever reads a
`.pptx` or `.pdf` back to learn what the deck says.**

**Why slides are flat rather than nested inside sections.** "Move slide 7 before
slide 4" is a one-line list operation on a flat list. On a nested structure it
is a cross-container move with re-parenting, and it is the single most common
edit users ask for. Sections carry titles and order; slides carry `section_id`;
`iter_sections()` reconstructs the nested view when one is needed.

**Consequence.** Every output format is consistent by construction. Fixing a
rendering bug fixes it in six formats at once.

---

## 2. Edits are operations, not regenerations

`deckforge/models/ops.py` defines a small edit language: `move_slide`,
`update_slide`, `merge_slides`, `split_slide`, `upsert_element`, `set_theme`,
`reorder_slides`, and a dozen more. Editing agents return a batch of these;
`apply_operations` executes them deterministically in Python.

**The alternative** — asking the model to return the whole edited deck — was
rejected because:

- it is slow (a 20-slide deck is ~15k tokens to re-emit),
- it is lossy (models silently drop the slide you hand-edited),
- it is unverifiable (you cannot diff intent, only outcome).

**Consequence.** The LLM decides *what* changes. The engine guarantees the deck
remains structurally valid: unknown slide ids are skipped rather than fatal,
locked slides are never touched, and the applied/skipped list becomes the
user-visible changelog. The same language backs the HTTP `POST
/presentations/{id}/operations` endpoint, so drag-to-reorder in the UI and an
agent edit go through one validated path.

---

## 3. Geometry is computed once, consumed by every renderer

```
Slide + Theme ──► LayoutEngine.resolve() ──► LayoutFrame
                                              ├── background
                                              ├── decor[]      shapes
                                              ├── texts[]      box + role
                                              └── elements[]   box + valign + z
                                                     │
                        ┌──────────────┬─────────────┴──────────────┐
                     HTML             PPTX                        PDF
```

A `LayoutFrame` is a flat list of absolutely positioned boxes on a 1280×720
logical canvas. One logical unit is one CSS pixel is 9525 EMU, which makes a
16:9 deck exactly 13.333in × 7.5in in PowerPoint with no conversion fudge.

**Why not let each exporter lay out its own slides?** Because then the preview
and the download disagree, and users only discover it after presenting.

Layouts compose primitives (`split_h`, `columns`, `grid_cells`, `stack`) rather
than hardcoding coordinates, so a theme's margins and rhythm change all 37
layouts at once. `layouts/measure.py` estimates content height before anything
renders, so two bullets and twelve bullets do not get the same box.

### Automatic layout selection

`LayoutEngine.plan()` scores every layout per slide on:

- the theme's declared preferences for that slide kind,
- whether the layout's element affinities are present (a split layout with no
  visual to put in the right column is *penalised*, not just unrewarded),
- capacity versus actual content volume,
- **repetition in the last three slides.**

That last term is the difference between a deck and a template. It is also why
the engine sometimes overrides a slide-level `layout_hint`: fourteen identical
slides is the most recognisable failure mode of AI-generated decks.

Layouts also declare `excludes` — element types they cannot render. `image_full`
has nowhere to put a bullet list, so it is disqualified for such a slide rather
than silently dropping the content.

---

## 4. Themes are data, never code

A theme package is one `theme.json`: palette, fonts, type scale, spacing, shape,
bullets, backgrounds per slide kind, decorative treatments, and preferred
layouts. `extends` resolves through a deep merge, so a brand variant is ten
lines.

Renderers resolve colours through *semantic tokens* (`primary`, `surface`,
`text_muted`) and never through literals. That is what lets "use our brand blue"
become a one-key override instead of a find-and-replace across the codebase.

**Partial overrides must merge, not replace.** `{"display": {"weight": 800}}`
means "the usual display style, but heavier". Pydantic's default behaviour is to
build a fresh object from that dict alone, so every unstated field falls back to
the *class* default — which silently turned 68pt headings into 20pt body text in
six shipped themes. `TypeScale` merges each partial override onto the default
for that role, and a test asserts every theme keeps display > title > body.

Themes are loaded from three sources of increasing priority: built-in packages,
`DECKFORGE_THEME_PATHS`, and plugin/database registrations. All twenty shipped
themes are asserted to meet WCAG AA contrast for body text in the test suite.

---

## 5. Agents: many small, typed, single-purpose units

Every agent has one job, one input type and one validated Pydantic output.
Agents never call each other; the coordinator wires them.

```
              ┌── router ──┐
              │            │
      create ─┤            ├─ edit/restyle/reorder ─► revision ─► apply ops
              │            │
              ▼            ▼
   planner → research → outline → slide writer (parallel)
        → theme → designer → layout → fact checker → critic → revision
```

**Why so many.** A single "write me a deck" prompt produces mush: the model
optimises the easy parts (bullet phrasing) and neglects the hard ones (arc,
variety, density). Separating *notice* from *fix* also keeps the critic honest —
an agent that must implement its own fixes learns to find easy problems.

**Why structured hand-offs.** Free text between agents compounds ambiguity. A
validated schema fails loudly and can be repaired: `provider.structured()`
prompts with the JSON Schema, repairs malformed JSON, and on a schema mismatch
feeds the error back for a retry. Small local models participate reliably as a
result.

**Why slides are written in parallel.** Neighbour context comes from the
*outline*, not from previously written slides, so nothing is lost by
parallelising. On a local 8B model this is the difference between a 30-second
and a four-minute deck.

**Degradation is designed in.** A slide whose generation fails falls back to its
outline points; the deck still ships. A failed visual designer falls back to
keyword-derived icons. A failed router falls back to "edit if a deck exists,
else create". The turn never dies because one agent had a bad day.

**Agent reasoning is never exposed.** Agents emit user-facing status events
("Writing slides (4 of 12)") with monotonically increasing progress. The
coordinator produces the single reply the user actually reads.

---

## 6. Saved LLM connections

Credentials are not a `.env` concern in a desktop app — there is no terminal.
`LlmProfile` is a *named connection*: label, provider adapter, base URL, model,
key and sampling defaults. Users keep several and switch the active one from
Settings.

**Why not one row per provider.** Two OpenAI-compatible endpoints with different
keys is an ordinary setup — work and personal, or a self-hosted vLLM and a cloud
gateway. A per-provider record cannot express that.

Resolution order is: an explicit conversation override, then the active
connection, then the environment. The last rung keeps headless deployments
working from a `.env` alone.

Two details that matter more than they look:

- **The key never leaves the server.** Reads return `has_api_key` and a masked
  hint (`sk-…f8149b`). Consequently an edit that omits `api_key` must *keep* the
  stored value — otherwise opening the form and pressing Save would silently
  destroy the credential.
- **Test before commit.** `POST /llm/test` accepts either an unsaved form or a
  `profile_id`, makes one real request, and returns latency plus the model list.
  A wrong key, a stopped local server or a mistyped model name surfaces there
  rather than as a failed generation three minutes later.

---

## 7. Providers behind one interface

`LLMProvider` defines `stream`, `complete`, `structured`, `list_models`. Nothing
above it knows which backend is in use.

Thirteen backends ship. Nine of them are five-line subclasses of the
OpenAI-compatible adapter, because they differ only in base URL and auth header.
The three that need real work are:

- **Ollama** — uses the native `/api/chat` for `format: json` constrained
  decoding, which materially improves structured output from small models.
- **Anthropic** — has no `response_format`, so JSON mode is emulated by
  prefilling an assistant turn with `{`.
- **Gemini** — different role names, different envelope, key in the query string.

Instances are cached per `(provider, model)` so the connection pool is shared.
Credentials come from the environment or from the database, applied as an
override without a restart.

---

## 8. Persistence

SQLAlchemy 2.0 async. SQLite by default (WAL, foreign keys on); PostgreSQL by
changing one URL — `JSONVariant` is `JSONB` there and plain `JSON` on SQLite.

```
User → Conversation ─┬─ Message
                     ├─ Asset ── AssetChunk        (retrieval)
                     └─ Presentation ─┬─ PresentationVersion   (immutable chain)
                                      ├─ Slide                 (denormalised index)
                                      └─ ExportRecord
```

The working copy of a deck lives on the `presentations` row; every accepted
change also appends an immutable version. **Undo appends rather than truncates**,
so "undo, then undo the undo" always works and history is never destroyed.

`Slide` is a denormalised index — the deck JSON stays authoritative — so the UI
can list and search slides without loading every snapshot.

Services depend on a `UnitOfWork` bundling repositories, never on a session
directly. Adding a repository does not ripple through constructors.

---

## 9. Retrieval without a download

Extraction is registered per file extension. Chunking is paragraph-aligned,
because a chunk that starts mid-sentence retrieves badly and reads worse when
quoted onto a slide. Ranking is BM25, implemented in ~60 lines.

**Why not embeddings?** A first run would download a model, which contradicts
"local-first, works offline, starts instantly". Over a handful of uploaded
documents BM25 is fast, explainable and good enough. The `Retriever` protocol is
one method — swapping in embeddings later means implementing `search`.

---

## 10. Streaming

Server-Sent Events, implemented directly on Starlette's `StreamingResponse`
(`api/sse.py`). Event types: `status`, `token`, `deck`, `slide`, `artifact`,
`message`, `error`, `done`.

Two things learned the hard way, both now encoded in the code:

- **The Next.js dev-server rewrite buffers SSE.** The browser therefore calls the
  backend origin directly and CORS is configured for it. Proxying through
  `next.config.mjs` silently breaks live progress.
- **`x-accel-buffering: no` and a leading comment frame** ensure headers flush
  immediately, so `fetch` resolves before the first real event.

The frontend parses SSE from `fetch` rather than using `EventSource`, because
`EventSource` cannot POST.

---

## 11. Three entry points, one service layer

The REST API, the desktop shell and the MCP server are all thin skins over the
same services. That is possible because services take `(container, uow)` and
know nothing about their transport — `api/deps.py` builds them per request, and
`mcp/runtime.py` builds them the same way per tool call.

The MCP server (`mcp/`) speaks JSON-RPC on stdio so another agent can spawn it on
demand. Its tools contain no deck logic; `create_deck` opens a conversation and
runs `ChatService.stream()`, exactly as an HTTP request would, which is why
version history, undo and the desktop UI keep working on agent-built decks.

Two constraints are specific to this transport and both are easy to violate:

- **stdout is the protocol.** `configure_logging()` takes a `stream` argument and
  the MCP entry point passes stderr *before* the container is built. One log line
  on stdout corrupts the JSON-RPC stream, and the client's symptom is a parse
  error at a byte offset that points nowhere near the cause. A test asserts that
  stdout carries only JSON frames, at `DEBUG`, and another that nothing in the
  package calls `print`.
- **It must reach the installed app's data.** `paths.user_data_dir()` resolves to
  `<repo>/data` from a source checkout, which is right for development and wrong
  here: the user's saved model connection lives in the per-user directory.
  `paths.shared_data_dir()` always returns the platform directory, and the MCP
  runtime pins `DECKFORGE_DATA_DIR` to it before `Settings` is constructed.

Running beside the desktop app is safe because SQLite is already in WAL mode with
a 30-second busy timeout (§8).

Long generations report progress: `RunEvent.status` carries a 0..1 fraction,
forwarded as MCP progress notifications when the client supplies a token.

---

## 12. Plugins

A plugin is any importable module exposing `register(registry)`. The registry is
a facade over every extension point, so a plugin never imports internals it does
not need:

```python
def register(registry: PluginRegistry) -> None:
    registry.add_theme_directory(Path(__file__).parent / "themes")
    registry.add_exporter(JsonExporter())
    registry.add_layout(LayoutDefinition(...))
    registry.add_icon("acme-mark", "M12 3l8 4.5v9L12 21l-8-4.5v-9z")
```

Discovery is from directories (`plugins/`, `DECKFORGE_PLUGIN_PATHS`) and from
`deckforge.plugins` entry points. **A plugin that raises during registration is
skipped with a warning** — one bad plugin must never take the application down.
Plugins load before the engines read the registries, so their contributions are
present from the first request.

---

## 13. Desktop packaging

The app freezes with PyInstaller and opens a native OS webview — WebView2,
WKWebView or WebKitGTK. No Chromium, no Node at runtime, ~74 MB.

Three assumptions had to be broken to make the frozen build behave:

- **Resources move.** `Path(__file__).parent` is meaningless in a bundle;
  everything routes through `deckforge/paths.py`, which resolves `sys._MEIPASS`
  when frozen and the package directory otherwise.
- **The install directory is read-only.** The database, uploads and exports go
  to a per-user application data folder, never next to the executable.
- **There are no standard streams.** With `console=False` PyInstaller sets
  `sys.stdout` and `sys.stderr` to `None`. Uvicorn's default logging config
  names `ext://sys.stdout`, so `dictConfig` raised before the server ever bound
  a port — a crash with nowhere to report itself. `desktop/streams.py` points
  the streams at the log file first, and the server passes `log_config=None`.

The API binds an **ephemeral loopback port**: a fixed one would collide with
other software and would let anything on the machine find it. A single-instance
guard validates its lock by calling the recorded port, so a lock left by a crash
never blocks the next launch.

**Downloads need a host.** An embedded WebView2 does not save files the way a
browser does — it hands the download to the host application, and a host that
ignores it produces no file, no error and no prompt. The export menu therefore
goes through `desktop/bridge.py`: the page asks Python, Python fetches from its
own API, opens a native save dialog and writes the file. Browsers keep the
ordinary blob download. The bridge only accepts paths under `/api/v1/` and only
reveals files it wrote itself, so the page cannot use it to read the disk.

`deckforge.main` builds the app through a module-level `__getattr__`, so
importing the module no longer constructs a container — the desktop shell wants
only `create_app`, and eager construction was loading every plugin and opening a
database engine twice per launch.

Credentials live in **saved connections** (§7), not in a `.env` the user cannot
reach without a terminal. On first launch an environment-configured provider is
adopted automatically — but a *local* one only if it actually answers, because
every machine has a plausible-looking Ollama URL and seeding a dead connection
would suppress the setup prompt and make a fresh install look broken.

---

## 14. Frontend

Next.js App Router, Tailwind, Zustand, resizable panels. Three panes:
conversations, chat, deck.

The interesting decision is **how slides are previewed**. The backend renders
slides to HTML and hands over the matching stylesheet; the client injects both.
Consequences:

- the preview is byte-for-byte what the HTML exporter produces,
- thumbnails and the full stage are the *same markup* at different widths —
  slide geometry is expressed in container-query units
  (`--df-u: calc(100cqw / 1280)`), so the parent's width is the only input,
- no iframe per thumbnail, and no duplicated rendering logic in TypeScript.

Every selector in the deck stylesheet is namespaced `df-`, so it cannot collide
with the application chrome.

---

## 15. Testing

137 tests, offline. `ScriptedProvider` implements the real `LLMProvider`
interface and answers each agent by recognising its system prompt, so the tests
exercise the genuine pipeline — JSON parsing, validation, retries, fallbacks —
deterministically and without a model.

Notable coverage: every layout renders every slide kind without leaving the
canvas; every theme meets WCAG AA; every exporter survives an empty deck and
hostile content (`<script>`, unicode, unbalanced markup); the PPTX package
contains one slide per deck slide plus notes; the whole product loop runs over
HTTP.

Bugs the suite caught during construction, all now regression-tested: a
non-deterministic sort in `reorder_slides`, a shallow merge that discarded theme
overrides, SVG arc flags parsed as a single number (which silently disabled
icons in PPTX and PDF), a progress bar that walked backwards, and list settings
that crashed startup when supplied as comma-separated environment values.

---

## Known limits

- **Mermaid and PlantUML diagrams are not rasterised server-side.** The source is
  preserved and rendered client-side; PPTX and PDF show the source in a styled
  panel unless a plugin supplies a rendered image. A diagram-renderer plugin is
  the intended fix.
- **No image generation.** `image_prompt` becomes an addressable placeholder for
  an image plugin to fill; uploaded images work fully today.
- **PDF text is Latin-1** unless you supply a Unicode TTF (`font_path` option or
  a `fonts/` directory beside the assets). PPTX and HTML are unaffected.
- **Single local user.** Auth, sharing and multi-tenancy are deliberately absent;
  the `User` entity exists so adding them is not a migration nightmare.
- **`create_all` instead of migrations.** Fine for a local app; production
  deployments should layer Alembic on top.
- **The background worker queue is in-process.** Redis is configured but not yet
  used; long generations hold an HTTP connection.
