"""Interactive guided session in the terminal. Writes out/<name>_step<n>.jpg for each new step.

    uv run python scripts/session_cli.py ../test_images/our_room.jpeg
    uv run python scripts/session_cli.py ../test_images/our_room.jpeg --from-json out/our_room.json --no-assess
    COACH_PROVIDER=claude uv run python scripts/session_cli.py ...

At the prompt type anything you'd say to the coach, or:
    /done  /skip        press the frontend buttons
    /photo PATH         send a closer or new photo
    /quit
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app import orchestrator  # noqa: E402
from app.pipeline import load_image  # noqa: E402
from app.render import render_focus, render_focus_tight  # noqa: E402
from app.schemas import AnalysisResult, Intent, SessionView, StepAction  # noqa: E402


def show(view: SessionView, out: Path, stem: str, written: set[str]) -> None:
    print(f"\ncoach [{view.intent.value if view.intent else '-'}]: {view.message}")
    step = view.current_step
    status = f"{view.status.value}, {view.completed} done, {view.remaining} left, {view.elapsed_min} min"
    if step is None:
        print(f"  ({status}; no current step)")
        return
    print(f"  ({status}; step {step.step.id} {step.step.action.value}: {', '.join(i.label for i in step.items) or step.step.zone_id})")
    session = orchestrator.store.get(view.session_id)
    p = session.get(step.step.id)
    key = f"{p.step.id}{'-small' if p.smaller else ''}"
    if key in written or step.focus is None:
        return
    photo = session.photos[p.photo_idx]
    result = photo.analysis.model_copy(update={"items": step.items})
    render = render_focus if p.step.action == StepAction.take_closer_photo else render_focus_tight
    path = out / f"{stem}_step{len(written) + 1}_{key}.jpg"
    render(photo.image, result, step.focus).save(path, quality=85)
    written.add(key)
    print(f"  wrote {path}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--out", default="out")
    p.add_argument("--from-json", help="reuse a saved AnalysisResult instead of calling the vision model")
    p.add_argument("--no-assess", action="store_true", help="skip the classifier call")
    args = p.parse_args()

    logging.basicConfig(level=logging.WARNING)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem
    written: set[str] = set()

    image = load_image(args.image)
    analysis = AnalysisResult.model_validate_json(Path(args.from_json).read_text()) if args.from_json else None
    print("analyzing...")
    view = orchestrator.start_session(image, analysis=analysis, assess=not args.no_assess)
    session = orchestrator.store.get(view.session_id)
    if session.assessment:
        a = session.assessment
        print(f"assessment: level {a.assigned_level} ({a.severity}, {a.confidence.value} confidence)")
    print("plan: " + " -> ".join(f"{s.step.id}[{s.step.action.value}:{','.join(s.step.item_ids)}]" for s in session.steps))
    show(view, out, stem, written)

    while True:
        try:
            line = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line.startswith("/photo "):
            view = orchestrator.add_photo(session, load_image(line.split(maxsplit=1)[1]))
            stem = Path(line.split(maxsplit=1)[1]).stem
        elif line in ("/done", "/skip"):
            view = orchestrator.handle_message(session, None, Intent(line[1:]))
        else:
            view = orchestrator.handle_message(session, line)
        show(view, out, stem, written)


if __name__ == "__main__":
    main()
