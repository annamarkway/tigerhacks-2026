"""SAM 2 box-prompted segmentation -> simplified polygons."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .geometry import Box
from .grounding import device

WEIGHTS = os.environ.get(
    "HOARD_SAM_WEIGHTS", str(Path(__file__).resolve().parent.parent / "models" / "sam2.1_b.pt")
)


@lru_cache(maxsize=1)
def _load():
    from ultralytics import SAM

    Path(WEIGHTS).parent.mkdir(parents=True, exist_ok=True)
    return SAM(WEIGHTS)


def masks_to_polygon(mask: np.ndarray, epsilon_frac: float = 0.004) -> list[tuple[int, int]] | None:
    """Largest external contour of a binary mask, simplified."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    eps = epsilon_frac * cv2.arcLength(c, True)
    approx = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
    if len(approx) < 3:
        return None
    return [(int(x), int(y)) for x, y in approx]


def segment_boxes(image: Image.Image, boxes: list[Box]) -> list[np.ndarray]:
    """One boolean HxW mask per box, in the same order."""
    if not boxes:
        return []
    model = _load()
    arr = np.asarray(image.convert("RGB"))[:, :, ::-1]  # ultralytics expects BGR ndarray
    results = model(arr, bboxes=[list(b) for b in boxes], device=device(), verbose=False)
    masks = results[0].masks
    if masks is None:
        return [np.zeros(arr.shape[:2], dtype=bool) for _ in boxes]
    data = masks.data.cpu().numpy() > 0.5
    if data.shape[1:] != arr.shape[:2]:
        data = np.stack(
            [cv2.resize(m.astype(np.uint8), (arr.shape[1], arr.shape[0]), interpolation=cv2.INTER_NEAREST) > 0 for m in data]
        )
    return list(data)
