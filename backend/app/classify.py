"""Classify agent: one Claude call that places the photo on the ICD Clutter-Hoarding Scale."""

from __future__ import annotations

import os

from PIL import Image

from .llm import claude_parse, image_block
from .prompts import load
from .schemas import Assessment
from .vlm import prepare_for_vlm


def classify(image: Image.Image) -> Assessment:
    model = os.environ.get("HOARD_CLASSIFY_MODEL", "claude-sonnet-5")
    content = [image_block(prepare_for_vlm(image)), {"type": "text", "text": "Assess the environment in this photo."}]
    return claude_parse(model, load("classify"), content, Assessment, max_tokens=8000, what="Assessment")
