"""Scene pass: one Claude call that returns a validated SceneAnalysis."""

from __future__ import annotations

import base64
import io
import os

import anthropic
from PIL import Image

from .prompts import SYSTEM_PROMPT, USER_PROMPT
from .schemas import SceneAnalysis

MODEL = os.environ.get("HOARD_VLM_MODEL", "claude-opus-5")
# Claude downsamples anything larger; sending at this size keeps boxes consistent.
MAX_LONG_EDGE = 1568

_client: anthropic.Anthropic | None = None


class SceneAnalysisError(RuntimeError):
    """The model answered but the answer is unusable (refusal, truncation)."""


class VLMUnavailableError(RuntimeError):
    """Claude couldn't be reached: missing credentials, network, rate limit, or server error."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def prepare_for_vlm(image: Image.Image) -> Image.Image:
    img = image.convert("RGB")
    scale = MAX_LONG_EDGE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    return img


def _call(image_b64: str, size: tuple[int, int]):
    return _get_client().beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": USER_PROMPT.format(width=size[0], height=size[1])},
                ],
            }
        ],
        output_format=SceneAnalysis,
    )


def analyze_scene(image: Image.Image) -> tuple[SceneAnalysis, tuple[int, int]]:
    """Returns the analysis and the size of the image Claude saw, which its boxes are relative to."""
    img = prepare_for_vlm(image)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    data = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

    try:
        response = _call(data, img.size)
    except anthropic.AuthenticationError as e:
        raise VLMUnavailableError("Claude rejected the API key.") from e
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
        raise VLMUnavailableError(f"Claude is temporarily unavailable: {e}") from e
    except TypeError as e:
        if "authentication" in str(e):
            raise VLMUnavailableError("No Anthropic credentials configured; set ANTHROPIC_API_KEY in backend/.env.") from e
        raise

    if response.stop_reason == "refusal":
        raise SceneAnalysisError("The model declined to analyze this image.")
    if response.stop_reason == "max_tokens":
        raise SceneAnalysisError("Scene analysis was cut off (max_tokens).")
    if response.parsed_output is None:
        raise SceneAnalysisError("Scene analysis returned no parseable output.")
    return response.parsed_output, img.size
