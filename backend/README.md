# Declutter vision backend

Image analysis for step-by-step decluttering help. One photo goes in. Out come zones, item groups with triage categories, pixel polygons, a "too complex, zoom in" flag, and one recommended first target.

Pipeline: **Claude** (scene reasoning, structured output) → **Grounding DINO** (tight boxes per item phrase) → **SAM 2.1** (masks → polygons). See `app/pipeline.py`.

## Setup
```sh
brew install uv
cd backend
uv sync --extra vision        # the vision extra pulls torch/transformers/ultralytics (~1 GB of weights on first run)
cp .env.example .env          # then set ANTHROPIC_API_KEY
```

## Run
```sh
uv run python scripts/analyze_cli.py ../test_images/image.png            # writes out/image.json, image_focus.jpg (box), image_focus_tight.jpg (outlines)
uv run python scripts/analyze_cli.py IMG --debug                         # also out/IMG_overview.jpg (every zone/item)
uv run python scripts/analyze_cli.py IMG --from-json out/IMG.json        # re-render only, no API call
uv run python scripts/analyze_cli.py ../test_images/table_closeup.jpg
uv run python scripts/analyze_cli.py IMG --vlm-only                      # Claude boxes only, no local models
uv run uvicorn app.main:app --reload                                     # POST /analyze, POST /render, docs at /docs
uv run pytest
```

`/analyze` takes a multipart `image` and returns `AnalysisResult` (see `app/schemas.py`). Coordinates are pixels on the uploaded image, and `polygon` is the outline to draw. `focus` holds the first task: the item ids, the box that frames them, and the instruction. `/render` (or `render.render_focus`) draws it: light blur outside the box, a red frame around it, and thinner red boxes on each item.

Images are processed in memory and never stored. Regions containing people, pets, photos, or screens come back in `exclude_regions_px`: they are never targets and are blurred in renders.
