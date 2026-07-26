# Built-in theme packages

Each subdirectory is one theme package. A package is a single `theme.json` file —
**adding a theme requires no Python changes**. Drop a folder here (or in any
directory listed in `DECKFORGE_THEME_PATHS`) and it appears in the theme picker
after a reload.

## Minimum viable theme

```json
{
  "name": "acme",
  "label": "Acme Brand",
  "description": "Our corporate palette.",
  "tags": ["brand", "light"],
  "mode": "light",
  "palette": { "primary": "#e2231a", "text": "#101820" }
}
```

Anything you omit falls back to the defaults in
[`themes/model.py`](../model.py).

## Inheriting from another theme

```json
{
  "name": "acme-dark",
  "extends": "modern_dark",
  "label": "Acme Dark",
  "palette": { "primary": "#e2231a" }
}
```

`extends` chains are resolved with a deep merge, so you only restate what differs.

## Keys

| Key | Purpose |
| --- | --- |
| `palette` | Semantic colour roles (`primary`, `text`, `surface`, …). Renderers never hardcode a colour. |
| `fonts` | Web families plus `office_heading`/`office_body` used for PPTX and PDF. |
| `type_scale` | Per-role type steps (`display`, `title`, `bullet`, `quote`, …) sized for the 1280×720 canvas. |
| `spacing` | Canvas margins and vertical rhythm in logical points. |
| `shape` | Corner radii, borders, shadow. |
| `bullets` | Marker glyph, colour, indent, row gap. |
| `background` / `backgrounds` | Deck default and per-slide-kind backgrounds (`solid`, `gradient`, `mesh`, `image`, `pattern`). |
| `decor` | Decorative flourish per slide kind (`bar`, `orbs`, `grid`, `dots`, `diagonal`, `underline`). |
| `layout_preferences` | Ordered layout candidates per slide kind. The layout selector treats these as strong hints. |
| `chart_palette` | Categorical series colours; derived from the palette when omitted. |
| `css` | Extra CSS appended to HTML and Reveal.js exports. |

## Testing a theme

```bash
python -m deckforge.cli render-sample --theme acme --out sample.html
```
