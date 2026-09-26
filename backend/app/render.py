"""Renders: `render_focus` is the user-facing view; `render_overview` is a debug view of everything found."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .schemas import AnalysisResult, Category, FocusTask

CATEGORY_COLORS = {
    Category.trash_biohazard: (255, 99, 71),
    Category.recycling_paper: (65, 150, 255),
    Category.usable_belongings: (180, 110, 255),
    Category.keep_sentimental: (255, 200, 60),
    Category.unsure: (160, 160, 160),
}
ZONE_COLOR = (0, 220, 170)


def blur_excluded(image: Image.Image, result: AnalysisResult) -> Image.Image:
    """Blur people/pets/photos so debug output doesn't keep identifiable faces."""
    arr = np.asarray(image.convert("RGB")).copy()
    for x1, y1, x2, y2 in result.exclude_regions_px:
        if x2 > x1 and y2 > y1:
            k = max(31, ((x2 - x1) // 6) | 1)
            arr[y1:y2, x1:x2] = cv2.GaussianBlur(arr[y1:y2, x1:x2], (k, k), 0)
    return Image.fromarray(arr)


def render_overview(image: Image.Image, result: AnalysisResult) -> Image.Image:
    """Zones + every detected instance, colored by category."""
    img = blur_excluded(image, result)
    draw = ImageDraw.Draw(img)
    lw = max(2, img.width // 400)
    for z in result.zones:
        draw.rectangle(z.bbox_px, outline=ZONE_COLOR, width=lw * (2 if z.suggested_first else 1))
        draw.text((z.bbox_px[0] + 4, z.bbox_px[1] + 2), f"{z.id}: {z.label}", fill=ZONE_COLOR)
    for item in result.items:
        color = CATEGORY_COLORS[item.category]
        for inst in item.instances:
            if inst.polygon:
                draw.polygon(inst.polygon, outline=color, width=lw)
            else:
                draw.rectangle(inst.bbox_px, outline=color, width=lw)
        if item.instances:
            b = item.instances[0].bbox_px
            draw.text((b[0], max(0, b[1] - 12)), item.label, fill=color)
    return img


FOCUS_RED = (255, 32, 32)
HALO = (20, 0, 0)


def _draw_red_box(arr: np.ndarray, box: tuple[int, int, int, int], thickness: int) -> None:
    """Red rectangle with a thin dark halo so it reads on light and dark surfaces."""
    x1, y1, x2, y2 = box
    halo = max(1, thickness // 3)
    cv2.rectangle(arr, (x1, y1), (x2, y2), HALO, thickness + 2 * halo, lineType=cv2.LINE_AA)
    cv2.rectangle(arr, (x1, y1), (x2, y2), FOCUS_RED, thickness, lineType=cv2.LINE_AA)


def _blur_outside(src: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Keep `mask` pixels exact; lightly blur and dim the rest, feathering outward only."""
    short = min(src.shape[:2])
    background = cv2.GaussianBlur(src, (0, 0), sigmaX=max(2.0, short * 0.004)) * 0.85
    feather = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(1.0, short * 0.004))
    alpha = np.maximum(mask, feather)[..., None]
    return np.clip(src * alpha + background * (1 - alpha), 0, 255).astype(np.uint8)


def _focus_instances(result: AnalysisResult, focus: FocusTask):
    return [inst for i in result.items if i.id in focus.item_ids for inst in i.instances]


def render_focus(image: Image.Image, result: AnalysisResult, focus: FocusTask | None = None) -> Image.Image:
    """Box style: sharp inside the focus box, red frame around it, thinner red boxes on each item."""
    focus = focus or result.focus
    src = np.asarray(blur_excluded(image, result)).astype(np.float32)
    h, w = src.shape[:2]
    short = min(w, h)

    mask = np.zeros((h, w), dtype=np.float32)
    if focus is not None:
        x1, y1, x2, y2 = focus.bbox_px
        mask[y1:y2, x1:x2] = 1.0
    out = _blur_outside(src, mask)
    if focus is None:
        return Image.fromarray(out)

    thick = max(6, short // 120)
    item_thick = max(2, round(thick * 0.4))
    item_pad = max(2, short // 200)
    for inst in _focus_instances(result, focus):
        bx1, by1, bx2, by2 = inst.bbox_px
        box = (max(0, bx1 - item_pad), max(0, by1 - item_pad), min(w - 1, bx2 + item_pad), min(h - 1, by2 + item_pad))
        _draw_red_box(out, box, item_thick)
    _draw_red_box(out, (x1, y1, min(w - 1, x2), min(h - 1, y2)), thick)
    return Image.fromarray(out)


def render_focus_tight(image: Image.Image, result: AnalysisResult, focus: FocusTask | None = None) -> Image.Image:
    """Outline style: only the target objects' own shapes stay sharp, each traced in red.

    Uses the SAM polygons; an instance without one falls back to its box.
    """
    focus = focus or result.focus
    src = np.asarray(blur_excluded(image, result)).astype(np.float32)
    h, w = src.shape[:2]
    short = min(w, h)

    mask = np.zeros((h, w), dtype=np.uint8)
    if focus is not None:
        for inst in _focus_instances(result, focus):
            if inst.polygon:
                cv2.fillPoly(mask, [np.array(inst.polygon, dtype=np.int32)], 255)
            else:
                x1, y1, x2, y2 = inst.bbox_px
                mask[y1:y2, x1:x2] = 255
        # Grow slightly so polygon simplification doesn't clip object edges.
        grow = max(3, short // 250)
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow + 1, 2 * grow + 1)))

    out = _blur_outside(src, mask.astype(np.float32) / 255)
    if not mask.any():
        return Image.fromarray(out)

    thick = max(4, short // 200)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(out, contours, -1, HALO, thick + 2 * max(1, thick // 3), lineType=cv2.LINE_AA)
    cv2.drawContours(out, contours, -1, FOCUS_RED, thick, lineType=cv2.LINE_AA)
    return Image.fromarray(out)
