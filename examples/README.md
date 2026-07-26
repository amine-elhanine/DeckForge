# Examples

## `sample-deck.json`

The deck model in full, as the agents actually produce it — every element type
appears at least once (bullets, quote, chart, metrics, timeline, cards, table,
code, diagram, image). Useful as a reference when writing a plugin or an
exporter.

Render it:

```bash
cd backend
python -m deckforge.cli export --deck ../examples/sample-deck.json --format pptx --out deck.pptx
python -m deckforge.cli export --deck ../examples/sample-deck.json --format pdf  --theme academic
```

Or load it over the API:

```bash
curl -X POST http://localhost:8000/api/v1/presentations/$ID/deck \
  -H 'content-type: application/json' \
  -d @examples/sample-deck.json
```

## `output/`

Generated artifacts — one file per exporter plus the same deck under four
themes, so you can see what the theme engine actually changes. Regenerate:

```bash
cd backend
python -m deckforge.cli render-sample --theme modern_dark --out ../examples/output/preview.html
python -m deckforge.cli render-sample --contact-sheet --out ../examples/output/contact-sheet.html
python -m deckforge.cli export --format pptx --out ../examples/output/deck.pptx
```

The directory is git-ignored; it exists so a fresh clone can produce something
to look at in one command.

## Trying the whole loop without a UI

```bash
# 1. start a conversation
CONV=$(curl -s -X POST http://localhost:8000/api/v1/conversations \
  -H 'content-type: application/json' -d '{}' | jq -r .id)

# 2. give the agent source material (optional)
curl -s -X POST http://localhost:8000/api/v1/conversations/$CONV/uploads \
  -F files=@notes.pdf

# 3. ask for a deck and watch the pipeline stream
curl -N -X POST http://localhost:8000/api/v1/conversations/$CONV/messages \
  -H 'content-type: application/json' \
  -d '{"content":"Create a 12-slide deck about reinforcement learning"}'

# 4. edit it
curl -N -X POST http://localhost:8000/api/v1/conversations/$CONV/messages \
  -H 'content-type: application/json' \
  -d '{"content":"Move slide 7 before slide 4 and use a dark theme"}'

# 5. download
curl -OJ "http://localhost:8000/api/v1/presentations/$PRES/download?format=pptx"
```
