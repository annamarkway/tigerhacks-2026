"""analyze(): VLM scene pass -> detector grounding -> SAM masks -> AnalysisResult."""

from __future__ import annotations

import io
import logging
import math
import statistics
import threading
from dataclasses import dataclass

from PIL import Image, ImageOps

from . import vlm
from .geometry import Box, area, center, containment, expand, nms, scale_box, union
from .schemas import (
    CATEGORY_PRIORITY,
    AnalysisResult,
    Category,
    FocusTask,
    Instance,
    ItemGroup,
    ItemResult,
    ZoneResult,
)

log = logging.getLogger(__name__)

MAX_INSTANCES = 20


@dataclass
class Options:
    use_detector: bool = True
    use_segmenter: bool = True
    # Ground/segment items even when the scene is flagged too complex.
    refine_when_complex: bool = False


class Cancelled(Exception):
    """The person cancelled (the request's client went away). Raised at the next stage boundary."""


def check_cancel(cancel: threading.Event | None) -> None:
    # A model call already under way can't be interrupted; this stops the work that would follow it.
    if cancel is not None and cancel.is_set():
        raise Cancelled()


def load_image(data: bytes | str) -> Image.Image:
    img = Image.open(data if isinstance(data, str) else io.BytesIO(data))
    return ImageOps.exif_transpose(img).convert("RGB")


def _ground_group(
    image: Image.Image,
    group: ItemGroup,
    vlm_boxes: list[Box],
    zone_box: Box | None,
    exclude: list[Box],
) -> list[Instance]:
    from .grounding import detect

    w, h = image.size
    # Search the zone (or the union of the VLM's boxes if there's no zone), with margin.
    if zone_box is not None:
        region = expand(zone_box, 0.1, w, h)
    else:
        region = expand(
            (min(b[0] for b in vlm_boxes), min(b[1] for b in vlm_boxes),
             max(b[2] for b in vlm_boxes), max(b[3] for b in vlm_boxes)),
            0.25, w, h,
        )
    if area(region) == 0:
        return []

    hints = [expand(b, 0.5, w, h) for b in vlm_boxes]
    kept_boxes: list[Box] = []
    kept_scores: list[float] = []
    for box, score in detect(image, group.detector_phrase, region):
        if area(box) > 0.4 * area(region):  # DINO sometimes boxes the whole crop
            continue
        if any(containment(box, ex) > 0.3 for ex in exclude):
            continue
        if hints and max(containment(box, hb) for hb in hints) < 0.5:
            continue
        kept_boxes.append(box)
        kept_scores.append(score)

    keep = nms(kept_boxes, kept_scores, 0.5)[:MAX_INSTANCES]
    return [Instance(bbox_px=kept_boxes[i], score=round(kept_scores[i], 3), source="detector") for i in keep]


MAX_FOCUS_GROUPS = 4


def choose_focus(
    items: list[ItemResult],
    requested_ids: list[str],
    suggested_zone_ids: set[str],
    instruction: str,
    image_size: tuple[int, int],
    allow_fallback: bool = True,
) -> FocusTask | None:
    """Pick the few nearby item groups for the first task and the box that frames them.

    Uses Claude's `requested_ids` when valid; otherwise every group in the lowest triage
    tier of the suggested zone, minus far-away outliers.
    """
    usable = {i.id: i for i in items if i.instances and i.category != Category.keep_sentimental}
    chosen = [usable[i] for i in dict.fromkeys(requested_ids) if i in usable][:MAX_FOCUS_GROUPS]

    if not chosen and allow_fallback:
        pool = [i for i in usable.values() if i.zone_id in suggested_zone_ids] or list(usable.values())
        if pool:
            tier = min(CATEGORY_PRIORITY[i.category] for i in pool)
            chosen = [i for i in pool if CATEGORY_PRIORITY[i.category] == tier]
            chosen = _drop_outliers(chosen)
            chosen.sort(key=lambda i: -len(i.instances))
            chosen = chosen[:MAX_FOCUS_GROUPS]
    if not chosen:
        return None

    w, h = image_size
    box = union([inst.bbox_px for i in chosen for inst in i.instances])
    pad = max(0.06 * max(box[2] - box[0], box[3] - box[1]), 0.015 * min(w, h))
    padded = (
        max(0, round(box[0] - pad)),
        max(0, round(box[1] - pad)),
        min(w, round(box[2] + pad)),
        min(h, round(box[3] + pad)),
    )
    zones = {i.zone_id for i in chosen}
    return FocusTask(
        item_ids=[i.id for i in chosen],
        zone_id=zones.pop() if len(zones) == 1 else None,
        bbox_px=padded,
        instruction=instruction,
    )


def _drop_outliers(groups: list[ItemResult]) -> list[ItemResult]:
    """Drop groups far from the rest so the focus box stays small."""
    if len(groups) < 3:
        return groups
    centers = [center(union([inst.bbox_px for inst in g.instances])) for g in groups]
    mx = statistics.median(c[0] for c in centers)
    my = statistics.median(c[1] for c in centers)
    dists = [math.dist(c, (mx, my)) for c in centers]
    spread = statistics.median(dists) or 1.0
    return [g for g, d in zip(groups, dists) if d <= 2.5 * spread]


def focus_from_result(result: AnalysisResult) -> FocusTask | None:
    """Recompute the focus for a saved result (e.g. JSON from before `focus` existed)."""
    return choose_focus(
        result.items,
        [],  # old results only carry a single recommended id, so regroup via the fallback
        {z.id for z in result.zones if z.suggested_first},
        result.first_step,
        result.image_size,
        allow_fallback=not result.complexity.too_complex,
    )


def analyze(image: Image.Image, options: Options | None = None, cancel: threading.Event | None = None) -> AnalysisResult:
    options = options or Options()
    w, h = image.size
    check_cancel(cancel)
    scene, sent_size = vlm.analyze_scene(image)
    to_px = lambda b: scale_box(b, sent_size, (w, h))  # noqa: E731

    zone_px = {z.id: to_px(z.box) for z in scene.zones}
    exclude = [to_px(r.box) for r in scene.exclude_regions]
    refine = not scene.complexity.too_complex or options.refine_when_complex

    items: list[ItemResult] = []
    for group in scene.items:
        check_cancel(cancel)
        vlm_boxes = [b for b in (to_px(nb) for nb in group.boxes) if area(b) > 0]
        instances: list[Instance] = []
        if refine and options.use_detector and vlm_boxes:
            try:
                instances = _ground_group(image, group, vlm_boxes, zone_px.get(group.zone_id), exclude)
            except Exception:
                log.exception("Grounding failed for %s; falling back to VLM boxes", group.label)
        if not instances:
            instances = [Instance(bbox_px=b, score=0.0, source="vlm") for b in vlm_boxes[:MAX_INSTANCES]]
        items.append(
            ItemResult(id=group.id, zone_id=group.zone_id, label=group.label, category=group.category, instances=instances)
        )

    check_cancel(cancel)
    if refine and options.use_segmenter:
        _attach_polygons(image, items)

    focus = choose_focus(
        items,
        scene.focus_item_ids,
        {z.id for z in scene.zones if z.suggested_first},
        scene.first_step,
        (w, h),
        allow_fallback=refine,
    )

    return AnalysisResult(
        image_size=(w, h),
        scene_summary=scene.scene_summary,
        room=scene.room,
        furniture=scene.furniture,
        complexity=scene.complexity,
        zones=[
            ZoneResult(
                id=z.id, label=z.label, bbox_px=zone_px[z.id], density=z.density, suggested_first=z.suggested_first,
                accessible=z.accessible, blocked_by=z.blocked_by, blocks_path=z.blocks_path, hazards=z.hazards,
            )
            for z in scene.zones
        ],
        items=items,
        exclude_regions_px=exclude,
        zoom_suggestion=scene.zoom_suggestion,
        recommended_item_id=focus.item_ids[0] if focus else None,
        first_step=scene.first_step,
        focus=focus,
    )


def _attach_polygons(image: Image.Image, items: list[ItemResult]) -> None:
    from .segment import masks_to_polygon, segment_boxes

    flat = [inst for item in items for inst in item.instances]
    if not flat:
        return
    try:
        masks = segment_boxes(image, [inst.bbox_px for inst in flat])
    except Exception:
        log.exception("Segmentation failed; returning boxes only")
        return
    for inst, mask in zip(flat, masks):
        inst.polygon = masks_to_polygon(mask)
