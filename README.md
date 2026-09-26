# Declutter vision backend

Image analysis for step-by-step decluttering help. One photo goes in. Out come zones, item groups with triage categories, pixel polygons, a "too complex, zoom in" flag, and one recommended first target.

Pipeline: **Claude** (scene reasoning, structured output) → **Grounding DINO** (tight boxes per item phrase) → **SAM 2.1** (masks → polygons). See `app/pipeline.py`.

## Setup
```sh
brew install uv
cd backend
uv sync --extra vision        # the vision extra pulls torch/transformers/ultralytics (~1 GB of weights on first run)
cp .env.example .env          # then set ANTHROPIC_API_KEY and GEMINI_API_KEY
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

Images are processed in memory and never written to disk. A guided session keeps its photos in memory until it has been idle for an hour. Regions containing people, pets, photos, or screens come back in `exclude_regions_px`: they are never targets and are blurred in renders.

## Guided sessions (agent orchestration)
A session turns one photo into a 10-15 minute run of small steps, and moves through them as the person replies. Code runs the flow; each agent is one structured-output call with its prompt in `backend/prompts/`:

| Agent | Model | Prompt | Job |
|---|---|---|---|
| Vision | Claude Opus 5 | `vision.md` | zones, items, accessibility (`accessible`, `blocked_by`, `blocks_path`), hazards |
| Classify | Claude Sonnet 5 | `classify.md` | ICD Clutter-Hoarding Scale level + PPE (runs in parallel with vision) |
| Triage | Claude Sonnet 5 | `triage.md` | ordered steps: accessibility first, then hazards, blocked paths, easy groups |
| Coach | Claude Haiku (or Gemini via `COACH_PROVIDER=gemini`) | `coach.md` | reads each reply as done / skip / smaller / support / pause / question / crisis, and writes the message |

Code validates the triage plan: it drops unknown or decision-heavy items and never schedules a zone before the zones blocking it. `app/session.py` applies each intent. The session also tracks the time budget, and a crisis check adds support resources and pauses the session.

```sh
uv run python scripts/session_cli.py ../test_images/our_room.jpeg     # interactive; writes out/<name>_step<n>_<id>.jpg
uv run python scripts/session_cli.py IMG --from-json out/IMG.json --no-assess   # skip vision + classify calls
COACH_PROVIDER=gemini uv run python scripts/session_cli.py IMG        # compare coaches
```
In the CLI, type messages naturally, or use `/done`, `/skip`, `/photo PATH`, and `/quit`.

API:
- `POST /sessions` (multipart `image`) returns a `SessionView`: the coach `message`, `current_step` (item polygons, `focus` box, `image_url`), progress, and PPE.
- `POST /sessions/{id}/messages` takes `{"text": "...", "action": "done"|"skip"|null}`. Buttons send `action`; free text goes to the coach.
- `POST /sessions/{id}/photo` takes a closer or new photo and continues the same session.
- `GET /sessions/{id}/steps/{step_id}/focus.jpg[?style=box]` returns the highlighted step image.
