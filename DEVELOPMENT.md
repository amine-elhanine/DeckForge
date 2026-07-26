# Development guide

## Setup

Python 3.14+, Node 20+. [`uv`](https://docs.astral.sh/uv/) is recommended but
`python -m venv` + `pip` works identically.

```bash
git clone <your-fork> && cd agentic_slide
cp .env.example .env

cd backend
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"

cd ../frontend
npm install
```

Paths below use `.venv/Scripts/python.exe` (Windows); on macOS/Linux use
`.venv/bin/python`.

## Running

```bash
# terminal 1
cd backend && .venv/Scripts/python.exe -m deckforge.cli serve --reload

# terminal 2
cd frontend && npm run dev
```

- App: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

> The browser calls the backend **directly**, not through a Next.js rewrite —
> the dev-server proxy buffers Server-Sent Events and silently breaks live
> progress. Point `NEXT_PUBLIC_API_URL` at the backend and make sure that origin
> is in `DECKFORGE_CORS_ORIGINS`.

## The CLI

```bash
python -m deckforge.cli doctor                       # config + provider reachability
python -m deckforge.cli catalog                      # themes, layouts, exporters, providers
python -m deckforge.cli render-sample --theme neon --out sample.html
python -m deckforge.cli render-sample --contact-sheet --out sheet.html   # every slide at once
python -m deckforge.cli export --format pptx --theme corporate --out deck.pptx
python -m deckforge.cli export --deck my-deck.json --format pdf
```

`render-sample --contact-sheet` is the fastest way to eyeball a theme or a
layout change: it puts all fourteen sample slides in one grid.

## Desktop shell

```bash
cd backend
.venv/Scripts/python.exe -m deckforge.desktop                    # native window
.venv/Scripts/python.exe -m deckforge.desktop --dev-url http://localhost:3000
```

`--dev-url` gives the native window with hot reload and devtools. Packaging is
covered in [DESKTOP.md](DESKTOP.md).

## Quality gate

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q                     # 202 tests
.venv/Scripts/python.exe -m pytest --cov=deckforge        # with coverage
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format src tests
.venv/Scripts/python.exe -m mypy                          # strict

cd ../frontend
npx tsc --noEmit
npm run lint
npm run build
```

All four backend checks must pass before a change lands.

## Testing philosophy

The suite never contacts a model. `tests/conftest.py` provides
`ScriptedProvider`, a real `LLMProvider` implementation that answers each agent
by recognising its system prompt. That means tests exercise the genuine
pipeline — JSON extraction, schema validation, retry-on-mismatch, fallbacks —
deterministically and offline.

Override a single agent's answer to test a specific path:

```python
ctx.provider.overrides = {
    "You edit an existing presentation": json.dumps({
        "summary": "Moved slide 7.",
        "operations": [{"op": "move_slide", "slide_id": target, "to_index": 3}],
    })
}
try:
    result = await CoordinatorAgent().handle(ctx)
finally:
    ctx.provider.overrides = {}
```

Fixtures: `settings` (isolated temp SQLite), `themes`, `layouts`, `renderer`,
`deck` (the sample deck), `container`, `app`, `client` (httpx against the ASGI
app, sharing one database engine with the container).

---

## Extending

### Add a theme

Create `backend/src/deckforge/themes/packages/<name>/theme.json`:

```json
{
  "name": "acme",
  "extends": "minimal",
  "label": "Acme Brand",
  "tags": ["brand", "light"],
  "palette": { "primary": "#e2231a", "text": "#101820" }
}
```

Then `python -m deckforge.cli render-sample --theme acme --contact-sheet --out acme.html`.

Full key reference: [`themes/packages/README.md`](backend/src/deckforge/themes/packages/README.md).
Themes may also be created at runtime via `POST /api/v1/themes`.

### Add a layout

```python
from deckforge.layouts.builtin import header, new_frame, split_h, stack
from deckforge.layouts.engine import register_layout
from deckforge.layouts.model import LayoutContext, LayoutDefinition, LayoutFrame

def build(ctx: LayoutContext) -> LayoutFrame:
    frame = new_frame(ctx, "my_layout")
    texts, body = header(ctx, ctx.content_box())
    frame.texts = texts
    left, right = split_h(body, 0.4, ctx.theme.spacing.gap)
    frame.elements = stack(ctx.elements_for(), left, ctx.theme)
    return frame

register_layout(LayoutDefinition(
    name="my_layout",
    label="My layout",
    description="What it is for — this text goes into the layout agent's prompt.",
    builder=build,
    suits=[SlideKind.CONTENT],
    capacity=4,
    requires=["image"],          # only selectable when an image is present
    excludes=["table"],          # never selectable when a table is present
))
```

Compose the geometry primitives rather than hardcoding coordinates, so themes
keep control of margins and rhythm. Test with
`test_all_layouts_render_every_slide_kind`, which asserts nothing leaves the
canvas.

### Add an exporter

```python
from deckforge.exporters.base import Exporter, ExportContext, register_exporter

class PngExporter(Exporter):
    name, label, extension = "png", "PNG images", "zip"
    media_type = "application/zip"
    description = "One PNG per slide."

    def render(self, deck, context: ExportContext) -> bytes:
        frames = context.renderer.layouts.resolve_deck(deck, context.theme)
        ...

register_exporter(PngExporter())
```

It appears in `GET /formats`, in the export menu and in export history with no
further changes.

### Add an LLM provider

If it speaks the OpenAI API:

```python
class MyProvider(OpenAICompatibleProvider):
    name, label = "myprovider", "My Provider"

register_provider(ProviderSpec(
    cls=MyProvider,
    base_url=lambda s: "https://api.example.com/v1",
    api_key=lambda s: s.extra.get("myprovider_key"),
    default_model="my-model-1",
))
```

Otherwise subclass `LLMProvider` and implement `stream`; `complete` and
`structured` come for free. Add a test with `httpx.MockTransport` — see
`tests/test_providers.py`.

### Add a document type

```python
class EpubExtractor(Extractor):
    extensions = ("epub",)
    kind = "document"

    def extract(self, path: Path) -> Extraction:
        return Extraction(pages=[ExtractedPage(text=...)], kind=self.kind)

register_extractor(EpubExtractor())
```

Uploads, chunking, indexing and the research agent pick it up automatically.

### Add an agent

Subclass `Agent[InputT, OutputT]`, define a Pydantic output model in
`models/plan.py`, and wire it into `CoordinatorAgent`. Keep it single-purpose;
if it needs two prompts it is two agents.

### Package a plugin

Bundle any of the above into a directory under `plugins/`:

```python
MANIFEST = PluginManifest(name="acme", version="1.0.0", description="…")

def register(registry: PluginRegistry) -> None:
    registry.add_theme_directory(Path(__file__).parent / "themes")
    registry.add_exporter(PngExporter())
```

Or publish it with a `deckforge.plugins` entry point. Check it loaded with
`GET /api/v1/plugins`; failures are listed at `GET /api/v1/capabilities`.

---

## Working on prompts

Deck quality is mostly prompting. All editorial rules live in
`agents/prompts.py` — `HOUSE_STYLE` and `ELEMENT_GUIDE` are shared by every
writing agent, so changing a rule changes it everywhere.

**Content density.** How much prose a slide carries is a separate axis from the
house style: `ContentDensity` is `concise`, `balanced` or `rich`, and
`density_clause()` turns it into concrete word budgets that the planner, outline,
writer and reviser all append to their system prompt. Density is the user's
call, never the model's — `AgentContext.density()` resolves it from the request
(`density_from_request`), then the conversation preference, then
`DECKFORGE_CONTENT_DENSITY` (default `rich`). Keep the budgets numeric: models
follow "45-80 words" far more reliably than "detailed".

Longer copy has to still fit. `measure.fit_scale` finds the largest type scale
at which a stack fits its box and `stack()` records it on each
`ElementPlacement.scale`; all three renderers apply it through
`Theme.type_scaled()`. The inverse also matters — `_absorb_slack` hands unused
height to charts, diagrams and images (which redraw at any size) and to cards,
tables and timelines up to `MAX_GROWTH`.

When iterating:

1. run a real generation against a small local model (that is where prompts
   break first),
2. render a contact sheet and look at it,
3. add a mechanical check to `PresentationCriticAgent._mechanical_issues` if the
   problem can be detected deterministically — that is cheaper and more reliable
   than asking a model to notice it.

## Database changes

Schema is created with `create_all`. For an existing local database, delete
`data/deckforge.db` or add Alembic for production. When you add a column, add it
to the entity and to whichever repository exposes it — services never touch the
session directly.

## Conventions

- Type hints everywhere; `mypy` runs strict.
- Docstrings say *why*, not *what the code already says*.
- Domain errors from `core/errors.py` — never `HTTPException` in business code;
  `main.py` maps them to status codes in one place.
- Structured logging: `log.info("export.done", format=fmt, bytes=size)`.
- New capability → new registry entry, not a new `if` branch.
