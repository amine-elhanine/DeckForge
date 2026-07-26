# DeckForge as an MCP server

DeckForge can be driven by other AI agents over the [Model Context
Protocol](https://modelcontextprotocol.io). An MCP client spawns `deckforge-mcp`
on demand, it speaks JSON-RPC on stdin/stdout, and it exits when the client
disconnects — **the desktop app never has to be running**.

It uses the same database as the desktop app, so the model connection you set up
in Settings works immediately, and decks an agent builds appear in the app's
sidebar next to your own.

---

## Install

```bash
uv pip install -e "backend[mcp]"
```

Check it:

```bash
deckforge-mcp --version
```

## Configure your client

The command is `deckforge-mcp` — use the absolute path to it, because MCP
clients rarely inherit your shell's `PATH`.

On Windows that is typically
`C:\path\to\agentic_slide\backend\.venv\Scripts\deckforge-mcp.exe`; on macOS and
Linux, `/path/to/agentic_slide/backend/.venv/bin/deckforge-mcp`.

**Claude Code** — add to `.mcp.json` in your project, or run
`claude mcp add deckforge -- /absolute/path/to/deckforge-mcp`:

```json
{
  "mcpServers": {
    "deckforge": {
      "command": "/absolute/path/to/deckforge-mcp"
    }
  }
}
```

**Claude Desktop** — same block, in `claude_desktop_config.json`.

Any other MCP client works the same way: one command, no arguments, stdio
transport.

## Tools

| Tool | What it does |
|---|---|
| `create_deck` | Generate a deck from a prompt. Returns a `deck_id` and the outline. |
| `refine_deck` | Change a deck with a natural-language instruction. Adds a version. |
| `export_deck` | Write `pptx`, `pdf`, `html`, `markdown`, `revealjs` or `marp` to disk. |
| `get_deck` | Read a deck back as an outline, as markdown, or as full JSON. |
| `list_decks` | Recent decks, so an earlier one can be picked up again. |
| `deckforge_capabilities` | Themes, layouts, formats, and whether a model is configured. |

A typical exchange:

```
create_deck  { "prompt": "A 10-slide briefing on RAG for backend engineers" }
             -> { "deck_id": "pres_f9e4…", "title": "…", "outline": "…" }

refine_deck  { "deck_id": "pres_f9e4…", "instruction": "make slide 4 a comparison table" }

export_deck  { "deck_id": "pres_f9e4…", "format": "pptx",
               "output_path": "C:/Users/me/Desktop/rag.pptx" }
             -> { "path": "C:\\Users\\me\\Desktop\\rag.pptx", "size_bytes": 52339 }
```

Omit `output_path` and the file goes to DeckForge's own exports folder; the
returned `path` is absolute either way.

`create_deck` accepts `theme`, `slide_count`, `density`
(`concise` / `balanced` / `rich`), `language` and `audience`.

## What to expect

**Generation takes one to four minutes.** `create_deck` and `refine_deck` call a
language model and run the whole pipeline. They report progress throughout
("Writing slides (4 of 6)"), which clients surface in their UI.

> If your client times out before a deck finishes, raise its tool timeout.
> Ask for fewer slides, or a faster model, as a workaround.

`export_deck`, `get_deck`, `list_decks` and `deckforge_capabilities` are fast and
run entirely offline.

**Call `deckforge_capabilities` first** if something is not working. It tells you
whether a model is configured, and what to do if not — which is quicker than
discovering it four minutes into a generation.

## Configuration

The server reads the desktop app's per-user data directory:

| Platform | Location |
|---|---|
| Windows | `%LOCALAPPDATA%\DeckForge` |
| macOS | `~/Library/Application Support/DeckForge` |
| Linux | `~/.local/share/deckforge` |

That is where the database, the model connections and `.env` live. Set
`DECKFORGE_DATA_DIR` in the client's `env` block to point somewhere else — for
an isolated agent workspace, say:

```json
{
  "mcpServers": {
    "deckforge": {
      "command": "/absolute/path/to/deckforge-mcp",
      "env": { "DECKFORGE_DATA_DIR": "/path/to/agent-workspace" }
    }
  }
}
```

A separate data directory means a separate database, so you would configure a
model connection there too (`DECKFORGE_DEEPSEEK_API_KEY=…` and friends in that
directory's `.env`).

**Running alongside the desktop app is fine.** SQLite is in WAL mode, so both
processes read and write the same database concurrently.

## Troubleshooting

**"No language model is configured"** — open the desktop app, go to Settings and
add a connection, or put the provider's key in the `.env` file in the data
directory above. `deckforge_capabilities` reports the current state.

**The client reports a JSON parse error, or the connection drops immediately** —
something is writing to stdout, which is the transport. DeckForge's own logging
goes to stderr; a plugin that `print`s would break this. Run the server by hand
and look: `deckforge-mcp < /dev/null` should print nothing to stdout.

**The server starts but sees none of your decks** — it is using a different data
directory. `deckforge_capabilities` returns `data_dir`; compare it with the table
above and check for a stray `DECKFORGE_DATA_DIR`.

**`deckforge-mcp: command not found`** — the client is not using your shell's
`PATH`. Use the absolute path to the executable.

## Notes for the curious

The server is a third entry point onto the same service layer as the REST API
and the desktop shell (`backend/src/deckforge/mcp/`). Tools contain no deck
logic; they call `ChatService`, `PresentationService` and `ExportService`
directly. Turns go through the ordinary pipeline, which is why version history,
undo and the desktop UI keep working on agent-created decks.

Each `create_deck` opens a conversation behind the scenes. Agents never see
conversation ids — `refine_deck` finds its way back from the `deck_id`.
