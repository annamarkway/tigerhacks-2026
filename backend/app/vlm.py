"""Scene pass: one Claude call that returns a validated SceneAnalysis."""

from __future__ import annotations

import os

from PIL import Image

from .llm import SceneAnalysisError, VLMUnavailableError, claude_parse, image_block  # noqa: F401 (re-exported)
from .prompts import SYSTEM_PROMPT, USER_PROMPT
from .schemas import SceneAnalysis

MODEL = os.environ.get("HOARD_VLM_MODEL", "claude-opus-5")
# Claude downsamples anything larger; sending at this size keeps boxes consistent.
MAX_LONG_EDGE = 1568


def prepare_for_vlm(image: Image.Image) -> Image.Image:
    img = image.convert("RGB")
    scale = MAX_LONG_EDGE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    return img


def analyze_scene(image: Image.Image) -> tuple[SceneAnalysis, tuple[int, int]]:
    """Returns the analysis and the size of the image Claude saw, which its boxes are relative to."""
    img = prepare_for_vlm(image)
    content = [image_block(img), {"type": "text", "text": USER_PROMPT.format(width=img.width, height=img.height)}]
    return claude_parse(MODEL, SYSTEM_PROMPT, content, SceneAnalysis, what="Scene analysis"), img.size
