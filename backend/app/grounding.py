"""Open-vocabulary detection (Grounding DINO) to tighten Claude's approximate boxes."""

from __future__ import annotations

import os
from functools import lru_cache

import torch
from PIL import Image

from .geometry import Box

MODEL_ID = os.environ.get("HOARD_DETECTOR_MODEL", "IDEA-Research/grounding-dino-tiny")


def device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@lru_cache(maxsize=1)
def _load():
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device()).eval()
    return processor, model


def detect(
    image: Image.Image,
    phrase: str,
    region: Box,
    box_threshold: float = 0.3,
    text_threshold: float = 0.25,
) -> list[tuple[Box, float]]:
    """Detect `phrase` inside `region` of `image`. Returned boxes are in full-image pixels."""
    processor, model = _load()
    rx1, ry1, rx2, ry2 = region
    crop = image.convert("RGB").crop(region)
    text = phrase.strip().lower().rstrip(".") + "."

    inputs = processor(images=crop, text=text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model(**inputs)
    result = processor.post_process_grounded_object_detection(
        outputs,
        inputs.input_ids,
        threshold=box_threshold,
        text_threshold=text_threshold,
        target_sizes=[(crop.height, crop.width)],
    )[0]

    detections: list[tuple[Box, float]] = []
    for box, score in zip(result["boxes"].tolist(), result["scores"].tolist()):
        x1, y1, x2, y2 = box
        detections.append(((round(x1) + rx1, round(y1) + ry1, round(x2) + rx1, round(y2) + ry1), float(score)))
    return detections
