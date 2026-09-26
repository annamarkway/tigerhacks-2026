"""Box math. Pixel boxes are (x1, y1, x2, y2) ints on the original image."""

from __future__ import annotations

from collections.abc import Sequence

from .schemas import VlmBox

Box = tuple[int, int, int, int]


def scale_box(box: VlmBox, src_size: tuple[int, int], dst_size: tuple[int, int]) -> Box:
    """Map a box from the image Claude saw (`src_size`) onto the original (`dst_size`)."""
    sw, sh = src_size
    dw, dh = dst_size
    x1, x2 = sorted((max(0, min(sw, box.x1)), max(0, min(sw, box.x2))))
    y1, y2 = sorted((max(0, min(sh, box.y1)), max(0, min(sh, box.y2))))
    return (round(x1 * dw / sw), round(y1 * dh / sh), round(x2 * dw / sw), round(y2 * dh / sh))


def area(b: Sequence[float]) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: Sequence[float], b: Sequence[float]) -> float:
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def containment(inner: Sequence[float], outer: Sequence[float]) -> float:
    """Fraction of `inner` that lies inside `outer`."""
    a = area(inner)
    return intersection(inner, outer) / a if a > 0 else 0.0


def union(boxes: Sequence[Sequence[int]]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def center(b: Sequence[float]) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def expand(b: Box, frac: float, width: int, height: int) -> Box:
    dx = (b[2] - b[0]) * frac
    dy = (b[3] - b[1]) * frac
    return (
        max(0, round(b[0] - dx)),
        max(0, round(b[1] - dy)),
        min(width, round(b[2] + dx)),
        min(height, round(b[3] + dy)),
    )


def nms(boxes: list[Box], scores: list[float], thresh: float = 0.5) -> list[int]:
    """Greedy non-max suppression; returns kept indices, highest score first."""
    order = sorted(range(len(boxes)), key=lambda i: scores[i], reverse=True)
    keep: list[int] = []
    for i in order:
        if all(iou(boxes[i], boxes[k]) < thresh for k in keep):
            keep.append(i)
    return keep
