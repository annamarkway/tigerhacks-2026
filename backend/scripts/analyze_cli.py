"""Run the pipeline on a local image; writes out/<name>.json, <name>_focus.jpg (box style)
and <name>_focus_tight.jpg (object outlines).

    uv run python scripts/analyze_cli.py ../test_images/image.png [--vlm-only] [--refine] [--debug]
    uv run python scripts/analyze_cli.py ../test_images/our_room.jpeg --from-json out/our_room.json   # re-render, no API call
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from app.pipeline import Options, analyze, focus_from_result, load_image  # noqa: E402
from app.render import render_focus, render_focus_tight, render_overview  # noqa: E402
from app.schemas import AnalysisResult  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("--out", default="out")
    p.add_argument("--vlm-only", action="store_true", help="skip detector + SAM")
    p.add_argument("--refine", action="store_true", help="ground/segment even if the scene is too complex")
    p.add_argument("--from-json", help="skip analysis and re-render a saved AnalysisResult")
    p.add_argument("--debug", action="store_true", help="also write <name>_overview.jpg with every zone and item")
    args = p.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.image).stem

    image = load_image(args.image)
    if args.from_json:
        result = AnalysisResult.model_validate_json(Path(args.from_json).read_text())
        if result.focus is None:
            result.focus = focus_from_result(result)
    else:
        opts = Options(use_detector=not args.vlm_only, use_segmenter=not args.vlm_only, refine_when_complex=args.refine)
        t = time.perf_counter()
        result = analyze(image, opts)
        print(f"analyzed in {time.perf_counter() - t:.1f}s")
        (out / f"{stem}.json").write_text(result.model_dump_json(indent=2))

    written = [] if args.from_json else [f"{stem}.json"]
    render_focus(image, result).save(out / f"{stem}_focus.jpg", quality=88)
    render_focus_tight(image, result).save(out / f"{stem}_focus_tight.jpg", quality=88)
    written += [f"{stem}_focus.jpg", f"{stem}_focus_tight.jpg"]
    if args.debug:
        render_overview(image, result).save(out / f"{stem}_overview.jpg", quality=88)
        written.append(f"{stem}_overview.jpg")

    c = result.complexity
    print(f"complexity {c.score}/5 too_complex={c.too_complex}: {c.reason}")
    for z in result.zones:
        print(f"  zone {z.id}{' *' if z.suggested_first else ''}: {z.label} ({z.density.value})")
    for i in result.items:
        srcs = {inst.source for inst in i.instances}
        print(f"  item {i.id} [{i.category.value}] {i.label}: {len(i.instances)} ({'/'.join(sorted(srcs))})")
    if result.zoom_suggestion:
        print(f"zoom: {result.zoom_suggestion.message}")
    if result.focus:
        labels = {i.id: i.label for i in result.items}
        names = ", ".join(f"{i} ({labels.get(i, '?')})" for i in result.focus.item_ids)
        print(f"focus: {names} in box {result.focus.bbox_px}")
    else:
        print("focus: none")
    print(f"first step: {result.first_step}")
    print(f"wrote {', '.join(str(out / f) for f in written)}")


if __name__ == "__main__":
    main()
