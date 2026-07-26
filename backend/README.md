# DeckForge backend

FastAPI + SQLAlchemy 2.0 async service that hosts the agent pipeline, the theme
and layout engines, and the exporters.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m deckforge.cli serve
```

See the repository root `README.md`, `ARCHITECTURE.md` and `DEVELOPMENT.md` for
the full picture.
